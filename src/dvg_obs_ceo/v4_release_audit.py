"""Fail-closed local release audit for the frozen V4 evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

from .baseline import ROOT
from .v3_protocol import _write_exclusive


RELEASE_AUDIT_TAG = "dvg-obs-v4-s10-release-v1"
REPORT = ROOT / "artifacts" / "v4" / "s9-report-v1-1" / "report.json"
S7_SUMMARY = ROOT / "artifacts" / "v4" / "s7-lih-development-v1-2" / "summary.json"
S7_AUDIT = ROOT / "artifacts" / "v4" / "s7-lih-independent-audit-v1.json"
S8_GATE = ROOT / "artifacts" / "v4" / "s8-deferred-validation-gate-v1.json"
EXPECTED_SUBMODULE = "a3f89d03e6a03c89767d3cf8ee7657a57653dda0"
REQUIRED_THREADS = {"OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
REQUIRED_TAGS = (
    "dvg-obs-v3-result-v1",
    "dvg-obs-v4-s0-preregistration-result-v1",
    "dvg-obs-v4-s6-calibration-result-v1",
    "dvg-obs-v4-s7-lih-result-v1.2",
    "dvg-obs-v4-s7-lih-audit-result-v1",
    "dvg-obs-v4-s8-deferred-v1",
    "dvg-obs-v4-s9-report-result-v1.1",
)


class V4ReleaseAuditError(RuntimeError):
    """Raised when a release invariant is not satisfied."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _strict_json(path: Path) -> Any:
    def reject(value: str) -> None:
        raise ValueError(f"non-finite JSON token {value} in {path}")

    return json.loads(path.read_text(encoding="utf-8"), parse_constant=reject)


def _git(*arguments: str) -> str:
    return subprocess.check_output(["git", "-C", str(ROOT), *arguments], text=True).strip()


def audit_evidence() -> tuple[dict[str, bool], dict[str, Any]]:
    report = _strict_json(REPORT)
    s7 = _strict_json(S7_SUMMARY)
    s7_audit = _strict_json(S7_AUDIT)
    s8 = _strict_json(S8_GATE)
    bundle = REPORT.parent
    report_outputs_match = all(
        (bundle / name).is_file() and _sha256(bundle / name) == digest
        for name, digest in report["output_sha256"].items()
    )
    source_paths = {
        "s7_summary": S7_SUMMARY,
        "v2_summary": ROOT / "artifacts" / "s10" / "lih-3a-first-accuracy-primary-v1-2" / "summary.json",
        "v2_trial": ROOT / "artifacts" / "s10" / "lih-3a-first-accuracy-primary-v1-2" / "selected-trial.json",
        "v3_result": ROOT / "artifacts" / "v3" / "s2-polishing-calibration-v1-2.json",
        "s4_result": ROOT / "artifacts" / "v4" / "s4-deterministic-search-audit-v1.json",
    }
    report_sources_match = all(
        path.is_file() and _sha256(path) == report["source_sha256"][name]
        for name, path in source_paths.items()
    )
    submodule_status = _git("submodule", "status", "vendor/ceo-adapt-vqe")
    tracked_raw = _git("ls-files", "artifacts/raw")
    tag_commits: dict[str, str | None] = {}
    for tag in REQUIRED_TAGS:
        try:
            tag_commits[tag] = _git("rev-parse", f"{tag}^{{}}")
        except subprocess.CalledProcessError:
            tag_commits[tag] = None
    source = s7["checkpoint"]["resources"]["snapshot"]
    winner_id = s7["endpoint_winners"]["circuit_primary"]
    winner = next(item for item in s7["attempts"] if item["constraint_semantic_id"] == winner_id)
    winner_path = winner["fallback"] or winner["primary"]
    winner_resources = winner["physical_resources"]["snapshot"]
    checks = {
        "report_outputs_match_hashes": report_outputs_match,
        "report_sources_match_hashes": report_sources_match,
        "report_claim_boundary": report["paper_measurement_cost"] is None and "no blind validation" in report["claim_boundary"],
        "report_headline_reproduced": report["headline"] == {
            "cnot_depth_reduction": source["cnot_depth"] - winner_resources["cnot_depth"],
            "cnot_reduction": source["cnot_count"] - winner_resources["cnot_count"],
            "energy_change_hartree": winner_path["energy_hartree"] - s7["checkpoint"]["energy_hartree"],
            "parameter_reduction": source["parameter_count"] - winner_resources["parameter_count"],
            "total_depth_reduction": source["total_depth"] - winner_resources["total_depth"],
        },
        "s7_independent_audit_passed": s7_audit["passed"] is True and not s7_audit["failed_checks"],
        "s7_no_new_baseline_growth": s7["work"]["new_ceo_star_adapt_iterations"] == 0 and s7["work"]["new_ordinary_adapt_iterations"] == 0,
        "s8_honestly_deferred": s8["status"] == "deferred-not-passed" and s8["new_molecular_executions"] == 0,
        "submodule_pinned_and_clean": submodule_status == f"{EXPECTED_SUBMODULE} vendor/ceo-adapt-vqe (a3f89d0)",
        "required_tags_resolve": all(tag_commits.values()),
        "report_freeze_tag_resolves": tag_commits["dvg-obs-v4-s9-report-result-v1.1"] is not None,
        "raw_artifacts_not_tracked": tracked_raw == "",
        "no_hidden_v4_staging": not any((ROOT / "artifacts" / "v4").glob(".*.staging")),
        "strict_json_inputs": True,
    }
    details = {
        "report_sha256": _sha256(REPORT),
        "s7_summary_sha256": _sha256(S7_SUMMARY),
        "s7_audit_sha256": _sha256(S7_AUDIT),
        "s8_gate_sha256": _sha256(S8_GATE),
        "submodule_status": submodule_status,
        "required_tag_commits": tag_commits,
        "tracked_raw_paths": tracked_raw.splitlines() if tracked_raw else [],
    }
    return checks, details


def _run_test_suite() -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"], cwd=ROOT,
        text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
    )
    matches = re.findall(r"(\d+) passed", completed.stdout)
    return {
        "passed": completed.returncode == 0 and bool(matches),
        "exit_code": completed.returncode,
        "passed_count": int(matches[-1]) if matches else None,
        "summary_tail": completed.stdout.strip().splitlines()[-1] if completed.stdout.strip() else "",
    }


def _verify_freeze() -> dict[str, Any]:
    head = _git("rev-parse", "HEAD")
    tag = _git("rev-parse", f"{RELEASE_AUDIT_TAG}^{{}}")
    dirty = _git("status", "--porcelain")
    threads = {name: os.environ.get(name) for name in REQUIRED_THREADS}
    if head != tag or dirty or threads != REQUIRED_THREADS:
        raise V4ReleaseAuditError("S10 audit requires clean tagged code and canonical threads")
    return {"head": head, "release_audit_tag": RELEASE_AUDIT_TAG, "threads": threads}


def run(artifact_path: Path) -> dict[str, Any]:
    freeze = _verify_freeze()
    checks, details = audit_evidence()
    tests = _run_test_suite()
    checks["full_test_suite"] = tests["passed"]
    failed = [name for name, passed in checks.items() if not passed]
    artifact = {
        "schema_version": "1.0.0",
        "artifact_kind": "v4-s10-local-release-audit",
        "audit_freeze": freeze,
        "passed": not failed,
        "checks": checks,
        "failed_checks": failed,
        "test_suite": tests,
        "details": details,
        "remote_checks": {
            "github_visibility": "verified separately from GitHub API after local artifact commit",
            "github_actions": "verified separately after push",
        },
        "claim_boundary": "Local integrity and reproducibility release gate; LiH remains development-only and paper Measurement Cost remains unavailable.",
    }
    if failed:
        raise V4ReleaseAuditError("V4-S10 audit failed: " + ", ".join(failed))
    _write_exclusive(artifact_path, artifact)
    return artifact


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact_path", type=Path)
    arguments = parser.parse_args()
    result = run(arguments.artifact_path)
    print(json.dumps({"passed": result["passed"], "test_suite": result["test_suite"]}, sort_keys=True))


if __name__ == "__main__":
    main()

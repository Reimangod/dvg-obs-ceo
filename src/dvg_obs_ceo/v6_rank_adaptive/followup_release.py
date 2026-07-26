"""Build and audit the V6 NS8-NS10 follow-up release manifest."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess
import sys
from typing import Any

from dvg_obs_ceo.artifact_io import atomic_write_new_json
from dvg_obs_ceo.baseline import ROOT
from dvg_obs_ceo.identity import sha256_hex


OUTPUT = ROOT / "artifacts/v6/release/ns8-ns10-manifest-v1.json"
VERSION = "v6-ns8-ns10-release-manifest-v1"
STAGES = {
    "ns7": {
        "execution_commit": "3a52c6f",
        "result_commit": "1620b12",
        "result_tag": "v6-ns7-primary-native-development-v1",
        "result": "artifacts/v6/ns7/energy-certification-v1.json",
        "audit": "artifacts/v6/ns7/result-audit-v1.json",
    },
    "ns8": {
        "protocol_commit": "8ab3f1b",
        "result_commit": "3c24247",
        "protocol_tag": "v6-ns8-followup-protocol-v1",
        "result_tag": "v6-ns8-h4-followup-result-v1",
        "result": "artifacts/v6/ns8/h4-followup-audit-v1.json",
        "audit": "artifacts/v6/ns8/result-audit-v1.json",
    },
    "ns9": {
        "protocol_commit": "eb93992",
        "freeze_commit": "3bc0caa",
        "result_commit": "16ee662",
        "protocol_tag": "v6-ns9-sequential-protocol-v1",
        "freeze_tag": "v6-ns9-queue-freeze-v1",
        "result_tag": "v6-ns9-h4-sequential-result-v1",
        "freeze": "artifacts/v6/ns9/queue-freeze-v1.json",
        "result": "artifacts/v6/ns9/sequential-pilot-v1.json",
        "audit": "artifacts/v6/ns9/result-audit-v1.json",
    },
    "ns10": {
        "protocol_commit": "4df0282",
        "freeze_commit": "d0f3a98",
        "result_commit": "6b48ee6",
        "protocol_tag": "v6-ns10-h6-optimizer-protocol-v1",
        "freeze_tag": "v6-ns10-h6-queue-freeze-v1",
        "result_tag": "v6-ns10-h6-optimizer-result-v1",
        "freeze": "artifacts/v6/ns10/queue-freeze-v1.json",
        "result": "artifacts/v6/ns10/h6-optimizer-ablation-v1.json",
        "audit": "artifacts/v6/ns10/result-audit-v1.json",
    },
}


class FollowupReleaseError(RuntimeError):
    """Raised when release provenance does not reconcile."""


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _resolve(reference: str) -> str:
    return _git("rev-list", "-n", "1", reference)


def build_manifest() -> dict[str, Any]:
    if OUTPUT.exists():
        raise FollowupReleaseError("release manifest already exists")
    if _git("status", "--porcelain"):
        raise FollowupReleaseError("release requires a clean worktree")
    records = {}
    checks = {}
    for stage, specification in STAGES.items():
        record = dict(specification)
        for key in ("freeze", "result", "audit"):
            relative = record.get(key)
            if relative is not None:
                path = ROOT / relative
                checks[f"{stage}_{key}_exists"] = path.is_file()
                record[f"{key}_sha256"] = _sha256(path)
                if key == "audit":
                    audit = json.loads(path.read_text(encoding="utf-8"))
                    checks[f"{stage}_audit_passed"] = (
                        audit.get("passed") is True
                    )
                    record["audit_digest"] = audit.get("audit_digest")
        for key in ("protocol_tag", "freeze_tag", "result_tag"):
            tag = record.get(key)
            if tag is not None:
                expected_key = key.replace("_tag", "_commit")
                expected = record[expected_key]
                checks[f"{stage}_{key}_resolves"] = _resolve(tag).startswith(
                    expected
                )
                record[f"{key}_resolved_commit"] = _resolve(tag)
        records[stage] = record
    manifest = {
        "schema_version": "1.0.0",
        "artifact_kind": "v6-ns8-ns10-release-manifest",
        "version": VERSION,
        "release_content_commit": _git("rev-parse", "HEAD"),
        "branch": _git("branch", "--show-current"),
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
            "dependencies": {
                name: importlib.metadata.version(name)
                for name in ("numpy", "scipy", "qiskit", "openfermion")
            },
        },
        "stages": records,
        "checks": checks,
        "all_checks_passed": all(checks.values()),
        "final_gates": {
            "native_rank_feasibility": "PASS",
            "h4_mechanism": "PASS",
            "h4_same_source_legacy_frontier_after_two_transitions": "PASS",
            "h6_fixed_optimizer_recovery": "FAIL",
            "cross_molecule_robustness": "NOT_ESTABLISHED",
            "prospective_validation": "NOT_RUN",
            "pra_performance_claim": "NOT_ESTABLISHED",
        },
        "incidents": [
            "docs/incidents/V6_NS7_PRE_EXECUTION_IMPORT_FAILURE.md",
            "docs/incidents/V6_NS9_WRONG_ENTRYPOINT_PRE_EXECUTION_FAILURE.md",
        ],
        "claim_boundary": (
            "Audited development release. H4 mechanism and a two-transition "
            "energy-resource frontier point are established. H6 recovery, "
            "cross-molecule robustness, prospective validation, matched-work "
            "global superiority, Measurement Cost, and PRA performance are "
            "not established."
        ),
        "paper_measurement_cost": None,
    }
    manifest["manifest_digest"] = sha256_hex(manifest)
    if not manifest["all_checks_passed"]:
        raise FollowupReleaseError(
            "release checks failed: "
            + ", ".join(
                name for name, value in checks.items() if not value
            )
        )
    return manifest


def main() -> None:
    try:
        manifest = build_manifest()
        atomic_write_new_json(OUTPUT, manifest)
    except (
        KeyError,
        OSError,
        subprocess.CalledProcessError,
        TypeError,
        ValueError,
        FollowupReleaseError,
    ) as error:
        print(f"V6 follow-up release failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    print(
        json.dumps(
            {
                "manifest_digest": manifest["manifest_digest"],
                "all_checks_passed": manifest["all_checks_passed"],
                "final_gates": manifest["final_gates"],
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()

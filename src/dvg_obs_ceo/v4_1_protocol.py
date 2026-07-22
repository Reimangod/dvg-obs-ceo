"""V4.1-S0 preregistration and immutable-parent evidence audit."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any

from .baseline import ROOT
from .identity import canonical_json_bytes
from .v3_protocol import _write_exclusive


PROTOCOL_ID = "dvg-obs-v4.1-scale-transfer-protocol-v1"
PROTOCOL_TAG = "dvg-obs-v4.1-s0-preregistration-v1"
DEFAULT_MANIFEST = ROOT / "manifests" / "v4.1-scale-transfer-protocol-v1.json"


class V41ProtocolError(RuntimeError):
    """Raised when V4.1 preregistration evidence is inconsistent."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _path(relative: str) -> Path:
    result = (ROOT / relative).resolve()
    try:
        result.relative_to(ROOT.resolve())
    except ValueError as error:
        raise V41ProtocolError(f"path escapes repository: {relative}") from error
    return result


def _git(*arguments: str) -> str:
    return subprocess.check_output(["git", "-C", str(ROOT), *arguments], text=True).strip()


def _canonical_digest_without(value: dict[str, Any], key: str) -> str:
    payload = dict(value)
    payload.pop(key, None)
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def audit_manifest(manifest_path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    checks: dict[str, bool] = {
        "protocol_id": manifest.get("protocol_id") == PROTOCOL_ID,
        "protocol_tag": manifest.get("protocol_tag") == PROTOCOL_TAG,
        "case_set": [case.get("case_id") for case in manifest.get("cases", [])]
        == ["h6-1.5", "h6-3.0", "beh2-3.0"],
        "dedicated_output_root": manifest.get("output_root") == "artifacts/v4.1/multisystem",
    }

    parent = manifest["parent"]
    result_tag_commit = _git("rev-parse", f"{parent['result_tag']}^{{}}")
    checks["parent_result_tag_commit"] = result_tag_commit == parent["result_commit"]
    checks["parent_is_ancestor"] = (
        subprocess.run(
            ["git", "-C", str(ROOT), "merge-base", "--is-ancestor", parent["result_commit"], "HEAD"],
            check=False,
        ).returncode
        == 0
    )
    plan = _path(parent["plan_path"])
    checks["plan_exists"] = plan.is_file()
    checks["plan_sha256"] = plan.is_file() and _sha256(plan) == parent["plan_sha256"]

    configuration = manifest["configuration"]
    config_path = _path(configuration["path"])
    config_value = json.loads(config_path.read_text(encoding="utf-8"))
    checks["configuration_sha256"] = _sha256(config_path) == configuration["file_sha256"]
    checks["configuration_canonical_digest"] = (
        hashlib.sha256(canonical_json_bytes(config_value["configuration"])).hexdigest()
        == configuration["canonical_digest"]
    )

    observed: dict[str, dict[str, str]] = {}
    for case in manifest["cases"]:
        case_id = case["case_id"]
        checkpoint = _path(case["checkpoint_path"])
        summary_path = _path(case["v4_summary_path"])
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        checkpoint_sha = _sha256(checkpoint)
        summary_sha = _sha256(summary_path)
        internal_digest = _canonical_digest_without(summary, "summary_digest")
        observed[case_id] = {
            "checkpoint_sha256": checkpoint_sha,
            "v4_summary_sha256": summary_sha,
            "v4_summary_digest": internal_digest,
        }
        checks[f"checkpoint_sha256:{case_id}"] = checkpoint_sha == case["checkpoint_sha256"]
        checks[f"summary_sha256:{case_id}"] = summary_sha == case["v4_summary_sha256"]
        checks[f"summary_internal_digest:{case_id}"] = bool(
            summary.get("case_id") == case_id
            and summary.get("summary_digest") == case["v4_summary_digest"]
            and internal_digest == case["v4_summary_digest"]
        )

    allowed = set(manifest["allowed_change_classes"])
    forbidden = set(manifest["forbidden_change_classes"])
    checks["change_classes_disjoint"] = allowed.isdisjoint(forbidden)
    invariants = manifest["frozen_scientific_invariants"]
    checks["scientific_guards"] = bool(
        invariants["cumulative_energy_budget_hartree"] == 1e-4
        and invariants["maximum_unique_exact_attempts_per_case"] == 4
        and invariants["actual_energy_is_final_pass_fail_only"] is True
        and invariants["exact_or_fci_energy_used_in_ranking"] is False
        and invariants["molecule_specific_tuning"] is False
    )
    policy = manifest["numerical_policy"]
    checks["numerical_fail_closed"] = bool(
        policy["diagonal_equilibration_is_required"] is True
        and policy["symmetric_positive_definite_and_cholesky_required"] is True
        and policy["silent_regularization"] is False
        and policy["nonfinite_values_fail_closed"] is True
    )
    safety = manifest["execution_safety"]
    checks["execution_fail_closed"] = all(safety.values())
    checks["identity_layers"] = manifest["identity_layers"] == [
        "StatePreparationID",
        "ProblemID",
        "MeasurementContextID",
        "ConstraintSemanticID",
        "ConstraintNumericalID",
    ]

    failures = [name for name, passed in checks.items() if not passed]
    result = {
        "schema_version": "1.0.0",
        "artifact_kind": "v4.1-s0-preregistration-audit",
        "protocol_id": PROTOCOL_ID,
        "manifest_sha256": _sha256(manifest_path),
        "parent_result_commit": result_tag_commit,
        "observed_evidence": observed,
        "passed": not failures,
        "checks": checks,
        "failed_checks": failures,
        "claim_boundary": "Preregistration and immutable-parent audit only; no candidate decision or VQE execution.",
    }
    if failures:
        raise V41ProtocolError("V4.1-S0 audit failed: " + ", ".join(failures))
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--artifact-path", type=Path)
    arguments = parser.parse_args()
    result = audit_manifest(arguments.manifest)
    if arguments.artifact_path is not None:
        _write_exclusive(arguments.artifact_path, result)
    print(json.dumps({"passed": result["passed"], "checks": len(result["checks"])}, sort_keys=True))


if __name__ == "__main__":
    main()

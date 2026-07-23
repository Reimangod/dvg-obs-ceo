"""V5-S0 preregistration and immutable V4.1 parent-release audit."""

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


PROTOCOL_ID = "dvg-obs-v5-risk-aware-sequential-protocol-v1"
PROTOCOL_TAG = "dvg-obs-v5-s0-preregistration-v1"
DEFAULT_MANIFEST = ROOT / "manifests" / "v5-risk-aware-sequential-protocol-v1.json"


class V5ProtocolError(RuntimeError):
    """Raised when V5 preregistration or immutable parent evidence drifts."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _path(relative: str) -> Path:
    result = (ROOT / relative).resolve()
    try:
        result.relative_to(ROOT.resolve())
    except ValueError as error:
        raise V5ProtocolError(f"path escapes repository: {relative}") from error
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
        "schema_version": manifest.get("schema_version") == "1.0.0",
        "protocol_id": manifest.get("protocol_id") == PROTOCOL_ID,
        "protocol_tag": manifest.get("protocol_tag") == PROTOCOL_TAG,
        "development_status": manifest.get("study_status") == "development",
        "dedicated_output_root": manifest.get("output_root") == "artifacts/v5",
        "no_confirmatory_case_predeclared": manifest.get("confirmatory_cases") == [],
    }

    parent = manifest["parent"]
    parent_commit = _git("rev-parse", f"{parent['result_tag']}^{{}}")
    checks["parent_result_tag_commit"] = parent_commit == parent["result_commit"]
    checks["parent_is_ancestor"] = (
        subprocess.run(
            ["git", "-C", str(ROOT), "merge-base", "--is-ancestor", parent_commit, "HEAD"],
            check=False,
        ).returncode
        == 0
    )

    release_manifest_path = _path(parent["release_manifest_path"])
    release_manifest = json.loads(release_manifest_path.read_text(encoding="utf-8"))
    checks["release_manifest_sha256"] = (
        _sha256(release_manifest_path) == parent["release_manifest_sha256"]
    )
    checks["release_bundle_digest"] = (
        release_manifest.get("bundle_digest") == parent["release_bundle_digest"]
    )
    comparison_path = _path(parent["comparison_path"])
    comparison = json.loads(comparison_path.read_text(encoding="utf-8"))
    checks["comparison_sha256"] = _sha256(comparison_path) == parent["comparison_sha256"]
    checks["paper_measurement_cost_null"] = comparison.get("paper_measurement_cost") is None
    checks["comparison_case_coverage"] = {
        row.get("case_id") for row in comparison.get("rows", [])
    } == {"lih-3.0", "h6-1.5", "h6-3.0", "beh2-3.0"}

    plan = manifest["plan"]
    plan_path = _path(plan["path"])
    checks["plan_sha256"] = plan_path.is_file() and _sha256(plan_path) == plan["sha256"]

    observed_checkpoints: dict[str, str] = {}
    case_ids: list[str] = []
    for checkpoint_record in manifest["source_checkpoints"]:
        case_id = checkpoint_record["case_id"]
        checkpoint_path = _path(checkpoint_record["path"])
        observed_sha256 = _sha256(checkpoint_path)
        case_ids.append(case_id)
        observed_checkpoints[case_id] = observed_sha256
        checks[f"checkpoint_sha256:{case_id}"] = observed_sha256 == checkpoint_record["sha256"]
    checks["source_case_ids_unique"] = len(case_ids) == len(set(case_ids))

    development_cases = manifest["development_cases"]
    checks["all_observed_cases_are_development"] = bool(
        set(case_ids).issubset(development_cases)
        and {"h2", "h4", "lih-3.0", "h6-1.5", "h6-3.0", "beh2-3.0"}
        == set(development_cases)
    )

    invariants = manifest["scientific_invariants"]
    checks["scientific_invariants"] = bool(
        invariants["source_relative_algorithmic_energy_budget_hartree"] == 1e-4
        and invariants["target_gradient_infinity_norm_max"] == 1e-8
        and invariants["fci_or_actual_candidate_energy_used_in_screening_or_ranking"] is False
        and invariants["actual_energy_updates_budget_only_between_rounds"] is True
        and invariants["chemical_accuracy_is_benchmark_only_guard"] is True
        and invariants["barrier_free_global_compilation"] is False
        and invariants["parameter_removal_requires_physical_circuit_removal"] is True
        and invariants["measurement_cost_is_null_until_exact_definition_exists"] is True
    )

    claim_boundary = manifest["claim_boundary"]
    checks["claim_boundary"] = bool(
        claim_boundary["existing_cases_are_development_only"] is True
        and claim_boundary["unseen_generalization_requires_new_frozen_case"] is True
        and claim_boundary["global_optimum_claim"] is False
        and claim_boundary["hardware_or_noise_claim"] is False
        and claim_boundary["paper_measurement_cost_available"] is False
        and claim_boundary["end_to_end_ceo_growth_changed"] is False
    )

    checks["stage_order"] = manifest["stage_order"] == [f"S{index}" for index in range(13)]
    checks["endpoint_contract"] = bool(
        manifest["primary_endpoints"] == ["cnot_count", "parameter_count"]
        and manifest["secondary_endpoints"]
        == ["cnot_depth", "total_depth", "logical_block_count"]
    )
    checks["identity_layers"] = manifest["identity_layers"] == [
        "StatePreparationID",
        "ProblemID",
        "MeasurementContextID",
        "ConstraintSemanticID",
        "ConstraintNumericalID",
    ]
    checks["core_order"] = manifest["core_feature_order"] == [
        "nested-transactions",
        "sequential-width-1",
        "risk-aware-pareto",
        "conditional-matrix-free-hvp",
        "conditional-target-native-polishing",
        "budgeted-multi-trajectory",
    ]

    adoption = manifest["adoption_rule"]
    checks["safe_adoption"] = bool(
        adoption["retain_v4_1_when_v5_does_not_pareto_improve"] is True
        and adoption["failed_round_rolls_back_current_round_only"] is True
        and adoption["whole_path_invalidation_requires_parent_corruption_or_provenance_failure"]
        is True
        and adoption["threshold_relaxation_for_preferred_result"] is False
    )

    allowed = set(manifest["allowed_change_classes"])
    forbidden = set(manifest["forbidden_change_classes"])
    checks["change_classes_disjoint"] = allowed.isdisjoint(forbidden)
    checks["critical_forbidden_changes"] = {
        "rewrite-v4-or-v4.1-artifacts",
        "fci-or-actual-energy-ranking",
        "silent-regularization-or-retry",
        "parameter-only-resource-claim",
        "measurement-cost-relabeling",
        "ordinary-adapt-or-ceo-growth-execution",
        "barrier-free-global-compilation",
    }.issubset(forbidden)
    checks["audit_policy_fail_closed"] = all(manifest["audit_policy"].values())

    failures = [name for name, passed in checks.items() if not passed]
    result = {
        "schema_version": "1.0.0",
        "artifact_kind": "v5-s0-preregistration-audit",
        "protocol_id": PROTOCOL_ID,
        "protocol_tag": PROTOCOL_TAG,
        "manifest_sha256": _sha256(manifest_path),
        "manifest_canonical_digest": hashlib.sha256(canonical_json_bytes(manifest)).hexdigest(),
        "parent_result_commit": parent_commit,
        "parent_release_bundle_digest": release_manifest["bundle_digest"],
        "comparison_artifact_digest": comparison["artifact_digest"],
        "observed_checkpoint_sha256": observed_checkpoints,
        "passed": not failures,
        "checks": checks,
        "failed_checks": failures,
        "claim_boundary": "Preregistration and immutable V4.1-parent audit only; no V5 candidate screening or VQE execution.",
    }
    result["artifact_digest"] = _canonical_digest_without(result, "artifact_digest")
    if failures:
        raise V5ProtocolError("V5-S0 audit failed: " + ", ".join(failures))
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

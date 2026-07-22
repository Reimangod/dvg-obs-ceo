"""V4.1-S3 scale-aware numerical-certificate replay on frozen sentinels."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Callable

import numpy as np

from .baseline import ROOT
from .block_ir import CompressionCandidate, enumerate_candidates, recover_dvg_blocks
from .composition import compose_registered_candidates
from .identity import canonical_json_bytes
from .joint_prediction import (
    JointQualityPolicy,
    evaluate_joint_quality,
    joint_obs_prediction,
    secant_pairs_from_capture,
)
from .multisystem_checkpoint import _algorithm as _multisystem_algorithm
from .resources import AnsatzStructure
from .s10_lih import _algorithm as _lih_algorithm
from .v3_protocol import _write_exclusive
from .v4_1_protocol import DEFAULT_MANIFEST, audit_manifest


LIH_CHECKPOINT = ROOT / "artifacts/s10/lih-3a-first-accuracy-primary-v1-2/checkpoint.json"
LIH_V4_SUMMARY = ROOT / "artifacts/v4/s7-lih-development-v1-2/summary.json"


class V41ScaleAuditError(RuntimeError):
    """Raised when a frozen numerical sentinel cannot be replayed safely."""


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _matches_stored(candidate: CompressionCandidate, stored: dict[str, Any]) -> bool:
    return bool(
        candidate.kind == stored["kind"]
        and candidate.source_block_id == stored["source_block_id"]
        and list(candidate.target_pool_indices) == stored["target_pool_indices"]
        and list(candidate.removed_source_slots) == stored["removed_source_slots"]
        and candidate.target_family == stored["target_family"]
        and np.allclose(
            candidate.transformation.jacobian,
            np.asarray(stored["jacobian"], dtype=np.float64),
            rtol=0.0,
            atol=1e-10,
        )
    )


def _replay(
    *,
    case_id: str,
    checkpoint: dict[str, Any],
    old_summary: dict[str, Any],
    selected_old_ids: tuple[str, ...],
    algorithm_factory: Callable[[], tuple[Any, Any]],
    old_prediction: dict[str, Any] | None,
) -> dict[str, Any]:
    algorithm, pool = algorithm_factory()
    algorithm.initialize()
    source = AnsatzStructure.create(
        checkpoint["ansatz_indices"],
        checkpoint["ansatz_coefficients"],
        checkpoint["iteration_counts"],
    )
    blocks = recover_dvg_blocks(
        pool,
        source.indices,
        source.coefficients,
        source.cumulative_parameter_counts,
    )
    representatives: dict[str, CompressionCandidate] = {}
    for candidate in enumerate_candidates(pool, blocks):
        representatives.setdefault(candidate.equivalence_class_id, candidate)
    candidates = tuple(representatives.values())
    stored_catalog = {
        item["candidate_id"]: item for item in old_summary["catalog"]["candidates"]
    }
    mapped: list[CompressionCandidate] = []
    mapping: list[dict[str, str]] = []
    for old_id in selected_old_ids:
        matches = [
            candidate
            for candidate in candidates
            if _matches_stored(candidate, stored_catalog[old_id])
        ]
        if len(matches) != 1:
            raise V41ScaleAuditError(
                f"{case_id} old candidate does not map uniquely into V4.1: {old_id}"
            )
        mapped.append(matches[0])
        mapping.append({"v4_candidate_id": old_id, "v4_1_candidate_id": matches[0].candidate_id})
    plan = compose_registered_candidates(source, blocks, mapped)
    internal = secant_pairs_from_capture(
        checkpoint["hessian_capture"]["secant_pairs"], required_source="internal-bfgs"
    )
    prediction = joint_obs_prediction(
        checkpoint["ansatz_coefficients"],
        checkpoint["gradient"],
        checkpoint["recycled_inverse_hessian"],
        plan.transformation,
        internal_pairs=internal,
        held_out_pairs=(),
    )
    config = json.loads(
        (ROOT / "manifests/v4-s6-frozen-config-v1.json").read_text(encoding="utf-8")
    )["configuration"]["quality_policy"]
    quality = evaluate_joint_quality(
        prediction,
        JointQualityPolicy(
            maximum_constraint_schur_condition_number=config[
                "maximum_constraint_schur_condition_number"
            ],
            maximum_target_hessian_condition_number=config[
                "maximum_target_hessian_condition_number"
            ],
            minimum_constraint_direction_coverage=config[
                "minimum_constraint_direction_coverage"
            ],
            maximum_internal_projected_residual=config[
                "maximum_internal_projected_residual"
            ],
            maximum_held_out_projected_residual=1e12,
            require_held_out_evidence=False,
            target_hessian_condition_is_scientific_gate=False,
            maximum_equilibrated_target_hessian_condition_number=1e12,
            maximum_target_hessian_relative_solve_residual=1e-10,
            maximum_target_hessian_relative_backward_error=1e-10,
        ),
    )
    prediction_delta = None
    if old_prediction is not None:
        prediction_delta = float(
            prediction["predicted_change_from_current_hartree"]
            - old_prediction["predicted_change_from_current_hartree"]
        )
        if abs(prediction_delta) > 1e-10:
            raise V41ScaleAuditError(
                f"{case_id} physical OBS prediction changed by {prediction_delta}"
            )
    if not quality["passed"]:
        failed = [name for name, passed in quality["checks"].items() if not passed]
        raise V41ScaleAuditError(f"{case_id} sentinel quality failed: {failed}")
    return {
        "case_id": case_id,
        "candidate_id_mapping": mapping,
        "constraint_semantic_id": plan.state.constraint_semantic_id,
        "predicted_change_from_current_hartree": prediction[
            "predicted_change_from_current_hartree"
        ],
        "v4_prediction_delta_hartree": prediction_delta,
        "diagnostics": prediction["diagnostics"],
        "quality": quality,
        "actual_or_exact_energy_used": False,
        "passed": True,
    }


def run(manifest_path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    s0 = audit_manifest(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    h6_record = next(case for case in manifest["cases"] if case["case_id"] == "h6-1.5")
    h6_summary = json.loads((ROOT / h6_record["v4_summary_path"]).read_text(encoding="utf-8"))
    h6_checkpoint = json.loads((ROOT / h6_record["checkpoint_path"]).read_text(encoding="utf-8"))
    h6_rejection = h6_summary["quality_rejections"][0]
    h6_record_match = next(
        record
        for record in h6_summary["search"]["records"]
        if record["candidate_ids"] == h6_rejection["candidate_ids"]
    )
    h6_old_prediction = {
        "predicted_change_from_current_hartree": h6_record_match["evaluation"][
            "predicted_loss_hartree"
        ]
    }
    h6 = _replay(
        case_id="h6-1.5-sentinel",
        checkpoint=h6_checkpoint,
        old_summary=h6_summary,
        selected_old_ids=tuple(h6_rejection["candidate_ids"]),
        algorithm_factory=lambda: _multisystem_algorithm(h6_checkpoint["case"]),
        old_prediction=h6_old_prediction,
    )

    lih_checkpoint = json.loads(LIH_CHECKPOINT.read_text(encoding="utf-8"))
    lih_summary = json.loads(LIH_V4_SUMMARY.read_text(encoding="utf-8"))
    accepted = next(
        attempt for attempt in lih_summary["attempts"] if attempt["transaction_status"] == "accepted"
    )
    lih = _replay(
        case_id="lih-3.0-v4-accepted",
        checkpoint=lih_checkpoint,
        old_summary=lih_summary,
        selected_old_ids=tuple(accepted["candidate_ids"]),
        algorithm_factory=lambda: _lih_algorithm()[:2],
        old_prediction=accepted["prediction"],
    )
    result: dict[str, Any] = {
        "schema_version": "1.0.0",
        "artifact_kind": "v4.1-s3-scale-aware-certificate-audit",
        "protocol_id": manifest["protocol_id"],
        "s0_manifest_sha256": s0["manifest_sha256"],
        "sentinels": [lih, h6],
        "source_inverse_hessian_modified": False,
        "molecule_specific_thresholds": False,
        "actual_or_exact_energy_used": False,
        "passed": True,
        "claim_boundary": (
            "Frozen-candidate quadratic replay only; no search reranking, exact energy, "
            "optimizer, resource selection, or VQE execution."
        ),
    }
    result["artifact_digest"] = _digest(result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--artifact-path", type=Path)
    arguments = parser.parse_args()
    result = run(arguments.manifest)
    if arguments.artifact_path is not None:
        _write_exclusive(arguments.artifact_path, result)
    print(json.dumps({"passed": result["passed"], "sentinels": len(result["sentinels"])}, sort_keys=True))


if __name__ == "__main__":
    main()

"""S8 nonzero-gradient OBS adapter, Pareto screen, and atomic freeze."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
import struct
import sys
from typing import Any, Mapping, Sequence

import numpy as np
from numpy.typing import NDArray

from dvg_obs_ceo.artifact_io import atomic_write_new_json
from dvg_obs_ceo.baseline import ROOT, _load_upstream
from dvg_obs_ceo.identity import sha256_hex
from dvg_obs_ceo.quadratic import (
    ConstraintTargetIR,
    QuadraticModel,
    predict_constrained_optimum,
    quadratic_change,
    solve_spd,
    validate_spd,
)
from dvg_obs_ceo.resources import AnsatzStructure
from dvg_obs_ceo.telemetry import ResourceSnapshot
from dvg_obs_ceo.v5_pareto import (
    RiskAwareCandidate,
    RiskDiagnostics,
    candidate_to_record,
    select_risk_aware_pareto,
)

from .exact_rewrite_engine import (
    RewriteRuleKind,
    apply_proposal,
    default_registry,
    enumerate_proposals,
    state_digest,
)


FloatArray = NDArray[np.float64]
DEFAULT_S6 = ROOT / "artifacts/v6/s6/exact-rewrite-trace-v1.json"
DEFAULT_S7 = ROOT / "artifacts/v6/s7/rank-candidate-catalog-v1.json"
DEFAULT_MODEL = ROOT / "artifacts/v4.1/multisystem/h6-1.5/summary.json"
DEFAULT_OUTPUT = ROOT / "artifacts/v6/s8/predictor-candidate-freeze-v1.json"
ADAPTER_VERSION = "v6-exact-rewrite-pullback-obs-adapter-v1"
SELECTOR_VERSION = "v6-development-pareto-freeze-v1"


class PredictorFreezeError(RuntimeError):
    """Raised when predictor adaptation or candidate freezing is unsafe."""


@dataclass(frozen=True)
class S8Config:
    screening_budget_hartree: float = 1e-4
    top_k_per_endpoint: int = 2
    maximum_unique_attempts: int = 2
    maximum_predictor_calls: int = 3
    require_no_component_regression: bool = False

    def __post_init__(self) -> None:
        if (
            not math.isfinite(self.screening_budget_hartree)
            or self.screening_budget_hartree < 0.0
            or self.top_k_per_endpoint <= 0
            or self.maximum_unique_attempts <= 0
            or self.maximum_predictor_calls <= 0
            or not isinstance(self.require_no_component_regression, bool)
        ):
            raise PredictorFreezeError("invalid S8 screening configuration")


def _decode_float64(value: str) -> float:
    if not isinstance(value, str) or len(value) != 16:
        raise PredictorFreezeError("invalid canonical float64 bytes")
    try:
        return struct.unpack(">d", bytes.fromhex(value))[0]
    except (ValueError, struct.error) as error:
        raise PredictorFreezeError("invalid canonical float64 bytes") from error


def _structure(value: Mapping[str, Any]) -> AnsatzStructure:
    return AnsatzStructure.create(
        value["indices"],
        [_decode_float64(item) for item in value["coefficient_float64_hex"]],
        value["iteration_counts"],
    )


def _extract_recycled_model(
    primary: Mapping[str, Any],
) -> QuadraticModel:
    """Read only the preregistered model fields from a legacy result record."""

    try:
        theta = primary["coordinates"]
        gradient = primary["gradient"]
        inverse_hessian = primary["final_inverse_hessian"]
    except KeyError as error:
        raise PredictorFreezeError(
            "recycled model field is missing"
        ) from error
    return QuadraticModel.create(theta, gradient, inverse_hessian)


def _fusion_forward_matrix(size: int, candidate: Any) -> FloatArray:
    if (
        candidate.source_parameter_count
        != candidate.target_parameter_count + 1
        or candidate.source_parameter_count
        != 1 + len(candidate.mvp_positions)
    ):
        raise PredictorFreezeError("fusion dimensions are inconsistent")
    position = int(candidate.ovp_position)
    if not 0 <= position < size:
        raise PredictorFreezeError("fusion removal position is outside state")
    matrix = np.zeros((size - 1, size), dtype=np.float64)
    for old_position in range(size):
        if old_position < position:
            matrix[old_position, old_position] = 1.0
        elif old_position > position:
            matrix[old_position - 1, old_position] = 1.0
    for mvp_position, weight in zip(
        candidate.mvp_positions,
        candidate.exact_signed_relation,
    ):
        target_position = (
            mvp_position if mvp_position < position else mvp_position - 1
        )
        matrix[target_position, position] += float(weight)
    return matrix


@dataclass(frozen=True)
class PulledBackModel:
    model: QuadraticModel
    forward_map: FloatArray
    old_source: AnsatzStructure
    new_source: AnsatzStructure
    provenance: Mapping[str, Any]


def build_pulled_back_model(
    pool: Any,
    s6_artifact: Mapping[str, Any],
    legacy_primary: Mapping[str, Any],
) -> PulledBackModel:
    if (
        s6_artifact.get("complete") is not True
        or s6_artifact.get("stop_reason") != "SATURATED"
    ):
        raise PredictorFreezeError("S6 parent is incomplete")
    model = _extract_recycled_model(legacy_primary)
    current = _structure(s6_artifact["source"])
    target = _structure(s6_artifact["target"])
    if (
        model.theta.size != len(current.indices)
        or not np.array_equal(model.theta, np.asarray(current.coefficients))
    ):
        raise PredictorFreezeError(
            "legacy quadratic model does not bind the S6 source coordinates"
        )
    registry, _ = default_registry(maximum_corridor_blocks=16)
    forward = np.eye(model.theta.size, dtype=np.float64)
    accepted_ids = []
    for step in sorted({int(item["step"]) for item in s6_artifact["trace"]}):
        accepted = [
            item
            for item in s6_artifact["trace"]
            if int(item["step"]) == step and item["accepted"]
        ]
        if not accepted:
            continue
        if len(accepted) != 1:
            raise PredictorFreezeError(
                "S6 step has an ambiguous accepted rewrite"
            )
        proposals = {
            item.proposal_id: item
            for item in enumerate_proposals(pool, current, registry)
        }
        try:
            proposal = proposals[accepted[0]["proposal_id"]]
        except KeyError as error:
            raise PredictorFreezeError(
                "accepted S6 proposal cannot be replayed"
            ) from error
        if proposal.kind is not RewriteRuleKind.OVP_MVP_ABSORPTION:
            raise PredictorFreezeError(
                "S8 adapter has no registered pullback for this rewrite kind"
            )
        step_map = _fusion_forward_matrix(
            len(current.indices),
            proposal.application,
        )
        forward = step_map @ forward
        current = apply_proposal(pool, current, proposal)
        accepted_ids.append(proposal.proposal_id)
    if (
        state_digest(current) != state_digest(target)
        or state_digest(target) != s6_artifact["target_state_digest"]
    ):
        raise PredictorFreezeError("S6 replay did not recover its target")
    mapped = forward @ model.theta
    mapping_residual = float(
        np.max(np.abs(mapped - np.asarray(target.coefficients)))
    )
    if mapping_residual != 0.0:
        raise PredictorFreezeError(
            "exact rewrite forward map does not reproduce S6 coordinates"
        )

    # Diagnostic only: demonstrate why directly relocating the recycled
    # Hessian to a zero-OVP gauge is not used for screening.
    embedding = np.linalg.pinv(forward)
    gauge_point = embedding @ np.asarray(target.coefficients)
    gauge_residual = float(
        np.max(np.abs(forward @ gauge_point - target.coefficients))
    )
    if gauge_residual > 1e-12:
        raise PredictorFreezeError("canonical gauge diagnostic is infeasible")
    gauge_model_change = quadratic_change(model, gauge_point)
    hessian = solve_spd(
        model.inverse_hessian,
        np.eye(model.theta.size, dtype=np.float64),
    )
    gauge_gradient = model.gradient + hessian @ (gauge_point - model.theta)
    provenance = {
        "adapter_version": ADAPTER_VERSION,
        "legacy_model_dimension": model.theta.size,
        "s6_dimension": len(target.indices),
        "accepted_exact_rewrite_proposal_ids": accepted_ids,
        "forward_map_digest": sha256_hex(forward.tolist()),
        "forward_map_rank": int(np.linalg.matrix_rank(forward)),
        "forward_mapping_residual_infinity": mapping_residual,
        "legacy_inverse_hessian_condition_number": (
            validate_spd(model.inverse_hessian).condition_number
        ),
        "legacy_gradient_infinity": float(
            np.max(np.abs(model.gradient))
        ),
        "rejected_direct_transport_diagnostic": {
            "canonical_gauge_displacement_l2": float(
                np.linalg.norm(gauge_point - model.theta)
            ),
            "recycled_quadratic_change_hartree": gauge_model_change,
            "relocated_gradient_infinity": float(
                np.max(np.abs(gauge_gradient))
            ),
            "decision": (
                "REJECT_DIRECT_HESSIAN_TRANSPORT_USE_CONSTRAINT_PULLBACK"
            ),
            "ranking_influence": False,
        },
    }
    return PulledBackModel(model, forward, _structure(s6_artifact["source"]), target, provenance)


def _constraint_parameterization(
    row: FloatArray,
    *,
    candidate_id: str,
) -> ConstraintTargetIR:
    vector = np.asarray(row, dtype=np.float64)
    if vector.ndim != 1 or not np.all(np.isfinite(vector)):
        raise PredictorFreezeError("pulled-back constraint row is invalid")
    nonzero = np.flatnonzero(vector)
    if nonzero.size == 0:
        raise PredictorFreezeError("pulled-back constraint is identically zero")
    pivot = int(nonzero[np.argmax(np.abs(vector[nonzero]))])
    columns = []
    target_slots = []
    for position in range(vector.size):
        if position == pivot:
            continue
        column = np.zeros(vector.size, dtype=np.float64)
        column[position] = 1.0
        column[pivot] = -vector[position] / vector[pivot]
        columns.append(column)
        target_slots.append(f"{candidate_id}:target:{position}")
    jacobian = np.column_stack(columns)
    return ConstraintTargetIR.create(
        constraint_matrix=vector.reshape(1, -1),
        constraint_rhs=np.zeros(1),
        offset=np.zeros(vector.size),
        jacobian=jacobian,
        source_slots=tuple(
            f"legacy-source-parameter:{index}"
            for index in range(vector.size)
        ),
        target_slots=tuple(target_slots),
        generator_normalization="paper-era-pool-arrange-v1",
        orientation="v6-exact-rewrite-pulled-back-rank-demotion",
    )


def _snapshot(
    value: Mapping[str, Any],
    digest: str,
    *,
    counter_version: str | None = None,
) -> ResourceSnapshot:
    return ResourceSnapshot(
        cnot_count=int(value["cnot_count"]),
        cnot_depth=int(value["cnot_depth"]),
        total_depth=int(value["total_depth"]),
        parameter_count=int(value["parameter_count"]),
        logical_block_count=int(value["logical_block_count"]),
        counter_version=(
            counter_version
            if counter_version is not None
            else value["counter_version"]
        ),
        structure_digest=digest,
    )


def build_prediction_records(
    pulled_back: PulledBackModel,
    s7_artifact: Mapping[str, Any],
    config: S8Config,
) -> tuple[list[dict[str, Any]], list[RiskAwareCandidate]]:
    candidates = list(s7_artifact["candidates"])
    if len(candidates) > config.maximum_predictor_calls:
        raise PredictorFreezeError(
            "predictor-call cap is smaller than the frozen candidate catalog"
        )
    if s7_artifact["source_state_digest"] != state_digest(
        pulled_back.new_source
    ):
        raise PredictorFreezeError("S7 catalog and predictor source differ")
    records = []
    risk_candidates = []
    for item in sorted(candidates, key=lambda value: value["candidate_id"]):
        if (
            item["screening_status"]
            != "ELIGIBLE_NATIVE_PHYSICAL_GAIN"
            or item["energy_evaluated"] is not False
        ):
            raise PredictorFreezeError(
                "S8 input candidate is ineligible or outcome-contaminated"
            )
        omitted_position = item["source_ansatz_positions"][
            item["omitted_source_slot"]
        ]
        row = pulled_back.forward_map[omitted_position]
        transformation = _constraint_parameterization(
            row,
            candidate_id=item["candidate_id"],
        )
        prediction = predict_constrained_optimum(
            pulled_back.model,
            transformation,
        )
        predicted_loss = max(
            0.0,
            float(prediction.predicted_change_from_current),
        )
        semantic_payload = {
            "adapter_version": ADAPTER_VERSION,
            "candidate_id": item["candidate_id"],
            "constraint_row": row.tolist(),
            "constraint_rhs": 0,
        }
        semantic_id = "constraint-semantic-v6:" + sha256_hex(
            semantic_payload
        )
        numerical_payload = {
            **semantic_payload,
            "source_theta_digest": sha256_hex(
                pulled_back.model.theta.tolist()
            ),
            "source_gradient_digest": sha256_hex(
                pulled_back.model.gradient.tolist()
            ),
            "source_inverse_hessian_digest": sha256_hex(
                pulled_back.model.inverse_hessian.tolist()
            ),
        }
        numerical_id = "constraint-numerical-v6:" + sha256_hex(
            numerical_payload
        )
        resources = item["resources"]["after"]
        resource_evidence = item["resources"]
        snapshot = _snapshot(
            resources,
            resource_evidence["after_digest"],
            counter_version=resource_evidence["resource_counter_version"],
        )
        diagnostic_payload = {
            "candidate_id": item["candidate_id"],
            "constraint_residual_infinity": (
                prediction.constraint_residual_infinity
            ),
            "direct_formula_difference": abs(
                prediction.predicted_change_from_current
                - prediction.direct_quadratic_change_from_current
            ),
            "calibration_status": "PENDING_S11",
        }
        risk = RiskAwareCandidate(
            candidate_ids=(item["candidate_id"],),
            constraint_semantic_id=semantic_id,
            constraint_numerical_id=numerical_id,
            predicted_loss_hartree=predicted_loss,
            resources=snapshot,
            diagnostics=RiskDiagnostics(
                quality_gate_passed=True,
                uncertainty_margin_hartree=0.0,
                quality_stratum="boundary",
                refinement_required=True,
                evidence_digest=sha256_hex(diagnostic_payload),
            ),
            full_resource_recount_succeeded=True,
            semantics_validated=True,
        )
        record = {
            "candidate_id": item["candidate_id"],
            "constraint_semantic_id": semantic_id,
            "constraint_numerical_id": numerical_id,
            "pulled_back_constraint_nonzero_positions": (
                np.flatnonzero(row).tolist()
            ),
            "predicted_constraint_penalty_hartree": float(
                prediction.predicted_constraint_penalty
            ),
            "predicted_change_from_current_hartree": float(
                prediction.predicted_change_from_current
            ),
            "predicted_loss_hartree": predicted_loss,
            "constraint_residual_infinity": (
                prediction.constraint_residual_infinity
            ),
            "risk_record": candidate_to_record(risk),
            "uncertainty_interpretation": (
                "Numeric margin is zero because empirical calibration is "
                "pending, not because predictor uncertainty is proven zero."
            ),
            "actual_or_fci_energy_used": False,
        }
        records.append(record)
        risk_candidates.append(risk)
    return records, risk_candidates


def select_frozen_candidates(
    candidates: Sequence[RiskAwareCandidate],
    source: ResourceSnapshot,
    config: S8Config,
) -> dict[str, Any]:
    selection = select_risk_aware_pareto(
        tuple(candidates),
        source,
        screening_budget_hartree=config.screening_budget_hartree,
        top_k_per_endpoint=config.top_k_per_endpoint,
        maximum_unique_attempts=config.maximum_unique_attempts,
        require_no_component_regression=(
            config.require_no_component_regression
        ),
    )
    by_semantic = {
        item.constraint_semantic_id: item.candidate_ids[0]
        for item in candidates
    }
    frozen_ids = [
        by_semantic[item]
        for item in selection["unique_attempt_semantic_ids"]
    ]
    return {
        "selection": selection,
        "frozen_candidate_ids": frozen_ids,
        "frozen_candidate_count": len(frozen_ids),
        "freeze_digest": sha256_hex(
            {
                "selector_version": SELECTOR_VERSION,
                "config": asdict(config),
                "source_structure_digest": source.structure_digest,
                "selection_digest": selection["selection_digest"],
                "frozen_candidate_ids": frozen_ids,
            }
        ),
    }


def build_report(
    s6_path: Path = DEFAULT_S6,
    s7_path: Path = DEFAULT_S7,
    model_path: Path = DEFAULT_MODEL,
    config: S8Config = S8Config(),
) -> dict[str, Any]:
    _, DVG_CEO, _, _ = _load_upstream()
    s6 = json.loads(s6_path.read_text(encoding="utf-8"))
    s7 = json.loads(s7_path.read_text(encoding="utf-8"))
    legacy = json.loads(model_path.read_text(encoding="utf-8"))
    attempt = next(
        item
        for item in legacy["attempts"]
        if item["attempt_number"] == 1
        and item["transaction_status"] == "accepted"
    )
    pulled_back = build_pulled_back_model(
        DVG_CEO(n=12),
        s6,
        attempt["primary"],
    )
    prediction_records, candidates = build_prediction_records(
        pulled_back,
        s7,
        config,
    )
    source = _snapshot(
        s7["source_recount"],
        s7["source_recount"]["circuit_qasm_digest"],
    )
    frozen = select_frozen_candidates(candidates, source, config)
    report = {
        "schema_version": "1.0.0",
        "artifact_kind": "v6-s8-predictor-candidate-freeze",
        "development_only": True,
        "adapter_version": ADAPTER_VERSION,
        "selector_version": SELECTOR_VERSION,
        "config": asdict(config),
        "inputs": {
            "s6": {
                "path": str(s6_path.relative_to(ROOT)),
                "sha256": hashlib.sha256(s6_path.read_bytes()).hexdigest(),
            },
            "s7": {
                "path": str(s7_path.relative_to(ROOT)),
                "sha256": hashlib.sha256(s7_path.read_bytes()).hexdigest(),
            },
            "legacy_model": {
                "path": str(model_path.relative_to(ROOT)),
                "sha256": hashlib.sha256(
                    model_path.read_bytes()
                ).hexdigest(),
                "fields_read": [
                    "coordinates",
                    "gradient",
                    "final_inverse_hessian",
                ],
            },
        },
        "model_adapter": dict(pulled_back.provenance),
        "prediction_records": prediction_records,
        **frozen,
        "information_firewall": {
            "actual_candidate_energy_available": False,
            "fci_reference_available": False,
            "candidate_outcomes_can_change_current_freeze": False,
            "legacy_energy_field_read": False,
            "poisoning_contract": (
                "Only coordinates, gradient, and final_inverse_hessian are "
                "read from the legacy primary record; screening records "
                "recursively reject actual and FCI fields."
            ),
        },
        "work": {
            "exact_rewrite_replays": len(
                pulled_back.provenance[
                    "accepted_exact_rewrite_proposal_ids"
                ]
            ),
            "quadratic_predictor_calls": len(prediction_records),
            "full_resource_recounts": 0,
            "energy_evaluations": 0,
            "gradient_vector_evaluations": 0,
            "hvp_evaluations": 0,
            "optimizer_starts": 0,
            "paper_measurement_cost": None,
        },
        "claim_boundary": (
            "Development-only quadratic prediction and immutable candidate "
            "freeze. The recycled model is approximate, empirical uncertainty "
            "is pending S11 calibration, and no candidate energy, accuracy, "
            "matched-work, or paper Measurement Cost result is established."
        ),
        "paper_measurement_cost": None,
    }
    report["report_digest"] = sha256_hex(report)
    return report


def main() -> None:
    try:
        report = build_report()
        atomic_write_new_json(DEFAULT_OUTPUT, report)
    except (
        ImportError,
        KeyError,
        OSError,
        TypeError,
        ValueError,
        PredictorFreezeError,
    ) as error:
        print(f"V6 S8 predictor freeze failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    print(
        json.dumps(
            {
                "frozen_candidate_ids": report["frozen_candidate_ids"],
                "freeze_digest": report["freeze_digest"],
                "report_digest": report["report_digest"],
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()

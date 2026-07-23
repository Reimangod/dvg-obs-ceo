"""Outcome-blind H4 resource-potential analysis for V5-S8.

The all-candidate fresh Hessian is an explicit diagnostic oracle.  It is not a
deployable V5 implementation.  Candidate selection is serialized before stored
exact outcomes are joined, and tests verify that outcome perturbations cannot
change the frozen queue.
"""

from __future__ import annotations

from dataclasses import asdict
import glob
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .identity import canonical_json_bytes
from .telemetry import ResourceSnapshot
from .v5_pareto import RiskAwareCandidate, RiskDiagnostics, select_risk_aware_pareto


ANALYZER_VERSION = "v5-s8-h4-resource-potential-v1"
RESOURCE_FIELDS = (
    "cnot_count",
    "cnot_depth",
    "total_depth",
    "parameter_count",
    "logical_block_count",
)


class V5S8ResourcePotentialError(ValueError):
    """Raised when reused calibration evidence is incomplete or inconsistent."""


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _final_resource(row: Mapping[str, Any]) -> ResourceSnapshot:
    path = row["paths"]["projection_on"]
    resource = path["resources"]
    # ``segments`` is an ADAPT-iteration trace, not the terminal circuit
    # snapshot: its length is not a block count and its last parameter count
    # is local to that trace.  The persisted snapshot is the authoritative
    # five-axis full-circuit recount.
    snapshot = resource.get("snapshot")
    if not isinstance(snapshot, Mapping):
        raise V5S8ResourcePotentialError("authoritative resource snapshot is absent")
    authoritative = ResourceSnapshot(**snapshot)
    if (
        authoritative.cnot_count != int(resource["cnot_count_by_iteration"][-1])
        or authoritative.cnot_depth != int(resource["cnot_depth_by_iteration"][-1])
        or authoritative.total_depth != int(resource["total_depth_by_iteration"][-1])
    ):
        raise V5S8ResourcePotentialError("snapshot and iteration trace disagree")
    return authoritative


def _source_resource(row: Mapping[str, Any], target: ResourceSnapshot) -> ResourceSnapshot:
    delta = row["paths"]["projection_on"]["resource_delta"]
    values = {
        field: int(getattr(target, field) - int(delta[field]))
        for field in RESOURCE_FIELDS
    }
    payload = {
        "counter_version": target.counter_version,
        # The source digest is absent from legacy candidate rows.  Bind the
        # reconstructed counts and the checkpoint digest instead of inventing it.
        "structure_digest": _digest({
            "checkpoint_digest": row["checkpoint_digest"],
            "counter_version": target.counter_version,
            "resources": values,
        }),
        **values,
    }
    return ResourceSnapshot(**payload)


def _row_by_candidate(rows_directory: Path, prefix: str) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for name in sorted(glob.glob(str(rows_directory / f"{prefix}*.json"))):
        row = _load(Path(name))
        candidate_id = str(row["candidate"]["candidate_id"])
        if candidate_id in result:
            raise V5S8ResourcePotentialError(f"duplicate candidate row: {candidate_id}")
        result[candidate_id] = row
    return result


def _clean_candidate(
    oracle: Mapping[str, Any], row: Mapping[str, Any]
) -> RiskAwareCandidate:
    target = _final_resource(row)
    candidate_id = str(oracle["candidate_id"])
    damping = float(oracle["selected_damping"])
    evidence = {
        "candidate_id": candidate_id,
        "solver_status": oracle["status"],
        "selected_damping": damping,
        "minimum_feasible_curvature": oracle["minimum_feasible_curvature"],
        "work": oracle["work"],
    }
    return RiskAwareCandidate(
        candidate_ids=(candidate_id,),
        constraint_semantic_id="constraint-semantic-" + _digest({
            "candidate": row["candidate"], "identity_role": "semantic"
        }),
        constraint_numerical_id="constraint-numerical-" + _digest({
            "candidate_id": candidate_id,
            "numerical_context_digest": row["candidate"]["numerical_context_digest"],
            "selected_damping": damping,
        }),
        predicted_loss_hartree=float(oracle["fresh_hessian_prediction_hartree"]),
        resources=target,
        diagnostics=RiskDiagnostics(
            quality_gate_passed=True,
            uncertainty_margin_hartree=0.0,
            quality_stratum="good" if damping <= 1e-8 else "boundary",
            refinement_required=damping > 1e-8,
            evidence_digest=_digest(evidence),
        ),
        full_resource_recount_succeeded=bool(
            row["paths"]["projection_on"]["resource_recount_consistent"]
        ),
        semantics_validated=True,
    )


def _deltas(source: ResourceSnapshot, target: ResourceSnapshot) -> dict[str, int]:
    return {field: int(getattr(target, field) - getattr(source, field)) for field in RESOURCE_FIELDS}


def _selected_candidate_ids(
    selection: Mapping[str, Any], candidates: Sequence[RiskAwareCandidate]
) -> list[str]:
    by_semantic = {candidate.constraint_semantic_id: candidate for candidate in candidates}
    return [
        by_semantic[semantic_id].candidate_ids[0]
        for semantic_id in selection["unique_attempt_semantic_ids"]
    ]


def build_h4_resource_potential(
    *,
    oracle_artifact: Mapping[str, Any],
    rows: Mapping[str, Mapping[str, Any]],
    screening_budget_hartree: float,
    maximum_unique_attempts: int = 4,
) -> dict[str, Any]:
    """Build a diagnostic queue, then join outcomes behind a digest firewall."""

    if oracle_artifact.get("passed") is not True:
        raise V5S8ResourcePotentialError("HVP oracle artifact did not pass")
    solved = [record for record in oracle_artifact["oracle_records"] if record["status"] == "solved"]
    if not solved:
        raise V5S8ResourcePotentialError("no solved oracle candidate")
    missing = sorted({str(record["candidate_id"]) for record in solved} - set(rows))
    if missing:
        raise V5S8ResourcePotentialError(f"missing candidate rows: {missing[:3]}")

    candidates = [_clean_candidate(record, rows[str(record["candidate_id"])]) for record in solved]
    sources = [
        _source_resource(rows[candidate.candidate_ids[0]], candidate.resources)
        for candidate in candidates
    ]
    source_signatures = {
        tuple(getattr(source, field) for field in (*RESOURCE_FIELDS, "counter_version"))
        for source in sources
    }
    if len(source_signatures) != 1:
        raise V5S8ResourcePotentialError("candidate rows reconstruct conflicting source resources")
    source = sources[0]

    selection = select_risk_aware_pareto(
        candidates,
        source,
        screening_budget_hartree=screening_budget_hartree,
        maximum_unique_attempts=maximum_unique_attempts,
        require_no_component_regression=True,
    )
    selected_ids = _selected_candidate_ids(selection, candidates)
    prereveal = {
        "analyzer_version": ANALYZER_VERSION,
        "evidence_role": "explicit-fresh-hessian-diagnostic-oracle-not-deployable-v5",
        "source_resources": asdict(source),
        "selection": selection,
        "selected_candidate_ids": selected_ids,
        "selected_resource_deltas": {
            candidate.candidate_ids[0]: _deltas(source, candidate.resources)
            for candidate in candidates if candidate.candidate_ids[0] in selected_ids
        },
    }
    prereveal_digest = _digest(prereveal)

    oracle_by_id = {str(record["candidate_id"]): record for record in solved}
    posthoc = [
        {
            "candidate_id": candidate_id,
            "actual_change_hartree": oracle_by_id[candidate_id]["posthoc_actual_change_hartree"],
            "complete_safe": oracle_by_id[candidate_id]["posthoc_complete_safe"],
            "resource_delta": prereveal["selected_resource_deltas"][candidate_id],
        }
        for candidate_id in selected_ids
    ]
    result: dict[str, Any] = {
        "schema_version": "1.0.0",
        "artifact_kind": "v5-s8-h4-resource-potential",
        "claim_boundary": [
            "All-candidate explicit fresh Hessian is a development diagnostic oracle, not deployable V5.",
            "The queue digest excludes stored exact outcomes; outcomes are joined only post hoc.",
            "Resource counts use paper-era-full-circuit-resource-v1; optimizer dimension is not a circuit parameter count.",
            "No molecular superiority or measurement-cost claim is supported.",
        ],
        "prereveal": prereveal,
        "prereveal_digest": prereveal_digest,
        "posthoc_selected_outcomes": posthoc,
        "summary": {
            "input_candidate_count": len(oracle_artifact["oracle_records"]),
            "solved_candidate_count": len(candidates),
            "selected_attempt_count": len(selected_ids),
            "selected_safe_count": sum(item["complete_safe"] is True for item in posthoc),
            "selected_false_safe_count": sum(item["complete_safe"] is not True for item in posthoc),
        },
        "paper_measurement_cost": None,
    }
    result["result_digest"] = _digest(result)
    return result


def run(root: Path) -> dict[str, Any]:
    protocol = _load(root / "manifests/v5-s8-calibration-protocol-v1.json")
    h4_input = next(item for item in protocol["inputs"] if item["case_id"] == "h4-1.5-iteration-12-or-convergence")
    rows = _row_by_candidate(root / h4_input["rows_directory"], h4_input["row_prefix"])
    result = build_h4_resource_potential(
        oracle_artifact=_load(root / "artifacts/v5/s8/h4-hvp-sentinels-damped.json"),
        rows=rows,
        screening_budget_hartree=float(protocol["fixed_scientific_gates"]["source_relative_energy_budget_hartree"]),
    )
    output = root / "artifacts/v5/s8/h4-resource-potential.json"
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    run(Path(__file__).resolve().parents[2])

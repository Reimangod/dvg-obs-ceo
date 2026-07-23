"""Independent synthetic audit for the V5-S4 risk-aware selector."""

from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import json
from pathlib import Path
from typing import Any

from .identity import sha256_hex
from .telemetry import ResourceSnapshot
from .v3_protocol import _write_exclusive
from .v5_pareto import (
    RiskAwareCandidate,
    RiskDiagnostics,
    V5ParetoError,
    candidate_from_record,
    candidate_to_record,
    select_quality_sentinels,
    select_risk_aware_pareto,
)


def _resources(values: tuple[int, int, int, int, int], label: str) -> ResourceSnapshot:
    cnot, cnot_depth, depth, parameters, blocks = values
    return ResourceSnapshot(
        cnot, cnot_depth, depth, parameters, blocks,
        "v5-s4-audit-counter-v1", sha256_hex({"label": label, "values": values}),
    )


def _candidate(
    label: str,
    values: tuple[int, int, int, int, int],
    loss: float,
    margin: float,
    stratum: str,
    *,
    quality: bool = True,
) -> RiskAwareCandidate:
    return RiskAwareCandidate(
        (f"candidate-v5:{sha256_hex(label)}",),
        f"constraint-semantic-v1:{sha256_hex({'semantic': label})}",
        f"constraint-numerical-v1:{sha256_hex({'numerical': label})}",
        loss,
        _resources(values, label),
        RiskDiagnostics(quality, margin, stratum, stratum != "good", sha256_hex({"evidence": label})),
    )


def run_audit() -> dict[str, Any]:
    source = _resources((100, 50, 160, 12, 10), "source")
    candidates = (
        _candidate("a", (70, 43, 125, 10, 9), 0.0, 1e-6, "good"),
        _candidate("b", (65, 47, 130, 11, 9), 2e-5, 2e-6, "boundary"),
        _candidate("c", (75, 40, 120, 9, 8), 1e-5, 4e-5, "poor", quality=False),
        _candidate("regression", (60, 52, 110, 8, 7), 1e-6, 0.0, "good"),
        _candidate("no-benefit", (100, 50, 160, 12, 10), 1e-6, 0.0, "good"),
    )
    forward = select_risk_aware_pareto(candidates, source)
    reverse = select_risk_aware_pareto(tuple(reversed(candidates)), source)

    scale = 7
    scaled_source = _resources(tuple(value * scale for value in (100, 50, 160, 12, 10)), "scaled-source")
    scaled_candidates = tuple(
        replace(
            candidate,
            resources=_resources(
                tuple(value * scale for value in (
                    candidate.resources.cnot_count,
                    candidate.resources.cnot_depth,
                    candidate.resources.total_depth,
                    candidate.resources.parameter_count,
                    candidate.resources.logical_block_count,
                )),
                "scaled-" + candidate.constraint_semantic_id,
            ),
        )
        for candidate in candidates
    )
    scaled = select_risk_aware_pareto(scaled_candidates, scaled_source)
    sentinel = select_quality_sentinels(candidates, source, screening_budget_hartree=1e-4)

    poison_rejected = 0
    base = candidate_to_record(candidates[0])
    for poisoned in (
        {**base, "actual_energy_hartree": -1.0},
        {**base, "diagnostics": {**base["diagnostics"], "nested_fci_reference": -1.1}},
    ):
        try:
            candidate_from_record(poisoned)
        except V5ParetoError:
            poison_rejected += 1

    assessments = {item["constraint_semantic_id"]: item for item in forward["assessments"]}
    regression_id = candidates[3].constraint_semantic_id
    no_benefit_id = candidates[4].constraint_semantic_id
    poor_id = candidates[2].constraint_semantic_id
    checks = {
        "candidate_order_permutation_invariant": (
            forward["unique_attempt_semantic_ids"] == reverse["unique_attempt_semantic_ids"]
            and forward["pareto_semantic_ids"] == reverse["pareto_semantic_ids"]
        ),
        "positive_resource_scaling_invariant": (
            forward["unique_attempt_semantic_ids"] == scaled["unique_attempt_semantic_ids"]
            and forward["pareto_semantic_ids"] == scaled["pareto_semantic_ids"]
        ),
        "forbidden_outcome_fields_fail_closed": poison_rejected == 2,
        "near_zero_loss_is_finite_without_scalar_ratio": (
            candidates[0].risk_adjusted_loss_hartree == 1e-6
            and "score" not in json.dumps(forward, sort_keys=True).lower()
        ),
        "component_regression_rejected": "componentwise-resource-regression" in assessments[regression_id]["rejection_reasons"],
        "no_physical_benefit_rejected": "no-physical-resource-benefit" in assessments[no_benefit_id]["rejection_reasons"],
        "quality_failure_not_in_production_queue": poor_id not in forward["unique_attempt_semantic_ids"],
        "quality_sentinel_strata_are_preregistered": sentinel["sentinel_strata"] == ["good", "boundary", "poor"],
        "pareto_axes_remain_separate": forward["pareto_axes"] == [
            "cnot_count", "cnot_depth", "total_depth", "parameter_count",
            "logical_block_count", "risk_adjusted_loss_hartree",
        ],
    }
    result = {
        "schema_version": "1.0.0",
        "artifact_kind": "v5-s4-risk-aware-pareto-independent-audit",
        "passed": all(checks.values()),
        "checks": checks,
        "selection_digest": forward["selection_digest"],
        "selected_count": len(forward["unique_attempt_semantic_ids"]),
        "pareto_count": len(forward["pareto_semantic_ids"]),
        "sentinel_selection": sentinel,
        "candidate_records": [candidate_to_record(candidate) for candidate in candidates],
        "claim_boundary": (
            "Synthetic selector audit only. It proves deterministic, energy-blind ranking "
            "properties and does not establish molecular energy or circuit improvement."
        ),
    }
    if not result["passed"]:
        failed = sorted(name for name, passed in checks.items() if not passed)
        raise RuntimeError(f"V5-S4 independent audit failed: {failed}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-path", type=Path)
    arguments = parser.parse_args()
    result = run_audit()
    if arguments.artifact_path is not None:
        _write_exclusive(arguments.artifact_path, result)
    print(json.dumps({"passed": result["passed"], "checks": len(result["checks"])}, sort_keys=True))


if __name__ == "__main__":
    main()

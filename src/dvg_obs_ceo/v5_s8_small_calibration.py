"""V5-S8 small-system predictor and pruning-baseline calibration analysis."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from .baseline import ROOT
from .identity import canonical_json_bytes
from .v3_protocol import _write_exclusive
from .v5_s8_protocol import DEFAULT_MANIFEST, audit_manifest


PREDICTORS = (
    "magnitude",
    "magnitude_position",
    "diagonal_hessian",
    "single_coordinate_obs",
    "general_constraint_obs",
    "exact_hessian_oracle",
)
SMALL_CASES = (
    "h2-1.5-iteration-1",
    "h4-1.5-first-chemical-accuracy",
    "h4-1.5-iteration-12-or-convergence",
)


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _metrics(rows: list[dict[str, Any]], predictor: str, budget: float) -> dict[str, Any]:
    pairs = [
        (float(row["predictors"][predictor]), float(row["actual_change_hartree"]))
        for row in rows if row["predictors"].get(predictor) is not None
    ]
    if not pairs:
        return {"coverage": 0, "available": False}
    predicted = np.asarray([pair[0] for pair in pairs], dtype=np.float64)
    observed = np.asarray([pair[1] for pair in pairs], dtype=np.float64)
    error = predicted - observed
    predicted_safe = predicted <= budget
    observed_safe = observed <= budget
    return {
        "coverage": len(pairs),
        "available": True,
        "mean_absolute_error_hartree": float(np.mean(np.abs(error))),
        "root_mean_square_error_hartree": float(np.sqrt(np.mean(np.square(error)))),
        "mean_signed_error_hartree": float(np.mean(error)),
        "maximum_absolute_error_hartree": float(np.max(np.abs(error))),
        "median_absolute_error_hartree": float(np.median(np.abs(error))),
        "underprediction_count": int(np.count_nonzero(error < 0)),
        "overprediction_count": int(np.count_nonzero(error > 0)),
        "energy_false_safe_count": int(np.count_nonzero(predicted_safe & ~observed_safe)),
        "energy_false_exclusion_count": int(np.count_nonzero(~predicted_safe & observed_safe)),
        "predicted_energy_safe_count": int(np.count_nonzero(predicted_safe)),
        "observed_energy_safe_count": int(np.count_nonzero(observed_safe)),
        "absolute_error_quantiles_hartree": {
            "q50": float(np.quantile(np.abs(error), 0.5)),
            "q90": float(np.quantile(np.abs(error), 0.9)),
            "q95": float(np.quantile(np.abs(error), 0.95)),
            "q100": float(np.max(np.abs(error))),
        },
    }


def _load_rows(manifest: dict[str, Any], case_id: str) -> list[dict[str, Any]]:
    record = next(item for item in manifest["inputs"] if item["case_id"] == case_id)
    paths = sorted((ROOT / record["rows_directory"]).glob(record["row_prefix"] + "*.json"))
    rows = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    if len(rows) != record["expected_row_count"] or any(row["case_id"] != case_id for row in rows):
        raise RuntimeError(f"calibration row set drift: {case_id}")
    return rows


def _pooled(rows_by_case: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    return [row for case_id in SMALL_CASES for row in rows_by_case[case_id]]


def run(manifest_path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    protocol = audit_manifest(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    budget = float(manifest["fixed_scientific_gates"]["source_relative_energy_budget_hartree"])
    rows_by_case = {case_id: _load_rows(manifest, case_id) for case_id in SMALL_CASES}
    case_results: dict[str, Any] = {}
    for case_id, rows in rows_by_case.items():
        case_results[case_id] = {
            "candidate_count": len(rows),
            "complete_safe_count": sum(bool(row["safe"]) for row in rows),
            "energy_safe_count": sum(float(row["actual_change_hartree"]) <= budget for row in rows),
            "actual_change_range_hartree": [
                min(float(row["actual_change_hartree"]) for row in rows),
                max(float(row["actual_change_hartree"]) for row in rows),
            ],
            "predictors": {predictor: _metrics(rows, predictor, budget) for predictor in PREDICTORS},
            "row_set_digest": protocol["inputs"][case_id]["row_set_digest"],
        }
    pooled = _pooled(rows_by_case)
    pooled_metrics = {predictor: _metrics(pooled, predictor, budget) for predictor in PREDICTORS}
    complete_coverage = {
        predictor: metrics for predictor, metrics in pooled_metrics.items()
        if metrics["coverage"] == len(pooled)
    }
    general = pooled_metrics["general_constraint_obs"]
    sensitivity = {
        f"{candidate_budget:.12g}": {
            predictor: {
                "false_safe": _metrics(pooled, predictor, candidate_budget).get("energy_false_safe_count"),
                "false_exclusion": _metrics(pooled, predictor, candidate_budget).get("energy_false_exclusion_count"),
            }
            for predictor in PREDICTORS
        }
        for candidate_budget in (0.5 * budget, budget, 2.0 * budget)
    }
    checks = {
        "all_preregistered_rows_loaded": len(pooled) == 79,
        "general_constraint_obs_complete": general["coverage"] == len(pooled),
        "exact_hessian_oracle_not_misrepresented_as_complete": pooled_metrics["exact_hessian_oracle"]["coverage"] < len(pooled),
        "early_h2_is_negative_control": case_results["h2-1.5-iteration-1"]["complete_safe_count"] == 0,
        "early_h4_is_boundary_control": case_results["h4-1.5-first-chemical-accuracy"]["complete_safe_count"] == 0,
        "late_h4_is_positive_control": case_results["h4-1.5-iteration-12-or-convergence"]["complete_safe_count"] > 0,
        "fixed_budget_not_tuned": budget == 1e-4,
        "measurement_cost_not_relabelled": manifest["fixed_scientific_gates"]["paper_measurement_cost"] is None,
    }
    result = {
        "schema_version": "1.0.0",
        "artifact_kind": "v5-s8-small-system-calibration",
        "passed": all(checks.values()),
        "checks": checks,
        "protocol_manifest_sha256": protocol["manifest_sha256"],
        "energy_budget_hartree": budget,
        "cases": case_results,
        "pooled_candidate_count": len(pooled),
        "pooled_predictor_metrics": pooled_metrics,
        "complete_coverage_predictors": sorted(complete_coverage),
        "budget_sensitivity_diagnostic_only": sensitivity,
        "provisional_scientific_decisions": {
            "predictor": "general_constraint_obs",
            "predictor_reason": "unchanged V4.1 causal baseline; complete H2/H4 coverage and no post-outcome model substitution",
            "global_empirical_energy_margin_hartree": None,
            "global_margin_reason": "a constant pooled outcome-derived margin would not rank candidates and would leak development outcomes into screening",
            "hvp_status": "conditional-study-required",
            "polishing_status": "conditional-repair-only",
            "lih_inspected_for_choice": False,
        },
        "paper_measurement_cost": None,
        "claim_boundary": (
            "Existing H2/H4 development observations only. Predictor errors are "
            "post-outcome diagnostics and are not screening features or molecular performance claims."
        ),
    }
    result["result_digest"] = _digest(result)
    if not result["passed"]:
        failed = sorted(name for name, passed in checks.items() if not passed)
        raise RuntimeError(f"V5-S8 small-system calibration failed: {failed}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--artifact-path", type=Path)
    arguments = parser.parse_args()
    result = run(arguments.manifest)
    if arguments.artifact_path is not None:
        _write_exclusive(arguments.artifact_path, result)
    print(json.dumps({
        "passed": result["passed"],
        "candidates": result["pooled_candidate_count"],
        "general_obs": result["pooled_predictor_metrics"]["general_constraint_obs"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()

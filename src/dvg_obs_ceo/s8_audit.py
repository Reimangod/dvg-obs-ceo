"""Independent consistency audit for a completed S8 calibration bundle."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
from pathlib import Path
from typing import Any

from .calibration import calibration_metrics
from .identity import canonical_json_bytes
import hashlib


PREDICTORS = (
    "magnitude",
    "magnitude_position",
    "diagonal_hessian",
    "single_coordinate_obs",
    "general_constraint_obs",
    "exact_hessian_oracle",
)

# scipy/numpy reductions can differ in the last few bits across supported CPU
# architectures.  These tolerances apply only to independently recomputed
# descriptive metrics; candidate decisions and scientific thresholds remain
# exact checks below.
METRIC_ABSOLUTE_TOLERANCE = 1e-14
METRIC_RELATIVE_TOLERANCE = 1e-12


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _measurement_cost_values(value: Any) -> list[Any]:
    result: list[Any] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "paper_measurement_cost":
                result.append(item)
            result.extend(_measurement_cost_values(item))
    elif isinstance(value, list):
        for item in value:
            result.extend(_measurement_cost_values(item))
    return result


def compare_recomputed_metrics(
    observed: Any,
    recorded: Any,
    *,
    absolute_tolerance: float = METRIC_ABSOLUTE_TOLERANCE,
    relative_tolerance: float = METRIC_RELATIVE_TOLERANCE,
) -> dict[str, Any]:
    """Compare metric trees while keeping non-floating fields exact.

    The returned diagnostics make the cross-platform allowance auditable.  A
    boolean, integer, string, key, or sequence difference is never softened.
    """

    mismatches: list[str] = []
    float_comparisons = 0
    max_absolute_difference = 0.0
    max_relative_difference = 0.0

    def visit(left: Any, right: Any, path: str) -> None:
        nonlocal float_comparisons, max_absolute_difference, max_relative_difference
        if isinstance(left, dict) and isinstance(right, dict):
            if set(left) != set(right):
                mismatches.append(f"{path}:keys")
                return
            for key in sorted(left):
                visit(left[key], right[key], f"{path}.{key}")
            return
        if isinstance(left, list) and isinstance(right, list):
            if len(left) != len(right):
                mismatches.append(f"{path}:length")
                return
            for index, (left_item, right_item) in enumerate(zip(left, right)):
                visit(left_item, right_item, f"{path}[{index}]")
            return
        if isinstance(left, bool) or isinstance(right, bool):
            if type(left) is not type(right) or left != right:
                mismatches.append(path)
            return
        if isinstance(left, float) and isinstance(right, float):
            float_comparisons += 1
            if not (math.isfinite(left) and math.isfinite(right)):
                if left != right:
                    mismatches.append(path)
                return
            absolute_difference = abs(left - right)
            scale = max(abs(left), abs(right))
            relative_difference = absolute_difference / scale if scale else 0.0
            max_absolute_difference = max(max_absolute_difference, absolute_difference)
            max_relative_difference = max(max_relative_difference, relative_difference)
            if not math.isclose(
                left,
                right,
                abs_tol=absolute_tolerance,
                rel_tol=relative_tolerance,
            ):
                mismatches.append(path)
            return
        if type(left) is not type(right) or left != right:
            mismatches.append(path)

    visit(observed, recorded, "metrics")
    return {
        "passed": not mismatches,
        "absolute_tolerance": absolute_tolerance,
        "relative_tolerance": relative_tolerance,
        "float_comparisons": float_comparisons,
        "max_absolute_difference": max_absolute_difference,
        "max_relative_difference": max_relative_difference,
        "mismatch_paths": mismatches,
    }


def validate_bundle(bundle: Path) -> dict[str, Any]:
    required = (
        "summary.json",
        "candidate-catalog.json",
        "all-candidates.jsonl",
        "all-candidates.csv",
    )
    checks: dict[str, bool] = {
        "required_files": all((bundle / name).is_file() for name in required),
    }
    if not checks["required_files"]:
        raise ValueError("S8 bundle is missing required files")
    summary = json.loads((bundle / "summary.json").read_text(encoding="utf-8"))
    expected_checkpoints = tuple(
        f"checkpoint-{checkpoint['case_id']}.json"
        for checkpoint in summary["checkpoints"]
    )
    checks["checkpoint_files"] = all(
        (bundle / name).is_file() for name in expected_checkpoints
    )
    expected_failures = tuple(
        f"checkpoint-failure-{failure['case_id']}.json"
        for failure in summary.get("checkpoint_failures", [])
    )
    checks["checkpoint_failure_files"] = all(
        (bundle / name).is_file() for name in expected_failures
    )
    checks["checkpoint_failure_count"] = len(expected_failures) == summary.get(
        "failed_checkpoint_count", 0
    )
    catalog = json.loads((bundle / "candidate-catalog.json").read_text(encoding="utf-8"))
    rows = [
        json.loads(line)
        for line in (bundle / "all-candidates.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    row_files = sorted((bundle / "rows").glob("*.json"))
    file_rows = [json.loads(path.read_text(encoding="utf-8")) for path in row_files]
    row_by_id = {row["candidate"]["candidate_id"]: row for row in rows}
    file_by_id = {row["candidate"]["candidate_id"]: row for row in file_rows}
    representative_ids = {
        row["executed_representative_candidate_id"] for row in catalog
    }
    checks.update(
        {
            "catalog_count": len(catalog) == summary["catalog_candidate_count"],
            "representative_count": len(representative_ids)
            == summary["executed_equivalence_classes"],
            "jsonl_unique_candidate_ids": len(row_by_id) == len(rows),
            "row_file_unique_candidate_ids": len(file_by_id) == len(file_rows),
            "jsonl_matches_durable_rows": row_by_id == file_by_id,
            "representatives_match_rows": representative_ids == set(row_by_id),
        }
    )
    successful = [row for row in rows if "error" not in row]
    failed = [row for row in rows if "error" in row]
    checks.update(
        {
            "success_count": len(successful) == summary["successful_candidate_evaluations"],
            "failure_count": len(failed) == summary["failed_candidate_evaluations"],
            "safe_count": sum(bool(row["safe"]) for row in successful)
            == summary["primary_safe_candidates"],
            "primary_projection_binding": all(
                row["actual_change_hartree"]
                == row["paths"][row["primary_actual_path"]]["actual_change_hartree"]
                and row["safe"] == row["paths"][row["primary_actual_path"]]["safe"]
                for row in successful
            ),
            "safe_is_conjunction": all(
                path["safe"] == all(path["safe_checks"].values())
                for row in successful
                for path in row["paths"].values()
            ),
            "measurement_cost_unclaimed": all(
                value is None for value in _measurement_cost_values(summary) + _measurement_cost_values(rows)
            ),
        }
    )
    recomputed_metrics = [calibration_metrics(successful, method) for method in PREDICTORS]
    metric_comparison = compare_recomputed_metrics(recomputed_metrics, summary["metrics"])
    checks["metrics_recomputed_within_cross_platform_tolerance"] = metric_comparison[
        "passed"
    ]
    checkpoint_digests: dict[str, str] = {}
    for name in expected_checkpoints:
        path = bundle / name
        checkpoint = json.loads(path.read_text(encoding="utf-8"))
        recorded = checkpoint.pop("checkpoint_digest")
        observed = _digest(checkpoint)
        checkpoint_digests[path.name] = observed
        checks[f"checkpoint_digest:{path.name}"] = observed == recorded
    for failure in summary.get("checkpoint_failures", []):
        path = bundle / f"checkpoint-failure-{failure['case_id']}.json"
        checks[f"checkpoint_failure_content:{path.name}"] = (
            json.loads(path.read_text(encoding="utf-8")) == failure
        )
    with (bundle / "all-candidates.csv").open(newline="", encoding="utf-8") as stream:
        csv_rows = list(csv.DictReader(stream))
    checks["csv_success_rows"] = len(csv_rows) == len(successful)
    checks["plots_exist"] = all((bundle / name).is_file() for name in summary["plots"])
    audit = {
        "schema_version": "1.1.0",
        "artifact_kind": "s8-calibration-bundle-independent-audit",
        "bundle": str(bundle),
        "passed": all(checks.values()),
        "checks": checks,
        "metric_recomputation": metric_comparison,
        "checkpoint_digests": checkpoint_digests,
        "catalog_candidates": len(catalog),
        "executed_candidates": len(rows),
        "successful_candidates": len(successful),
        "failed_candidates": len(failed),
        "safe_candidates": sum(bool(row["safe"]) for row in successful),
        "claim_boundary": "Consistency validation only; this audit adds no performance claim.",
    }
    if not audit["passed"]:
        failed_checks = [name for name, passed in checks.items() if not passed]
        raise ValueError("S8 bundle audit failed: " + ", ".join(failed_checks))
    return audit


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--artifact", type=Path, required=True)
    arguments = parser.parse_args()
    audit = validate_bundle(arguments.bundle)
    if arguments.artifact.exists():
        raise FileExistsError(f"refusing to overwrite S8 audit: {arguments.artifact}")
    arguments.artifact.parent.mkdir(parents=True, exist_ok=True)
    temporary = arguments.artifact.with_suffix(arguments.artifact.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(audit, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, arguments.artifact)
    print(json.dumps({"artifact": str(arguments.artifact), "passed": audit["passed"]}))


if __name__ == "__main__":
    main()

"""Independent consistency audit for a completed S8 calibration bundle."""

from __future__ import annotations

import argparse
import csv
import json
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


def validate_bundle(bundle: Path) -> dict[str, Any]:
    required = (
        "summary.json",
        "candidate-catalog.json",
        "all-candidates.jsonl",
        "all-candidates.csv",
        "checkpoint-h2-1.5-iteration-1.json",
        "checkpoint-h4-1.5-first-chemical-accuracy.json",
    )
    checks: dict[str, bool] = {
        "required_files": all((bundle / name).is_file() for name in required),
    }
    if not checks["required_files"]:
        raise ValueError("S8 bundle is missing required files")
    summary = json.loads((bundle / "summary.json").read_text(encoding="utf-8"))
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
    checks["metrics_recomputed_exactly"] = recomputed_metrics == summary["metrics"]
    checkpoint_digests: dict[str, str] = {}
    for path in sorted(bundle.glob("checkpoint-*.json")):
        checkpoint = json.loads(path.read_text(encoding="utf-8"))
        recorded = checkpoint.pop("checkpoint_digest")
        observed = _digest(checkpoint)
        checkpoint_digests[path.name] = observed
        checks[f"checkpoint_digest:{path.name}"] = observed == recorded
    with (bundle / "all-candidates.csv").open(newline="", encoding="utf-8") as stream:
        csv_rows = list(csv.DictReader(stream))
    checks["csv_success_rows"] = len(csv_rows) == len(successful)
    checks["plots_exist"] = all((bundle / name).is_file() for name in summary["plots"])
    audit = {
        "schema_version": "1.0.0",
        "artifact_kind": "s8-calibration-bundle-independent-audit",
        "bundle": str(bundle),
        "passed": all(checks.values()),
        "checks": checks,
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

"""Independent checks for the frozen V4-S6 calibration/configuration."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any

from .baseline import ROOT
from .identity import canonical_json_bytes
from .v3_protocol import _write_exclusive
from .v4_protocol import audit_manifest


PROTOCOL_TAG = "dvg-obs-v4-s6-calibration-v1"
DEFAULT_CONFIG = ROOT / "manifests" / "v4-s6-frozen-config-v1.json"
REQUIRED_THREADS = {
    "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
}


class V4CalibrationAuditError(RuntimeError):
    """Raised when frozen calibration evidence is inconsistent."""


def _git(*arguments: str) -> str:
    return subprocess.check_output(["git", "-C", str(ROOT), *arguments], text=True).strip()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_freeze() -> dict[str, Any]:
    head = _git("rev-parse", "HEAD")
    tagged = _git("rev-parse", f"{PROTOCOL_TAG}^{{}}")
    dirty = _git("status", "--porcelain")
    threads = {name: os.environ.get(name) for name in REQUIRED_THREADS}
    if head != tagged or dirty or threads != REQUIRED_THREADS:
        raise V4CalibrationAuditError(
            f"V4-S6 requires clean tagged code and canonical threads: head={head}, "
            f"tag={tagged}, dirty={bool(dirty)}, threads={threads}"
        )
    return {"head": head, "protocol_tag": PROTOCOL_TAG, "threads": threads}


def _rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def run(artifact_path: Path, config_path: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    freeze = verify_freeze()
    s0 = audit_manifest()
    manifest = json.loads(config_path.read_text(encoding="utf-8"))
    configuration = manifest["configuration"]
    observed_digest = hashlib.sha256(canonical_json_bytes(configuration)).hexdigest()
    input_hashes: dict[str, str] = {}
    input_artifacts: dict[str, Any] = {}
    for name, item in manifest["inputs"].items():
        path = ROOT / item["path"]
        input_hashes[name] = _sha256(path)
        if path.suffix == ".json":
            input_artifacts[name] = json.loads(path.read_text(encoding="utf-8"))
    rows = [row for row in _rows(ROOT / manifest["inputs"]["primary_single_candidate_outcomes"]["path"]) if "error" not in row]
    budget = configuration["screening_budget_hartree"]
    predictions = [float(row["predictors"]["general_constraint_obs"]) for row in rows]
    actual = [float(row["actual_change_hartree"]) for row in rows]
    s3 = input_artifacts["s3_joint_prediction"]
    ranges = s3["diagnostic_ranges"]
    quality = configuration["quality_policy"]
    h4 = next(case for case in input_artifacts["s4_search"]["cases"] if case["case_id"].startswith("h4"))
    h4_resources = next(case for case in input_artifacts["s5_resources"]["cases"] if case["case_id"].startswith("h4"))
    budgets = configuration["search_budgets"]
    checks = {
        "s0_audit": s0["passed"],
        "input_hashes": all(input_hashes[name] == item["sha256"] for name, item in manifest["inputs"].items()),
        "configuration_digest": observed_digest == manifest["configuration_digest"],
        "calibration_row_count": len(rows) == 17,
        "no_predicted_positive_class": sum(value <= budget for value in predictions) == 0,
        "no_actual_positive_class": sum(value <= budget for value in actual) == 0,
        "positive_metrics_explicitly_unavailable": manifest["calibration_interpretation"]["positive_class_metrics_available"] is False,
        "quality_bounds_enclose_s3": bool(
            quality["maximum_constraint_schur_condition_number"] >= ranges["constraint_schur_condition_number"][1]
            and quality["maximum_target_hessian_condition_number"] >= ranges["target_hessian_condition_number"][1]
            and quality["minimum_constraint_direction_coverage"] <= ranges["constraint_direction_coverage"][0]
            and quality["maximum_internal_projected_residual"] >= ranges["internal_projected_max_relative_residual"][1]
        ),
        "held_out_absence_not_hidden": bool(
            ranges["held_out_projected_residual"] is None
            and quality["require_held_out_evidence"] is False
            and "not-probabilistically-calibrated" in manifest["calibration_interpretation"]["confidence_status"]
        ),
        "deterministic_budgets_cover_four_h4_exhaustive_runs": bool(
            budgets["maximum_expanded_nodes"] >= 4 * h4["exhaustive"]["counts"]["expanded"]
            and budgets["maximum_completed_states"] >= 4 * h4["exhaustive"]["counts"]["completed"]
            and budgets["maximum_quadratic_solves"] >= 4 * h4["exhaustive"]["counts"]["quadratic_solves"]
            and budgets["maximum_full_resource_recounts"] >= 4 * h4_resources["unique_circuit_recounts"]
        ),
        "exact_attempt_bounds_match_s0": configuration["exact_vqe_budget"] == {
            "top_k_per_endpoint": 2, "maximum_unique_exact_attempts": 4,
        },
        "stop_rules_fail_closed": all(manifest["stop_rules"].values()),
    }
    failed = [name for name, passed in checks.items() if not passed]
    artifact = {
        "schema_version": "1.0.0",
        "artifact_kind": "v4-s6-calibration-independent-audit",
        "execution_freeze": freeze,
        "passed": not failed,
        "checks": checks,
        "failed_checks": failed,
        "configuration_digest": observed_digest,
        "input_sha256": input_hashes,
        "observed": {
            "calibration_rows": len(rows),
            "predicted_positive_count": sum(value <= budget for value in predictions),
            "actual_positive_count": sum(value <= budget for value in actual),
            "maximum_actual_minus_predicted_hartree": max(a - p for a, p in zip(actual, predictions)),
            "s3_diagnostic_ranges": ranges,
            "h4_exhaustive_counts": h4["exhaustive"]["counts"],
        },
        "work": {"vqe_energy_evaluations": 0, "new_molecular_executions": 0, "paper_measurement_cost": None},
        "claim_boundary": manifest["claim_boundary"],
    }
    if failed:
        raise V4CalibrationAuditError("V4-S6 audit failed: " + ", ".join(failed))
    _write_exclusive(artifact_path, artifact)
    return artifact


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-path", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    arguments = parser.parse_args()
    result = run(arguments.artifact_path, arguments.config)
    print(json.dumps({"passed": result["passed"], "observed": result["observed"], "configuration_digest": result["configuration_digest"]}, sort_keys=True))


if __name__ == "__main__":
    main()

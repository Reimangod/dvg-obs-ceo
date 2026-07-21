"""Audit joint OBS predictions and fixed-surrogate monotonicity on H4."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
import math
import os
from pathlib import Path
import subprocess
from typing import Any

import numpy as np

from .baseline import ROOT
from .block_ir import enumerate_candidates, recover_dvg_blocks
from .composition import compose_registered_candidates
from .joint_prediction import joint_obs_prediction, secant_pairs_from_capture
from .resources import AnsatzStructure
from .s8_probe import _algorithm
from .v3_gradient_audit import _load_and_verify
from .v3_protocol import _write_exclusive
from .v4_protocol import audit_manifest


PROTOCOL_TAG = "dvg-obs-v4-s3-joint-prediction-v1"
COMPOSITION_ARTIFACT = ROOT / "artifacts" / "v4" / "s2-global-composition-audit-v1-1.json"
REQUIRED_THREADS = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
}


class V4JointPredictionAuditError(RuntimeError):
    """Raised when joint OBS prediction invariants fail."""


def _git(*arguments: str) -> str:
    return subprocess.check_output(["git", "-C", str(ROOT), *arguments], text=True).strip()


def verify_freeze() -> dict[str, Any]:
    head = _git("rev-parse", "HEAD")
    tagged = _git("rev-parse", f"{PROTOCOL_TAG}^{{}}")
    dirty = _git("status", "--porcelain")
    threads = {name: os.environ.get(name) for name in REQUIRED_THREADS}
    if head != tagged or dirty or threads != REQUIRED_THREADS:
        raise V4JointPredictionAuditError(
            f"V4-S3 requires clean tagged code and canonical threads: head={head}, "
            f"tag={tagged}, dirty={bool(dirty)}, threads={threads}"
        )
    return {"head": head, "protocol_tag": PROTOCOL_TAG, "threads": threads}


def run(artifact_path: Path) -> dict[str, Any]:
    freeze = verify_freeze()
    s0 = audit_manifest()
    composition = json.loads(COMPOSITION_ARTIFACT.read_text(encoding="utf-8"))
    if not composition["passed"]:
        raise V4JointPredictionAuditError("S2 composition evidence did not pass")
    _, _, checkpoints = _load_and_verify(
        ROOT / "manifests" / "v3-s1-gradient-audit-v1.json"
    )
    records: list[dict[str, Any]] = []
    monotonic_failures: list[dict[str, Any]] = []
    family_counts: Counter[str] = Counter()
    total_quadratic_solves = 0

    for case_id in sorted({record["case_id"] for record in composition["records"]}):
        checkpoint = checkpoints[case_id]
        _, pool = _algorithm(case_id)
        source = AnsatzStructure.create(
            checkpoint["ansatz_indices"], checkpoint["ansatz_coefficients"], checkpoint["iteration_counts"]
        )
        blocks = recover_dvg_blocks(
            pool, source.indices, source.coefficients, source.cumulative_parameter_counts
        )
        representatives: dict[str, Any] = {}
        for candidate in enumerate_candidates(pool, blocks):
            representatives.setdefault(candidate.equivalence_class_id, candidate)
        candidates = {candidate.candidate_id: candidate for candidate in representatives.values()}
        internal = secant_pairs_from_capture(
            checkpoint["hessian_capture"]["secant_pairs"], required_source="internal-bfgs"
        )
        theta = checkpoint["ansatz_coefficients"]
        gradient = checkpoint["gradient"]
        inverse = checkpoint["recycled_inverse_hessian"]
        prediction_cache: dict[frozenset[str], dict[str, Any]] = {}

        def prediction_for(candidate_ids: frozenset[str]) -> dict[str, Any]:
            if candidate_ids not in prediction_cache:
                batch = [candidates[identifier] for identifier in sorted(candidate_ids)]
                plan = compose_registered_candidates(source, blocks, batch)
                prediction_cache[candidate_ids] = joint_obs_prediction(
                    theta,
                    gradient,
                    inverse,
                    plan.transformation,
                    internal_pairs=internal,
                    held_out_pairs=(),
                )
            return prediction_cache[candidate_ids]

        case_records = [
            record for record in composition["records"] if record["case_id"] == case_id
        ]
        for source_record in case_records:
            identifiers = frozenset(source_record["candidate_ids"])
            prediction = prediction_for(identifiers)
            value = float(prediction["predicted_change_from_current_hartree"])
            subset_values: list[float] = []
            for removed in identifiers:
                subset = identifiers - {removed}
                if subset:
                    subset_value = float(
                        prediction_for(subset)["predicted_change_from_current_hartree"]
                    )
                    subset_values.append(subset_value)
                    if value + 1e-12 < subset_value:
                        monotonic_failures.append(
                            {
                                "candidate_ids": sorted(identifiers),
                                "subset_ids": sorted(subset),
                                "joint": value,
                                "subset": subset_value,
                            }
                        )
            kinds = tuple(sorted(candidates[identifier].kind for identifier in identifiers))
            family = "+".join(kinds)
            family_counts[family] += 1
            diagnostics = prediction["diagnostics"]
            records.append(
                {
                    "case_id": case_id,
                    "candidate_ids": sorted(identifiers),
                    "family": family,
                    "predicted_change_from_current_hartree": value,
                    "largest_immediate_subset_prediction_hartree": max(subset_values),
                    "constraint_residual_infinity": prediction["constraint_residual_infinity"],
                    "diagnostics": diagnostics,
                    "held_out_status": "unavailable-not-relabelled",
                }
            )
        total_quadratic_solves += len(prediction_cache)
    conditions = [
        record["diagnostics"]["constraint_schur_condition_number"] for record in records
    ]
    target_conditions = [
        record["diagnostics"]["target_hessian_condition_number"] for record in records
    ]
    coverage = [record["diagnostics"]["constraint_direction_coverage"] for record in records]
    internal_maxima = [
        record["diagnostics"]["internal_projected_secants"]["maximum_relative_residual"]
        for record in records
    ]
    checks = {
        "s0_audit": s0["passed"],
        "composition_input": composition["passed"],
        "all_joint_batches_predicted": len(records) == composition["completed_joint_batches"],
        "finite_predictions": all(
            math.isfinite(record["predicted_change_from_current_hartree"])
            for record in records
        ),
        "fixed_surrogate_monotonicity": not monotonic_failures,
        "constraint_residuals": all(
            record["constraint_residual_infinity"] <= 1e-10 for record in records
        ),
        "finite_conditioning": all(math.isfinite(value) for value in conditions + target_conditions),
        "coverage_bounded": all(0.0 <= value <= 1.0 for value in coverage),
        "internal_evidence_present": all(value is not None for value in internal_maxima),
        "held_out_not_relabelled": all(
            not record["diagnostics"]["held_out_evidence_available"]
            and record["held_out_status"] == "unavailable-not-relabelled"
            for record in records
        ),
    }
    failed = [name for name, passed in checks.items() if not passed]
    artifact = {
        "schema_version": "1.0.0",
        "artifact_kind": "v4-s3-joint-obs-prediction-audit",
        "execution_freeze": freeze,
        "passed": not failed,
        "checks": checks,
        "failed_checks": failed,
        "joint_prediction_count": len(records),
        "monotonicity_failure_count": len(monotonic_failures),
        "monotonicity_failures": monotonic_failures,
        "diagnostic_ranges": {
            "constraint_schur_condition_number": [min(conditions), max(conditions)],
            "target_hessian_condition_number": [min(target_conditions), max(target_conditions)],
            "constraint_direction_coverage": [min(coverage), max(coverage)],
            "internal_projected_max_relative_residual": [min(internal_maxima), max(internal_maxima)],
            "held_out_projected_residual": None,
        },
        "family_counts": dict(sorted(family_counts.items())),
        "work": {
            "quadratic_solves": total_quadratic_solves,
            "vqe_energy_evaluations": 0,
            "ordinary_gsd_adapt_iterations": 0,
            "ceo_star_adapt_iterations": 0,
            "paper_measurement_cost": None,
        },
        "claim_boundary": (
            "Fixed-surrogate joint prediction diagnostics only. Held-out secants are absent and "
            "no quality threshold, safe-candidate claim, or actual energy is assigned in S3."
        ),
        "records": records,
    }
    if failed:
        raise V4JointPredictionAuditError("V4-S3 audit failed: " + ", ".join(failed))
    _write_exclusive(artifact_path, artifact)
    return artifact


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-path", type=Path, required=True)
    arguments = parser.parse_args()
    result = run(arguments.artifact_path)
    print(json.dumps({
        "passed": result["passed"],
        "joint_prediction_count": result["joint_prediction_count"],
        "diagnostic_ranges": result["diagnostic_ranges"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()

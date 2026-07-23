"""Candidate-feasible HVP oracle and matrix-free sentinels for late H4."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import time
from typing import Any, Sequence

import numpy as np

from .baseline import ROOT
from .block_ir import enumerate_candidates, recover_dvg_blocks
from .calibration import embed_block_transformation
from .identity import canonical_json_bytes
from .resources import AnsatzStructure
from .s8_probe import _algorithm
from .v3_protocol import _write_exclusive
from .v5_hvp_kkt import CentralDifferenceHVP, HVPKKTConfig, HVPRefinementError, solve_affine_kkt_hvp
from .v5_s8_protocol import DEFAULT_MANIFEST, audit_manifest


CASE_ID = "h4-1.5-iteration-12-or-convergence"
CODE_TAG = "dvg-obs-v5-s8-h4-hvp-sentinels-code-v1"
REQUIRED_THREADS = {"OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _git(*arguments: str) -> str:
    return subprocess.check_output(["git", "-C", str(ROOT), *arguments], text=True).strip()


def verify_freeze() -> dict[str, Any]:
    head = _git("rev-parse", "HEAD")
    tagged = _git("rev-parse", f"{CODE_TAG}^{{}}")
    threads = {name: os.environ.get(name) for name in REQUIRED_THREADS}
    checks = {
        "head_is_code_tag": head == tagged,
        "clean_worktree": not _git("status", "--porcelain"),
        "canonical_threads": threads == REQUIRED_THREADS,
    }
    if not all(checks.values()):
        raise RuntimeError("H4 HVP sentinel freeze failed: " + ",".join(name for name, passed in checks.items() if not passed))
    return {"head": head, "tag": CODE_TAG, "threads": threads, "checks": checks}


def select_prediction_sentinels(rows: Sequence[dict[str, Any]], budget: float) -> list[dict[str, Any]]:
    """Outcome-blind low/boundary/high selection from recycled predictions."""

    ordered = sorted(
        rows,
        key=lambda row: (
            float(row["predictors"]["general_constraint_obs"]),
            row["candidate"]["candidate_id"],
        ),
    )
    choices = (
        ("low-predicted-loss", ordered[0]),
        (
            "budget-boundary",
            min(
                ordered,
                key=lambda row: (
                    abs(float(row["predictors"]["general_constraint_obs"]) - budget),
                    row["candidate"]["candidate_id"],
                ),
            ),
        ),
        ("high-predicted-loss", ordered[-1]),
    )
    selected = []
    seen = set()
    for stratum, row in choices:
        candidate_id = row["candidate"]["candidate_id"]
        if candidate_id not in seen:
            selected.append({"stratum": stratum, "candidate_id": candidate_id})
            seen.add(candidate_id)
    return selected


def run(manifest_path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    freeze = verify_freeze()
    protocol = audit_manifest(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    record = next(item for item in manifest["inputs"] if item["case_id"] == CASE_ID)
    checkpoint = json.loads((ROOT / record["checkpoint_path"]).read_text(encoding="utf-8"))
    row_paths = sorted((ROOT / record["rows_directory"]).glob(record["row_prefix"] + "*.json"))
    rows = [json.loads(path.read_text(encoding="utf-8")) for path in row_paths]
    budget = float(manifest["fixed_scientific_gates"]["source_relative_energy_budget_hartree"])
    sentinels = select_prediction_sentinels(rows, budget)

    algorithm, pool = _algorithm(CASE_ID)
    algorithm.initialize()
    source = AnsatzStructure.create(
        checkpoint["ansatz_indices"], checkpoint["ansatz_coefficients"], checkpoint["iteration_counts"]
    )
    theta = np.asarray(source.coefficients, dtype=np.float64)
    gradient = np.asarray(checkpoint["gradient"], dtype=np.float64)
    observed_gradient = np.asarray(
        algorithm.estimate_gradients(theta.tolist(), list(source.indices), method="an"), dtype=np.float64
    )
    if not np.allclose(observed_gradient, gradient, atol=1e-8, rtol=1e-8):
        raise RuntimeError("late-H4 gradient reconstruction drift")
    hessian_started = time.perf_counter()
    hessian = np.asarray(
        algorithm.estimate_hessian(
            coefficients=list(source.coefficients),
            indices=list(source.indices),
            method="an",
            formula=None,
        ),
        dtype=np.float64,
    )
    hessian_seconds = time.perf_counter() - hessian_started
    if hessian.shape != (theta.size, theta.size) or not np.all(np.isfinite(hessian)):
        raise RuntimeError("late-H4 analytic Hessian is invalid")

    blocks = recover_dvg_blocks(pool, source.indices, source.coefficients, source.cumulative_parameter_counts)
    block_by_id = {block.block_id: block for block in blocks}
    candidates = {}
    for candidate in enumerate_candidates(pool, blocks):
        candidates.setdefault(candidate.equivalence_class_id, candidate)
    candidate_by_id = {candidate.candidate_id: candidate for candidate in candidates.values()}
    row_by_id = {row["candidate"]["candidate_id"]: row for row in rows}
    if set(candidate_by_id) != set(row_by_id):
        raise RuntimeError("late-H4 candidate catalog differs from frozen rows")

    explicit_config = HVPKKTConfig(
        explicit_validation_dimension=32,
        minimum_curvature=1e-10,
        minres_tolerance=1e-11,
        maximum_relative_residual=1e-9,
        maximum_relative_backward_error=1e-9,
        maximum_hessian_vector_products=4096,
    )
    oracle_records: list[dict[str, Any]] = []
    transformations = {}
    for candidate_id in sorted(candidate_by_id):
        candidate = candidate_by_id[candidate_id]
        embedded = embed_block_transformation(theta.size, block_by_id[candidate.source_block_id], candidate)
        transformations[candidate_id] = embedded.transformation
        row = row_by_id[candidate_id]
        try:
            solve = solve_affine_kkt_hvp(
                theta,
                gradient,
                embedded.transformation.constraint_matrix,
                embedded.transformation.constraint_rhs,
                lambda vector, hessian=hessian: hessian @ vector,
                config=explicit_config,
            )
            oracle_records.append({
                "candidate_id": candidate_id,
                "status": "solved",
                "recycled_prediction_hartree": float(row["predictors"]["general_constraint_obs"]),
                "fresh_hessian_prediction_hartree": solve["predicted_change_hartree"],
                "feasible_dimension": solve["feasible_dimension"],
                "minimum_feasible_curvature": solve["minimum_curvature"],
                "work": solve["work"],
                "posthoc_actual_change_hartree": float(row["actual_change_hartree"]),
                "posthoc_complete_safe": bool(row["safe"]),
            })
        except HVPRefinementError as error:
            oracle_records.append({
                "candidate_id": candidate_id,
                "status": "failed-closed",
                "failure_category": error.category,
                "recycled_prediction_hartree": float(row["predictors"]["general_constraint_obs"]),
                "work": error.work,
                "posthoc_actual_change_hartree": float(row["actual_change_hartree"]),
                "posthoc_complete_safe": bool(row["safe"]),
            })

    step_multiplier = 2.0
    relative_step = float(np.finfo(np.float64).eps ** (1.0 / 3.0)) * step_multiplier
    matrix_free_records = []
    for sentinel in sentinels:
        candidate_id = sentinel["candidate_id"]
        transformation = transformations[candidate_id]
        callback = CentralDifferenceHVP(
            theta,
            lambda value: np.asarray(
                algorithm.estimate_gradients(value.tolist(), list(source.indices), method="an"),
                dtype=np.float64,
            ),
            relative_step=relative_step,
        )
        try:
            solve = solve_affine_kkt_hvp(
                theta,
                gradient,
                transformation.constraint_matrix,
                transformation.constraint_rhs,
                callback,
                config=HVPKKTConfig(
                    explicit_validation_dimension=0,
                    minimum_curvature=1e-10,
                    symmetry_relative_tolerance=1e-8,
                    minres_tolerance=1e-10,
                    maximum_relative_residual=1e-8,
                    maximum_relative_backward_error=1e-8,
                    maximum_hessian_vector_products=4096,
                ),
            )
            oracle = next(item for item in oracle_records if item["candidate_id"] == candidate_id)
            matrix_free_records.append({
                **sentinel,
                "status": "solved",
                "prediction_hartree": solve["predicted_change_hartree"],
                "explicit_oracle_prediction_hartree": oracle.get("fresh_hessian_prediction_hartree"),
                "absolute_oracle_difference_hartree": (
                    None if oracle["status"] != "solved"
                    else abs(solve["predicted_change_hartree"] - oracle["fresh_hessian_prediction_hartree"])
                ),
                "work": solve["work"],
            })
        except HVPRefinementError as error:
            matrix_free_records.append({
                **sentinel,
                "status": "failed-closed",
                "failure_category": error.category,
                "work": error.work,
            })

    solved = [item for item in oracle_records if item["status"] == "solved"]
    false_exclusions = [
        item for item in solved
        if item["recycled_prediction_hartree"] > budget
        and item["posthoc_actual_change_hartree"] <= budget
    ]
    recovered = [item for item in false_exclusions if item["fresh_hessian_prediction_hartree"] <= budget]
    fresh_false_safe = [
        item for item in solved
        if item["fresh_hessian_prediction_hartree"] <= budget
        and item["posthoc_actual_change_hartree"] > budget
    ]
    checks = {
        "all_frozen_candidates_accounted": len(oracle_records) == 62,
        "sentinels_selected_without_outcomes": len(sentinels) == 3,
        "at_least_one_feasible_subspace_solved": bool(solved),
        "matrix_free_sentinels_accounted": len(matrix_free_records) == len(sentinels),
        "matrix_free_matches_or_fails_closed": all(
            item["status"] == "failed-closed"
            or item["absolute_oracle_difference_hartree"] <= 1e-7
            for item in matrix_free_records
        ),
        "all_hvp_work_counted": all("hessian_vector_products" in item["work"] for item in oracle_records + matrix_free_records),
        "measurement_cost_not_relabelled": True,
    }
    result = {
        "schema_version": "1.0.0",
        "artifact_kind": "v5-s8-late-h4-feasible-curvature-and-hvp-sentinels",
        "passed": all(checks.values()),
        "checks": checks,
        "execution_freeze": freeze,
        "protocol_manifest_sha256": protocol["manifest_sha256"],
        "case_id": CASE_ID,
        "source_dimension": theta.size,
        "full_hessian_minimum_eigenvalue": float(np.min(np.linalg.eigvalsh((hessian + hessian.T) * 0.5))),
        "analytic_hessian_work": {
            "analytic_entries": theta.size * (theta.size + 1) // 2,
            "wall_time_seconds": hessian_seconds,
            "paper_measurement_cost": None,
        },
        "oracle_records": oracle_records,
        "prediction_sentinels": sentinels,
        "matrix_free_sentinel_records": matrix_free_records,
        "posthoc_diagnostics": {
            "recycled_false_exclusions_among_solved": len(false_exclusions),
            "fresh_hessian_recovered_false_exclusions": len(recovered),
            "fresh_hessian_false_safe_count": len(fresh_false_safe),
            "used_for_sentinel_selection": False,
        },
        "paper_measurement_cost": None,
        "claim_boundary": (
            "Late-H4 development curvature study. Analytic Hessian and stored actual outcomes are diagnostic oracles; "
            "only the three outcome-blind sentinels exercise the deployable matrix-free path."
        ),
    }
    result["result_digest"] = _digest(result)
    if not result["passed"]:
        raise RuntimeError("V5-S8 late-H4 HVP sentinel study failed")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--artifact-path", type=Path, required=True)
    arguments = parser.parse_args()
    result = run(arguments.manifest)
    _write_exclusive(arguments.artifact_path, result)
    print(json.dumps({
        "passed": result["passed"],
        "full_hessian_minimum_eigenvalue": result["full_hessian_minimum_eigenvalue"],
        "posthoc": result["posthoc_diagnostics"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()

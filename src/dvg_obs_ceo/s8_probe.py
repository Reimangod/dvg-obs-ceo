"""Execute the preregistered H2/H4 predictor calibration bundle."""

from __future__ import annotations

import argparse
from collections import Counter
import csv
from dataclasses import asdict
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import random
import sys
import time
from typing import Any, Mapping, Sequence
import warnings

import numpy as np

from .baseline import _environment, _load_upstream, _nested_sum, verify_upstream
from .block_ir import block_to_dict, candidate_to_dict, enumerate_candidates, recover_dvg_blocks
from .calibration import (
    CALIBRATION_VERSION,
    ENERGY_PREDICTORS,
    calibration_metrics,
    embed_block_transformation,
    least_squares_native_coordinates,
    obs_warm_start,
    predictor_values,
)
from .hessian import HessianCaptureSession, capture_to_dict, checkpoint_optimality
from .identity import canonical_json_bytes
from .quadratic import QuadraticModelError, validate_spd
from .resources import (
    AnsatzStructure,
    apply_candidate_structure,
    evaluate_full_circuit_resources,
    paper_era_backend,
    resources_to_dict,
)


CHEMICAL_ACCURACY_HARTREE = 1.6e-3
LOCAL_BUDGET_HARTREE = 1e-4
OPTIMIZER_MAX_ITERATIONS = 200
OPTIMIZER_G_TOL = 1e-8


def _sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _write_exclusive(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    payload = json.dumps(value, indent=2, sort_keys=True, allow_nan=False).encode("utf-8") + b"\n"
    try:
        offset = 0
        while offset < len(payload):
            count = os.write(descriptor, payload[offset:])
            if count <= 0:
                raise RuntimeError("S8 artifact write made no progress")
            offset += count
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_atomic_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    payload = json.dumps(value, indent=2, sort_keys=True, allow_nan=False).encode("utf-8") + b"\n"
    with temporary.open("wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    _fsync_directory(path.parent)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _algorithm(case_id: str) -> tuple[Any, Any]:
    LinAlgAdapt, DVG_CEO, creators, _ = _load_upstream()
    create_h2, _ = creators
    molecules = importlib.import_module("adaptvqe.molecules")
    if case_id == "h2-1.5-iteration-1":
        molecule = create_h2(1.5)
    elif case_id in {
        "h4-1.5-first-chemical-accuracy",
        "h4-1.5-iteration-8",
        "h4-1.5-iteration-12-or-convergence",
    }:
        molecule = molecules.create_h4(1.5)
    else:
        raise ValueError(f"unregistered S8 case: {case_id}")
    pool = DVG_CEO(molecule)
    algorithm = LinAlgAdapt(
        pool=pool,
        molecule=molecule,
        verbose=False,
        max_adapt_iter=12,
        max_opt_iter=10000,
        full_opt=True,
        threshold=1e-6,
        convergence_criterion="total_g_norm",
        tetris=True,
        progressive_opt=False,
        candidates=1,
        sel_criterion="gradient",
        recycle_hessian=True,
        penalize_cnots=False,
        rand_degenerate=False,
        shots=None,
    )
    return algorithm, pool


def _build_checkpoint(case_id: str) -> tuple[Any, Any, AnsatzStructure, dict[str, Any], Any]:
    checkpoint_started = time.perf_counter()
    random.seed(0)
    np.random.seed(0)
    algorithm, pool = _algorithm(case_id)
    adapt_module = importlib.import_module("adaptvqe.algorithms.adapt_vqe")
    algorithm.initialize()
    trajectory: list[dict[str, Any]] = []
    counts: list[int] = []
    with HessianCaptureSession(adapt_module) as capture:
        while algorithm.data.iteration_counter < algorithm.max_adapt_iter:
            finished = bool(algorithm.run_iteration())
            iteration = int(algorithm.data.iteration_counter)
            error = abs(float(algorithm.energy) - float(algorithm.exact_energy))
            counts.append(len(algorithm.indices))
            trajectory.append(
                {
                    "adapt_iteration": iteration,
                    "energy_hartree": float(algorithm.energy),
                    "absolute_error_hartree": error,
                    "parameter_count": len(algorithm.coefficients),
                    "finished": finished,
                }
            )
            if case_id == "h2-1.5-iteration-1" and iteration == 1:
                break
            if case_id == "h4-1.5-first-chemical-accuracy" and error < CHEMICAL_ACCURACY_HARTREE:
                break
            if case_id == "h4-1.5-iteration-8" and iteration == 8:
                break
            if finished:
                break
    if not capture.records:
        raise RuntimeError(f"{case_id} captured no optimizer record")
    if case_id == "h4-1.5-first-chemical-accuracy":
        if not trajectory or trajectory[-1]["absolute_error_hartree"] >= CHEMICAL_ACCURACY_HARTREE:
            raise RuntimeError("registered H4 checkpoint did not reach chemical accuracy by iteration 12")
    if case_id == "h4-1.5-iteration-8" and trajectory[-1]["adapt_iteration"] != 8:
        raise RuntimeError("registered H4 iteration-8 checkpoint converged before iteration 8")
    structure = AnsatzStructure.create(algorithm.indices, algorithm.coefficients, counts)
    last_capture = capture.records[-1]
    inverse_hessian = np.asarray(algorithm.inv_hessian, dtype=np.float64)
    gradient = np.asarray(algorithm.gradients, dtype=np.float64)
    if inverse_hessian.shape != (len(structure.indices), len(structure.indices)):
        raise RuntimeError("checkpoint inverse Hessian dimension mismatch")
    if gradient.shape != (len(structure.indices),):
        raise RuntimeError("checkpoint gradient dimension mismatch")
    if not np.array_equal(inverse_hessian, last_capture.final_inverse_hessian):
        raise RuntimeError("captured and runtime inverse Hessians differ")
    exact_hessian_started = time.perf_counter()
    exact_hessian = np.asarray(
        algorithm.estimate_hessian(
            coefficients=list(structure.coefficients),
            indices=list(structure.indices),
            method="an",
            formula=None,
        ),
        dtype=np.float64,
    )
    exact_hessian_wall = time.perf_counter() - exact_hessian_started
    exact_hessian_reason = None
    try:
        exact_diagnostics = asdict(validate_spd(exact_hessian))
    except QuadraticModelError as error:
        exact_diagnostics = None
        exact_hessian_reason = str(error)
        exact_hessian = None
    source_energy_check = float(
        algorithm.evaluate_energy(list(structure.coefficients), list(structure.indices))
    )
    if abs(source_energy_check - float(algorithm.energy)) > 1e-10:
        raise RuntimeError("independent checkpoint energy mismatch")
    state = np.asarray(algorithm.compute_state(list(structure.coefficients), list(structure.indices)).toarray()).ravel()
    state /= np.linalg.norm(state)
    checkpoint = {
        "case_id": case_id,
        "trajectory": trajectory,
        "ansatz_indices": list(structure.indices),
        "ansatz_coefficients": list(structure.coefficients),
        "iteration_counts": list(structure.cumulative_parameter_counts),
        "energy_hartree": float(algorithm.energy),
        "independent_energy_hartree": source_energy_check,
        "fci_energy_hartree": float(algorithm.exact_energy),
        "absolute_error_hartree": abs(float(algorithm.energy) - float(algorithm.exact_energy)),
        "gradient": gradient.tolist(),
        "gradient_infinity": float(np.max(np.abs(gradient))) if gradient.size else 0.0,
        "recycled_inverse_hessian": inverse_hessian.tolist(),
        "hessian_capture": capture_to_dict(last_capture),
        "exact_hessian": None if exact_hessian is None else exact_hessian.tolist(),
        "exact_hessian_diagnostics": exact_diagnostics,
        "exact_hessian_unavailable_reason": exact_hessian_reason,
        "work": {
            "baseline_optimizer_energy_evaluations": _nested_sum(algorithm.data.evolution.nfevs),
            "baseline_optimizer_gradient_component_equivalent": _nested_sum(algorithm.data.evolution.ngevs),
            "exact_hessian_analytic_entries": len(structure.indices) * (len(structure.indices) + 1) // 2,
            "exact_hessian_wall_time_seconds": exact_hessian_wall,
            "independent_checkpoint_energy_evaluations": 1,
            "independent_checkpoint_state_recomputations": 1,
            "total_checkpoint_wall_time_seconds": time.perf_counter() - checkpoint_started,
            "statevector_kernel_total": None,
            "statevector_kernel_total_reason": "upstream analytic routines are not instrumented at kernel granularity",
            "paper_measurement_cost": None
        },
        "statevector_sha256": hashlib.sha256(np.asarray(state, dtype=">c16").tobytes()).hexdigest(),
    }
    checkpoint["checkpoint_digest"] = _sha256(checkpoint)
    return algorithm, pool, structure, checkpoint, exact_hessian


def _state_vector(algorithm: Any, coefficients: Sequence[float], indices: Sequence[int]) -> np.ndarray:
    value = np.asarray(algorithm.compute_state(list(coefficients), list(indices)).toarray()).ravel()
    value = np.asarray(value, dtype=np.complex128)
    return value / np.linalg.norm(value)


def _optimize_target(
    algorithm: Any,
    indices: Sequence[int],
    initial_coordinates: np.ndarray,
    initial_inverse_hessian: np.ndarray,
    baseline_state: np.ndarray,
) -> dict[str, Any]:
    from adaptvqe.minimize import minimize_bfgs

    dimension = len(indices)
    started = time.perf_counter()
    if dimension == 0:
        energy = float(algorithm.evaluate_energy([], []))
        independent_energy = float(algorithm.evaluate_energy([], []))
        gradient = np.zeros(0, dtype=np.float64)
        coordinates = np.zeros(0, dtype=np.float64)
        success = True
        status = 0
        message = "exact zero-dimensional target"
        nit = nfev = njev = 0
        hessian = np.zeros((0, 0), dtype=np.float64)
    else:
        def energy_function(x: np.ndarray, target_indices: Sequence[int]) -> float:
            return float(algorithm.evaluate_energy(list(x), list(target_indices)))

        def gradient_function(x: np.ndarray, target_indices: Sequence[int]) -> np.ndarray:
            return np.asarray(
                algorithm.estimate_gradients(list(x), list(target_indices), method="an"),
                dtype=np.float64,
            )

        result = minimize_bfgs(
            energy_function,
            initial_coordinates,
            [list(indices)],
            jac=gradient_function,
            initial_inv_hessian=initial_inverse_hessian,
            gtol=OPTIMIZER_G_TOL,
            maxiter=OPTIMIZER_MAX_ITERATIONS,
            disp=False,
        )
        coordinates = np.asarray(result.x, dtype=np.float64)
        energy = float(result.fun)
        independent_energy = float(algorithm.evaluate_energy(list(coordinates), list(indices)))
        gradient = gradient_function(coordinates, list(indices))
        success = bool(result.success)
        status = int(result.status)
        message = str(result.message)
        nit = int(result.nit)
        nfev = int(result.nfev)
        njev = int(result.njev)
        hessian = np.asarray(result.hess_inv, dtype=np.float64)
    state_first = _state_vector(algorithm, coordinates, indices)
    state_second = _state_vector(algorithm, coordinates, indices)
    repeat_fidelity = float(abs(np.vdot(state_first, state_second)) ** 2)
    baseline_fidelity = float(abs(np.vdot(baseline_state, state_first)) ** 2)
    finite = bool(
        math.isfinite(energy)
        and math.isfinite(independent_energy)
        and np.all(np.isfinite(coordinates))
        and np.all(np.isfinite(gradient))
        and np.all(np.isfinite(hessian))
    )
    return {
        "coordinates": coordinates.tolist(),
        "energy_hartree": energy,
        "independent_energy_hartree": independent_energy,
        "independent_energy_difference_hartree": abs(energy - independent_energy),
        "gradient": gradient.tolist(),
        "gradient_l2": float(np.linalg.norm(gradient)),
        "gradient_infinity": float(np.max(np.abs(gradient))) if gradient.size else 0.0,
        "optimizer": {
            "implementation": "pinned-upstream-minimize_bfgs",
            "success": success,
            "status": status,
            "message": message,
            "iterations": nit,
            "function_evaluations": nfev,
            "gradient_vector_evaluations": njev,
            "gradient_component_equivalent": njev * dimension,
            "maximum_iterations": OPTIMIZER_MAX_ITERATIONS,
            "gradient_tolerance": OPTIMIZER_G_TOL,
        },
        "independent_work": {
            "initial_energy_evaluations_for_audit": 1,
            "energy_evaluations": 1,
            "gradient_vector_evaluations": 0 if dimension == 0 else 1,
            "explicit_state_recomputations": 2,
        },
        "wall_time_seconds": time.perf_counter() - started,
        "finite": finite,
        "independent_state_recomputation_fidelity": repeat_fidelity,
        "source_candidate_state_fidelity": baseline_fidelity,
        "final_inverse_hessian": hessian.tolist(),
        "paper_measurement_cost": None,
    }


def _resource_delta(before: Any, after: Any) -> dict[str, int]:
    return {
        field: int(getattr(after, field) - getattr(before, field))
        for field in (
            "cnot_count",
            "cnot_depth",
            "total_depth",
            "parameter_count",
            "logical_block_count",
        )
    }


def _safe_label(
    path: Mapping[str, Any],
    baseline_energy: float,
    fci_energy: float,
    constraint_residual: float,
    before: Any,
    after: Any,
    resource_consistent: bool,
) -> tuple[bool, dict[str, bool]]:
    resource_pairs = [
        (getattr(before, field), getattr(after, field))
        for field in (
            "cnot_count",
            "cnot_depth",
            "total_depth",
            "parameter_count",
            "logical_block_count",
        )
    ]
    checks = {
        "finite": bool(path["finite"]),
        "local_energy_budget": path["energy_hartree"] - baseline_energy <= LOCAL_BUDGET_HARTREE,
        "chemical_accuracy": abs(path["independent_energy_hartree"] - fci_energy) < CHEMICAL_ACCURACY_HARTREE,
        "independent_energy": path["independent_energy_difference_hartree"] <= 1e-10,
        "independent_state": path["independent_state_recomputation_fidelity"] >= 1.0 - 1e-10,
        "constraint": constraint_residual <= 1e-10,
        "kkt": path["gradient_infinity"] <= 1e-8,
        "optimizer_path": bool(path["optimizer"]["success"]),
        "resource_recount_consistent": resource_consistent,
        "pareto_nonworse": all(new <= old for old, new in resource_pairs),
        "resource_improved": any(new < old for old, new in resource_pairs),
    }
    return all(checks.values()), checks


def _evaluate_candidate(
    algorithm: Any,
    pool: Any,
    source: AnsatzStructure,
    checkpoint: Mapping[str, Any],
    exact_hessian: np.ndarray | None,
    block: Any,
    candidate: Any,
    before_resources: Any,
    backend: Any,
) -> dict[str, Any]:
    candidate_started = time.perf_counter()
    embedded = embed_block_transformation(len(source.indices), block, candidate)
    transform = embedded.transformation
    theta = np.asarray(source.coefficients, dtype=np.float64)
    gradient = np.asarray(checkpoint["gradient"], dtype=np.float64)
    inverse_hessian = np.asarray(checkpoint["recycled_inverse_hessian"], dtype=np.float64)
    prediction_started = time.perf_counter()
    predictors = predictor_values(
        theta,
        gradient,
        inverse_hessian,
        transform,
        exact_hessian=exact_hessian,
    )
    projection_off = least_squares_native_coordinates(theta, transform)
    projection_on, target_inverse_hessian, constraint_prediction = obs_warm_start(
        theta, gradient, inverse_hessian, transform
    )
    prediction_wall = time.perf_counter() - prediction_started
    baseline_state = _state_vector(algorithm, source.coefficients, source.indices)
    paths: dict[str, Any] = {}
    for path_name, initial in (
        ("projection_off", projection_off),
        ("projection_on", projection_on),
    ):
        local_coordinates = initial[embedded.local_target_slice]
        initial_structure = apply_candidate_structure(
            pool, source, candidate, local_coordinates
        )
        if len(initial_structure.indices) != len(initial):
            raise RuntimeError("global target coordinates differ from target ansatz dimension")
        path = _optimize_target(
            algorithm,
            initial_structure.indices,
            initial,
            target_inverse_hessian,
            baseline_state,
        )
        final_coordinates = np.asarray(path["coordinates"], dtype=np.float64)
        final_local = final_coordinates[embedded.local_target_slice]
        final_structure = apply_candidate_structure(pool, source, candidate, final_local)
        final_structure = AnsatzStructure.create(
            final_structure.indices,
            final_coordinates,
            final_structure.cumulative_parameter_counts,
        )
        physical_resources = evaluate_full_circuit_resources(pool, final_structure, backend)
        structural_resources = evaluate_full_circuit_resources(
            pool,
            final_structure,
            backend,
            coefficient_policy="deterministic-structural",
        )
        resource_consistent = physical_resources.snapshot == structural_resources.snapshot
        source_theta = transform.offset + transform.jacobian @ final_coordinates
        constraint_residual = float(
            np.max(np.abs(transform.constraint_matrix @ source_theta - transform.constraint_rhs))
        ) if transform.constraint_matrix.shape[0] else 0.0
        safe, checks = _safe_label(
            path,
            float(checkpoint["energy_hartree"]),
            float(checkpoint["fci_energy_hartree"]),
            constraint_residual,
            before_resources.snapshot,
            physical_resources.snapshot,
            resource_consistent,
        )
        path.update(
            {
                "initial_coordinates": initial.tolist(),
                "initial_energy_hartree": float(
                    algorithm.evaluate_energy(list(initial), list(initial_structure.indices))
                ),
                "actual_change_hartree": path["independent_energy_hartree"]
                - float(checkpoint["energy_hartree"]),
                "constraint_residual_infinity": constraint_residual,
                "resources": resources_to_dict(physical_resources),
                "deterministic_structural_resources": resources_to_dict(structural_resources),
                "resource_recount_consistent": resource_consistent,
                "resource_delta": _resource_delta(
                    before_resources.snapshot, physical_resources.snapshot
                ),
                "safe": safe,
                "safe_checks": checks,
            }
        )
        paths[path_name] = path
    primary = paths["projection_on"]
    return {
        "calibration_version": CALIBRATION_VERSION,
        "case_id": checkpoint["case_id"],
        "checkpoint_digest": checkpoint["checkpoint_digest"],
        "candidate": candidate_to_dict(candidate),
        "source_block": block_to_dict(block),
        "global_constraint_shape": list(transform.constraint_matrix.shape),
        "global_jacobian_shape": list(transform.jacobian.shape),
        "predictors": predictors,
        "constraint_prediction": {
            "predicted_constraint_penalty_hartree": constraint_prediction.predicted_constraint_penalty,
            "predicted_change_from_current_hartree": constraint_prediction.predicted_change_from_current,
            "reference_energy_kind": constraint_prediction.reference_energy_kind,
        },
        "paths": paths,
        "primary_actual_path": "projection_on",
        "actual_change_hartree": primary["actual_change_hartree"],
        "safe": primary["safe"],
        "paper_measurement_cost": None,
        "candidate_shared_work": {
            "source_state_recomputations": 1,
            "prediction_wall_time_seconds": prediction_wall,
            "total_candidate_wall_time_seconds": time.perf_counter() - candidate_started,
            "paper_measurement_cost": None
        },
    }


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    fields = [
        "case_id", "candidate_id", "kind", "target_family", "safe",
        "actual_change_hartree", "magnitude", "magnitude_position",
        "diagonal_hessian", "single_coordinate_obs", "general_constraint_obs",
        "exact_hessian_oracle", "projection_on_success", "projection_on_iterations",
        "projection_on_nfev", "projection_on_njev", "projection_on_wall_seconds",
        "projection_off_success", "projection_off_iterations", "projection_off_nfev",
        "projection_off_njev", "projection_off_wall_seconds", "delta_cnot_count",
        "delta_cnot_depth", "delta_total_depth", "delta_parameters", "delta_blocks",
        "paper_measurement_cost",
    ]
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            if "error" in row:
                continue
            candidate = row["candidate"]
            on = row["paths"]["projection_on"]
            off = row["paths"]["projection_off"]
            delta = on["resource_delta"]
            writer.writerow({
                "case_id": row["case_id"],
                "candidate_id": candidate["candidate_id"],
                "kind": candidate["kind"],
                "target_family": candidate["target_family"],
                "safe": row["safe"],
                "actual_change_hartree": row["actual_change_hartree"],
                **{name: row["predictors"].get(name) for name in (
                    "magnitude", "magnitude_position", "diagonal_hessian",
                    "single_coordinate_obs", "general_constraint_obs", "exact_hessian_oracle",
                )},
                "projection_on_success": on["optimizer"]["success"],
                "projection_on_iterations": on["optimizer"]["iterations"],
                "projection_on_nfev": on["optimizer"]["function_evaluations"],
                "projection_on_njev": on["optimizer"]["gradient_vector_evaluations"],
                "projection_on_wall_seconds": on["wall_time_seconds"],
                "projection_off_success": off["optimizer"]["success"],
                "projection_off_iterations": off["optimizer"]["iterations"],
                "projection_off_nfev": off["optimizer"]["function_evaluations"],
                "projection_off_njev": off["optimizer"]["gradient_vector_evaluations"],
                "projection_off_wall_seconds": off["wall_time_seconds"],
                "delta_cnot_count": delta["cnot_count"],
                "delta_cnot_depth": delta["cnot_depth"],
                "delta_total_depth": delta["total_depth"],
                "delta_parameters": delta["parameter_count"],
                "delta_blocks": delta["logical_block_count"],
                "paper_measurement_cost": None,
            })
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    _fsync_directory(path.parent)


def _write_plots(directory: Path, rows: Sequence[Mapping[str, Any]]) -> list[str]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    outputs: list[str] = []
    for method in ENERGY_PREDICTORS:
        points = [row for row in rows if "error" not in row and row["predictors"].get(method) is not None]
        if not points:
            continue
        figure, axis = plt.subplots(figsize=(6.4, 4.8))
        for case_id, marker in (("h2-1.5-iteration-1", "o"), ("h4-1.5-first-chemical-accuracy", "s")):
            selected = [row for row in points if row["case_id"] == case_id]
            axis.scatter(
                [row["predictors"][method] for row in selected],
                [row["actual_change_hartree"] for row in selected],
                marker=marker,
                label=case_id,
            )
        bounds = [
            min(min(row["predictors"][method], row["actual_change_hartree"]) for row in points),
            max(max(row["predictors"][method], row["actual_change_hartree"]) for row in points),
        ]
        axis.plot(bounds, bounds, linestyle="--", color="black", linewidth=1, label="ideal")
        axis.axhline(LOCAL_BUDGET_HARTREE, color="red", linewidth=1, label="actual budget")
        axis.axvline(LOCAL_BUDGET_HARTREE, color="red", linewidth=1, linestyle=":", label="predicted budget")
        axis.set_xlabel(f"{method} predicted change (Hartree)")
        axis.set_ylabel("Actual optimized change (Hartree)")
        axis.set_title("S8 development-system calibration")
        axis.legend(fontsize=7)
        figure.tight_layout()
        output = directory / f"scatter-{method}.svg"
        temporary = output.with_suffix(".svg.tmp")
        figure.savefig(temporary, format="svg")
        plt.close(figure)
        os.replace(temporary, output)
        outputs.append(output.name)
    return outputs


def run_cases(
    bundle: Path,
    *,
    cases: Sequence[str],
    artifact_kind: str,
    protocol_tag: str,
    protocol_amendment_tag: str | None,
    claim_boundary: Sequence[str],
    resume: bool = False,
) -> dict[str, Any]:
    provenance = verify_upstream()
    if bundle.exists():
        raise FileExistsError(f"refusing to overwrite completed S8 bundle: {bundle}")
    staging = bundle.with_name(f".{bundle.name}.staging")
    if staging.exists() and not resume:
        raise FileExistsError(f"S8 staging exists; inspect it and pass --resume: {staging}")
    staging.mkdir(parents=True, exist_ok=True)
    (staging / "rows").mkdir(exist_ok=True)
    _fsync_directory(staging.parent)
    all_rows: list[dict[str, Any]] = []
    checkpoints: list[dict[str, Any]] = []
    catalog: list[dict[str, Any]] = []
    warning_records: list[warnings.WarningMessage] = []
    for case_id in cases:
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            algorithm, pool, source, checkpoint, exact_hessian = _build_checkpoint(case_id)
        warning_records.extend(captured)
        checkpoint_path = staging / f"checkpoint-{case_id}.json"
        if checkpoint_path.exists():
            existing = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            if existing["checkpoint_digest"] != checkpoint["checkpoint_digest"]:
                raise RuntimeError("resume checkpoint digest mismatch")
        else:
            _write_exclusive(checkpoint_path, checkpoint)
        checkpoints.append(checkpoint)
        backend = paper_era_backend()
        before_resources = evaluate_full_circuit_resources(pool, source, backend)
        blocks = recover_dvg_blocks(
            pool,
            source.indices,
            source.coefficients,
            source.cumulative_parameter_counts,
        )
        candidates = enumerate_candidates(pool, blocks)
        representatives: dict[str, Any] = {}
        for candidate in candidates:
            representatives.setdefault(candidate.equivalence_class_id, candidate)
        for candidate in candidates:
            catalog.append({
                "case_id": case_id,
                "candidate": candidate_to_dict(candidate),
                "executed_representative_candidate_id": representatives[candidate.equivalence_class_id].candidate_id,
                "is_executed_representative": representatives[candidate.equivalence_class_id].candidate_id == candidate.candidate_id,
            })
        block_by_id = {block.block_id: block for block in blocks}
        for ordinal, candidate in enumerate(representatives.values()):
            row_path = staging / "rows" / f"{case_id}-{ordinal:04d}-{candidate.candidate_id.split(':')[-1]}.json"
            if row_path.exists():
                row = json.loads(row_path.read_text(encoding="utf-8"))
            else:
                started = time.perf_counter()
                try:
                    row = _evaluate_candidate(
                        algorithm,
                        pool,
                        source,
                        checkpoint,
                        exact_hessian,
                        block_by_id[candidate.source_block_id],
                        candidate,
                        before_resources,
                        backend,
                    )
                except Exception as error:
                    row = {
                        "calibration_version": CALIBRATION_VERSION,
                        "case_id": case_id,
                        "checkpoint_digest": checkpoint["checkpoint_digest"],
                        "candidate": candidate_to_dict(candidate),
                        "error": {"type": type(error).__name__, "message": str(error)},
                        "wall_time_seconds_before_failure": time.perf_counter() - started,
                        "safe": False,
                        "paper_measurement_cost": None,
                    }
                _write_exclusive(row_path, row)
            all_rows.append(row)
    successful = [row for row in all_rows if "error" not in row]
    predictor_names = (
        "magnitude",
        "magnitude_position",
        "diagonal_hessian",
        "single_coordinate_obs",
        "general_constraint_obs",
        "exact_hessian_oracle",
    )
    metrics = [calibration_metrics(successful, method) for method in predictor_names]
    _write_atomic_json(staging / "candidate-catalog.json", catalog)
    jsonl_path = staging / "all-candidates.jsonl"
    jsonl_temporary = jsonl_path.with_suffix(".jsonl.tmp")
    with jsonl_temporary.open("w", encoding="utf-8") as stream:
        for row in all_rows:
            stream.write(json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(jsonl_temporary, jsonl_path)
    _fsync_directory(staging)
    _write_csv(staging / "all-candidates.csv", all_rows)
    plots = _write_plots(staging, successful)
    warning_counts = Counter(
        f"{record.category.__module__}.{record.category.__name__}: {record.message}"
        for record in warning_records
    )
    summary = {
        "schema_version": "1.0.0",
        "artifact_kind": artifact_kind,
        "calibration_version": CALIBRATION_VERSION,
        "protocol_tag": protocol_tag,
        "protocol_amendment_tag": protocol_amendment_tag,
        "upstream": provenance,
        "environment": _environment(),
        "checkpoints": [
            {
                "case_id": value["case_id"],
                "checkpoint_digest": value["checkpoint_digest"],
                "adapt_iteration": value["trajectory"][-1]["adapt_iteration"],
                "energy_hartree": value["energy_hartree"],
                "fci_energy_hartree": value["fci_energy_hartree"],
                "absolute_error_hartree": value["absolute_error_hartree"],
                "parameter_count": len(value["ansatz_indices"]),
                "hessian_quality_usable": value["hessian_capture"]["quality"]["numerically_usable"],
                "exact_hessian_available": value["exact_hessian"] is not None,
            }
            for value in checkpoints
        ],
        "catalog_candidate_count": len(catalog),
        "executed_equivalence_classes": len(all_rows),
        "successful_candidate_evaluations": len(successful),
        "failed_candidate_evaluations": len(all_rows) - len(successful),
        "primary_safe_candidates": sum(bool(row["safe"]) for row in successful),
        "metrics": metrics,
        "warnings": {
            "total_captured": len(warning_records),
            "unique": [
                {"warning": warning, "count": count}
                for warning, count in sorted(warning_counts.items())
            ],
        },
        "plots": plots,
        "paper_measurement_cost": None,
        "claim_boundary": list(claim_boundary),
    }
    _write_atomic_json(staging / "summary.json", summary)
    _fsync_directory(staging)
    bundle.parent.mkdir(parents=True, exist_ok=True)
    os.replace(staging, bundle)
    _fsync_directory(bundle.parent)
    return summary


def run_probe(bundle: Path, *, resume: bool = False) -> dict[str, Any]:
    return run_cases(
        bundle,
        cases=("h2-1.5-iteration-1", "h4-1.5-first-chemical-accuracy"),
        artifact_kind="s8-h2-h4-predictor-calibration",
        protocol_tag="dvg-obs-s8-calibration-protocol-v1",
        protocol_amendment_tag="dvg-obs-s8-calibration-protocol-amendment-1",
        claim_boundary=(
            "H2/H4 are non-blind development systems used only for selector calibration.",
            "Failed candidates and optimizer failures are retained and counted.",
            "nfev/njev and statevector work are not paper-equivalent measurement cost.",
            "No LiH or out-of-sample performance claim is made at S8.",
        ),
        resume=resume,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    arguments = parser.parse_args()
    sys.argv[:] = [sys.argv[0]]
    result = run_probe(arguments.bundle, resume=arguments.resume)
    print(json.dumps({
        "bundle": str(arguments.bundle),
        "executed": result["executed_equivalence_classes"],
        "safe": result["primary_safe_candidates"],
        "failed": result["failed_candidate_evaluations"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()

"""Independent numerical and failure audit for V5-S5."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np

from .quadratic import ConstraintTargetIR, QuadraticModel, predict_constrained_optimum
from .v3_protocol import _write_exclusive
from .v5_hvp_kkt import CentralDifferenceHVP, HVPKKTConfig, HVPRefinementError, solve_affine_kkt_hvp


def run_audit() -> dict[str, Any]:
    hessian = np.asarray([[5.0, 1.0, 0.2], [1.0, 4.0, 0.5], [0.2, 0.5, 3.0]])
    theta = np.asarray([0.2, -0.1, 0.3])
    gradient = np.asarray([0.03, -0.08, 0.02])
    matrix = np.asarray([[1.0, 1.0, 0.0]])
    rhs = np.asarray([0.05])
    transformation = ConstraintTargetIR.create(
        constraint_matrix=matrix,
        constraint_rhs=rhs,
        offset=[0.025, 0.025, 0.0],
        jacobian=[[1.0, 0.0], [-1.0, 0.0], [0.0, 1.0]],
        source_slots=("a", "b", "c"),
        target_slots=("u", "v"),
        generator_normalization="audit",
        orientation="audit",
    )
    legacy = predict_constrained_optimum(
        QuadraticModel.create(theta, gradient, np.linalg.inv(hessian)), transformation
    )
    fixed = dict(
        minimum_curvature=1e-12,
        minres_tolerance=1e-13,
        maximum_relative_residual=1e-10,
        maximum_relative_backward_error=1e-10,
        maximum_hessian_vector_products=512,
    )
    explicit = solve_affine_kkt_hvp(
        theta, gradient, matrix, rhs, lambda vector: hessian @ vector,
        config=HVPKKTConfig(explicit_validation_dimension=12, **fixed),
    )
    matrix_free = solve_affine_kkt_hvp(
        theta, gradient, matrix, rhs, lambda vector: hessian @ vector,
        config=HVPKKTConfig(explicit_validation_dimension=0, **fixed),
        preconditioner_diagonal=np.diag(hessian),
    )
    finite_difference = solve_affine_kkt_hvp(
        theta,
        gradient,
        matrix,
        rhs,
        CentralDifferenceHVP(theta, lambda point: hessian @ point + gradient),
        config=HVPKKTConfig(explicit_validation_dimension=12, **fixed),
    )

    failures: dict[str, str] = {}
    probes = {
        "indefinite": np.diag([1.0, -1.0, 2.0]),
        "singular": np.diag([1.0, 0.0, 2.0]),
        "asymmetric": np.asarray([[2.0, 1.0, 0.0], [0.0, 2.0, 0.0], [0.0, 0.0, 2.0]]),
    }
    for name, probe in probes.items():
        try:
            solve_affine_kkt_hvp(theta, gradient, matrix, rhs, lambda vector, probe=probe: probe @ vector, config=HVPKKTConfig(explicit_validation_dimension=12, **fixed))
        except HVPRefinementError as error:
            failures[name] = error.category
    try:
        solve_affine_kkt_hvp(theta, gradient, matrix, rhs, lambda vector: hessian @ vector, config=HVPKKTConfig(explicit_validation_dimension=12, maximum_hessian_vector_products=1, **{key: value for key, value in fixed.items() if key != "maximum_hessian_vector_products"}))
    except HVPRefinementError as error:
        failures["budget"] = error.category

    checks = {
        "explicit_matches_existing_obs": np.allclose(explicit["candidate_theta"], legacy.constrained_theta, atol=1e-11, rtol=1e-11),
        "matrix_free_matches_explicit": np.allclose(matrix_free["candidate_theta"], explicit["candidate_theta"], atol=1e-10, rtol=1e-10),
        "finite_difference_matches_analytic": np.allclose(finite_difference["candidate_theta"], explicit["candidate_theta"], atol=1e-9, rtol=1e-9),
        "failure_categories_are_deterministic": failures == {
            "indefinite": "nonpositive-curvature",
            "singular": "nonpositive-curvature",
            "asymmetric": "asymmetric-hessian",
            "budget": "hvp-budget-exceeded",
        },
        "matrix_free_work_is_counted": matrix_free["work"]["hessian_vector_products"] > 0 and matrix_free["work"]["solver_products"] > 0,
        "finite_difference_gradient_work_is_counted": finite_difference["work"]["gradient_vector_evaluations"] == 6,
        "no_silent_damping": explicit["damping"] == 0.0 and explicit["damping_reason"] is None,
        "measurement_cost_not_relabelled": explicit["paper_measurement_cost"] is None,
    }
    result = {
        "schema_version": "1.0.0",
        "artifact_kind": "v5-s5-matrix-free-kkt-independent-audit",
        "passed": all(checks.values()),
        "checks": checks,
        "failure_categories": failures,
        "explicit_result": explicit,
        "matrix_free_result": matrix_free,
        "finite_difference_result": finite_difference,
        "claim_boundary": "Synthetic quadratic/KKT validation only; no molecular VQE performance claim.",
    }
    if not result["passed"]:
        failed = sorted(name for name, passed in checks.items() if not passed)
        raise RuntimeError(f"V5-S5 audit failed: {failed}")
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

import numpy as np
import pytest

from dvg_obs_ceo.quadratic import ConstraintTargetIR, QuadraticModel, predict_constrained_optimum
from dvg_obs_ceo.v5_hvp_kkt import (
    CentralDifferenceHVP,
    HVPKKTConfig,
    HVPRefinementError,
    solve_affine_kkt_hvp,
)


HESSIAN = np.asarray([[4.0, 1.0], [1.0, 3.0]])
THETA = np.asarray([0.3, -0.2])
GRADIENT = np.asarray([0.1, -0.4])
CONSTRAINT = np.asarray([[1.0, 1.0]])
RHS = np.asarray([0.1])


def config(**updates):
    values = {
        "explicit_validation_dimension": 12,
        "minimum_curvature": 1e-12,
        "minres_tolerance": 1e-13,
        "maximum_relative_residual": 1e-10,
        "maximum_relative_backward_error": 1e-10,
    }
    values.update(updates)
    return HVPKKTConfig(**values)


def test_hvp_kkt_matches_existing_constrained_obs_solution() -> None:
    transformation = ConstraintTargetIR.create(
        constraint_matrix=CONSTRAINT,
        constraint_rhs=RHS,
        offset=[0.05, 0.05],
        jacobian=[[1.0], [-1.0]],
        source_slots=("a", "b"),
        target_slots=("t",),
        generator_normalization="test",
        orientation="test",
    )
    legacy = predict_constrained_optimum(
        QuadraticModel.create(THETA, GRADIENT, np.linalg.inv(HESSIAN)),
        transformation,
    )
    refined = solve_affine_kkt_hvp(
        THETA, GRADIENT, CONSTRAINT, RHS, lambda vector: HESSIAN @ vector,
        config=config(),
    )
    np.testing.assert_allclose(refined["candidate_theta"], legacy.constrained_theta, atol=1e-11, rtol=1e-11)
    assert refined["constraint_residual_infinity"] <= 1e-11
    assert refined["stationarity_residual_infinity"] <= 1e-10


def test_forced_matrix_free_route_matches_explicit_route() -> None:
    explicit = solve_affine_kkt_hvp(THETA, GRADIENT, CONSTRAINT, RHS, lambda value: HESSIAN @ value, config=config())
    matrix_free = solve_affine_kkt_hvp(
        THETA,
        GRADIENT,
        CONSTRAINT,
        RHS,
        lambda value: HESSIAN @ value,
        config=config(explicit_validation_dimension=0, maximum_hessian_vector_products=256),
        preconditioner_diagonal=np.diag(HESSIAN),
    )
    assert not matrix_free["explicit_validation_used"]
    np.testing.assert_allclose(matrix_free["candidate_theta"], explicit["candidate_theta"], atol=1e-10, rtol=1e-10)
    assert matrix_free["work"]["hessian_vector_products"] > 0
    assert matrix_free["work"]["solver_products"] > 0


def test_central_gradient_hvp_is_counted_and_exact_for_quadratic() -> None:
    callback = CentralDifferenceHVP(THETA, lambda point: HESSIAN @ point + GRADIENT)
    result = solve_affine_kkt_hvp(THETA, GRADIENT, CONSTRAINT, RHS, callback, config=config())
    assert result["work"]["hessian_vector_products"] == 2
    assert result["work"]["gradient_vector_evaluations"] == 4


@pytest.mark.parametrize(
    ("matrix", "category"),
    [
        (np.asarray([[1.0, 2.0], [0.0, 1.0]]), "asymmetric-hessian"),
        (np.asarray([[1.0, 0.0], [0.0, -1.0]]), "nonpositive-curvature"),
        (np.zeros((2, 2)), "nonpositive-curvature"),
    ],
)
def test_invalid_hessian_classes_fail_closed(matrix, category) -> None:
    with pytest.raises(HVPRefinementError) as captured:
        solve_affine_kkt_hvp(THETA, GRADIENT, CONSTRAINT, RHS, lambda value: matrix @ value, config=config())
    assert captured.value.category == category
    assert captured.value.work["hessian_vector_products"] > 0


def test_rank_deficient_constraint_and_hvp_budget_fail_closed() -> None:
    with pytest.raises(HVPRefinementError) as captured:
        solve_affine_kkt_hvp(THETA, GRADIENT, [[1.0, 1.0], [2.0, 2.0]], [0.1, 0.2], lambda value: HESSIAN @ value, config=config())
    assert captured.value.category == "rank-deficient-constraints"
    with pytest.raises(HVPRefinementError) as captured:
        solve_affine_kkt_hvp(THETA, GRADIENT, CONSTRAINT, RHS, lambda value: HESSIAN @ value, config=config(maximum_hessian_vector_products=1))
    assert captured.value.category == "hvp-budget-exceeded"


def test_damping_requires_registered_provenance() -> None:
    with pytest.raises(HVPRefinementError, match="registered reason"):
        config(damping=1e-5).validate()
    accepted = config(damping=1e-5, damping_reason="registered-stabilization-study")
    result = solve_affine_kkt_hvp(THETA, GRADIENT, CONSTRAINT, RHS, lambda value: HESSIAN @ value, config=accepted)
    assert result["damping"] == 1e-5
    assert result["damping_reason"] == "registered-stabilization-study"


def test_deterministic_nongradient_noise_is_rejected_as_asymmetric() -> None:
    callback = CentralDifferenceHVP(
        THETA,
        lambda point: HESSIAN @ point + np.asarray([1e-2 * point[1], 0.0]),
    )
    with pytest.raises(HVPRefinementError) as captured:
        solve_affine_kkt_hvp(THETA, GRADIENT, CONSTRAINT, RHS, callback, config=config(symmetry_relative_tolerance=1e-8))
    assert captured.value.category == "asymmetric-hessian"


def test_one_dimensional_forced_matrix_free_route_is_supported() -> None:
    result = solve_affine_kkt_hvp(
        [0.2], [0.1], np.zeros((0, 1)), [], lambda value: 2.0 * value,
        config=config(explicit_validation_dimension=0),
    )
    np.testing.assert_allclose(result["candidate_theta"], [0.15], atol=1e-12)
    assert result["minimum_curvature"] == pytest.approx(2.0)


def test_minres_nonconvergence_has_stable_failure_category() -> None:
    hessian = np.diag([1.0, 2.0, 4.0, 8.0])
    with pytest.raises(HVPRefinementError) as captured:
        solve_affine_kkt_hvp(
            [0.1, -0.2, 0.3, -0.4],
            [1.0, 2.0, 3.0, 4.0],
            [[1.0, 1.0, 1.0, 1.0]],
            [0.0],
            lambda value: hessian @ value,
            config=HVPKKTConfig(
                explicit_validation_dimension=12,
                minimum_curvature=1e-12,
                minres_tolerance=1e-15,
                maximum_iterations=1,
            ),
        )
    assert captured.value.category == "minres-nonconvergence"


def test_indefinite_full_hessian_is_allowed_when_reduced_hessian_is_spd() -> None:
    hessian = np.diag([-2.0, 3.0])
    result = solve_affine_kkt_hvp(
        [0.2, -0.1],
        [0.4, 0.3],
        [[1.0, 0.0]],
        [0.0],
        lambda value: hessian @ value,
        config=config(),
    )
    assert result["feasible_dimension"] == 1
    assert result["minimum_curvature"] == pytest.approx(3.0)
    np.testing.assert_allclose(result["candidate_theta"], [0.0, -0.2], atol=1e-11)

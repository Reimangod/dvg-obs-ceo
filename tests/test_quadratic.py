import numpy as np
import pytest

from dvg_obs_ceo.quadratic import (
    ConstraintTargetIR,
    NumericalPolicy,
    QuadraticModel,
    QuadraticModelError,
    predict_constrained_optimum,
    solve_spd,
    target_native_model,
    target_newton_direction,
    validate_spd,
)


def model(theta, gradient, hessian) -> QuadraticModel:
    return QuadraticModel.create(theta, gradient, solve_spd(hessian, np.eye(len(theta))))


def deletion_ir(dimension: int, deleted: tuple[int, ...]) -> ConstraintTargetIR:
    kept = tuple(index for index in range(dimension) if index not in deleted)
    a = np.zeros((len(deleted), dimension))
    for row, index in enumerate(deleted):
        a[row, index] = 1.0
    j = np.zeros((dimension, len(kept)))
    for column, index in enumerate(kept):
        j[index, column] = 1.0
    return ConstraintTargetIR.create(
        constraint_matrix=a,
        constraint_rhs=np.zeros(len(deleted)),
        offset=np.zeros(dimension),
        jacobian=j,
        source_slots=tuple(f"source-{index}" for index in range(dimension)),
        target_slots=tuple(f"target-{index}" for index in kept),
        generator_normalization="unit-test-v1",
        orientation="canonical-positive",
    )


def relation_ir(sign: float) -> ConstraintTargetIR:
    # sign=+1 means theta_0 = theta_1; sign=-1 means theta_0 = -theta_1.
    return ConstraintTargetIR.create(
        constraint_matrix=[[1.0, -sign]],
        constraint_rhs=[0.0],
        offset=[0.0, 0.0],
        jacobian=[[1.0], [sign]],
        source_slots=("left", "right"),
        target_slots=("native",),
        generator_normalization="unit-test-v1",
        orientation="plus" if sign > 0 else "minus",
    )


def analytic_kkt(theta, gradient, hessian, a, b):
    n = len(theta)
    kkt = np.block([[hessian, a.T], [a, np.zeros((a.shape[0], a.shape[0]))]])
    rhs = np.concatenate([hessian @ theta - gradient, b])
    return np.linalg.solve(kkt, rhs)[:n]


@pytest.mark.parametrize("deleted", [(1,), (0, 2)])
def test_coordinate_and_multiple_deletion_match_analytic_kkt(deleted) -> None:
    theta = np.array([0.4, -0.3, 0.7])
    gradient = np.array([0.2, -0.1, 0.3])
    hessian = np.array([[3.0, 0.2, 0.1], [0.2, 2.0, -0.1], [0.1, -0.1, 4.0]])
    source = model(theta, gradient, hessian)
    ir = deletion_ir(3, deleted)
    predicted = predict_constrained_optimum(source, ir)
    expected = analytic_kkt(theta, gradient, hessian, ir.constraint_matrix, ir.constraint_rhs)
    native = target_native_model(source, ir)
    np.testing.assert_allclose(predicted.constrained_theta, expected, atol=1e-11)
    np.testing.assert_allclose(native.optimum_source_theta, expected, atol=1e-11)
    assert predicted.predicted_change_from_current == pytest.approx(
        predicted.direct_quadratic_change_from_current, abs=1e-12
    )


@pytest.mark.parametrize("sign", [1.0, -1.0])
def test_equal_and_opposite_parameter_relations(sign: float) -> None:
    hessian = np.array([[4.0, 0.3], [0.3, 2.0]])
    source = model([0.2, -0.4], [0.7, -0.2], hessian)
    ir = relation_ir(sign)
    predicted = predict_constrained_optimum(source, ir)
    native = target_native_model(source, ir)
    np.testing.assert_allclose(predicted.constrained_theta, native.optimum_source_theta, atol=1e-12)
    assert predicted.constrained_theta[0] == pytest.approx(
        sign * predicted.constrained_theta[1], abs=1e-12
    )


def test_nonzero_gradient_reference_terms_are_not_conflated() -> None:
    hessian = np.diag([2.0, 5.0])
    source = model([0.5, 0.1], [0.4, -0.8], hessian)
    predicted = predict_constrained_optimum(source, deletion_ir(2, (0,)))
    unconstrained_change = -0.5 * source.gradient @ source.inverse_hessian @ source.gradient
    assert predicted.predicted_constraint_penalty >= 0.0
    assert predicted.predicted_change_from_current == pytest.approx(
        unconstrained_change + predicted.predicted_constraint_penalty
    )
    assert predicted.reference_energy_kind == "current-checkpoint-quadratic-model"


def test_stationary_single_deletion_matches_known_obs_saliency() -> None:
    inverse_hessian = np.array([[0.8, 0.1], [0.1, 0.5]])
    source = QuadraticModel.create([0.3, -0.2], [0.0, 0.0], inverse_hessian)
    predicted = predict_constrained_optimum(source, deletion_ir(2, (0,)))
    expected = source.theta[0] ** 2 / (2.0 * inverse_hessian[0, 0])
    assert predicted.predicted_constraint_penalty == pytest.approx(expected, abs=1e-13)
    assert predicted.predicted_change_from_current == pytest.approx(expected, abs=1e-13)


def test_nonzero_affine_constraint_matches_analytic_kkt() -> None:
    hessian = np.array([[2.0, 0.4], [0.4, 3.0]])
    source = model([0.3, -0.2], [0.6, -0.1], hessian)
    ir = ConstraintTargetIR.create(
        constraint_matrix=[[1.0, 1.0]],
        constraint_rhs=[0.7],
        offset=[0.7, 0.0],
        jacobian=[[1.0], [-1.0]],
        source_slots=("left", "right"),
        target_slots=("affine",),
        generator_normalization="unit-test-v1",
        orientation="affine-positive",
    )
    expected = analytic_kkt(
        source.theta,
        source.gradient,
        hessian,
        ir.constraint_matrix,
        ir.constraint_rhs,
    )
    np.testing.assert_allclose(
        predict_constrained_optimum(source, ir).constrained_theta, expected, atol=1e-12
    )
    np.testing.assert_allclose(target_native_model(source, ir).optimum_source_theta, expected, atol=1e-12)


def test_slot_permutation_sign_and_basis_rotation_preserve_source_optimum() -> None:
    rng = np.random.default_rng(20260720)
    raw = rng.normal(size=(4, 4))
    hessian = raw.T @ raw + np.eye(4)
    source = model(rng.normal(size=4), rng.normal(size=4), hessian)
    base = deletion_ir(4, (3,))
    base_native = target_native_model(source, base)
    q, _ = np.linalg.qr(rng.normal(size=(3, 3)))
    signed_permutation = q @ np.diag([1.0, -1.0, 1.0])
    rotated = ConstraintTargetIR.create(
        constraint_matrix=base.constraint_matrix,
        constraint_rhs=base.constraint_rhs,
        offset=base.offset,
        jacobian=base.jacobian @ signed_permutation,
        source_slots=base.source_slots,
        target_slots=("rotated-2", "rotated-0", "rotated-1"),
        generator_normalization=base.generator_normalization,
        orientation="rotated-test-basis",
    )
    rotated_native = target_native_model(source, rotated)
    np.testing.assert_allclose(
        rotated_native.optimum_source_theta,
        base_native.optimum_source_theta,
        atol=1e-10,
    )
    np.testing.assert_allclose(
        rotated_native.hessian,
        signed_permutation.T @ base_native.hessian @ signed_permutation,
        atol=1e-10,
    )
    np.testing.assert_allclose(
        rotated_native.hessian @ rotated_native.inverse_hessian,
        np.eye(3),
        atol=1e-10,
    )

    permutation = np.array([2, 0, 3, 1])
    permutation_matrix = np.eye(4)[permutation]
    permuted_model = QuadraticModel.create(
        permutation_matrix @ source.theta,
        permutation_matrix @ source.gradient,
        permutation_matrix @ source.inverse_hessian @ permutation_matrix.T,
    )
    permuted_ir = ConstraintTargetIR.create(
        constraint_matrix=base.constraint_matrix @ permutation_matrix.T,
        constraint_rhs=base.constraint_rhs,
        offset=permutation_matrix @ base.offset,
        jacobian=permutation_matrix @ base.jacobian,
        source_slots=tuple(base.source_slots[index] for index in permutation),
        target_slots=base.target_slots,
        generator_normalization=base.generator_normalization,
        orientation="source-slot-permuted",
    )
    permuted_native = target_native_model(permuted_model, permuted_ir)
    np.testing.assert_allclose(
        permutation_matrix.T @ permuted_native.optimum_source_theta,
        base_native.optimum_source_theta,
        atol=1e-10,
    )


def test_analytic_target_newton_direction_reaches_optimum() -> None:
    source = model([0.3, -0.2], [0.5, -0.7], [[3.0, 0.2], [0.2, 1.5]])
    ir = relation_ir(1.0)
    current = np.array([0.6])
    direction = target_newton_direction(source, ir, current)
    native = target_native_model(source, ir)
    np.testing.assert_allclose(current + direction, native.optimum_coordinates, atol=1e-12)


def test_random_spd_quadratics_match_kkt_and_target_native_solution() -> None:
    rng = np.random.default_rng(731)
    for dimension in range(2, 8):
        for _ in range(20):
            raw = rng.normal(size=(dimension, dimension))
            hessian = raw.T @ raw + 0.5 * np.eye(dimension)
            theta = rng.normal(size=dimension)
            gradient = rng.normal(size=dimension)
            deleted = tuple(sorted(rng.choice(dimension, size=max(1, dimension // 3), replace=False)))
            source = model(theta, gradient, hessian)
            ir = deletion_ir(dimension, deleted)
            predicted = predict_constrained_optimum(source, ir)
            native = target_native_model(source, ir)
            expected = analytic_kkt(theta, gradient, hessian, ir.constraint_matrix, ir.constraint_rhs)
            np.testing.assert_allclose(predicted.constrained_theta, expected, atol=2e-10)
            np.testing.assert_allclose(native.optimum_source_theta, expected, atol=2e-10)
            assert predicted.predicted_constraint_penalty >= -1e-13


def test_ill_conditioned_asymmetric_and_redundant_inputs_fail_closed() -> None:
    strict = NumericalPolicy(maximum_condition_number=1e8)
    with pytest.raises(QuadraticModelError, match="condition"):
        validate_spd(np.diag([1.0, 1e-10]), strict)
    with pytest.raises(QuadraticModelError, match="symmetry"):
        validate_spd([[2.0, 0.2], [0.0, 1.0]])
    source = model([0.1, 0.2], [0.0, 0.0], np.eye(2))
    redundant = ConstraintTargetIR.create(
        constraint_matrix=[[1.0, 0.0], [2.0, 0.0]],
        constraint_rhs=[0.0, 0.0],
        offset=[0.0, 0.0],
        jacobian=np.zeros((2, 0)),
        source_slots=("a", "b"),
        target_slots=(),
        generator_normalization="unit-test-v1",
        orientation="deletion",
    )
    with pytest.raises(QuadraticModelError, match="rank deficient"):
        predict_constrained_optimum(source, redundant)


def test_invalid_target_jacobian_and_offset_fail_closed() -> None:
    source = model([0.1, 0.2], [0.0, 0.0], np.eye(2))
    bad_jacobian = ConstraintTargetIR.create(
        constraint_matrix=[[1.0, -1.0]],
        constraint_rhs=[0.0],
        offset=[0.0, 0.0],
        jacobian=[[1.0], [0.0]],
        source_slots=("a", "b"),
        target_slots=("target",),
        generator_normalization="unit-test-v1",
        orientation="bad",
    )
    with pytest.raises(QuadraticModelError, match="A @ J"):
        predict_constrained_optimum(source, bad_jacobian)


def test_model_inputs_are_defensively_copied_and_immutable() -> None:
    theta = np.array([0.1, 0.2])
    source = QuadraticModel.create(theta, [0.0, 0.0], np.eye(2))
    theta[0] = 99.0
    assert source.theta[0] == pytest.approx(0.1)
    with pytest.raises(ValueError):
        source.theta[0] = 2.0

import numpy as np
import pytest

from dvg_obs_ceo.hessian import SecantPair
from dvg_obs_ceo.joint_prediction import (
    JointPredictionError,
    JointQualityPolicy,
    evaluate_joint_quality,
    joint_obs_prediction,
)
from dvg_obs_ceo.quadratic import ConstraintTargetIR


def _pair(step, hessian, source="internal-bfgs"):
    step = np.asarray(step, dtype=float)
    return SecantPair.create(
        np.zeros_like(step), step, np.zeros_like(step), hessian @ step, source=source
    )


def _transform(rows, rhs, jacobian, offset=None):
    source = len(jacobian)
    target = len(jacobian[0]) if source else 0
    return ConstraintTargetIR.create(
        constraint_matrix=rows,
        constraint_rhs=rhs,
        offset=np.zeros(source) if offset is None else offset,
        jacobian=jacobian,
        source_slots=[f"s:{i}" for i in range(source)],
        target_slots=[f"t:{i}" for i in range(target)],
        generator_normalization="test",
        orientation="test",
    )


def test_exact_quadratic_joint_prediction_and_projected_secants() -> None:
    hessian = np.array([[2.0, 0.2], [0.2, 1.5]])
    inverse = np.linalg.inv(hessian)
    internal = [_pair([1.0, 0.0], hessian), _pair([0.0, 1.0], hessian)]
    held = [_pair([1.0, 1.0], hessian, "held-out-independent")]
    transform = _transform([[1.0, 0.0]], [0.0], [[0.0], [1.0]])
    result = joint_obs_prediction(
        [0.3, -0.2], [0.1, -0.05], inverse, transform,
        internal_pairs=internal, held_out_pairs=held,
    )
    diagnostics = result["diagnostics"]
    assert diagnostics["constraint_direction_coverage"] == pytest.approx(1.0)
    assert diagnostics["internal_projected_secants"]["maximum_relative_residual"] < 1e-14
    assert diagnostics["held_out_projected_secants"]["maximum_relative_residual"] < 1e-14
    quality = evaluate_joint_quality(
        result,
        JointQualityPolicy(
            minimum_constraint_direction_coverage=0.99,
            maximum_internal_projected_residual=1e-12,
            maximum_held_out_projected_residual=1e-12,
            require_held_out_evidence=True,
        ),
    )
    assert quality["passed"]


def test_held_out_evidence_is_unknown_not_relabelled_internal() -> None:
    hessian = np.eye(2)
    result = joint_obs_prediction(
        [0.2, 0.1], [0.0, 0.0], hessian,
        _transform([[1.0, 0.0]], [0.0], [[0.0], [1.0]]),
        internal_pairs=[_pair([1.0, 0.0], hessian)],
    )
    assert not result["diagnostics"]["held_out_evidence_available"]
    assert result["diagnostics"]["held_out_projected_secants"]["maximum_relative_residual"] is None
    quality = evaluate_joint_quality(
        result, JointQualityPolicy(require_held_out_evidence=True)
    )
    assert not quality["passed"]
    assert not quality["checks"]["held_out_evidence"]


def test_nested_constraints_have_nondecreasing_fixed_surrogate_loss() -> None:
    model = dict(theta=[0.3, -0.2], gradient=[0.01, -0.03], inverse_hessian=np.eye(2))
    pairs = [_pair([1.0, 0.0], np.eye(2)), _pair([0.0, 1.0], np.eye(2))]
    one = joint_obs_prediction(
        **model,
        transformation=_transform([[1.0, 0.0]], [0.0], [[0.0], [1.0]]),
        internal_pairs=pairs,
    )
    two = joint_obs_prediction(
        **model,
        transformation=_transform(
            [[1.0, 0.0], [0.0, 1.0]], [0.0, 0.0], [[], []]
        ),
        internal_pairs=pairs,
    )
    assert two["predicted_change_from_current_hartree"] >= (
        one["predicted_change_from_current_hartree"] - 1e-12
    )


def test_overlapping_secant_roles_and_singular_solve_fail_closed() -> None:
    hessian = np.eye(2)
    pair = _pair([1.0, 0.0], hessian)
    held = SecantPair(
        pair.pair_id, "held-out-independent", pair.step, pair.gradient_change,
        pair.curvature, pair.normalized_curvature, pair.valid_for_bfgs_quality,
    )
    transform = _transform([[1.0, 0.0]], [0.0], [[0.0], [1.0]])
    with pytest.raises(JointPredictionError, match="overlap"):
        joint_obs_prediction(
            [0.0, 0.0], [0.0, 0.0], hessian, transform,
            internal_pairs=[pair], held_out_pairs=[held],
        )
    with pytest.raises(JointPredictionError, match="numerical solve"):
        joint_obs_prediction(
            [0.0, 0.0], [0.0, 0.0], [[1.0, 0.0], [0.0, 0.0]], transform,
            internal_pairs=[pair],
        )

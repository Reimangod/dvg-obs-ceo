from types import ModuleType, SimpleNamespace

import numpy as np
import pytest

from dvg_obs_ceo.hessian import (
    HessianCaptureError,
    HessianCaptureSession,
    HessianQualityPolicy,
    SecantPair,
    checkpoint_optimality,
    diagnose_inverse_hessian,
    require_usable_hessian,
)
from dvg_obs_ceo.s5_probe import compare_off_on


def pair(old_x, new_x, old_g, new_g, source="internal-bfgs"):
    return SecantPair.create(old_x, new_x, old_g, new_g, source=source)


def test_exact_inverse_hessian_secants_and_held_out_are_separate() -> None:
    hessian = np.diag([2.0, 4.0])
    inverse = np.diag([0.5, 0.25])
    internal = pair([0, 0], [1, 0], [0, 0], hessian @ np.array([1, 0]))
    held = pair([0, 0], [0, 1], [0, 0], hessian @ np.array([0, 1]), source="held-out-independent")
    report = diagnose_inverse_hessian(inverse, [internal], [held])
    assert report.internal_secant_max_relative_residual == pytest.approx(0.0)
    assert report.held_out_secant_max_relative_residual == pytest.approx(0.0)
    assert report.secant_direction_coverage == pytest.approx(0.5)
    assert report.numerically_usable
    require_usable_hessian(report)


def test_overlap_bad_curvature_and_bad_matrix_fail_closed() -> None:
    internal = pair([0, 0], [1, 0], [0, 0], [2, 0])
    held_same_data = pair([0, 0], [1, 0], [0, 0], [2, 0], source="held-out-independent")
    with pytest.raises(HessianCaptureError, match="overlap"):
        diagnose_inverse_hessian(np.eye(2), [internal], [held_same_data])
    bad_pair = pair([0, 0], [1, 0], [0, 0], [-1, 0])
    report = diagnose_inverse_hessian(
        [[1.0, 0.3], [0.0, -1.0]],
        [bad_pair],
        policy=HessianQualityPolicy(maximum_age_steps=0),
    )
    assert not report.numerically_usable
    assert "asymmetric" in report.rejection_reasons
    assert "not-sufficiently-positive-definite" in report.rejection_reasons
    assert "insufficient-valid-updates" in report.rejection_reasons
    with pytest.raises(HessianCaptureError, match="rejected"):
        require_usable_hessian(report)
    nonfinite = diagnose_inverse_hessian([[float("nan"), 0.0], [0.0, 1.0]], [internal])
    assert not nonfinite.finite
    assert nonfinite.symmetry_relative_residual is None
    assert "non-finite" in nonfinite.rejection_reasons


def test_checkpoint_optimality_reports_projected_gradient_and_kkt() -> None:
    result = checkpoint_optimality(
        [1.0, -1.0],
        theta=[0.2, 0.2],
        constraint_matrix=[[1.0, -1.0]],
        constraint_rhs=[0.0],
        target_jacobian=[[1.0], [1.0]],
        parameter_step=[0.01, -0.01],
        recent_energy_change_hartree=-1e-7,
    )
    assert result.projected_gradient_l2 == pytest.approx(0.0)
    assert result.constraint_residual_infinity == pytest.approx(0.0)
    assert result.kkt_residual == pytest.approx(0.0)
    assert result.gradient_l2 > 0.0


def test_capture_wrapper_preserves_result_callback_and_evaluation_counts() -> None:
    module = ModuleType("fake_adapt_vqe")
    callback_calls = []

    def fake_minimize(fun, x0, *, callback=None, g0=None, initial_inv_hessian=None, **kwargs):
        first = SimpleNamespace(x=np.array([0.5]), fun=0.25, inv_hessian=np.array([[0.5]]), gradient=np.array([1.0]))
        second = SimpleNamespace(x=np.array([0.0]), fun=0.0, inv_hessian=np.array([[0.5]]), gradient=np.array([0.0]))
        callback(first)
        callback(second)
        return SimpleNamespace(
            x=second.x,
            jac=second.gradient,
            hess_inv=second.inv_hessian,
            success=True,
            status=0,
            message="ok",
            nit=2,
            nfev=5,
            njev=3,
        )

    module.minimize_bfgs = fake_minimize
    original = module.minimize_bfgs
    with HessianCaptureSession(module) as capture:
        result = module.minimize_bfgs(
            lambda x: float(x @ x),
            [1.0],
            callback=lambda item: callback_calls.append(item.fun),
            g0=[2.0],
            initial_inv_hessian=[[0.5]],
        )
    assert module.minimize_bfgs is original
    assert result.nfev == 5 and result.njev == 3
    assert callback_calls == [0.25, 0.0]
    assert len(capture.records) == 1
    record = capture.records[0]
    assert record.function_evaluations == 5
    assert record.gradient_evaluations == 3
    assert len(record.secant_pairs) == 2
    assert record.quality.numerically_usable


def test_capture_observes_optimizer_computed_initial_gradient_without_extra_call() -> None:
    module = ModuleType("fake_adapt_vqe_without_g0")
    jac_calls = []

    def fake_minimize(fun, x0, *, callback=None, jac=None, **kwargs):
        initial_gradient = jac(np.array(x0))
        current = SimpleNamespace(
            x=np.array([0.0]),
            fun=0.0,
            inv_hessian=np.array([[0.5]]),
            gradient=np.array([0.0]),
        )
        callback(current)
        return SimpleNamespace(
            x=current.x,
            jac=current.gradient,
            hess_inv=current.inv_hessian,
            success=True,
            status=0,
            message="ok",
            nit=1,
            nfev=2,
            njev=1,
        )

    module.minimize_bfgs = fake_minimize

    def jacobian(x):
        jac_calls.append(tuple(x))
        return 2.0 * np.asarray(x)

    with HessianCaptureSession(module) as capture:
        module.minimize_bfgs(lambda x: float(x @ x), [1.0], jac=jacobian)
    assert jac_calls == [(1.0,)]
    assert len(capture.records[0].secant_pairs) == 1


def test_capture_session_rejects_nesting_and_restores_after_error() -> None:
    module = ModuleType("fake_adapt_vqe")
    module.minimize_bfgs = lambda *args, **kwargs: None
    original = module.minimize_bfgs
    with pytest.raises(RuntimeError):
        with HessianCaptureSession(module):
            with pytest.raises(HessianCaptureError, match="active"):
                with HessianCaptureSession(module):
                    pass
            raise RuntimeError("injected")
    assert module.minimize_bfgs is original


def test_off_on_comparator_excludes_only_time_and_environment() -> None:
    base = {
        "energy_hartree": -1.0,
        "fci_energy_hartree": -1.1,
        "absolute_error_hartree": 0.1,
        "first_chemical_accuracy_iteration": None,
        "ansatz_indices": [4],
        "ansatz_coefficients": [0.2],
        "parameter_count": 1,
        "cnot_count": 9,
        "cnot_depth": 7,
        "cnot_counts_by_iteration": [0, 9],
        "cnot_depths_by_iteration": [0, 7],
        "trajectory": [{"adapt_iteration": 1}],
        "scientific_state_digest": "a" * 64,
        "work": {
            "nfev": 3,
            "ngev_component_equivalent": 2,
            "paper_measurement_cost": None,
            "wall_time_seconds": 1.0,
        },
        "environment": {"platform": "first"},
    }
    observed = {**base, "work": {**base["work"], "wall_time_seconds": 2.0}, "environment": {"platform": "second"}}
    assert compare_off_on(base, observed)["passed"]
    observed["cnot_count"] = 10
    result = compare_off_on(base, observed)
    assert not result["passed"]
    assert next(item for item in result["comparisons"] if item["field"] == "cnot_count")["exact_equal"] is False

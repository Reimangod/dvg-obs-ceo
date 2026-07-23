import numpy as np

from dvg_obs_ceo.polishing import TrustNCGConfig, polish_trust_ncg


def test_trust_ncg_polishes_spd_quadratic_deterministically() -> None:
    hessian = np.array([[3.0, 0.2], [0.2, 1.5]])
    center = np.array([0.3, -0.4])

    def energy(x: np.ndarray) -> float:
        delta = x - center
        return float(0.5 * delta @ hessian @ delta - 1.0)

    def gradient(x: np.ndarray) -> np.ndarray:
        return hessian @ (x - center)

    first = polish_trust_ncg([0.9, 0.1], energy, gradient)
    second = polish_trust_ncg([0.9, 0.1], energy, gradient)
    assert first == second
    assert first["success"]
    assert first["gradient_infinity"] <= 5e-9
    np.testing.assert_allclose(first["coordinates"], center, atol=1e-9, rtol=0.0)
    assert first["work"]["hessian_vector_gradient_evaluations"] == 2 * first["work"]["hessian_vector_products"]
    assert first["scipy_reported"]["function_evaluations"] + 1 == first["work"]["energy_evaluations"]
    assert (
        first["scipy_reported"]["hessian_evaluations_including_dummy"]
        == first["work"]["hessian_vector_products"] + 1
    )
    assert first["scipy_reported"]["dummy_hessian_initializations"] == 1
    assert (
        first["scipy_reported"]["gradient_evaluations_excluding_hvp"]
        + first["work"]["hessian_vector_gradient_evaluations"]
        + 1
        == first["work"]["gradient_vector_evaluations"]
    )


def test_trust_ncg_budget_exhaustion_fails_closed_without_mutating_input() -> None:
    initial = np.array([10.0, -5.0])
    before = initial.copy()
    config = TrustNCGConfig(maximum_gradient_vector_evaluations=1)
    result = polish_trust_ncg(
        initial,
        lambda x: float(x @ x),
        lambda x: 2.0 * x,
        config=config,
    )
    assert not result["success"]
    assert result["failure_reason"] == "EvaluationBudgetExceeded"
    np.testing.assert_array_equal(initial, before)
    np.testing.assert_array_equal(result["coordinates"], before)


def test_zero_dimensional_target_is_exact_and_does_not_request_gradient() -> None:
    result = polish_trust_ncg(
        [],
        lambda _x: -1.0,
        lambda _x: (_ for _ in ()).throw(AssertionError("gradient must not be called")),
    )
    assert result["success"]
    assert result["gradient"] == []
    assert result["work"]["gradient_vector_evaluations"] == 0


def test_already_certified_target_does_not_enter_scipy() -> None:
    result = polish_trust_ncg(
        [0.2],
        lambda x: float(x[0] ** 2),
        lambda _x: np.array([9e-9]),
    )
    assert result["success"]
    assert result["termination_origin"] == "preflight-certificate"
    assert result["iterations"] == 0
    assert result["work"]["energy_evaluations"] == 1
    assert result["work"]["gradient_vector_evaluations"] == 1

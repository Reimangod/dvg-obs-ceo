import numpy as np

from dvg_obs_ceo.v5_s8_hvp_step import central_hvp


def test_central_hvp_matches_quadratic_and_is_direction_antisymmetric() -> None:
    hessian = np.asarray([[3.0, 0.2], [0.2, 1.5]])
    point = np.asarray([0.4, -0.3])
    direction = np.asarray([0.6, 0.8])
    gradient = lambda value: hessian @ value + np.asarray([0.1, -0.2])
    forward, step = central_hvp(point, direction, gradient, 1e-5)
    reverse, reverse_step = central_hvp(point, -direction, gradient, 1e-5)
    np.testing.assert_allclose(forward, hessian @ direction, atol=1e-11, rtol=1e-11)
    np.testing.assert_allclose(reverse, -forward, atol=1e-12, rtol=0.0)
    assert step == reverse_step

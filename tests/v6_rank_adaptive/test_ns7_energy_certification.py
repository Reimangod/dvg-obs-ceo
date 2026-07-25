import numpy as np

from dvg_obs_ceo.v6_rank_adaptive.ns7_energy_certification import (
    _algorithm_for,
    affine_embedding,
    projected_initial_coordinates,
)


def test_affine_embedding_has_exact_registered_rank_and_constraint():
    parameter_map = np.asarray(
        [[-1, -1], [1, 0], [0, 1]], dtype=np.float64
    )
    embedding, slots = affine_embedding(
        6, (1, 2, 3), parameter_map
    )
    assert embedding.shape == (6, 5)
    assert np.linalg.matrix_rank(embedding) == 5
    assert len(slots) == 5
    assert np.allclose(
        np.asarray([1, 1, 1])
        @ embedding[[1, 2, 3], :],
        0.0,
    )


def test_euclidean_projection_is_deterministic_and_feasible():
    parameter_map = np.asarray(
        [[-1, 1], [1, 0], [0, 1]], dtype=np.float64
    )
    embedding, _ = affine_embedding(
        5, (0, 1, 2), parameter_map
    )
    source = np.asarray([0.2, -0.3, 0.4, 0.5, -0.6])
    first = projected_initial_coordinates(source, embedding)
    second = projected_initial_coordinates(source, embedding)
    assert np.array_equal(first, second)
    mapped = embedding @ first
    assert np.isclose(
        np.asarray([1, 1, -1]) @ mapped[:3],
        0.0,
        atol=1e-15,
    )


def test_upstream_optimizer_is_importable_after_algorithm_loader():
    algorithm, pool = _algorithm_for("h4-1.5-late")
    from adaptvqe.minimize import minimize_bfgs

    assert algorithm is not None
    assert pool is not None
    assert callable(minimize_bfgs)

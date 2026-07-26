import numpy as np

from dvg_obs_ceo.v6_rank_adaptive.ns9_sequential_pilot import (
    combined_embedding,
    projected_coordinates,
)


def test_combined_embedding_enforces_two_independent_planes():
    first = np.asarray([[-1, 1], [1, 0], [0, 1]], dtype=float)
    second = np.asarray([[-1, -1], [1, 0], [0, 1]], dtype=float)
    embedding, slots = combined_embedding(
        8,
        (
            ("a", (0, 1, 2), first),
            ("b", (4, 5, 6), second),
        ),
    )
    assert embedding.shape == (8, 6)
    assert np.linalg.matrix_rank(embedding) == 6
    assert np.allclose(
        np.asarray([1, 1, -1]) @ embedding[[0, 1, 2], :], 0
    )
    assert np.allclose(
        np.asarray([1, 1, 1]) @ embedding[[4, 5, 6], :], 0
    )
    assert len(slots) == 6


def test_combined_projection_is_feasible_and_deterministic():
    parameter_map = np.asarray(
        [[-1, -1], [1, 0], [0, 1]], dtype=float
    )
    embedding, _ = combined_embedding(
        7,
        (
            ("a", (0, 1, 2), parameter_map),
            ("b", (3, 4, 5), parameter_map),
        ),
    )
    source = np.linspace(-0.3, 0.3, 7)
    first = projected_coordinates(source, embedding)
    second = projected_coordinates(source, embedding)
    assert np.array_equal(first, second)
    mapped = embedding @ first
    assert np.isclose(np.sum(mapped[:3]), 0.0, atol=1e-15)
    assert np.isclose(np.sum(mapped[3:6]), 0.0, atol=1e-15)

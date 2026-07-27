from __future__ import annotations

import numpy as np

from dvg_obs_ceo.pra_path.s6_development_evaluation import (
    _orthonormal_tangent,
)
from dvg_obs_ceo.v6_rank_adaptive.ns7_energy_certification import (
    affine_embedding,
)


def test_orthonormal_tangent_is_coordinate_invariant_basis() -> None:
    parameter_map = np.asarray([[1, 0], [0, 1], [-1, -1]], dtype=float)
    embedding, _ = affine_embedding(7, (1, 2, 3), parameter_map)
    q = _orthonormal_tangent(embedding)
    assert q.shape == embedding.shape
    np.testing.assert_allclose(q.T @ q, np.eye(q.shape[1]), atol=1e-12)
    projector = q @ q.T
    np.testing.assert_allclose(projector @ embedding, embedding, atol=1e-12)


def test_coordinate_scaling_does_not_change_tangent_projector() -> None:
    parameter_map = np.asarray([[1, 0], [0, 1], [-1, -1]], dtype=float)
    embedding, _ = affine_embedding(7, (1, 2, 3), parameter_map)
    q1 = _orthonormal_tangent(embedding)
    scale = np.diag(np.linspace(0.5, 2.0, embedding.shape[1]))
    q2 = _orthonormal_tangent(embedding @ scale)
    np.testing.assert_allclose(q1 @ q1.T, q2 @ q2.T, atol=1e-12)

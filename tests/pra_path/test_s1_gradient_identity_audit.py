from __future__ import annotations

import numpy as np

from dvg_obs_ceo.pra_path.s1_gradient_identity_audit import (
    _decode_float64,
)
from dvg_obs_ceo.identity import canonical_float64_hex


def test_float64_coordinate_round_trip_is_exact() -> None:
    values = np.asarray([-1.25, 0.0, 3.5], dtype=np.float64)
    assert np.array_equal(
        _decode_float64(canonical_float64_hex(values)), values
    )


def test_orthonormal_tangent_projection_is_scale_invariant() -> None:
    embedding = np.asarray([[2.0, 0.0], [0.0, 3.0], [0.0, 0.0]])
    rescaled = embedding @ np.diag([7.0, 0.5])
    first, _ = np.linalg.qr(embedding, mode="reduced")
    second, _ = np.linalg.qr(rescaled, mode="reduced")
    assert np.allclose(first @ first.T, second @ second.T)

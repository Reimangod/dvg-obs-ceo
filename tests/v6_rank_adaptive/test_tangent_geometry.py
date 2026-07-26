from __future__ import annotations

import numpy as np
import pytest

from dvg_obs_ceo.v6_rank_adaptive.tangent_geometry import (
    TangentGeometryError,
    central_projective_tangents,
    conditional_geometry,
    normalized_rayleigh,
    null_space_alignment,
    normalized_state,
)


def test_global_phase_is_removed_from_projective_tangent() -> None:
    def state(theta: np.ndarray) -> np.ndarray:
        return np.exp(1j * theta[0]) * np.array([1.0, 0.0])

    _, tangents = central_projective_tangents(state, [0.2], step=1e-6)
    assert np.linalg.norm(tangents) < 1e-9


def test_real_linear_conditioning_removes_compensable_direction() -> None:
    # Columns 0 and 2 are identical real-parameter tangent directions.
    tangents = np.array(
        [[1.0, 0.0, 1.0], [0.0, 1j, 0.0]], dtype=np.complex128
    )
    evidence = conditional_geometry(tangents, [0, 1])
    assert evidence.rest_rank == 1
    assert evidence.local_gram[0, 0] == pytest.approx(1.0)
    assert evidence.conditional_gram[0, 0] < 1e-28
    assert evidence.conditional_gram[1, 1] == pytest.approx(1.0)


def test_null_normal_has_zero_score_and_unit_alignment() -> None:
    gram = np.diag([0.0, 2.0, 3.0])
    assert normalized_rayleigh(gram, [1, 0, 0]) == pytest.approx(0.0)
    alignment, dimension = null_space_alignment(gram, [1, 0, 0])
    assert dimension == 1
    assert alignment == pytest.approx(1.0)


def test_kernel_is_deterministic() -> None:
    def state(theta: np.ndarray) -> np.ndarray:
        value = np.array([np.cos(theta[0]), np.sin(theta[0])])
        return value.astype(np.complex128)

    first = central_projective_tangents(state, [0.3], step=1e-6)[1]
    second = central_projective_tangents(state, [0.3], step=1e-6)[1]
    assert np.array_equal(first, second)


@pytest.mark.parametrize(
    "state",
    [
        np.array([]),
        np.array([0.0, 0.0]),
        np.array([np.nan, 0.0]),
        np.array([2.0, 0.0]),
    ],
)
def test_invalid_states_fail_closed(state: np.ndarray) -> None:
    with pytest.raises(TangentGeometryError):
        normalized_state(state)

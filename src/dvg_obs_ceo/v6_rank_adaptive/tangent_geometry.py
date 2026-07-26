"""Fail-closed real-parameter projective tangent geometry for V6.1."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np


class TangentGeometryError(ValueError):
    """Raised when tangent evidence cannot be certified."""


@dataclass(frozen=True)
class ConditionalGeometry:
    local_gram: np.ndarray
    conditional_gram: np.ndarray
    residual_tangents: np.ndarray
    rest_rank: int
    rest_singular_values: np.ndarray


def normalized_state(value: np.ndarray) -> np.ndarray:
    state = np.asarray(value, dtype=np.complex128).reshape(-1)
    norm = float(np.linalg.norm(state))
    if state.size == 0 or not np.all(np.isfinite(state)) or not np.isfinite(norm):
        raise TangentGeometryError("state must be finite and nonempty")
    if not np.isclose(norm, 1.0, rtol=0.0, atol=1e-10):
        raise TangentGeometryError("state must be normalized")
    return state


def projective_tangent(state: np.ndarray, derivative: np.ndarray) -> np.ndarray:
    psi = normalized_state(state)
    vector = np.asarray(derivative, dtype=np.complex128).reshape(-1)
    if vector.shape != psi.shape or not np.all(np.isfinite(vector)):
        raise TangentGeometryError("derivative is incompatible or nonfinite")
    return vector - psi * np.vdot(psi, vector)


def central_projective_tangents(
    state_function: Callable[[np.ndarray], np.ndarray],
    coordinates: Sequence[float],
    *,
    step: float,
) -> tuple[np.ndarray, np.ndarray]:
    theta = np.asarray(coordinates, dtype=np.float64)
    if (
        theta.ndim != 1
        or theta.size == 0
        or not np.all(np.isfinite(theta))
        or not np.isfinite(step)
        or step <= 0
    ):
        raise TangentGeometryError("coordinates and step must be finite")
    psi = normalized_state(state_function(theta.copy()))
    columns: list[np.ndarray] = []
    for index in range(theta.size):
        plus = theta.copy()
        minus = theta.copy()
        plus[index] += step
        minus[index] -= step
        derivative = (
            normalized_state(state_function(plus))
            - normalized_state(state_function(minus))
        ) / (2.0 * step)
        columns.append(projective_tangent(psi, derivative))
    tangents = np.column_stack(columns)
    if not np.all(np.isfinite(tangents)):
        raise TangentGeometryError("tangent matrix is nonfinite")
    return psi, tangents


def real_parameter_matrix(tangents: np.ndarray) -> np.ndarray:
    value = np.asarray(tangents, dtype=np.complex128)
    if value.ndim != 2 or not np.all(np.isfinite(value)):
        raise TangentGeometryError("tangent matrix must be finite and rank two")
    return np.vstack((value.real, value.imag))


def symmetric_gram(real_tangents: np.ndarray) -> np.ndarray:
    value = np.asarray(real_tangents, dtype=np.float64)
    if value.ndim != 2 or not np.all(np.isfinite(value)):
        raise TangentGeometryError("real tangent matrix is invalid")
    gram = value.T @ value
    return (gram + gram.T) / 2.0


def conditional_geometry(
    tangents: np.ndarray,
    block_positions: Sequence[int],
    *,
    relative_cutoff: float = 1e-10,
) -> ConditionalGeometry:
    real = real_parameter_matrix(tangents)
    positions = tuple(int(value) for value in block_positions)
    if (
        not positions
        or len(set(positions)) != len(positions)
        or min(positions) < 0
        or max(positions) >= real.shape[1]
        or not 0 < relative_cutoff < 1
    ):
        raise TangentGeometryError("block positions or cutoff are invalid")
    rest_positions = tuple(
        index for index in range(real.shape[1]) if index not in positions
    )
    block = real[:, positions]
    rest = real[:, rest_positions]
    if rest.shape[1] == 0:
        residual = block.copy()
        singular = np.empty(0, dtype=np.float64)
        rank = 0
    else:
        u, singular, _ = np.linalg.svd(rest, full_matrices=False)
        threshold = (
            relative_cutoff * singular[0] if singular.size else 0.0
        )
        rank = int(np.count_nonzero(singular > threshold))
        residual = block - u[:, :rank] @ (u[:, :rank].T @ block)
    return ConditionalGeometry(
        local_gram=symmetric_gram(block),
        conditional_gram=symmetric_gram(residual),
        residual_tangents=residual,
        rest_rank=rank,
        rest_singular_values=singular,
    )


def ordered_eigensystem(gram: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    value = np.asarray(gram, dtype=np.float64)
    if (
        value.ndim != 2
        or value.shape[0] != value.shape[1]
        or not np.all(np.isfinite(value))
        or not np.allclose(value, value.T, rtol=0.0, atol=1e-12)
    ):
        raise TangentGeometryError("Gram matrix must be finite and symmetric")
    eigenvalues, eigenvectors = np.linalg.eigh(value)
    scale = max(1.0, float(np.max(np.abs(eigenvalues), initial=0.0)))
    if float(np.min(eigenvalues, initial=0.0)) < -1e-10 * scale:
        raise TangentGeometryError("Gram matrix is not positive semidefinite")
    return np.maximum(eigenvalues, 0.0), eigenvectors


def normalized_rayleigh(gram: np.ndarray, normal: Sequence[float]) -> float:
    eigenvalues, _ = ordered_eigensystem(gram)
    vector = np.asarray(normal, dtype=np.float64)
    if (
        vector.shape != (gram.shape[0],)
        or not np.all(np.isfinite(vector))
        or np.linalg.norm(vector) == 0
    ):
        raise TangentGeometryError("normal is invalid")
    largest = float(eigenvalues[-1]) if eigenvalues.size else 0.0
    numerator = float(vector @ gram @ vector)
    denominator = float(vector @ vector) * max(largest, np.finfo(float).eps)
    score = numerator / denominator
    if not np.isfinite(score):
        raise TangentGeometryError("Rayleigh score is nonfinite")
    return max(0.0, score)


def null_space_alignment(
    gram: np.ndarray,
    normal: Sequence[float],
    *,
    relative_cutoff: float = 1e-10,
) -> tuple[float, int]:
    eigenvalues, eigenvectors = ordered_eigensystem(gram)
    vector = np.asarray(normal, dtype=np.float64)
    vector = vector / np.linalg.norm(vector)
    threshold = relative_cutoff * max(
        float(eigenvalues[-1]), np.finfo(float).eps
    )
    null = eigenvectors[:, eigenvalues <= threshold]
    alignment = float(np.sum((null.T @ vector) ** 2))
    return min(1.0, max(0.0, alignment)), int(null.shape[1])

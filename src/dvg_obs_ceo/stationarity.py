"""Independent target/source gradient agreement certificates."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Callable, Sequence

import numpy as np
from numpy.typing import ArrayLike, NDArray

from .quadratic import ConstraintTargetIR


FloatArray = NDArray[np.float64]
ComplexArray = NDArray[np.complex128]


class GradientAuditError(RuntimeError):
    """Raised when a gradient certificate cannot be evaluated safely."""


@dataclass(frozen=True)
class GradientAgreementPolicy:
    """Scale-aware vector agreement policy frozen before LiH execution."""

    absolute_tolerance: float = 1e-10
    relative_tolerance: float = 1e-8

    def validate(self) -> None:
        for name, value in (
            ("absolute_tolerance", self.absolute_tolerance),
            ("relative_tolerance", self.relative_tolerance),
        ):
            if not math.isfinite(value) or value < 0.0:
                raise GradientAuditError(f"{name} must be finite and nonnegative")
        if self.absolute_tolerance == 0.0 and self.relative_tolerance == 0.0:
            raise GradientAuditError("bitwise gradient agreement is not a valid policy")


def _vector(name: str, value: ArrayLike, dimension: int) -> FloatArray:
    result = np.asarray(value, dtype=np.float64)
    if result.shape != (dimension,) or not np.all(np.isfinite(result)):
        raise GradientAuditError(f"{name} must be a finite vector of length {dimension}")
    return result


def _state(name: str, value: ArrayLike) -> ComplexArray:
    result = np.asarray(value, dtype=np.complex128).ravel()
    norm = float(np.linalg.norm(result))
    if result.size == 0 or not np.all(np.isfinite(result)) or not math.isfinite(norm) or norm == 0.0:
        raise GradientAuditError(f"{name} must be a finite nonzero state vector")
    return result / norm


def audit_gradient_paths(
    coordinates: ArrayLike,
    transformation: ConstraintTargetIR,
    target_gradient: Callable[[FloatArray], ArrayLike],
    source_gradient: Callable[[FloatArray], ArrayLike],
    *,
    target_state: Callable[[FloatArray], ArrayLike] | None = None,
    source_state: Callable[[FloatArray], ArrayLike] | None = None,
    target_energy: Callable[[FloatArray], float] | None = None,
    source_energy: Callable[[FloatArray], float] | None = None,
    policy: GradientAgreementPolicy = GradientAgreementPolicy(),
) -> dict[str, object]:
    """Compare direct ``dE/dphi`` with ``J.T @ dE/dtheta`` at one point.

    The two derivative callables must be independent evaluations.  In
    particular, this function never accepts or reuses the checkpoint gradient.
    """

    policy.validate()
    source_dimension, target_dimension = transformation.jacobian.shape
    transformation.validate(source_dimension)
    phi = _vector("coordinates", coordinates, target_dimension)
    theta = transformation.offset + transformation.jacobian @ phi
    if not np.all(np.isfinite(theta)):
        raise GradientAuditError("mapped source coordinates are not finite")

    direct = _vector("target_gradient", target_gradient(phi.copy()), target_dimension)
    source = _vector("source_gradient", source_gradient(theta.copy()), source_dimension)
    projected = np.asarray(transformation.jacobian.T @ source, dtype=np.float64)
    difference = direct - projected
    limits = policy.absolute_tolerance + policy.relative_tolerance * np.maximum(
        np.abs(direct), np.abs(projected)
    )
    component_pass = np.abs(difference) <= limits
    passed = bool(np.all(component_pass))

    result: dict[str, object] = {
        "coordinates": phi.tolist(),
        "mapped_source_coordinates": theta.tolist(),
        "target_native_gradient": direct.tolist(),
        "source_gradient": source.tolist(),
        "projected_source_gradient": projected.tolist(),
        "componentwise_difference": difference.tolist(),
        "componentwise_limit": limits.tolist(),
        "componentwise_pass": component_pass.tolist(),
        "difference_infinity": float(np.max(np.abs(difference))) if difference.size else 0.0,
        "difference_l2": float(np.linalg.norm(difference)),
        "target_gradient_infinity": float(np.max(np.abs(direct))) if direct.size else 0.0,
        "projected_gradient_infinity": float(np.max(np.abs(projected))) if projected.size else 0.0,
        "passed": passed,
        "policy": {
            "absolute_tolerance": policy.absolute_tolerance,
            "relative_tolerance": policy.relative_tolerance,
        },
        "work": {
            "target_gradient_vector_evaluations": 1,
            "source_gradient_vector_evaluations": 1,
            "target_gradient_component_equivalent": target_dimension,
            "source_gradient_component_equivalent": source_dimension,
            "statevector_recomputations": 0,
            "energy_evaluations": 0,
            "paper_measurement_cost": None,
        },
    }

    if (target_state is None) != (source_state is None):
        raise GradientAuditError("both state paths must be supplied together")
    if target_state is not None and source_state is not None:
        target_value = _state("target_state", target_state(phi.copy()))
        source_value = _state("source_state", source_state(theta.copy()))
        if target_value.shape != source_value.shape:
            raise GradientAuditError("source and target states have different dimensions")
        fidelity = float(abs(np.vdot(target_value, source_value)) ** 2)
        fidelity = min(1.0, max(0.0, fidelity))
        result["source_target_state_fidelity"] = fidelity
        result["work"]["statevector_recomputations"] = 2  # type: ignore[index]

    if (target_energy is None) != (source_energy is None):
        raise GradientAuditError("both energy paths must be supplied together")
    if target_energy is not None and source_energy is not None:
        target_value = float(target_energy(phi.copy()))
        source_value = float(source_energy(theta.copy()))
        if not math.isfinite(target_value) or not math.isfinite(source_value):
            raise GradientAuditError("source or target energy is not finite")
        result["target_energy_hartree"] = target_value
        result["source_energy_hartree"] = source_value
        result["source_target_energy_difference_hartree"] = abs(target_value - source_value)
        result["work"]["energy_evaluations"] = 2  # type: ignore[index]
    return result


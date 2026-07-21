"""Budgeted target-native trust-region Newton-CG polishing."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Callable

import numpy as np
from numpy.typing import ArrayLike, NDArray
from scipy.optimize import minimize


FloatArray = NDArray[np.float64]
POLISHER_VERSION = "target-native-trust-ncg-central-gradient-hvp-v1"


class PolishingError(RuntimeError):
    """Raised when polishing inputs or numerical outputs are unsafe."""


class EvaluationBudgetExceeded(PolishingError):
    """Raised internally when a deterministic evaluation budget is exhausted."""


@dataclass(frozen=True)
class TrustNCGConfig:
    relative_hvp_step: float = float(np.finfo(np.float64).eps ** (1.0 / 3.0))
    damping: float = 0.0
    initial_trust_radius: float = 0.05
    maximum_trust_radius: float = 0.5
    acceptance_eta: float = 0.15
    gradient_l2_tolerance: float = 5e-9
    maximum_iterations: int = 8
    maximum_energy_evaluations: int = 16
    maximum_gradient_vector_evaluations: int = 128
    maximum_hessian_vector_products: int = 64
    permitted_success_statuses: tuple[int, ...] = (0,)
    fallback_policy: str = "none-fail-closed"

    def validate(self) -> None:
        finite_nonnegative = {
            "relative_hvp_step": self.relative_hvp_step,
            "damping": self.damping,
            "gradient_l2_tolerance": self.gradient_l2_tolerance,
        }
        if any(not math.isfinite(value) or value < 0.0 for value in finite_nonnegative.values()):
            raise PolishingError("step, damping, and gradient tolerance must be finite and nonnegative")
        if self.relative_hvp_step == 0.0 or self.gradient_l2_tolerance == 0.0:
            raise PolishingError("step and gradient tolerance must be positive")
        if not 0.0 <= self.acceptance_eta < 0.25:
            raise PolishingError("trust-region eta must be in [0, 0.25)")
        if not 0.0 < self.initial_trust_radius < self.maximum_trust_radius:
            raise PolishingError("trust radii must satisfy 0 < initial < maximum")
        integer_budgets = (
            self.maximum_iterations,
            self.maximum_energy_evaluations,
            self.maximum_gradient_vector_evaluations,
            self.maximum_hessian_vector_products,
        )
        if any(not isinstance(value, int) or value <= 0 for value in integer_budgets):
            raise PolishingError("all deterministic budgets must be positive integers")
        if self.permitted_success_statuses != (0,) or self.fallback_policy != "none-fail-closed":
            raise PolishingError("V3 permits only SciPy status 0 and no fallback")


@dataclass
class _Ledger:
    energy_evaluations: int = 0
    gradient_vector_evaluations: int = 0
    hessian_vector_products: int = 0
    hessian_vector_gradient_evaluations: int = 0


def _finite_vector(name: str, value: ArrayLike, dimension: int) -> FloatArray:
    result = np.asarray(value, dtype=np.float64)
    if result.shape != (dimension,) or not np.all(np.isfinite(result)):
        raise PolishingError(f"{name} must be a finite vector of length {dimension}")
    return result


def polish_trust_ncg(
    initial_coordinates: ArrayLike,
    energy_function: Callable[[FloatArray], float],
    gradient_function: Callable[[FloatArray], ArrayLike],
    *,
    config: TrustNCGConfig = TrustNCGConfig(),
) -> dict[str, object]:
    """Polish one target circuit with an explicitly counted central HVP."""

    config.validate()
    initial = np.asarray(initial_coordinates, dtype=np.float64)
    if initial.ndim != 1 or not np.all(np.isfinite(initial)):
        raise PolishingError("initial coordinates must be one finite vector")
    dimension = initial.size
    if dimension == 0:
        return {
            "version": POLISHER_VERSION,
            "coordinates": [],
            "energy_hartree": float(energy_function(initial.copy())),
            "gradient": [],
            "gradient_l2": 0.0,
            "gradient_infinity": 0.0,
            "success": True,
            "status": 0,
            "message": "exact zero-dimensional target",
            "iterations": 0,
            "scipy_reported": {
                "function_evaluations": 1,
                "gradient_evaluations_excluding_hvp": 0,
                "hessian_evaluations_including_dummy": 0,
                "dummy_hessian_initializations": 0,
            },
            "config": asdict(config),
            "work": {
                "energy_evaluations": 1,
                "gradient_vector_evaluations": 0,
                "hessian_vector_products": 0,
                "hessian_vector_gradient_evaluations": 0,
                "paper_measurement_cost": None,
            },
        }

    ledger = _Ledger()

    def energy(x: FloatArray) -> float:
        if ledger.energy_evaluations >= config.maximum_energy_evaluations:
            raise EvaluationBudgetExceeded("energy-evaluation budget exceeded")
        value = float(energy_function(np.asarray(x, dtype=np.float64).copy()))
        ledger.energy_evaluations += 1
        if not math.isfinite(value):
            raise PolishingError("energy evaluation returned a non-finite value")
        return value

    def gradient(x: FloatArray, *, from_hvp: bool = False) -> FloatArray:
        if ledger.gradient_vector_evaluations >= config.maximum_gradient_vector_evaluations:
            raise EvaluationBudgetExceeded("gradient-vector budget exceeded")
        value = _finite_vector(
            "analytic gradient",
            gradient_function(np.asarray(x, dtype=np.float64).copy()),
            dimension,
        )
        ledger.gradient_vector_evaluations += 1
        if from_hvp:
            ledger.hessian_vector_gradient_evaluations += 1
        return value

    def hessian_product(x: FloatArray, direction: FloatArray) -> FloatArray:
        if ledger.hessian_vector_products >= config.maximum_hessian_vector_products:
            raise EvaluationBudgetExceeded("Hessian-vector-product budget exceeded")
        vector = _finite_vector("HVP direction", direction, dimension)
        norm = float(np.linalg.norm(vector))
        ledger.hessian_vector_products += 1
        if norm == 0.0:
            return np.zeros(dimension, dtype=np.float64)
        scale = max(1.0, float(np.linalg.norm(x)))
        step = config.relative_hvp_step * scale / norm
        plus = gradient(np.asarray(x) + step * vector, from_hvp=True)
        minus = gradient(np.asarray(x) - step * vector, from_hvp=True)
        value = (plus - minus) / (2.0 * step) + config.damping * vector
        return _finite_vector("central-difference HVP", value, dimension)

    try:
        result = minimize(
            energy,
            initial.copy(),
            method="trust-ncg",
            jac=gradient,
            hessp=hessian_product,
            options={
                "initial_trust_radius": config.initial_trust_radius,
                "max_trust_radius": config.maximum_trust_radius,
                "eta": config.acceptance_eta,
                "gtol": config.gradient_l2_tolerance,
                "maxiter": config.maximum_iterations,
                "disp": False,
            },
        )
        coordinates = _finite_vector("optimizer coordinates", result.x, dimension)
        final_gradient = _finite_vector("optimizer gradient", result.jac, dimension)
        final_energy = float(result.fun)
        status = int(result.status)
        success = bool(result.success and status in config.permitted_success_statuses)
        message = str(result.message)
        iterations = int(result.nit)
        scipy_reported = {
            "function_evaluations": int(result.nfev),
            "gradient_evaluations_excluding_hvp": int(result.njev),
            "hessian_evaluations_including_dummy": int(result.nhev),
            "dummy_hessian_initializations": 1,
        }
        failure_reason = None
    except (EvaluationBudgetExceeded, PolishingError) as error:
        coordinates = initial.copy()
        final_energy = math.nan
        final_gradient = np.full(dimension, math.nan)
        status = -1
        success = False
        message = str(error)
        iterations = 0
        scipy_reported = None
        failure_reason = type(error).__name__

    return {
        "version": POLISHER_VERSION,
        "coordinates": coordinates.tolist(),
        "energy_hartree": final_energy,
        "gradient": final_gradient.tolist(),
        "gradient_l2": float(np.linalg.norm(final_gradient)),
        "gradient_infinity": float(np.max(np.abs(final_gradient))),
        "success": success,
        "status": status,
        "message": message,
        "failure_reason": failure_reason,
        "iterations": iterations,
        "scipy_reported": scipy_reported,
        "config": asdict(config),
        "work": {
            "energy_evaluations": ledger.energy_evaluations,
            "gradient_vector_evaluations": ledger.gradient_vector_evaluations,
            "hessian_vector_products": ledger.hessian_vector_products,
            "hessian_vector_gradient_evaluations": ledger.hessian_vector_gradient_evaluations,
            "paper_measurement_cost": None,
        },
    }

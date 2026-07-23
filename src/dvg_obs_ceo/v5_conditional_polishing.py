"""V5-S6 conditional polishing after exact target-coordinate elimination."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import math
from typing import Any, Callable

import numpy as np
from numpy.typing import ArrayLike, NDArray

from .polishing import TrustNCGConfig, polish_trust_ncg
from .quadratic import ConstraintTargetIR, QuadraticModelError
from .transaction import CompressionRuntime


FloatArray = NDArray[np.float64]
CONDITIONAL_POLISHING_VERSION = "v5-conditional-target-native-polishing-v1"
SECOND_START_TRIGGER = "primary-failed-and-distinct-least-squares-start"


class V5PolishingError(RuntimeError):
    """Raised when conditional polishing violates a scientific safety gate."""


@dataclass(frozen=True)
class PolishingEligibility:
    semantics_validated: bool
    physical_resource_benefit: bool
    predicted_energy_within_budget: bool
    refinement_required: bool


@dataclass(frozen=True)
class ConditionalPolishingConfig:
    polisher: TrustNCGConfig = TrustNCGConfig()
    maximum_constraint_residual: float = 1e-10
    required_gradient_infinity: float = 1e-8
    enable_second_least_squares_start: bool = False
    second_start_trigger: str | None = None
    minimum_second_start_distance: float = 1e-8
    maximum_total_energy_evaluations: int = 32
    maximum_total_gradient_vector_evaluations: int = 256
    maximum_total_hessian_vector_products: int = 128

    def validate(self) -> None:
        self.polisher.validate()
        if self.polisher.certification_infinity_threshold != 1e-8 or self.required_gradient_infinity != 1e-8:
            raise V5PolishingError("V5 must retain the frozen ||g_target||_inf <= 1e-8 certificate")
        if (
            not math.isfinite(self.maximum_constraint_residual)
            or self.maximum_constraint_residual <= 0
            or not math.isfinite(self.minimum_second_start_distance)
            or self.minimum_second_start_distance < 0
        ):
            raise V5PolishingError("conditional polishing tolerances are invalid")
        totals = (
            self.maximum_total_energy_evaluations,
            self.maximum_total_gradient_vector_evaluations,
            self.maximum_total_hessian_vector_products,
        )
        if any(not isinstance(value, int) or value <= 0 for value in totals):
            raise V5PolishingError("conditional polishing total budgets must be positive integers")
        if self.enable_second_least_squares_start:
            if self.second_start_trigger != SECOND_START_TRIGGER:
                raise V5PolishingError("second start requires the frozen trigger")
        elif self.second_start_trigger is not None:
            raise V5PolishingError("disabled second start cannot carry a trigger")


def _finite_vector(name: str, value: ArrayLike, dimension: int) -> FloatArray:
    result = np.asarray(value, dtype=np.float64)
    if result.shape != (dimension,) or not np.all(np.isfinite(result)):
        raise V5PolishingError(f"{name} must be a finite vector of length {dimension}")
    return result


def _target_coordinates(
    source: FloatArray,
    transformation: ConstraintTargetIR,
    tolerance: float,
    name: str,
) -> FloatArray:
    jacobian = transformation.jacobian
    target_dimension = jacobian.shape[1]
    if target_dimension == 0:
        coordinates = np.zeros(0, dtype=np.float64)
    else:
        coordinates, _, rank, _ = np.linalg.lstsq(
            jacobian, source - transformation.offset, rcond=None
        )
        if rank != target_dimension:
            raise V5PolishingError("target Jacobian is rank deficient")
    reconstructed = transformation.offset + jacobian @ coordinates
    residual = float(np.max(np.abs(reconstructed - source))) if source.size else 0.0
    if residual > tolerance:
        raise V5PolishingError(f"{name} is outside the exact target affine space")
    return np.asarray(coordinates, dtype=np.float64)


def _sum_work(results: list[dict[str, Any]]) -> dict[str, Any]:
    fields = (
        "energy_evaluations",
        "gradient_vector_evaluations",
        "hessian_vector_products",
        "hessian_vector_gradient_evaluations",
    )
    return {
        **{field: sum(int(result["work"][field]) for result in results) for field in fields},
        "paper_measurement_cost": None,
    }


def polish_target_native_conditionally(
    transformation: ConstraintTargetIR,
    projected_source_theta: ArrayLike,
    reference_source_theta: ArrayLike,
    source_energy: Callable[[FloatArray], float],
    source_gradient: Callable[[FloatArray], ArrayLike],
    eligibility: PolishingEligibility,
    *,
    config: ConditionalPolishingConfig = ConditionalPolishingConfig(),
    runtime_guard: CompressionRuntime | None = None,
) -> dict[str, Any]:
    """Polish only eligible candidates in exact reduced coordinates.

    The function never commits or mutates an ansatz. If a callback changes the
    guarded runtime (including RNG state), the complete snapshot is restored and
    the attempt is reported as an incident.
    """

    config.validate()
    source_dimension = transformation.offset.size
    try:
        transformation.validate(source_dimension)
    except QuadraticModelError as error:
        raise V5PolishingError("target transformation validation failed") from error
    projected = _finite_vector("projected source theta", projected_source_theta, source_dimension)
    reference = _finite_vector("reference source theta", reference_source_theta, source_dimension)
    blocked = []
    if not eligibility.semantics_validated:
        blocked.append("semantic-validation-failed")
    if not eligibility.physical_resource_benefit:
        blocked.append("no-physical-resource-benefit")
    if not eligibility.predicted_energy_within_budget:
        blocked.append("clear-predicted-energy-failure")
    if not eligibility.refinement_required:
        blocked.append("refinement-not-required")
    if blocked:
        return {
            "version": CONDITIONAL_POLISHING_VERSION,
            "performed": False,
            "success": False,
            "blocked_reasons": blocked,
            "attempts": [],
            "work": _sum_work([]),
            "paper_measurement_cost": None,
        }

    primary = _target_coordinates(
        projected, transformation, config.maximum_constraint_residual, "OBS/HVP projection"
    )
    secondary = np.linalg.lstsq(
        transformation.jacobian,
        reference - transformation.offset,
        rcond=None,
    )[0] if transformation.jacobian.shape[1] else np.zeros(0, dtype=np.float64)
    secondary = np.asarray(secondary, dtype=np.float64)
    before = runtime_guard.snapshot() if runtime_guard is not None else None

    def to_source(coordinates: FloatArray) -> FloatArray:
        return np.asarray(
            transformation.offset + transformation.jacobian @ coordinates,
            dtype=np.float64,
        )

    def energy(coordinates: FloatArray) -> float:
        source = to_source(coordinates)
        residual = transformation.constraint_matrix @ source - transformation.constraint_rhs
        if residual.size and float(np.max(np.abs(residual))) > config.maximum_constraint_residual:
            raise V5PolishingError("target map violated exact source constraint")
        value = float(source_energy(source.copy()))
        if not math.isfinite(value):
            raise V5PolishingError("source energy callback returned non-finite data")
        return value

    def gradient(coordinates: FloatArray) -> FloatArray:
        source = to_source(coordinates)
        source_value = _finite_vector(
            "source gradient", source_gradient(source.copy()), source_dimension
        )
        return np.asarray(transformation.jacobian.T @ source_value, dtype=np.float64)

    attempts: list[dict[str, Any]] = []
    try:
        primary_result = polish_trust_ncg(primary, energy, gradient, config=config.polisher)
        attempts.append({"start": "obs-hvp-projection", "result": primary_result})
        primary_certified = bool(
            primary_result["success"]
            and primary_result["gradient_infinity"] is not None
            and float(primary_result["gradient_infinity"])
            <= config.required_gradient_infinity
        )
        selected = primary_result if primary_certified else None

        total = _sum_work([item["result"] for item in attempts])
        distinct = float(np.linalg.norm(primary - secondary)) >= config.minimum_second_start_distance
        can_retry = (
            selected is None
            and config.enable_second_least_squares_start
            and config.second_start_trigger == SECOND_START_TRIGGER
            and distinct
        )
        if can_retry:
            remaining_energy = config.maximum_total_energy_evaluations - total["energy_evaluations"]
            remaining_gradient = config.maximum_total_gradient_vector_evaluations - total["gradient_vector_evaluations"]
            remaining_hvp = config.maximum_total_hessian_vector_products - total["hessian_vector_products"]
            if min(remaining_energy, remaining_gradient, remaining_hvp) > 0:
                second_config = replace(
                    config.polisher,
                    maximum_energy_evaluations=min(config.polisher.maximum_energy_evaluations, remaining_energy),
                    maximum_gradient_vector_evaluations=min(config.polisher.maximum_gradient_vector_evaluations, remaining_gradient),
                    maximum_hessian_vector_products=min(config.polisher.maximum_hessian_vector_products, remaining_hvp),
                )
                second_result = polish_trust_ncg(secondary, energy, gradient, config=second_config)
                attempts.append({"start": "registered-least-squares-reference", "result": second_result})
                if (
                    second_result["success"]
                    and second_result["gradient_infinity"] is not None
                    and float(second_result["gradient_infinity"])
                    <= config.required_gradient_infinity
                ):
                    selected = second_result

        total = _sum_work([item["result"] for item in attempts])
        if (
            total["energy_evaluations"] > config.maximum_total_energy_evaluations
            or total["gradient_vector_evaluations"] > config.maximum_total_gradient_vector_evaluations
            or total["hessian_vector_products"] > config.maximum_total_hessian_vector_products
        ):
            raise V5PolishingError("conditional polishing total work budget exceeded")
        success = bool(
            selected is not None
            and selected["gradient_infinity"] is not None
            and float(selected["gradient_infinity"]) <= config.required_gradient_infinity
        )
        if selected is not None:
            selected_coordinates = _finite_vector(
                "selected target coordinates", selected["coordinates"], transformation.jacobian.shape[1]
            )
            selected_source = to_source(selected_coordinates)
            constraint_residual = transformation.constraint_matrix @ selected_source - transformation.constraint_rhs
            constraint_infinity = float(np.max(np.abs(constraint_residual))) if constraint_residual.size else 0.0
            if constraint_infinity > config.maximum_constraint_residual:
                success = False
        else:
            selected_coordinates = None
            selected_source = None
            constraint_infinity = None
        result = {
            "version": CONDITIONAL_POLISHING_VERSION,
            "performed": True,
            "success": success,
            "blocked_reasons": [],
            "attempts": attempts,
            "selected_start": None if selected is None else next(
                item["start"] for item in attempts if item["result"] is selected
            ),
            "target_coordinates": None if selected_coordinates is None else selected_coordinates.tolist(),
            "source_theta": None if selected_source is None else selected_source.tolist(),
            "constraint_residual_infinity": constraint_infinity,
            "gradient_infinity": None if selected is None else selected["gradient_infinity"],
            "gradient_rms": (
                None if selected is None or selected["gradient"] is None
                else float(np.sqrt(np.mean(np.square(selected["gradient"]))))
            ),
            "work": total,
            "config": asdict(config),
            "paper_measurement_cost": None,
        }
    finally:
        if runtime_guard is not None and before is not None:
            if runtime_guard.snapshot().snapshot_digest != before.snapshot_digest:
                runtime_guard.restore(before)
                raise V5PolishingError("runtime-mutation-incident: guarded runtime was restored")
    return result

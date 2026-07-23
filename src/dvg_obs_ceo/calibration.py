"""S8 predictor calibration primitives with fixed source/target coordinates."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping, Sequence

import numpy as np
from numpy.typing import ArrayLike, NDArray
from scipy.stats import kendalltau, spearmanr

from .block_ir import CompressionCandidate, DVGBlock
from .quadratic import (
    ConstraintPrediction,
    ConstraintTargetIR,
    QuadraticModel,
    QuadraticModelError,
    predict_constrained_optimum,
    solve_spd,
    target_native_model,
)


FloatArray = NDArray[np.float64]
CALIBRATION_VERSION = "predictor-calibration-v1"
ENERGY_PREDICTORS = (
    "diagonal_hessian",
    "single_coordinate_obs",
    "general_constraint_obs",
    "exact_hessian_oracle",
)


@dataclass(frozen=True)
class EmbeddedTransformation:
    transformation: ConstraintTargetIR
    local_target_start: int
    local_target_stop: int

    @property
    def local_target_slice(self) -> slice:
        return slice(self.local_target_start, self.local_target_stop)


def embed_block_transformation(
    source_dimension: int,
    block: DVGBlock,
    candidate: CompressionCandidate,
) -> EmbeddedTransformation:
    """Embed a block-local S4 transform in the complete ordered ansatz."""
    positions = block.ansatz_positions
    if not positions or positions != tuple(range(positions[0], positions[-1] + 1)):
        raise QuadraticModelError("candidate block positions must be non-empty and contiguous")
    if positions[-1] >= source_dimension or candidate.source_block_id != block.block_id:
        raise QuadraticModelError("candidate source block does not match the global ansatz")
    local = candidate.transformation
    local.validate(len(positions))
    before = positions[0]
    after = source_dimension - positions[-1] - 1
    local_targets = local.jacobian.shape[1]
    target_dimension = before + local_targets + after
    jacobian = np.zeros((source_dimension, target_dimension), dtype=np.float64)
    if before:
        jacobian[:before, :before] = np.eye(before)
    jacobian[positions[0] : positions[-1] + 1, before : before + local_targets] = local.jacobian
    if after:
        jacobian[positions[-1] + 1 :, before + local_targets :] = np.eye(after)
    constraint = np.zeros(
        (local.constraint_matrix.shape[0], source_dimension), dtype=np.float64
    )
    constraint[:, positions[0] : positions[-1] + 1] = local.constraint_matrix
    offset = np.zeros(source_dimension, dtype=np.float64)
    offset[positions[0] : positions[-1] + 1] = local.offset
    target_slots = (
        tuple(f"ansatz-position:{index}" for index in range(before))
        + tuple(f"{candidate.candidate_id}:target:{index}" for index in range(local_targets))
        + tuple(
            f"ansatz-position:{index}"
            for index in range(positions[-1] + 1, source_dimension)
        )
    )
    transformation = ConstraintTargetIR.create(
        constraint_matrix=constraint,
        constraint_rhs=local.constraint_rhs,
        offset=offset,
        jacobian=jacobian,
        source_slots=tuple(f"ansatz-position:{index}" for index in range(source_dimension)),
        target_slots=target_slots,
        generator_normalization=local.generator_normalization,
        orientation=f"global-embed:{local.orientation}",
        units=local.units,
    )
    transformation.validate(source_dimension)
    return EmbeddedTransformation(
        transformation,
        before,
        before + local_targets,
    )


def least_squares_native_coordinates(
    theta: ArrayLike,
    transformation: ConstraintTargetIR,
) -> FloatArray:
    """Projection-off warm start: closest native coordinates to current theta."""
    source = np.asarray(theta, dtype=np.float64)
    transformation.validate(source.size)
    if transformation.jacobian.shape[1] == 0:
        return np.zeros(0, dtype=np.float64)
    coordinates, _, rank, _ = np.linalg.lstsq(
        transformation.jacobian,
        source - transformation.offset,
        rcond=None,
    )
    if rank != transformation.jacobian.shape[1] or not np.all(np.isfinite(coordinates)):
        raise QuadraticModelError("least-squares native warm start is rank deficient")
    return np.asarray(coordinates, dtype=np.float64)


def _diagonal_inverse_hessian(inverse_hessian: FloatArray) -> FloatArray:
    hessian = solve_spd(inverse_hessian, np.eye(inverse_hessian.shape[0]))
    diagonal = np.diag(hessian)
    if np.any(diagonal <= 0.0) or not np.all(np.isfinite(diagonal)):
        raise QuadraticModelError("solved Hessian has a non-positive diagonal")
    return np.diag(1.0 / diagonal)


def _single_coordinate_deletion(transformation: ConstraintTargetIR) -> bool:
    matrix = transformation.constraint_matrix
    if matrix.shape[0] != 1:
        return False
    nonzero = np.flatnonzero(np.abs(matrix[0]) > 1e-12)
    return bool(len(nonzero) == 1 and abs(abs(matrix[0, nonzero[0]]) - 1.0) <= 1e-12)


def predictor_values(
    theta: ArrayLike,
    gradient: ArrayLike,
    recycled_inverse_hessian: ArrayLike,
    transformation: ConstraintTargetIR,
    *,
    exact_hessian: ArrayLike | None,
) -> dict[str, float | None]:
    theta_value = np.asarray(theta, dtype=np.float64)
    gradient_value = np.asarray(gradient, dtype=np.float64)
    recycled = np.asarray(recycled_inverse_hessian, dtype=np.float64)
    transformation.validate(theta_value.size)
    residual = transformation.constraint_matrix @ theta_value - transformation.constraint_rhs
    magnitude = float(residual @ residual)
    involved = np.flatnonzero(
        np.any(np.abs(transformation.constraint_matrix) > 1e-12, axis=0)
    )
    normalized_mean_position = (
        float(np.mean(involved / max(theta_value.size - 1, 1))) if involved.size else 0.0
    )
    result: dict[str, float | None] = {
        "magnitude": magnitude,
        "magnitude_position": magnitude / (1.0 + normalized_mean_position),
    }
    source = QuadraticModel.create(theta_value, gradient_value, recycled)
    general = predict_constrained_optimum(source, transformation)
    result["general_constraint_obs"] = general.predicted_change_from_current
    result["single_coordinate_obs"] = (
        general.predicted_change_from_current
        if _single_coordinate_deletion(transformation)
        else None
    )
    diagonal_model = QuadraticModel.create(
        theta_value,
        gradient_value,
        _diagonal_inverse_hessian(recycled),
    )
    result["diagonal_hessian"] = predict_constrained_optimum(
        diagonal_model, transformation
    ).predicted_change_from_current
    result["exact_hessian_oracle"] = None
    if exact_hessian is not None:
        exact = np.asarray(exact_hessian, dtype=np.float64)
        exact_inverse = solve_spd(exact, np.eye(exact.shape[0]))
        exact_model = QuadraticModel.create(theta_value, gradient_value, exact_inverse)
        result["exact_hessian_oracle"] = predict_constrained_optimum(
            exact_model, transformation
        ).predicted_change_from_current
    return result


def obs_warm_start(
    theta: ArrayLike,
    gradient: ArrayLike,
    inverse_hessian: ArrayLike,
    transformation: ConstraintTargetIR,
) -> tuple[FloatArray, FloatArray, ConstraintPrediction]:
    model = QuadraticModel.create(theta, gradient, inverse_hessian)
    native = target_native_model(model, transformation)
    prediction = predict_constrained_optimum(model, transformation)
    return (
        native.optimum_coordinates,
        native.inverse_hessian,
        prediction,
    )


def calibration_metrics(
    rows: Sequence[Mapping[str, Any]],
    method: str,
) -> dict[str, Any]:
    paired = [
        (float(row["predictors"][method]), float(row["actual_change_hartree"]), bool(row["safe"]))
        for row in rows
        if row["predictors"].get(method) is not None
        and math.isfinite(float(row["predictors"][method]))
        and math.isfinite(float(row["actual_change_hartree"]))
    ]
    if not paired:
        return {"method": method, "count": 0, "reason": "no-finite-pairs"}
    predicted = np.asarray([item[0] for item in paired])
    actual = np.asarray([item[1] for item in paired])
    spearman = spearmanr(predicted, actual)
    kendall = kendalltau(predicted, actual)
    result: dict[str, Any] = {
        "method": method,
        "count": len(paired),
        "spearman": None if not math.isfinite(float(spearman.statistic)) else float(spearman.statistic),
        "kendall": None if not math.isfinite(float(kendall.statistic)) else float(kendall.statistic),
    }
    if method in ENERGY_PREDICTORS:
        if len(paired) >= 2 and float(np.ptp(predicted)) > 0.0:
            slope, intercept = np.polyfit(predicted, actual, 1)
            result["calibration_slope"] = float(slope)
            result["calibration_intercept_hartree"] = float(intercept)
        else:
            result["calibration_slope"] = None
            result["calibration_intercept_hartree"] = None
        predicted_safe = predicted <= 1e-4
        actual_safe = np.asarray([item[2] for item in paired], dtype=bool)
        true_positive = int(np.count_nonzero(predicted_safe & actual_safe))
        false_positive = int(np.count_nonzero(predicted_safe & ~actual_safe))
        false_negative = int(np.count_nonzero(~predicted_safe & actual_safe))
        true_negative = int(np.count_nonzero(~predicted_safe & ~actual_safe))
        result["classification"] = {
            "threshold_hartree": 1e-4,
            "true_positive": true_positive,
            "false_positive": false_positive,
            "false_negative": false_negative,
            "true_negative": true_negative,
            "precision": true_positive / (true_positive + false_positive)
            if true_positive + false_positive
            else None,
            "recall": true_positive / (true_positive + false_negative)
            if true_positive + false_negative
            else None,
            "false_safe_rate": false_positive / (false_positive + true_negative)
            if false_positive + true_negative
            else None,
            "false_reject_rate": false_negative / (false_negative + true_positive)
            if false_negative + true_positive
            else None,
        }
    else:
        result["classification"] = {
            "applicable": False,
            "reason": "heuristic score has no preregistered Hartree threshold",
        }
    return result

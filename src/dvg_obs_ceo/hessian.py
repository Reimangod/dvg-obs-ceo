"""Evaluation-free capture and diagnostics for recycled inverse Hessians."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import math
import threading
from types import ModuleType
from typing import Any, Iterable, Sequence

import numpy as np
from numpy.typing import ArrayLike, NDArray

from .identity import canonical_float64_hex, canonical_json_bytes


FloatArray = NDArray[np.float64]
HESSIAN_DIAGNOSTICS_VERSION = "hessian-diagnostics-v1"


class HessianCaptureError(RuntimeError):
    """Raised when capture provenance or Hessian quality is unsafe."""


def _array(value: ArrayLike, dimension: int | None = None) -> FloatArray:
    result = np.array(value, dtype=np.float64, copy=True)
    if result.ndim != 1 or not np.all(np.isfinite(result)):
        raise HessianCaptureError("captured vector must be finite and one-dimensional")
    if dimension is not None and result.shape != (dimension,):
        raise HessianCaptureError("captured vector has the wrong dimension")
    result.flags.writeable = False
    return result


def _matrix(value: ArrayLike, dimension: int | None = None) -> FloatArray:
    result = np.array(value, dtype=np.float64, copy=True)
    if result.ndim != 2 or result.shape[0] != result.shape[1]:
        raise HessianCaptureError("captured inverse Hessian must be square")
    if dimension is not None and result.shape != (dimension, dimension):
        raise HessianCaptureError("captured inverse Hessian has the wrong dimension")
    result.flags.writeable = False
    return result


def _digest_arrays(*values: FloatArray) -> str:
    payload = [canonical_float64_hex(value.ravel()) for value in values]
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


@dataclass(frozen=True)
class SecantPair:
    pair_id: str
    source: str
    step: FloatArray
    gradient_change: FloatArray
    curvature: float
    normalized_curvature: float
    valid_for_bfgs_quality: bool

    @classmethod
    def create(
        cls,
        old_parameters: ArrayLike,
        new_parameters: ArrayLike,
        old_gradient: ArrayLike,
        new_gradient: ArrayLike,
        *,
        source: str,
        curvature_tolerance: float = 1e-12,
    ) -> "SecantPair":
        if source not in {"internal-bfgs", "held-out-independent"}:
            raise HessianCaptureError("secant-pair source is not registered")
        old_x = _array(old_parameters)
        new_x = _array(new_parameters, old_x.size)
        old_g = _array(old_gradient, old_x.size)
        new_g = _array(new_gradient, old_x.size)
        step = _array(new_x - old_x)
        gradient_change = _array(new_g - old_g)
        denominator = float(np.linalg.norm(step) * np.linalg.norm(gradient_change))
        curvature = float(step @ gradient_change)
        normalized = curvature / denominator if denominator else 0.0
        valid = bool(
            denominator > 0.0
            and math.isfinite(normalized)
            and normalized > curvature_tolerance
        )
        return cls(
            "secant-v1:" + _digest_arrays(old_x, new_x, old_g, new_g),
            source,
            step,
            gradient_change,
            curvature,
            normalized,
            valid,
        )


@dataclass(frozen=True)
class HessianQualityPolicy:
    symmetry_relative_tolerance: float = 1e-10
    maximum_condition_number: float = 1e12
    minimum_eigenvalue: float = 1e-12
    minimum_valid_updates: int = 1
    maximum_age_steps: int = 20

    def __post_init__(self) -> None:
        positive = (
            self.symmetry_relative_tolerance,
            self.maximum_condition_number,
            self.minimum_eigenvalue,
        )
        if any(not math.isfinite(value) or value <= 0 for value in positive):
            raise HessianCaptureError("Hessian quality tolerances must be finite and positive")
        if self.minimum_valid_updates < 0 or self.maximum_age_steps < 0:
            raise HessianCaptureError("Hessian update and age limits must be non-negative")


@dataclass(frozen=True)
class HessianQualityReport:
    version: str
    matrix_digest: str
    dimension: int
    finite: bool
    symmetry_relative_residual: float | None
    minimum_eigenvalue: float | None
    condition_number: float | None
    positive_definite: bool
    valid_update_count: int
    invalid_update_count: int
    age_steps: int
    internal_secant_count: int
    internal_secant_rms_relative_residual: float | None
    internal_secant_max_relative_residual: float | None
    held_out_secant_count: int
    held_out_secant_rms_relative_residual: float | None
    held_out_secant_max_relative_residual: float | None
    secant_direction_coverage: float
    numerically_usable: bool
    rejection_reasons: tuple[str, ...]


def _secant_residuals(matrix: FloatArray, pairs: Sequence[SecantPair]) -> tuple[float | None, float | None]:
    residuals: list[float] = []
    for pair in pairs:
        denominator = max(
            float(np.linalg.norm(pair.step)),
            float(np.linalg.norm(matrix) * np.linalg.norm(pair.gradient_change)),
            np.finfo(np.float64).tiny,
        )
        residuals.append(
            float(np.linalg.norm(matrix @ pair.gradient_change - pair.step) / denominator)
        )
    if not residuals:
        return None, None
    return float(np.sqrt(np.mean(np.square(residuals)))), float(max(residuals))


def diagnose_inverse_hessian(
    inverse_hessian: ArrayLike,
    internal_pairs: Sequence[SecantPair],
    held_out_pairs: Sequence[SecantPair] = (),
    policy: HessianQualityPolicy = HessianQualityPolicy(),
) -> HessianQualityReport:
    matrix = _matrix(inverse_hessian)
    if any(pair.source != "internal-bfgs" for pair in internal_pairs):
        raise HessianCaptureError("internal secant list contains a non-internal pair")
    if any(pair.source != "held-out-independent" for pair in held_out_pairs):
        raise HessianCaptureError("held-out secant list contains a non-held-out pair")
    overlap = {pair.pair_id for pair in internal_pairs} & {pair.pair_id for pair in held_out_pairs}
    if overlap:
        raise HessianCaptureError("internal and held-out secant sets overlap")
    finite = bool(np.all(np.isfinite(matrix)))
    if finite:
        scale = max(float(np.linalg.norm(matrix, ord="fro")), np.finfo(np.float64).tiny)
        symmetry = float(np.linalg.norm(matrix - matrix.T, ord="fro") / scale)
        symmetric = (matrix + matrix.T) * 0.5
        eigenvalues = np.linalg.eigvalsh(symmetric)
        minimum_eigenvalue = float(eigenvalues[0])
        condition = float(np.linalg.cond(symmetric))
        positive = bool(minimum_eigenvalue > 0.0)
    else:
        symmetry = None
        minimum_eigenvalue = None
        condition = None
        positive = False
    valid_indices = [index for index, pair in enumerate(internal_pairs) if pair.valid_for_bfgs_quality]
    valid_count = len(valid_indices)
    age = len(internal_pairs) - 1 - valid_indices[-1] if valid_indices else len(internal_pairs)
    internal_rms, internal_max = _secant_residuals(matrix, internal_pairs) if finite else (None, None)
    held_rms, held_max = _secant_residuals(matrix, held_out_pairs) if finite else (None, None)
    valid_directions = [pair.gradient_change for pair in internal_pairs if pair.valid_for_bfgs_quality]
    if valid_directions:
        direction_matrix = np.column_stack(valid_directions)
        singular_values = np.linalg.svd(direction_matrix, compute_uv=False)
        rank = int(np.count_nonzero(singular_values > 1e-12 * singular_values[0]))
        coverage = rank / matrix.shape[0]
    else:
        coverage = 0.0
    reasons: list[str] = []
    if not finite:
        reasons.append("non-finite")
    if symmetry is None or symmetry > policy.symmetry_relative_tolerance:
        reasons.append("asymmetric")
    if not positive or minimum_eigenvalue is None or minimum_eigenvalue < policy.minimum_eigenvalue:
        reasons.append("not-sufficiently-positive-definite")
    if condition is None or not math.isfinite(condition) or condition > policy.maximum_condition_number:
        reasons.append("ill-conditioned")
    if valid_count < policy.minimum_valid_updates:
        reasons.append("insufficient-valid-updates")
    if age > policy.maximum_age_steps:
        reasons.append("stale")
    return HessianQualityReport(
        HESSIAN_DIAGNOSTICS_VERSION,
        hashlib.sha256(
            str(matrix.shape).encode("ascii")
            + np.asarray(matrix, dtype=">f8").tobytes(order="C")
        ).hexdigest(),
        matrix.shape[0],
        finite,
        symmetry,
        minimum_eigenvalue,
        condition,
        positive,
        valid_count,
        len(internal_pairs) - valid_count,
        age,
        len(internal_pairs),
        internal_rms,
        internal_max,
        len(held_out_pairs),
        held_rms,
        held_max,
        coverage,
        not reasons,
        tuple(reasons),
    )


def require_usable_hessian(report: HessianQualityReport) -> None:
    if not report.numerically_usable:
        raise HessianCaptureError(
            "inverse Hessian rejected: " + ", ".join(report.rejection_reasons)
        )


@dataclass(frozen=True)
class CheckpointOptimality:
    gradient_l2: float
    gradient_rms: float
    gradient_infinity: float
    projected_gradient_l2: float
    projected_gradient_rms: float
    projected_gradient_infinity: float
    constraint_residual_infinity: float
    kkt_stationarity_l2: float
    kkt_residual: float
    parameter_step_l2: float | None
    recent_energy_change_hartree: float | None


def checkpoint_optimality(
    gradient: ArrayLike,
    *,
    theta: ArrayLike | None = None,
    constraint_matrix: ArrayLike | None = None,
    constraint_rhs: ArrayLike | None = None,
    target_jacobian: ArrayLike | None = None,
    parameter_step: ArrayLike | None = None,
    recent_energy_change_hartree: float | None = None,
) -> CheckpointOptimality:
    g = _array(gradient)
    matrix = np.zeros((0, g.size)) if constraint_matrix is None else np.asarray(constraint_matrix, dtype=float)
    rhs = np.zeros(matrix.shape[0]) if constraint_rhs is None else np.asarray(constraint_rhs, dtype=float)
    if (
        matrix.ndim != 2
        or matrix.shape[1] != g.size
        or rhs.shape != (matrix.shape[0],)
        or not np.all(np.isfinite(matrix))
        or not np.all(np.isfinite(rhs))
    ):
        raise HessianCaptureError("KKT constraint dimensions are invalid")
    if matrix.shape[0] and theta is None:
        raise HessianCaptureError("theta is required for constrained KKT diagnostics")
    if theta is None:
        feasibility = 0.0
    else:
        x = _array(theta, g.size)
        feasibility = float(np.max(np.abs(matrix @ x - rhs))) if matrix.shape[0] else 0.0
    if target_jacobian is None:
        projected = g
    else:
        jacobian = np.asarray(target_jacobian, dtype=float)
        if jacobian.ndim != 2 or jacobian.shape[0] != g.size:
            raise HessianCaptureError("target Jacobian dimensions are invalid")
        projected = jacobian.T @ g
    if matrix.shape[0]:
        multiplier, *_ = np.linalg.lstsq(matrix.T, -g, rcond=None)
        stationarity = g + matrix.T @ multiplier
    else:
        stationarity = g
    gradient_l2 = float(np.linalg.norm(g))
    projected_l2 = float(np.linalg.norm(projected))
    stationarity_l2 = float(np.linalg.norm(stationarity))
    step_l2 = None if parameter_step is None else float(np.linalg.norm(_array(parameter_step, g.size)))
    if recent_energy_change_hartree is not None and not math.isfinite(recent_energy_change_hartree):
        raise HessianCaptureError("recent energy change must be finite")
    return CheckpointOptimality(
        gradient_l2,
        gradient_l2 / math.sqrt(g.size),
        float(np.max(np.abs(g))),
        projected_l2,
        projected_l2 / math.sqrt(max(projected.size, 1)),
        float(np.max(np.abs(projected))) if projected.size else 0.0,
        feasibility,
        stationarity_l2,
        float(math.hypot(stationarity_l2, feasibility)),
        step_l2,
        recent_energy_change_hartree,
    )


@dataclass(frozen=True)
class OptimizationCapture:
    optimization_id: str
    initial_parameters: FloatArray
    initial_gradient: FloatArray | None
    initial_inverse_hessian: FloatArray
    secant_pairs: tuple[SecantPair, ...]
    final_parameters: FloatArray
    final_gradient: FloatArray
    final_inverse_hessian: FloatArray
    success: bool
    status: int
    message: str
    iterations: int
    function_evaluations: int
    gradient_evaluations: int
    quality: HessianQualityReport
    optimality: CheckpointOptimality


_CAPTURE_LOCK = threading.Lock()


class HessianCaptureSession:
    """Temporarily observe the upstream minimizer without extra evaluations."""

    def __init__(self, adapt_vqe_module: ModuleType) -> None:
        self.module = adapt_vqe_module
        self.records: list[OptimizationCapture] = []
        self._original: Any = None

    def __enter__(self) -> "HessianCaptureSession":
        if not _CAPTURE_LOCK.acquire(blocking=False):
            raise HessianCaptureError("another Hessian capture session is active")
        self._original = self.module.minimize_bfgs
        session = self

        def observed_minimize(*args: Any, **kwargs: Any) -> Any:
            initial_parameters = _array(args[1] if len(args) > 1 else kwargs["x0"])
            initial_gradient_raw = kwargs.get("g0")
            initial_gradient = None if initial_gradient_raw is None else _array(initial_gradient_raw, initial_parameters.size)
            initial_hessian_raw = kwargs.get("initial_inv_hessian")
            initial_hessian = _matrix(
                np.eye(initial_parameters.size) if initial_hessian_raw is None else initial_hessian_raw,
                initial_parameters.size,
            )
            original_callback = kwargs.get("callback")
            previous_x = initial_parameters
            previous_g = initial_gradient
            pairs: list[SecantPair] = []
            gradient_observations: dict[tuple[str, ...], FloatArray] = {}

            def point_key(value: ArrayLike) -> tuple[str, ...]:
                return canonical_float64_hex(np.asarray(value, dtype=np.float64).ravel())

            positional = list(args)
            original_jac = kwargs.get("jac")
            jac_is_positional = False
            if original_jac is None and len(positional) > 3:
                original_jac = positional[3]
                jac_is_positional = True

            if original_jac is not None:
                def observed_jac(*jac_args: Any, **jac_kwargs: Any) -> Any:
                    result = original_jac(*jac_args, **jac_kwargs)
                    gradient_observations[point_key(jac_args[0])] = _array(
                        result, initial_parameters.size
                    )
                    return result

                if jac_is_positional:
                    positional[3] = observed_jac
                else:
                    kwargs["jac"] = observed_jac

            def callback(intermediate: Any) -> None:
                nonlocal previous_x, previous_g
                if original_callback is not None:
                    original_callback(intermediate)
                current_x = _array(intermediate.x, initial_parameters.size)
                current_g = _array(intermediate.gradient, initial_parameters.size)
                if previous_g is None:
                    previous_g = gradient_observations.get(point_key(previous_x))
                if previous_g is not None:
                    pairs.append(
                        SecantPair.create(
                            previous_x,
                            current_x,
                            previous_g,
                            current_g,
                            source="internal-bfgs",
                        )
                    )
                previous_x = current_x
                previous_g = current_g

            kwargs["callback"] = callback
            result = session._original(*positional, **kwargs)
            final_x = _array(result.x, initial_parameters.size)
            final_g = _array(result.jac, initial_parameters.size)
            final_hessian = _matrix(result.hess_inv, initial_parameters.size)
            if len(pairs) != int(result.nit):
                raise HessianCaptureError(
                    "capture missed one or more optimizer BFGS updates"
                )
            quality = diagnose_inverse_hessian(final_hessian, pairs)
            optimality = checkpoint_optimality(final_g)
            record_number = len(session.records)
            optimization_id = "optimizer-v1:" + hashlib.sha256(
                canonical_json_bytes(
                    {
                        "record_number": record_number,
                        "initial_parameters": canonical_float64_hex(initial_parameters),
                        "final_parameters": canonical_float64_hex(final_x),
                    }
                )
            ).hexdigest()
            session.records.append(
                OptimizationCapture(
                    optimization_id,
                    initial_parameters,
                    initial_gradient,
                    initial_hessian,
                    tuple(pairs),
                    final_x,
                    final_g,
                    final_hessian,
                    bool(result.success),
                    int(result.status),
                    str(result.message),
                    int(result.nit),
                    int(result.nfev),
                    int(result.njev),
                    quality,
                    optimality,
                )
            )
            return result

        self.module.minimize_bfgs = observed_minimize
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        try:
            self.module.minimize_bfgs = self._original
        finally:
            _CAPTURE_LOCK.release()


def capture_to_dict(record: OptimizationCapture) -> dict[str, Any]:
    def vector(value: FloatArray | None) -> list[float] | None:
        return None if value is None else value.tolist()

    return {
        "optimization_id": record.optimization_id,
        "initial_parameters": vector(record.initial_parameters),
        "initial_gradient": vector(record.initial_gradient),
        "initial_inverse_hessian": record.initial_inverse_hessian.tolist(),
        "secant_pairs": [
            {
                "pair_id": pair.pair_id,
                "source": pair.source,
                "step": pair.step.tolist(),
                "gradient_change": pair.gradient_change.tolist(),
                "curvature": pair.curvature,
                "normalized_curvature": pair.normalized_curvature,
                "valid_for_bfgs_quality": pair.valid_for_bfgs_quality,
            }
            for pair in record.secant_pairs
        ],
        "final_parameters": record.final_parameters.tolist(),
        "final_gradient": record.final_gradient.tolist(),
        "final_inverse_hessian": record.final_inverse_hessian.tolist(),
        "result": {
            "success": record.success,
            "status": record.status,
            "message": record.message,
            "iterations": record.iterations,
            "function_evaluations": record.function_evaluations,
            "gradient_evaluations": record.gradient_evaluations,
        },
        "quality": asdict(record.quality),
        "optimality": asdict(record.optimality),
    }

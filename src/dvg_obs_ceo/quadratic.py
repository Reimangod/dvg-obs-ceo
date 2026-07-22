"""Auditable quadratic-model kernels for DVG-aware OBS transformations.

The source model around ``theta`` is

    q(x) - q(theta) = g.T @ (x - theta)
                       + 1/2 (x - theta).T @ H @ (x - theta),

where ``inverse_hessian`` is the recycled approximation ``M ~= H^-1``.
No function in this module silently regularizes or forms a matrix inverse.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable

import numpy as np
from numpy.typing import ArrayLike, NDArray


FloatArray = NDArray[np.float64]
KERNEL_VERSION = "quadratic-kernel-v1.1"


class QuadraticModelError(ValueError):
    """Raised when a quadratic prediction is numerically or semantically unsafe."""


@dataclass(frozen=True)
class NumericalPolicy:
    symmetry_relative_tolerance: float = 1e-10
    feasibility_absolute_tolerance: float = 1e-10
    solve_relative_tolerance: float = 1e-10
    rank_relative_tolerance: float = 1e-12
    maximum_condition_number: float = 1e12
    negative_energy_roundoff_hartree: float = 1e-12

    def __post_init__(self) -> None:
        values = (
            self.symmetry_relative_tolerance,
            self.feasibility_absolute_tolerance,
            self.solve_relative_tolerance,
            self.rank_relative_tolerance,
            self.maximum_condition_number,
            self.negative_energy_roundoff_hartree,
        )
        if any(not math.isfinite(value) or value <= 0 for value in values):
            raise QuadraticModelError("all numerical tolerances must be finite and positive")


@dataclass(frozen=True)
class MatrixDiagnostics:
    dimension: int
    symmetry_relative_residual: float
    condition_number: float
    minimum_cholesky_diagonal: float


@dataclass(frozen=True)
class ScaleAwareSolveCertificate:
    """Numerical evidence for a diagonally equilibrated physical solve."""

    raw: MatrixDiagnostics
    equilibrated: MatrixDiagnostics
    minimum_coordinate_scale: float
    maximum_coordinate_scale: float
    relative_residual: float
    relative_backward_error: float


@dataclass(frozen=True)
class CertifiedSPDSolution:
    value: FloatArray
    certificate: ScaleAwareSolveCertificate


@dataclass(frozen=True)
class QuadraticModel:
    theta: FloatArray
    gradient: FloatArray
    inverse_hessian: FloatArray

    @classmethod
    def create(
        cls,
        theta: ArrayLike,
        gradient: ArrayLike,
        inverse_hessian: ArrayLike,
    ) -> "QuadraticModel":
        return cls(
            _vector("theta", theta),
            _vector("gradient", gradient),
            _matrix("inverse_hessian", inverse_hessian),
        )

    def __post_init__(self) -> None:
        object.__setattr__(self, "theta", _vector("theta", self.theta))
        object.__setattr__(self, "gradient", _vector("gradient", self.gradient))
        object.__setattr__(
            self,
            "inverse_hessian",
            _matrix("inverse_hessian", self.inverse_hessian),
        )
        size = self.theta.size
        if self.gradient.shape != (size,) or self.inverse_hessian.shape != (size, size):
            raise QuadraticModelError("theta, gradient, and inverse Hessian dimensions differ")


@dataclass(frozen=True)
class ConstraintTargetIR:
    """A constraint and a canonical native target-coordinate map.

    ``A @ source = b`` and ``source = offset + jacobian @ target``.
    The target map must parameterize the complete feasible affine subspace.
    """

    constraint_matrix: FloatArray
    constraint_rhs: FloatArray
    offset: FloatArray
    jacobian: FloatArray
    source_slots: tuple[str, ...]
    target_slots: tuple[str, ...]
    generator_normalization: str
    orientation: str
    units: str = "radian"

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "constraint_matrix",
            _matrix("constraint_matrix", self.constraint_matrix, allow_zero_rows=True),
        )
        object.__setattr__(self, "constraint_rhs", _vector("constraint_rhs", self.constraint_rhs))
        object.__setattr__(self, "offset", _vector("offset", self.offset))
        object.__setattr__(
            self,
            "jacobian",
            _matrix("jacobian", self.jacobian, allow_zero_columns=True),
        )
        object.__setattr__(self, "source_slots", tuple(self.source_slots))
        object.__setattr__(self, "target_slots", tuple(self.target_slots))

    @classmethod
    def create(
        cls,
        *,
        constraint_matrix: ArrayLike,
        constraint_rhs: ArrayLike,
        offset: ArrayLike,
        jacobian: ArrayLike,
        source_slots: Iterable[str],
        target_slots: Iterable[str],
        generator_normalization: str,
        orientation: str,
        units: str = "radian",
    ) -> "ConstraintTargetIR":
        return cls(
            _matrix("constraint_matrix", constraint_matrix, allow_zero_rows=True),
            _vector("constraint_rhs", constraint_rhs),
            _vector("offset", offset),
            _matrix("jacobian", jacobian, allow_zero_columns=True),
            tuple(source_slots),
            tuple(target_slots),
            generator_normalization,
            orientation,
            units,
        )

    def validate(
        self,
        source_dimension: int,
        policy: NumericalPolicy = NumericalPolicy(),
    ) -> None:
        rows = self.constraint_matrix.shape[0]
        targets = self.jacobian.shape[1]
        if self.constraint_matrix.shape != (rows, source_dimension):
            raise QuadraticModelError("constraint matrix has the wrong source dimension")
        if self.constraint_rhs.shape != (rows,):
            raise QuadraticModelError("constraint RHS has the wrong dimension")
        if self.offset.shape != (source_dimension,):
            raise QuadraticModelError("target offset has the wrong source dimension")
        if self.jacobian.shape != (source_dimension, targets):
            raise QuadraticModelError("target Jacobian has the wrong source dimension")
        if (
            len(self.source_slots) != source_dimension
            or len(set(self.source_slots)) != source_dimension
            or any(not slot for slot in self.source_slots)
        ):
            raise QuadraticModelError("source slot order must be explicit and unique")
        if (
            len(self.target_slots) != targets
            or len(set(self.target_slots)) != targets
            or any(not slot for slot in self.target_slots)
        ):
            raise QuadraticModelError("target slot order must be explicit and unique")
        if not self.generator_normalization or not self.orientation or not self.units:
            raise QuadraticModelError("normalization, orientation, and units must be explicit")
        expected_dimension = source_dimension - rows
        if targets != expected_dimension:
            raise QuadraticModelError(
                "target Jacobian must span the complete constraint null space"
            )
        if rows and _rank(self.constraint_matrix, policy.rank_relative_tolerance) != rows:
            raise QuadraticModelError("constraints are rank deficient or redundant")
        if targets and _rank(self.jacobian, policy.rank_relative_tolerance) != targets:
            raise QuadraticModelError("target Jacobian is rank deficient")
        if rows:
            jacobian_residual = _absolute_max(self.constraint_matrix @ self.jacobian)
            offset_residual = _absolute_max(
                self.constraint_matrix @ self.offset - self.constraint_rhs
            )
            if jacobian_residual > policy.feasibility_absolute_tolerance:
                raise QuadraticModelError("target Jacobian does not satisfy A @ J = 0")
            if offset_residual > policy.feasibility_absolute_tolerance:
                raise QuadraticModelError("target offset does not satisfy A @ c = b")


@dataclass(frozen=True)
class ConstraintPrediction:
    constrained_theta: FloatArray
    unconstrained_newton_theta: FloatArray
    predicted_constraint_penalty: float
    predicted_change_from_current: float
    direct_quadratic_change_from_current: float
    reference_energy_kind: str
    constraint_residual_infinity: float


@dataclass(frozen=True)
class TargetNativeModel:
    inverse_hessian: FloatArray
    hessian: FloatArray
    optimum_coordinates: FloatArray
    optimum_source_theta: FloatArray
    source_model_change_from_current: float
    diagnostics: MatrixDiagnostics
    solve_certificate: ScaleAwareSolveCertificate | None = None


def _vector(name: str, value: ArrayLike) -> FloatArray:
    array = np.asarray(value, dtype=np.float64)
    if array.ndim != 1 or not np.all(np.isfinite(array)):
        raise QuadraticModelError(f"{name} must be a finite one-dimensional array")
    result = np.array(array, dtype=np.float64, copy=True)
    result.flags.writeable = False
    return result


def _matrix(
    name: str,
    value: ArrayLike,
    *,
    allow_zero_rows: bool = False,
    allow_zero_columns: bool = False,
) -> FloatArray:
    array = np.asarray(value, dtype=np.float64)
    if array.ndim != 2 or not np.all(np.isfinite(array)):
        raise QuadraticModelError(f"{name} must be a finite two-dimensional array")
    if array.shape[0] == 0 and not allow_zero_rows:
        raise QuadraticModelError(f"{name} must have at least one row")
    if array.shape[1] == 0 and not allow_zero_columns:
        raise QuadraticModelError(f"{name} must have at least one column")
    result = np.array(array, dtype=np.float64, copy=True)
    result.flags.writeable = False
    return result


def _absolute_max(value: FloatArray) -> float:
    return float(np.max(np.abs(value))) if value.size else 0.0


def _rank(value: FloatArray, relative_tolerance: float) -> int:
    singular_values = np.linalg.svd(value, compute_uv=False)
    if not singular_values.size or singular_values[0] == 0.0:
        return 0
    return int(np.count_nonzero(singular_values > relative_tolerance * singular_values[0]))


def validate_spd(
    matrix: ArrayLike,
    policy: NumericalPolicy = NumericalPolicy(),
) -> MatrixDiagnostics:
    value = _matrix("SPD matrix", matrix)
    if value.shape[0] != value.shape[1]:
        raise QuadraticModelError("SPD matrix must be square")
    scale = max(float(np.linalg.norm(value, ord="fro")), np.finfo(np.float64).tiny)
    symmetry = float(np.linalg.norm(value - value.T, ord="fro") / scale)
    if symmetry > policy.symmetry_relative_tolerance:
        raise QuadraticModelError("matrix symmetry residual exceeds policy")
    symmetric = (value + value.T) * 0.5
    try:
        factor = np.linalg.cholesky(symmetric)
    except np.linalg.LinAlgError as error:
        raise QuadraticModelError("matrix is not positive definite") from error
    condition = float(np.linalg.cond(symmetric))
    if not math.isfinite(condition) or condition > policy.maximum_condition_number:
        raise QuadraticModelError("matrix condition number exceeds policy")
    return MatrixDiagnostics(
        value.shape[0],
        symmetry,
        condition,
        float(np.min(np.diag(factor))),
    )


def solve_spd(
    matrix: ArrayLike,
    rhs: ArrayLike,
    policy: NumericalPolicy = NumericalPolicy(),
) -> FloatArray:
    value = _matrix("SPD matrix", matrix)
    validate_spd(value, policy)
    right = np.asarray(rhs, dtype=np.float64)
    if right.ndim not in (1, 2) or right.shape[0] != value.shape[0] or not np.all(np.isfinite(right)):
        raise QuadraticModelError("solve RHS is finite but dimensionally incompatible")
    symmetric = (value + value.T) * 0.5
    factor = np.linalg.cholesky(symmetric)
    solution = np.linalg.solve(factor.T, np.linalg.solve(factor, right))
    denominator = max(
        float(np.linalg.norm(right)),
        float(np.linalg.norm(symmetric) * np.linalg.norm(solution)),
        np.finfo(np.float64).tiny,
    )
    residual = float(np.linalg.norm(symmetric @ solution - right) / denominator)
    if not math.isfinite(residual) or residual > policy.solve_relative_tolerance:
        raise QuadraticModelError("SPD solve residual exceeds policy")
    return np.asarray(solution, dtype=np.float64)


def solve_spd_equilibrated(
    matrix: ArrayLike,
    rhs: ArrayLike,
    policy: NumericalPolicy = NumericalPolicy(),
) -> CertifiedSPDSolution:
    """Solve an SPD system after canonical symmetric diagonal equilibration.

    The input matrix and right-hand side are never modified.  The returned
    solution is mapped back to the original physical coordinates, and both a
    relative residual and normwise relative backward error are checked there.
    """

    value = _matrix("SPD matrix", matrix)
    raw = validate_spd(value, policy)
    right = np.asarray(rhs, dtype=np.float64)
    if (
        right.ndim not in (1, 2)
        or right.shape[0] != value.shape[0]
        or not np.all(np.isfinite(right))
    ):
        raise QuadraticModelError("solve RHS is finite but dimensionally incompatible")
    symmetric = (value + value.T) * 0.5
    diagonal = np.diag(symmetric)
    if np.any(~np.isfinite(diagonal)) or np.any(diagonal <= 0.0):
        raise QuadraticModelError("SPD equilibration requires finite positive diagonal")
    scale = 1.0 / np.sqrt(diagonal)
    if np.any(~np.isfinite(scale)) or np.any(scale <= 0.0):
        raise QuadraticModelError("SPD equilibration produced invalid coordinate scales")
    equilibrated_matrix = scale[:, None] * symmetric * scale[None, :]
    equilibrated = validate_spd(equilibrated_matrix, policy)
    equilibrated_rhs = scale[:, None] * right if right.ndim == 2 else scale * right
    factor = np.linalg.cholesky(equilibrated_matrix)
    equilibrated_solution = np.linalg.solve(
        factor.T, np.linalg.solve(factor, equilibrated_rhs)
    )
    solution = (
        scale[:, None] * equilibrated_solution
        if right.ndim == 2
        else scale * equilibrated_solution
    )
    residual_vector = symmetric @ solution - right
    residual_norm = float(np.linalg.norm(residual_vector))
    rhs_norm = float(np.linalg.norm(right))
    operator_solution = float(np.linalg.norm(symmetric) * np.linalg.norm(solution))
    tiny = np.finfo(np.float64).tiny
    relative_residual = residual_norm / max(rhs_norm, tiny)
    backward_error = residual_norm / max(operator_solution + rhs_norm, tiny)
    if (
        not math.isfinite(relative_residual)
        or relative_residual > policy.solve_relative_tolerance
    ):
        raise QuadraticModelError("equilibrated SPD relative residual exceeds policy")
    if (
        not math.isfinite(backward_error)
        or backward_error > policy.solve_relative_tolerance
    ):
        raise QuadraticModelError("equilibrated SPD backward error exceeds policy")
    result = np.asarray(solution, dtype=np.float64)
    result.flags.writeable = False
    return CertifiedSPDSolution(
        result,
        ScaleAwareSolveCertificate(
            raw=raw,
            equilibrated=equilibrated,
            minimum_coordinate_scale=float(np.min(scale)),
            maximum_coordinate_scale=float(np.max(scale)),
            relative_residual=relative_residual,
            relative_backward_error=backward_error,
        ),
    )


def quadratic_change(
    model: QuadraticModel,
    candidate_theta: ArrayLike,
    policy: NumericalPolicy = NumericalPolicy(),
) -> float:
    validate_spd(model.inverse_hessian, policy)
    candidate = _vector("candidate_theta", candidate_theta)
    if candidate.shape != model.theta.shape:
        raise QuadraticModelError("candidate theta has the wrong dimension")
    displacement = candidate - model.theta
    hessian_displacement = solve_spd(model.inverse_hessian, displacement, policy)
    return float(model.gradient @ displacement + 0.5 * displacement @ hessian_displacement)


def predict_constrained_optimum(
    model: QuadraticModel,
    transformation: ConstraintTargetIR,
    policy: NumericalPolicy = NumericalPolicy(),
) -> ConstraintPrediction:
    validate_spd(model.inverse_hessian, policy)
    transformation.validate(model.theta.size, policy)
    unconstrained = model.theta - model.inverse_hessian @ model.gradient
    matrix = transformation.constraint_matrix
    if matrix.shape[0]:
        residual = matrix @ unconstrained - transformation.constraint_rhs
        schur = matrix @ model.inverse_hessian @ matrix.T
        multiplier = solve_spd(schur, residual, policy)
        constrained = unconstrained - model.inverse_hessian @ matrix.T @ multiplier
        penalty = float(0.5 * residual @ multiplier)
        if penalty < -policy.negative_energy_roundoff_hartree:
            raise QuadraticModelError("constraint penalty is unphysically negative")
        penalty = max(0.0, penalty)
    else:
        constrained = unconstrained
        penalty = 0.0
    formula_change = float(
        -0.5 * model.gradient @ model.inverse_hessian @ model.gradient + penalty
    )
    direct_change = quadratic_change(model, constrained, policy)
    if abs(formula_change - direct_change) > policy.solve_relative_tolerance * max(
        1.0, abs(formula_change), abs(direct_change)
    ):
        raise QuadraticModelError("constraint prediction and direct quadratic model disagree")
    feasibility = _absolute_max(
        matrix @ constrained - transformation.constraint_rhs
    )
    if feasibility > policy.feasibility_absolute_tolerance:
        raise QuadraticModelError("constrained solution violates the registered constraint")
    return ConstraintPrediction(
        constrained_theta=np.asarray(constrained, dtype=np.float64),
        unconstrained_newton_theta=np.asarray(unconstrained, dtype=np.float64),
        predicted_constraint_penalty=penalty,
        predicted_change_from_current=formula_change,
        direct_quadratic_change_from_current=direct_change,
        reference_energy_kind="current-checkpoint-quadratic-model",
        constraint_residual_infinity=feasibility,
    )


def target_native_model(
    model: QuadraticModel,
    transformation: ConstraintTargetIR,
    policy: NumericalPolicy = NumericalPolicy(),
) -> TargetNativeModel:
    validate_spd(model.inverse_hessian, policy)
    transformation.validate(model.theta.size, policy)
    jacobian = transformation.jacobian
    if jacobian.shape[1] == 0:
        source = transformation.offset.copy()
        return TargetNativeModel(
            inverse_hessian=np.zeros((0, 0), dtype=np.float64),
            hessian=np.zeros((0, 0), dtype=np.float64),
            optimum_coordinates=np.zeros(0, dtype=np.float64),
            optimum_source_theta=source,
            source_model_change_from_current=quadratic_change(model, source, policy),
            diagnostics=MatrixDiagnostics(0, 0.0, 1.0, math.inf),
            solve_certificate=None,
        )
    hessian_jacobian = solve_spd(model.inverse_hessian, jacobian, policy)
    target_hessian = jacobian.T @ hessian_jacobian
    diagnostics = validate_spd(target_hessian, policy)
    target_inverse_solve = solve_spd_equilibrated(
        target_hessian,
        np.eye(target_hessian.shape[0], dtype=np.float64),
        policy,
    )
    target_inverse = target_inverse_solve.value
    target_inverse = (target_inverse + target_inverse.T) * 0.5
    hessian_theta_minus_offset = solve_spd(
        model.inverse_hessian,
        model.theta - transformation.offset,
        policy,
    )
    rhs = jacobian.T @ (hessian_theta_minus_offset - model.gradient)
    coordinate_solve = solve_spd_equilibrated(target_hessian, rhs, policy)
    coordinates = coordinate_solve.value
    source = transformation.offset + jacobian @ coordinates
    feasibility = _absolute_max(
        transformation.constraint_matrix @ source - transformation.constraint_rhs
    )
    if feasibility > policy.feasibility_absolute_tolerance:
        raise QuadraticModelError("target-native optimum violates the registered constraint")
    return TargetNativeModel(
        inverse_hessian=np.asarray(target_inverse, dtype=np.float64),
        hessian=np.asarray(target_hessian, dtype=np.float64),
        optimum_coordinates=np.asarray(coordinates, dtype=np.float64),
        optimum_source_theta=np.asarray(source, dtype=np.float64),
        source_model_change_from_current=quadratic_change(model, source, policy),
        diagnostics=diagnostics,
        solve_certificate=coordinate_solve.certificate,
    )


def target_newton_direction(
    model: QuadraticModel,
    transformation: ConstraintTargetIR,
    current_target_coordinates: ArrayLike,
    policy: NumericalPolicy = NumericalPolicy(),
) -> FloatArray:
    native = target_native_model(model, transformation, policy)
    coordinates = _vector("current_target_coordinates", current_target_coordinates)
    if coordinates.shape != native.optimum_coordinates.shape:
        raise QuadraticModelError("target coordinate vector has the wrong dimension")
    source = transformation.offset + transformation.jacobian @ coordinates
    source_displacement = source - model.theta
    source_gradient = model.gradient + solve_spd(
        model.inverse_hessian, source_displacement, policy
    )
    target_gradient = transformation.jacobian.T @ source_gradient
    return -native.inverse_hessian @ target_gradient

"""V5-S5 counted matrix-free Hessian-vector affine KKT refinement."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any, Callable

import numpy as np
from numpy.typing import ArrayLike, NDArray
from scipy.sparse.linalg import ArpackNoConvergence, LinearOperator, eigsh, minres


FloatArray = NDArray[np.float64]
HVP_KKT_VERSION = "v5-matrix-free-affine-kkt-v1"
REGISTERED_DAMPING_REASONS = (
    "near-singular-curvature-fallback",
    "registered-stabilization-study",
)


class HVPRefinementError(RuntimeError):
    """Fail-closed numerical error with counted work and a stable category."""

    def __init__(self, category: str, message: str, work: dict[str, int] | None = None) -> None:
        super().__init__(f"{category}: {message}")
        self.category = category
        self.work = work or {}


@dataclass(frozen=True)
class HVPKKTConfig:
    symmetry_relative_tolerance: float = 1e-10
    minimum_curvature: float = 1e-10
    minres_tolerance: float = 1e-11
    maximum_relative_residual: float = 1e-9
    maximum_relative_backward_error: float = 1e-9
    maximum_constraint_residual: float = 1e-10
    maximum_stationarity_residual: float = 1e-8
    maximum_iterations: int = 500
    maximum_hessian_vector_products: int = 4096
    explicit_validation_dimension: int = 12
    damping: float = 0.0
    damping_reason: str | None = None

    def validate(self) -> None:
        positive = (
            self.symmetry_relative_tolerance,
            self.minimum_curvature,
            self.minres_tolerance,
            self.maximum_relative_residual,
            self.maximum_relative_backward_error,
            self.maximum_constraint_residual,
            self.maximum_stationarity_residual,
        )
        if any(not math.isfinite(value) or value <= 0 for value in positive):
            raise HVPRefinementError("invalid-config", "numerical tolerances must be finite and positive")
        if (
            not isinstance(self.maximum_iterations, int)
            or self.maximum_iterations <= 0
            or not isinstance(self.maximum_hessian_vector_products, int)
            or self.maximum_hessian_vector_products <= 0
            or not isinstance(self.explicit_validation_dimension, int)
            or self.explicit_validation_dimension < 0
            or not math.isfinite(self.damping)
            or self.damping < 0
        ):
            raise HVPRefinementError("invalid-config", "iteration, work, dimension, or damping setting is invalid")
        if self.damping == 0 and self.damping_reason is not None:
            raise HVPRefinementError("invalid-config", "zero damping cannot carry a fallback reason")
        if self.damping > 0 and self.damping_reason not in REGISTERED_DAMPING_REASONS:
            raise HVPRefinementError("invalid-config", "nonzero damping requires a registered reason")


@dataclass
class HVPWorkLedger:
    hessian_vector_products: int = 0
    gradient_vector_evaluations: int = 0
    validation_products: int = 0
    curvature_products: int = 0
    solver_products: int = 0
    certification_products: int = 0
    minres_iterations: int = 0

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


class CentralDifferenceHVP:
    """Counted central-gradient HVP at one frozen coordinate vector."""

    def __init__(
        self,
        point: ArrayLike,
        gradient: Callable[[FloatArray], ArrayLike],
        *,
        relative_step: float = float(np.finfo(np.float64).eps ** (1.0 / 3.0)),
    ) -> None:
        self.point = np.asarray(point, dtype=np.float64)
        if self.point.ndim != 1 or not np.all(np.isfinite(self.point)):
            raise HVPRefinementError("invalid-input", "finite-difference point is invalid")
        if not math.isfinite(relative_step) or relative_step <= 0:
            raise HVPRefinementError("invalid-config", "finite-difference step is invalid")
        self.gradient = gradient
        self.relative_step = relative_step
        self.gradient_evaluations = 0

    def __call__(self, direction: FloatArray) -> FloatArray:
        vector = np.asarray(direction, dtype=np.float64)
        norm = float(np.linalg.norm(vector))
        if vector.shape != self.point.shape or not np.all(np.isfinite(vector)):
            raise HVPRefinementError("invalid-hvp", "finite-difference direction is invalid")
        if norm == 0:
            return np.zeros_like(vector)
        step = self.relative_step * max(1.0, float(np.linalg.norm(self.point))) / norm
        plus = np.asarray(self.gradient(self.point + step * vector), dtype=np.float64)
        minus = np.asarray(self.gradient(self.point - step * vector), dtype=np.float64)
        self.gradient_evaluations += 2
        if plus.shape != self.point.shape or minus.shape != self.point.shape or not np.all(np.isfinite(plus)) or not np.all(np.isfinite(minus)):
            raise HVPRefinementError("invalid-hvp", "gradient callback returned an invalid vector")
        return np.asarray((plus - minus) / (2.0 * step), dtype=np.float64)


def _vector(name: str, value: ArrayLike, dimension: int | None = None) -> FloatArray:
    result = np.asarray(value, dtype=np.float64)
    if result.ndim != 1 or not np.all(np.isfinite(result)) or (dimension is not None and result.shape != (dimension,)):
        raise HVPRefinementError("invalid-input", f"{name} must be a finite vector")
    return result


def _matrix(name: str, value: ArrayLike, columns: int) -> FloatArray:
    result = np.asarray(value, dtype=np.float64)
    if result.ndim != 2 or result.shape[1] != columns or not np.all(np.isfinite(result)):
        raise HVPRefinementError("invalid-input", f"{name} must be a finite matrix with {columns} columns")
    return result


def solve_affine_kkt_hvp(
    theta: ArrayLike,
    gradient: ArrayLike,
    constraint_matrix: ArrayLike,
    constraint_rhs: ArrayLike,
    hessian_product: Callable[[FloatArray], ArrayLike],
    *,
    config: HVPKKTConfig = HVPKKTConfig(),
    preconditioner_diagonal: ArrayLike | None = None,
) -> dict[str, Any]:
    """Solve ``min g'd + .5 d'Hd`` subject to ``A(theta+d)=b``.

    There is no automatic damping or retry. Any fallback is a separate,
    explicitly configured call whose provenance is returned in the result.
    """

    config.validate()
    theta_value = _vector("theta", theta)
    dimension = theta_value.size
    if dimension == 0:
        raise HVPRefinementError("invalid-input", "source dimension must be positive")
    gradient_value = _vector("gradient", gradient, dimension)
    matrix = _matrix("constraint matrix", constraint_matrix, dimension)
    rhs_value = _vector("constraint RHS", constraint_rhs, matrix.shape[0])
    if matrix.shape[0] and np.linalg.matrix_rank(matrix) != matrix.shape[0]:
        raise HVPRefinementError("rank-deficient-constraints", "constraint rows are not independent")
    ledger = HVPWorkLedger()
    initial_gradient_evaluations = int(getattr(hessian_product, "gradient_evaluations", 0))

    def work() -> dict[str, int]:
        ledger.gradient_vector_evaluations = int(getattr(hessian_product, "gradient_evaluations", 0)) - initial_gradient_evaluations
        return ledger.to_dict()

    def product(vector: FloatArray, role: str) -> FloatArray:
        if ledger.hessian_vector_products >= config.maximum_hessian_vector_products:
            raise HVPRefinementError("hvp-budget-exceeded", "Hessian-vector-product cap reached", work())
        direction = _vector("HVP direction", vector, dimension)
        try:
            value = _vector("HVP result", hessian_product(direction.copy()), dimension)
        except HVPRefinementError:
            raise
        except Exception as error:
            raise HVPRefinementError("hvp-callback-failure", repr(error), work()) from error
        ledger.hessian_vector_products += 1
        setattr(ledger, role, getattr(ledger, role) + 1)
        return value + config.damping * direction

    explicit_hessian: FloatArray | None = None
    hessian_norm = 0.0
    try:
        if dimension <= config.explicit_validation_dimension:
            columns = [product(np.eye(dimension)[:, index], "validation_products") for index in range(dimension)]
            observed = np.column_stack(columns) if columns else np.zeros((0, 0), dtype=np.float64)
            scale = max(1.0, float(np.linalg.norm(observed, ord=2)))
            symmetry_error = float(np.linalg.norm(observed - observed.T, ord=2) / scale)
            if symmetry_error > config.symmetry_relative_tolerance:
                raise HVPRefinementError("asymmetric-hessian", f"relative asymmetry {symmetry_error:.3e}", work())
            explicit_hessian = (observed + observed.T) * 0.5
            eigenvalues = np.linalg.eigvalsh(explicit_hessian)
            minimum_curvature = float(eigenvalues[0]) if eigenvalues.size else math.inf
            hessian_norm = float(np.linalg.norm(explicit_hessian, ord=2)) if dimension else 0.0
        else:
            probes = []
            if dimension:
                probes.extend((np.eye(dimension)[0], np.eye(dimension)[-1], np.ones(dimension), (-1.0) ** np.arange(dimension)))
            symmetry_error = 0.0
            for left, right in zip(probes[::2], probes[1::2]):
                h_right = product(right, "validation_products")
                h_left = product(left, "validation_products")
                denominator = max(1.0, abs(float(left @ h_right)), abs(float(right @ h_left)))
                symmetry_error = max(symmetry_error, abs(float(left @ h_right - right @ h_left)) / denominator)
            if symmetry_error > config.symmetry_relative_tolerance:
                raise HVPRefinementError("asymmetric-hessian", f"probe asymmetry {symmetry_error:.3e}", work())
            if dimension == 1:
                only = float(product(np.ones(1), "curvature_products")[0])
                minimum_curvature = only
                hessian_norm = abs(only)
            else:
                hop = LinearOperator((dimension, dimension), matvec=lambda vector: product(vector, "curvature_products"), dtype=np.float64)
                try:
                    minimum_curvature = float(eigsh(hop, k=1, which="SA", return_eigenvectors=False, tol=config.minres_tolerance, maxiter=config.maximum_iterations)[0])
                    largest_magnitude = float(abs(eigsh(hop, k=1, which="LM", return_eigenvectors=False, tol=config.minres_tolerance, maxiter=config.maximum_iterations)[0]))
                except ArpackNoConvergence as error:
                    raise HVPRefinementError("curvature-nonconvergence", repr(error), work()) from error
                hessian_norm = largest_magnitude
        if minimum_curvature < config.minimum_curvature:
            raise HVPRefinementError("nonpositive-curvature", f"minimum curvature {minimum_curvature:.3e}", work())

        constraints = matrix.shape[0]
        total = dimension + constraints
        kkt_rhs = np.concatenate((-gradient_value, rhs_value - matrix @ theta_value))

        def kkt_matvec(value: FloatArray) -> FloatArray:
            displacement = value[:dimension]
            multiplier = value[dimension:]
            hd = explicit_hessian @ displacement if explicit_hessian is not None else product(displacement, "solver_products")
            return np.concatenate((hd + matrix.T @ multiplier, matrix @ displacement))

        kkt = LinearOperator((total, total), matvec=kkt_matvec, rmatvec=kkt_matvec, dtype=np.float64)
        preconditioner = None
        if preconditioner_diagonal is not None:
            diagonal = _vector("preconditioner diagonal", preconditioner_diagonal, dimension)
            if np.any(diagonal <= 0):
                raise HVPRefinementError("invalid-preconditioner", "preconditioner diagonal must be positive", work())
            full_diagonal = np.concatenate((diagonal + config.damping, np.ones(constraints)))
            preconditioner = LinearOperator((total, total), matvec=lambda value: value / full_diagonal, dtype=np.float64)

        def callback(_: FloatArray) -> None:
            ledger.minres_iterations += 1

        solution, info = minres(
            kkt,
            kkt_rhs,
            tol=config.minres_tolerance,
            maxiter=config.maximum_iterations,
            M=preconditioner,
            callback=callback,
            check=False,
        )
        if info != 0:
            category = "minres-nonconvergence" if info > 0 else "minres-breakdown"
            raise HVPRefinementError(category, f"SciPy MINRES info={info}", work())
        residual = kkt @ solution - kkt_rhs
        residual_norm = float(np.linalg.norm(residual))
        rhs_norm = float(np.linalg.norm(kkt_rhs))
        relative_residual = residual_norm / max(rhs_norm, np.finfo(np.float64).tiny)
        constraint_norm = float(np.linalg.norm(matrix, ord=2)) if constraints else 0.0
        kkt_norm_upper = max(1.0, hessian_norm + constraint_norm)
        backward_error = residual_norm / max(
            rhs_norm + kkt_norm_upper * float(np.linalg.norm(solution)),
            np.finfo(np.float64).tiny,
        )
        if relative_residual > config.maximum_relative_residual:
            raise HVPRefinementError("residual-certificate-failed", f"relative residual {relative_residual:.3e}", work())
        if backward_error > config.maximum_relative_backward_error:
            raise HVPRefinementError("backward-error-certificate-failed", f"relative backward error {backward_error:.3e}", work())
        displacement = np.asarray(solution[:dimension], dtype=np.float64)
        candidate_theta = theta_value + displacement
        feasibility = float(np.max(np.abs(matrix @ candidate_theta - rhs_value))) if constraints else 0.0
        h_displacement = explicit_hessian @ displacement if explicit_hessian is not None else product(displacement, "certification_products")
        stationarity = float(np.max(np.abs(h_displacement + gradient_value + matrix.T @ solution[dimension:]))) if dimension else 0.0
        if feasibility > config.maximum_constraint_residual:
            raise HVPRefinementError("constraint-certificate-failed", f"constraint residual {feasibility:.3e}", work())
        if stationarity > config.maximum_stationarity_residual:
            raise HVPRefinementError("stationarity-certificate-failed", f"stationarity residual {stationarity:.3e}", work())
        predicted_change = float(gradient_value @ displacement + 0.5 * displacement @ h_displacement)
    except HVPRefinementError as error:
        if not error.work:
            error.work = work()
        raise

    return {
        "version": HVP_KKT_VERSION,
        "success": True,
        "solver": "scipy-minres-affine-kkt",
        "candidate_theta": candidate_theta.tolist(),
        "displacement": displacement.tolist(),
        "lagrange_multipliers": np.asarray(solution[dimension:], dtype=np.float64).tolist(),
        "predicted_change_hartree": predicted_change,
        "constraint_residual_infinity": feasibility,
        "stationarity_residual_infinity": stationarity,
        "relative_residual": relative_residual,
        "relative_backward_error": backward_error,
        "minimum_curvature": minimum_curvature,
        "symmetry_relative_error": symmetry_error,
        "hessian_norm_estimate": hessian_norm,
        "damping": config.damping,
        "damping_reason": config.damping_reason,
        "explicit_validation_used": explicit_hessian is not None,
        "work": work(),
        "config": asdict(config),
        "paper_measurement_cost": None,
    }

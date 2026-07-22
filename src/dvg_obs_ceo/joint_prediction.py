"""Joint OBS predictions with candidate-specific Hessian evidence diagnostics."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any, Mapping, Sequence

import numpy as np
from numpy.typing import ArrayLike, NDArray

from .hessian import SecantPair
from .quadratic import (
    ConstraintTargetIR,
    NumericalPolicy,
    QuadraticModel,
    QuadraticModelError,
    predict_constrained_optimum,
    solve_spd,
    target_native_model,
    validate_spd,
)


FloatArray = NDArray[np.float64]
JOINT_PREDICTION_VERSION = "joint-obs-prediction-v1.1"


class JointPredictionError(RuntimeError):
    """Raised when joint prediction evidence is invalid or insufficient."""


@dataclass(frozen=True)
class ProjectedSecantStatistics:
    count: int
    rms_relative_residual: float | None
    maximum_relative_residual: float | None


@dataclass(frozen=True)
class JointPredictionDiagnostics:
    constraint_rank: int
    constraint_schur_condition_number: float
    target_hessian_condition_number: float
    target_hessian_equilibrated_condition_number: float
    target_hessian_relative_solve_residual: float
    target_hessian_relative_backward_error: float
    constraint_direction_coverage: float
    internal_projected_secants: ProjectedSecantStatistics
    held_out_projected_secants: ProjectedSecantStatistics
    held_out_evidence_available: bool


@dataclass(frozen=True)
class JointQualityPolicy:
    maximum_constraint_schur_condition_number: float = 1e12
    maximum_target_hessian_condition_number: float = 1e12
    minimum_constraint_direction_coverage: float = 0.0
    maximum_internal_projected_residual: float = math.inf
    maximum_held_out_projected_residual: float = math.inf
    require_held_out_evidence: bool = False
    target_hessian_condition_is_scientific_gate: bool = True
    maximum_equilibrated_target_hessian_condition_number: float = 1e12
    maximum_target_hessian_relative_solve_residual: float = 1e-10
    maximum_target_hessian_relative_backward_error: float = 1e-10

    def validate(self) -> None:
        if (
            not math.isfinite(self.maximum_constraint_schur_condition_number)
            or self.maximum_constraint_schur_condition_number <= 0
            or not math.isfinite(self.maximum_target_hessian_condition_number)
            or self.maximum_target_hessian_condition_number <= 0
            or not 0.0 <= self.minimum_constraint_direction_coverage <= 1.0
            or self.maximum_internal_projected_residual < 0
            or self.maximum_held_out_projected_residual < 0
            or not math.isfinite(self.maximum_equilibrated_target_hessian_condition_number)
            or self.maximum_equilibrated_target_hessian_condition_number <= 0
            or not math.isfinite(self.maximum_target_hessian_relative_solve_residual)
            or self.maximum_target_hessian_relative_solve_residual <= 0
            or not math.isfinite(self.maximum_target_hessian_relative_backward_error)
            or self.maximum_target_hessian_relative_backward_error <= 0
        ):
            raise JointPredictionError("joint quality policy is invalid")


@dataclass(frozen=True)
class JointScreeningContext:
    """Fixed-source quadratic context for memory-bounded surrogate screening.

    The expensive source-Hessian validation and factorization are performed
    once.  Candidate evaluation uses the same constrained-Newton formula as
    :func:`joint_obs_prediction`, including an independent direct-quadratic
    consistency check, but deliberately does not construct target-native
    coordinates or diagnostics.  Those are recomputed in full for every
    energy-eligible candidate before quality filtering or selection.
    """

    model: QuadraticModel
    source_hessian: FloatArray
    unconstrained_theta: FloatArray
    unconstrained_change_from_current: float
    numerical_policy: NumericalPolicy

    @classmethod
    def create(
        cls,
        theta: ArrayLike,
        gradient: ArrayLike,
        inverse_hessian: ArrayLike,
        numerical_policy: NumericalPolicy = NumericalPolicy(),
    ) -> "JointScreeningContext":
        model = QuadraticModel.create(theta, gradient, inverse_hessian)
        try:
            source_hessian = solve_spd(
                model.inverse_hessian,
                np.eye(model.theta.size, dtype=np.float64),
                numerical_policy,
            )
        except QuadraticModelError as error:
            raise JointPredictionError("screening source Hessian is invalid") from error
        source_hessian = (source_hessian + source_hessian.T) * 0.5
        unconstrained = model.theta - model.inverse_hessian @ model.gradient
        change = float(-0.5 * model.gradient @ model.inverse_hessian @ model.gradient)
        return cls(model, source_hessian, unconstrained, change, numerical_policy)

    def predicted_change(self, transformation: ConstraintTargetIR) -> float:
        """Return the fixed-source constrained optimum change for one state."""

        policy = self.numerical_policy
        try:
            # Composition already validates the complete target IR.  Repeating
            # its target-Jacobian SVD here would change no scientific check and
            # dominates large-system screening.  Constraint-space quantities
            # below are nevertheless checked independently and fail closed.
            matrix = np.asarray(transformation.constraint_matrix, dtype=np.float64)
            rhs = np.asarray(transformation.constraint_rhs, dtype=np.float64)
            if (
                matrix.ndim != 2
                or matrix.shape[1] != self.model.theta.size
                or rhs.shape != (matrix.shape[0],)
                or not np.all(np.isfinite(matrix))
                or not np.all(np.isfinite(rhs))
            ):
                raise QuadraticModelError("screening constraint dimensions are invalid")
            if matrix.shape[0]:
                residual = matrix @ self.unconstrained_theta - rhs
                schur = matrix @ self.model.inverse_hessian @ matrix.T
                multiplier = solve_spd(schur, residual, policy)
                constrained = (
                    self.unconstrained_theta
                    - self.model.inverse_hessian @ matrix.T @ multiplier
                )
                penalty = float(0.5 * residual @ multiplier)
                if penalty < -policy.negative_energy_roundoff_hartree:
                    raise QuadraticModelError(
                        "constraint penalty is unphysically negative"
                    )
                penalty = max(0.0, penalty)
            else:
                constrained = self.unconstrained_theta
                penalty = 0.0
            predicted = self.unconstrained_change_from_current + penalty
            displacement = constrained - self.model.theta
            direct = float(
                self.model.gradient @ displacement
                + 0.5 * displacement @ self.source_hessian @ displacement
            )
            if abs(predicted - direct) > policy.solve_relative_tolerance * max(
                1.0, abs(predicted), abs(direct)
            ):
                raise QuadraticModelError(
                    "screening prediction and direct quadratic model disagree"
                )
            feasibility = (
                float(np.max(np.abs(matrix @ constrained - rhs)))
                if matrix.shape[0]
                else 0.0
            )
            if feasibility > policy.feasibility_absolute_tolerance:
                raise QuadraticModelError(
                    "screening constrained solution violates the registered constraint"
                )
        except QuadraticModelError as error:
            raise JointPredictionError("joint OBS screening solve failed") from error
        return predicted


def secant_pairs_from_capture(
    records: Sequence[Mapping[str, Any]],
    *,
    required_source: str,
) -> tuple[SecantPair, ...]:
    pairs: list[SecantPair] = []
    for record in records:
        if record.get("source") != required_source:
            raise JointPredictionError("secant source label does not match requested evidence role")
        pair = SecantPair(
            str(record["pair_id"]),
            str(record["source"]),
            np.asarray(record["step"], dtype=np.float64),
            np.asarray(record["gradient_change"], dtype=np.float64),
            float(record["curvature"]),
            float(record["normalized_curvature"]),
            bool(record["valid_for_bfgs_quality"]),
        )
        if not np.all(np.isfinite(pair.step)) or not np.all(np.isfinite(pair.gradient_change)):
            raise JointPredictionError("secant pair contains non-finite vectors")
        pairs.append(pair)
    if len({pair.pair_id for pair in pairs}) != len(pairs):
        raise JointPredictionError("secant evidence contains duplicate IDs")
    return tuple(pairs)


def _constraint_basis(matrix: FloatArray, tolerance: float) -> FloatArray:
    if matrix.shape[0] == 0:
        return np.zeros((matrix.shape[1], 0), dtype=np.float64)
    _, singular, right = np.linalg.svd(matrix, full_matrices=False)
    if singular.size == 0 or singular[0] == 0.0:
        raise JointPredictionError("constraint matrix has no resolvable rank")
    rank = int(np.count_nonzero(singular > tolerance * singular[0]))
    if rank != matrix.shape[0]:
        raise JointPredictionError("constraint matrix is rank deficient")
    return np.asarray(right[:rank].T, dtype=np.float64)


def _direction_coverage(
    constraint_basis: FloatArray,
    pairs: Sequence[SecantPair],
    tolerance: float,
) -> float:
    rank = constraint_basis.shape[1]
    if rank == 0:
        return 1.0
    directions = [pair.gradient_change for pair in pairs if pair.valid_for_bfgs_quality]
    if not directions:
        return 0.0
    matrix = np.column_stack(directions)
    left, singular, _ = np.linalg.svd(matrix, full_matrices=False)
    if singular.size == 0 or singular[0] == 0.0:
        return 0.0
    data_rank = int(np.count_nonzero(singular > tolerance * singular[0]))
    basis = left[:, :data_rank]
    coverage = float(np.linalg.norm(basis.T @ constraint_basis, ord="fro") ** 2 / rank)
    return min(1.0, max(0.0, coverage))


def _projected_secant_statistics(
    inverse_hessian: FloatArray,
    constraint_basis: FloatArray,
    pairs: Sequence[SecantPair],
) -> ProjectedSecantStatistics:
    if not pairs:
        return ProjectedSecantStatistics(0, None, None)
    projector = (
        constraint_basis @ constraint_basis.T
        if constraint_basis.shape[1]
        else np.eye(inverse_hessian.shape[0])
    )
    residuals: list[float] = []
    for pair in pairs:
        full_predicted = inverse_hessian @ pair.gradient_change
        predicted = projector @ full_predicted
        observed = projector @ pair.step
        denominator = max(
            float(np.linalg.norm(full_predicted)),
            float(np.linalg.norm(pair.step)),
            np.finfo(np.float64).tiny,
        )
        residuals.append(float(np.linalg.norm(predicted - observed) / denominator))
    return ProjectedSecantStatistics(
        len(residuals),
        float(np.sqrt(np.mean(np.square(residuals)))),
        float(max(residuals)),
    )


def joint_obs_prediction(
    theta: ArrayLike,
    gradient: ArrayLike,
    inverse_hessian: ArrayLike,
    transformation: ConstraintTargetIR,
    *,
    internal_pairs: Sequence[SecantPair],
    held_out_pairs: Sequence[SecantPair] = (),
    numerical_policy: NumericalPolicy = NumericalPolicy(),
) -> dict[str, Any]:
    model = QuadraticModel.create(theta, gradient, inverse_hessian)
    if any(pair.source != "internal-bfgs" for pair in internal_pairs):
        raise JointPredictionError("internal evidence contains a non-internal secant")
    if any(pair.source != "held-out-independent" for pair in held_out_pairs):
        raise JointPredictionError("held-out evidence contains a non-held-out secant")
    overlap = {pair.pair_id for pair in internal_pairs} & {
        pair.pair_id for pair in held_out_pairs
    }
    if overlap:
        raise JointPredictionError("internal and held-out evidence overlap")
    try:
        prediction = predict_constrained_optimum(model, transformation, numerical_policy)
        native = target_native_model(model, transformation, numerical_policy)
        matrix = transformation.constraint_matrix
        basis = _constraint_basis(matrix, numerical_policy.rank_relative_tolerance)
        if matrix.shape[0]:
            schur = matrix @ model.inverse_hessian @ matrix.T
            schur_diagnostics = validate_spd(schur, numerical_policy)
            schur_condition = schur_diagnostics.condition_number
        else:
            schur_condition = 1.0
    except QuadraticModelError as error:
        raise JointPredictionError("joint OBS numerical solve failed") from error
    internal = _projected_secant_statistics(model.inverse_hessian, basis, internal_pairs)
    held = _projected_secant_statistics(model.inverse_hessian, basis, held_out_pairs)
    diagnostics = JointPredictionDiagnostics(
        matrix.shape[0],
        schur_condition,
        native.diagnostics.condition_number,
        (
            native.solve_certificate.equilibrated.condition_number
            if native.solve_certificate is not None
            else 1.0
        ),
        (
            native.solve_certificate.relative_residual
            if native.solve_certificate is not None
            else 0.0
        ),
        (
            native.solve_certificate.relative_backward_error
            if native.solve_certificate is not None
            else 0.0
        ),
        _direction_coverage(
            basis, internal_pairs, numerical_policy.rank_relative_tolerance
        ),
        internal,
        held,
        bool(held_out_pairs),
    )
    return {
        "version": JOINT_PREDICTION_VERSION,
        "predicted_change_from_current_hartree": prediction.predicted_change_from_current,
        "predicted_constraint_penalty_hartree": prediction.predicted_constraint_penalty,
        "direct_quadratic_change_from_current_hartree": prediction.direct_quadratic_change_from_current,
        "constrained_source_theta": prediction.constrained_theta.tolist(),
        "target_native_coordinates": native.optimum_coordinates.tolist(),
        "target_inverse_hessian": native.inverse_hessian.tolist(),
        "constraint_residual_infinity": prediction.constraint_residual_infinity,
        "reference_energy_kind": prediction.reference_energy_kind,
        "diagnostics": asdict(diagnostics),
    }


def evaluate_joint_quality(
    prediction: Mapping[str, Any],
    policy: JointQualityPolicy,
) -> dict[str, Any]:
    policy.validate()
    diagnostics = prediction["diagnostics"]
    internal = diagnostics["internal_projected_secants"]
    held = diagnostics["held_out_projected_secants"]
    checks = {
        "constraint_schur_condition": diagnostics["constraint_schur_condition_number"]
        <= policy.maximum_constraint_schur_condition_number,
        "target_hessian_condition": (
            not policy.target_hessian_condition_is_scientific_gate
            or diagnostics["target_hessian_condition_number"]
            <= policy.maximum_target_hessian_condition_number
        ),
        "target_hessian_equilibrated_condition": diagnostics[
            "target_hessian_equilibrated_condition_number"
        ]
        <= policy.maximum_equilibrated_target_hessian_condition_number,
        "target_hessian_relative_solve_residual": diagnostics[
            "target_hessian_relative_solve_residual"
        ]
        <= policy.maximum_target_hessian_relative_solve_residual,
        "target_hessian_relative_backward_error": diagnostics[
            "target_hessian_relative_backward_error"
        ]
        <= policy.maximum_target_hessian_relative_backward_error,
        "constraint_direction_coverage": diagnostics["constraint_direction_coverage"]
        >= policy.minimum_constraint_direction_coverage,
        "internal_projected_residual": internal["maximum_relative_residual"] is not None
        and internal["maximum_relative_residual"]
        <= policy.maximum_internal_projected_residual,
        "held_out_evidence": (not policy.require_held_out_evidence)
        or diagnostics["held_out_evidence_available"],
        "held_out_projected_residual": (not policy.require_held_out_evidence)
        or (
            held["maximum_relative_residual"] is not None
            and held["maximum_relative_residual"]
            <= policy.maximum_held_out_projected_residual
        ),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "policy": asdict(policy),
    }

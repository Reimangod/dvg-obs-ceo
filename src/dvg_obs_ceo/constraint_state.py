"""Exact semantic and canonical numerical identities for Global OBS states."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import math
from typing import Any, Iterable, Sequence

import numpy as np
from numpy.typing import NDArray

from .block_ir import CompressionCandidate
from .identity import canonical_float64_hex, sha256_hex
from .quadratic import ConstraintTargetIR, QuadraticModelError


FloatArray = NDArray[np.float64]
SEMANTIC_VERSION = "constraint-semantic-v1"
NUMERICAL_VERSION = "constraint-numerical-v1"
ATOMIC_SYMBOLIC_VERSION = "atomic-ceo-symbolic-v1"


class ConstraintStateError(RuntimeError):
    """Raised when exact provenance or numerical maps are inconsistent."""


def _fraction(value: int | str | Fraction) -> Fraction:
    if isinstance(value, bool) or isinstance(value, float):
        raise ConstraintStateError("exact constraints cannot be inferred from floats")
    try:
        result = value if isinstance(value, Fraction) else Fraction(value)
    except (ValueError, ZeroDivisionError) as error:
        raise ConstraintStateError(f"invalid exact rational: {value!r}") from error
    return result


def _fraction_text(value: Fraction) -> str:
    return str(value.numerator) if value.denominator == 1 else f"{value.numerator}/{value.denominator}"


def _rref(rows: Sequence[Sequence[Fraction]], columns: int) -> tuple[tuple[Fraction, ...], ...]:
    matrix = [list(row) for row in rows]
    if any(len(row) != columns for row in matrix):
        raise ConstraintStateError("exact augmented rows have inconsistent width")
    pivot_row = 0
    for column in range(columns - 1):
        pivot = next((index for index in range(pivot_row, len(matrix)) if matrix[index][column]), None)
        if pivot is None:
            continue
        matrix[pivot_row], matrix[pivot] = matrix[pivot], matrix[pivot_row]
        scale = matrix[pivot_row][column]
        matrix[pivot_row] = [value / scale for value in matrix[pivot_row]]
        for index, row in enumerate(matrix):
            if index == pivot_row or row[column] == 0:
                continue
            factor = row[column]
            matrix[index] = [left - factor * right for left, right in zip(row, matrix[pivot_row])]
        pivot_row += 1
        if pivot_row == len(matrix):
            break
    nonzero = [row for row in matrix if any(value for value in row)]
    for row in nonzero:
        if not any(row[:-1]) and row[-1]:
            raise ConstraintStateError("exact affine constraints are inconsistent")
    return tuple(tuple(row) for row in nonzero)


@dataclass(frozen=True)
class ExactConstraintSystem:
    """Canonical exact RREF of ``A theta = b`` in source-slot order."""

    source_slots: tuple[str, ...]
    augmented_rref: tuple[tuple[str, ...], ...]

    @classmethod
    def create(
        cls,
        source_slots: Iterable[str],
        constraint_rows: Iterable[Iterable[int | str | Fraction]],
        rhs: Iterable[int | str | Fraction],
    ) -> "ExactConstraintSystem":
        slots = tuple(str(slot) for slot in source_slots)
        if not slots or len(set(slots)) != len(slots) or any(not slot for slot in slots):
            raise ConstraintStateError("source slots must be nonempty, explicit, and unique")
        rows = [tuple(_fraction(value) for value in row) for row in constraint_rows]
        values = tuple(_fraction(value) for value in rhs)
        if len(rows) != len(values) or any(len(row) != len(slots) for row in rows):
            raise ConstraintStateError("exact constraint dimensions are inconsistent")
        order = tuple(sorted(range(len(slots)), key=lambda index: slots[index]))
        ordered_slots = tuple(slots[index] for index in order)
        augmented = [tuple(row[index] for index in order) + (value,) for row, value in zip(rows, values)]
        reduced = _rref(augmented, len(slots) + 1)
        return cls(
            ordered_slots,
            tuple(tuple(_fraction_text(value) for value in row) for row in reduced),
        )

    @property
    def rank(self) -> int:
        return len(self.augmented_rref)

    @property
    def source_dimension(self) -> int:
        return len(self.source_slots)

    def rational_matrix(self) -> tuple[list[list[Fraction]], list[Fraction]]:
        rows = [[Fraction(value) for value in row] for row in self.augmented_rref]
        return [row[:-1] for row in rows], [row[-1] for row in rows]

    def payload(self) -> dict[str, Any]:
        return {
            "version": SEMANTIC_VERSION,
            "source_slots": list(self.source_slots),
            "augmented_rref": [list(row) for row in self.augmented_rref],
        }


@dataclass(frozen=True)
class AtomicExactConstraint:
    system: ExactConstraintSystem
    primitive: dict[str, Any]
    audit_provenance: dict[str, Any]


def exact_atomic_constraint(
    candidate: CompressionCandidate,
    *,
    numerical_tolerance: float = 1e-12,
) -> AtomicExactConstraint:
    """Recover exact rational semantics from a registered candidate kind.

    Floats are used only to validate the registered symbolic relation; they
    are never rounded to invent semantic provenance.
    """

    transform = candidate.transformation
    source_dimension, target_dimension = transform.jacobian.shape
    source_slots = transform.source_slots
    rows: list[list[int]] = []
    expected = np.zeros_like(transform.jacobian)
    kind = candidate.kind
    if kind in {"block-deletion", "mvp-whole-deletion"}:
        if target_dimension != 0:
            raise ConstraintStateError("whole deletion must have zero target dimension")
        rows = np.eye(source_dimension, dtype=int).tolist()
        relation = "empty"
    elif kind in {"mvp-constituent-deletion", "mvp-to-single-qe"}:
        kept = [index for index in range(source_dimension) if index not in candidate.removed_source_slots]
        if target_dimension != len(kept):
            raise ConstraintStateError("ordered subset target dimension is inconsistent")
        for target, source in enumerate(kept):
            expected[source, target] = 1.0
        rows = np.eye(source_dimension, dtype=int)[list(candidate.removed_source_slots)].tolist()
        relation = "identity-subset"
    elif kind in {"mvp-to-ovp-sum", "mvp-to-ovp-diff"}:
        if (source_dimension, target_dimension) != (2, 1):
            raise ConstraintStateError("registered OVP tie must map two sources to one target")
        sign = 1 if kind.endswith("sum") else -1
        expected[:, 0] = [1.0, float(sign)]
        rows = [[1, -sign]]
        relation = "existing-ovp-sum" if sign == 1 else "existing-ovp-difference"
    else:
        raise ConstraintStateError(f"candidate kind lacks exact symbolic support: {kind}")
    if not np.allclose(transform.jacobian, expected, rtol=0.0, atol=numerical_tolerance):
        raise ConstraintStateError("numerical Jacobian disagrees with registered exact primitive")
    if not np.allclose(transform.offset, 0.0, rtol=0.0, atol=numerical_tolerance):
        raise ConstraintStateError("registered atomic transform requires exact zero offset")
    system = ExactConstraintSystem.create(source_slots, rows, [0] * len(rows))
    primitive = {
        "version": ATOMIC_SYMBOLIC_VERSION,
        "generator_relation": relation,
        "source_block_id": candidate.source_block_id,
        "source_slots": list(source_slots),
        "source_pool_indices": list(candidate.source_pool_indices),
        "target_family": candidate.target_family,
        "target_pool_indices": list(candidate.target_pool_indices),
        "target_operator_digests": list(candidate.target_operator_digests),
        "removed_source_slots": list(candidate.removed_source_slots),
        "generator_normalization": transform.generator_normalization,
        "units": transform.units,
        "exact_augmented_rref": [list(row) for row in system.augmented_rref],
    }
    provenance = {
        "candidate_id": candidate.candidate_id,
        "kind": candidate.kind,
        "equivalence_class_id": candidate.equivalence_class_id,
        "original_orientation": transform.orientation,
        "numerical_context_digest": candidate.numerical_context_digest,
    }
    return AtomicExactConstraint(system, primitive, provenance)


@dataclass(frozen=True)
class CanonicalConstraintState:
    exact_system: ExactConstraintSystem
    transformation_primitives: tuple[dict[str, Any], ...]
    constraint_semantic_id: str
    constraint_numerical_id: str
    numerical_payload: dict[str, Any]
    diagnostics: dict[str, Any]

    @classmethod
    def create(
        cls,
        exact_system: ExactConstraintSystem,
        numerical: ConstraintTargetIR,
        transformation_primitives: Iterable[dict[str, Any]],
        *,
        feasibility_tolerance: float = 1e-10,
    ) -> "CanonicalConstraintState":
        try:
            numerical.validate(len(numerical.source_slots))
        except QuadraticModelError as error:
            raise ConstraintStateError("numerical target IR is invalid") from error
        if set(numerical.source_slots) != set(exact_system.source_slots):
            raise ConstraintStateError("exact and numerical source slots differ")
        if exact_system.rank != len(numerical.source_slots) - len(numerical.target_slots):
            raise ConstraintStateError("exact constraint rank and target dimension differ")
        source_order = [numerical.source_slots.index(slot) for slot in exact_system.source_slots]
        target_slots = tuple(sorted(numerical.target_slots))
        target_order = [numerical.target_slots.index(slot) for slot in target_slots]
        offset = np.asarray(numerical.offset[source_order], dtype=np.float64)
        jacobian = np.asarray(
            numerical.jacobian[np.ix_(source_order, target_order)], dtype=np.float64
        )
        exact_a, exact_b = exact_system.rational_matrix()
        matrix = np.asarray([[float(value) for value in row] for row in exact_a], dtype=np.float64)
        rhs = np.asarray([float(value) for value in exact_b], dtype=np.float64)
        offset_residual = float(np.max(np.abs(matrix @ offset - rhs))) if len(rhs) else 0.0
        jacobian_residual = float(np.max(np.abs(matrix @ jacobian))) if matrix.size else 0.0
        if offset_residual > feasibility_tolerance or jacobian_residual > feasibility_tolerance:
            raise ConstraintStateError("numerical affine map violates exact constraints")
        primitives = tuple(
            sorted((dict(value) for value in transformation_primitives), key=sha256_hex)
        )
        if not primitives:
            raise ConstraintStateError("constraint state requires exact transformation provenance")
        semantic_payload = {
            **exact_system.payload(),
            "transformation_primitives": list(primitives),
        }
        condition = float(np.linalg.cond(jacobian)) if jacobian.size else 1.0
        if not math.isfinite(condition):
            raise ConstraintStateError("numerical target Jacobian is ill-conditioned")
        numerical_payload = {
            "version": NUMERICAL_VERSION,
            "source_slots": list(exact_system.source_slots),
            "target_slots": list(target_slots),
            "constraint_matrix_float64": [list(canonical_float64_hex(row)) for row in matrix],
            "constraint_rhs_float64": list(canonical_float64_hex(rhs)),
            "offset_float64": list(canonical_float64_hex(offset)),
            "jacobian_float64": [list(canonical_float64_hex(row)) for row in jacobian],
            "rank": exact_system.rank,
            "condition_number_float64": canonical_float64_hex([condition])[0],
        }
        diagnostics = {
            "source_dimension": exact_system.source_dimension,
            "target_dimension": len(target_slots),
            "exact_rank": exact_system.rank,
            "offset_constraint_residual_infinity": offset_residual,
            "jacobian_constraint_residual_infinity": jacobian_residual,
            "jacobian_condition_number": condition,
        }
        return cls(
            exact_system,
            primitives,
            "constraint-semantic-v1:" + sha256_hex(semantic_payload),
            "constraint-numerical-v1:" + sha256_hex(numerical_payload),
            numerical_payload,
            diagnostics,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "constraint_semantic_id": self.constraint_semantic_id,
            "constraint_numerical_id": self.constraint_numerical_id,
            "exact_system": self.exact_system.payload(),
            "transformation_primitives": list(self.transformation_primitives),
            "numerical_payload": self.numerical_payload,
            "diagnostics": self.diagnostics,
        }

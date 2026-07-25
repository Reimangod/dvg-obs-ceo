"""Fail-closed mathematical and numerical evidence kernels for V6.

Exact family claims use rational Pauli algebra. Floating-point matrix and state
comparisons are always emitted as numerical, pointwise evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import itertools
import json
import math
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
from numpy.typing import NDArray

from dvg_obs_ceo.identity import (
    canonical_float64_hex,
    canonical_json_bytes,
    sha256_hex,
)

from .architecture_state import ParameterMapIR, ParameterMapRepresentation
from .evidence import (
    ContextScope,
    EvidenceError,
    EvidenceRecord,
    EvidenceStatus,
    EvidenceStrength,
    EvidenceType,
    NativeSynthesisScope,
    SemanticScope,
)


ComplexArray = NDArray[np.complex128]
PauliWord = tuple[tuple[int, str], ...]


class MathematicalEvidenceError(ValueError):
    """Raised when a requested proof or validation is unsupported."""


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {
                str(key): _freeze_json(item)
                for key, item in sorted(value.items())
            }
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    return value


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _fraction(value: int | str | Fraction) -> Fraction:
    try:
        result = Fraction(value)
    except (TypeError, ValueError, ZeroDivisionError) as error:
        raise MathematicalEvidenceError(
            f"invalid exact rational value: {value}"
        ) from error
    return result


def _fraction_text(value: Fraction) -> str:
    return str(value)


def _rref_solve(
    matrix: Sequence[Sequence[Fraction]],
    rhs: Sequence[Fraction],
) -> tuple[bool, tuple[Fraction, ...], bool]:
    """Solve A x = b exactly, choosing zero for free variables."""
    rows = [list(row) + [value] for row, value in zip(matrix, rhs)]
    row_count = len(rows)
    column_count = len(matrix[0]) if matrix else 0
    if len(rhs) != row_count or any(
        len(row) != column_count for row in matrix
    ):
        raise MathematicalEvidenceError("linear-system dimensions disagree")
    pivot_columns: list[int] = []
    pivot_row = 0
    for column in range(column_count):
        pivot = next(
            (
                row
                for row in range(pivot_row, row_count)
                if rows[row][column] != 0
            ),
            None,
        )
        if pivot is None:
            continue
        rows[pivot_row], rows[pivot] = rows[pivot], rows[pivot_row]
        scale = rows[pivot_row][column]
        rows[pivot_row] = [value / scale for value in rows[pivot_row]]
        for row in range(row_count):
            if row == pivot_row:
                continue
            factor = rows[row][column]
            if factor:
                rows[row] = [
                    left - factor * right
                    for left, right in zip(rows[row], rows[pivot_row])
                ]
        pivot_columns.append(column)
        pivot_row += 1
        if pivot_row == row_count:
            break
    inconsistent = any(
        all(value == 0 for value in row[:column_count])
        and row[column_count] != 0
        for row in rows
    )
    if inconsistent:
        return False, (), False
    solution = [Fraction(0) for _ in range(column_count)]
    for row, column in enumerate(pivot_columns):
        solution[column] = rows[row][column_count]
    return True, tuple(solution), len(pivot_columns) == column_count


@dataclass(frozen=True)
class ParameterMembership:
    member: bool
    target_coordinates: tuple[str, ...]
    periodic_windings: tuple[int, ...] | None
    unique: bool
    equation: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "member": self.member,
            "target_coordinates": list(self.target_coordinates),
            "periodic_windings": (
                None
                if self.periodic_windings is None
                else list(self.periodic_windings)
            ),
            "unique": self.unique,
            "equation": self.equation,
        }


def validate_affine_parameter_map(parameter_map: ParameterMapIR) -> str:
    """Validate a map supported by the exact S4 affine kernels."""
    if parameter_map.representation not in {
        ParameterMapRepresentation.IDENTITY,
        ParameterMapRepresentation.AFFINE_EXACT,
        ParameterMapRepresentation.PERIODIC_AFFINE_EXACT,
    }:
        raise MathematicalEvidenceError(
            "registered analytic maps require a separate named proof kernel"
        )
    payload = parameter_map.to_dict()
    # Construction already verifies canonical rationals and exact rank.
    return sha256_hex(payload)


def source_parameter_membership(
    parameter_map: ParameterMapIR,
    source_parameters: Sequence[int | str | Fraction],
    *,
    periodic_windings: Sequence[int] | None = None,
) -> ParameterMembership:
    """Check theta + k*p = c + J*phi with exact rational arithmetic.

    Periodic equivalence is accepted only with an explicit integer winding
    witness. The kernel never searches a finite winding window and presents it
    as a complete membership decision.
    """
    validate_affine_parameter_map(parameter_map)
    theta = tuple(_fraction(value) for value in source_parameters)
    if len(theta) != parameter_map.source_dimension:
        raise MathematicalEvidenceError(
            "source parameter dimension does not match the map"
        )
    periodic = (
        parameter_map.representation
        is ParameterMapRepresentation.PERIODIC_AFFINE_EXACT
    )
    if periodic:
        if periodic_windings is None:
            raise MathematicalEvidenceError(
                "periodic membership requires an explicit winding witness"
            )
        windings = tuple(periodic_windings)
        if (
            len(windings) != parameter_map.source_dimension
            or any(type(value) is not int for value in windings)
        ):
            raise MathematicalEvidenceError(
                "periodic windings must be one integer per source coordinate"
            )
        periods = tuple(_fraction(value) for value in parameter_map.periodicity or ())
    else:
        if periodic_windings is not None:
            raise MathematicalEvidenceError(
                "non-periodic membership cannot carry winding data"
            )
        windings = None
        periods = (Fraction(0),) * parameter_map.source_dimension
    offset = tuple(_fraction(value) for value in parameter_map.offset)
    jacobian = tuple(
        tuple(_fraction(value) for value in row)
        for row in parameter_map.jacobian
    )
    adjusted = tuple(
        value
        + (Fraction(windings[index]) * periods[index] if windings else 0)
        - offset[index]
        for index, value in enumerate(theta)
    )
    member, coordinates, unique = _rref_solve(jacobian, adjusted)
    return ParameterMembership(
        member=member,
        target_coordinates=(
            tuple(_fraction_text(value) for value in coordinates)
            if member
            else ()
        ),
        periodic_windings=windings,
        unique=unique if member else False,
        equation="theta + winding*period = offset + jacobian*phi",
    )


def parameter_membership_evidence(
    parameter_map: ParameterMapIR,
    source_parameters: Sequence[int | str | Fraction],
    *,
    source_semantic_id: str,
    target_semantic_id: str,
    periodic_windings: Sequence[int] | None = None,
) -> EvidenceRecord:
    membership = source_parameter_membership(
        parameter_map,
        source_parameters,
        periodic_windings=periodic_windings,
    )
    inputs = {
        "parameter_map": parameter_map.to_dict(),
        "source_parameters": [str(_fraction(value)) for value in source_parameters],
        "periodic_windings": (
            None if periodic_windings is None else list(periodic_windings)
        ),
    }
    details = membership.to_dict()
    return EvidenceRecord(
        evidence_type=EvidenceType.SOURCE_PARAMETER_MEMBERSHIP,
        status=(
            EvidenceStatus.PASSED
            if membership.member
            else EvidenceStatus.FAILED
        ),
        strength=EvidenceStrength.ALGEBRAICALLY_PROVEN,
        semantic_scope=SemanticScope.PARAMETER_MAP,
        context_scope=ContextScope.LOCAL_BLOCK,
        method_id="v6-exact-rational-affine-membership-v1",
        source_semantic_id=source_semantic_id,
        target_semantic_id=target_semantic_id,
        input_digest=sha256_hex(inputs),
        output_digest=sha256_hex(details),
        details=details,
    )


@dataclass(frozen=True)
class ExactComplex:
    real: Fraction = Fraction(0)
    imag: Fraction = Fraction(0)

    def __post_init__(self) -> None:
        if not isinstance(self.real, Fraction) or not isinstance(
            self.imag,
            Fraction,
        ):
            raise MathematicalEvidenceError(
                "exact complex coefficients require Fraction components"
            )

    @classmethod
    def create(
        cls,
        real: int | str | Fraction = 0,
        imag: int | str | Fraction = 0,
    ) -> "ExactComplex":
        return cls(_fraction(real), _fraction(imag))

    def __add__(self, other: "ExactComplex") -> "ExactComplex":
        return ExactComplex(self.real + other.real, self.imag + other.imag)

    def __sub__(self, other: "ExactComplex") -> "ExactComplex":
        return ExactComplex(self.real - other.real, self.imag - other.imag)

    def __mul__(self, other: "ExactComplex") -> "ExactComplex":
        return ExactComplex(
            self.real * other.real - self.imag * other.imag,
            self.real * other.imag + self.imag * other.real,
        )

    def scale(self, value: Fraction) -> "ExactComplex":
        return ExactComplex(self.real * value, self.imag * value)

    @property
    def is_zero(self) -> bool:
        return self.real == 0 and self.imag == 0

    def to_dict(self) -> dict[str, str]:
        return {"real": str(self.real), "imag": str(self.imag)}


_PAULI_PRODUCT: dict[tuple[str, str], tuple[str, ExactComplex]] = {
    ("X", "Y"): ("Z", ExactComplex.create(imag=1)),
    ("Y", "X"): ("Z", ExactComplex.create(imag=-1)),
    ("Y", "Z"): ("X", ExactComplex.create(imag=1)),
    ("Z", "Y"): ("X", ExactComplex.create(imag=-1)),
    ("Z", "X"): ("Y", ExactComplex.create(imag=1)),
    ("X", "Z"): ("Y", ExactComplex.create(imag=-1)),
}


def _canonical_word(word: Iterable[tuple[int, str]]) -> PauliWord:
    values = tuple((int(qubit), str(pauli)) for qubit, pauli in word)
    if (
        tuple(sorted(values)) != values
        or len({qubit for qubit, _ in values}) != len(values)
        or any(qubit < 0 or pauli not in {"X", "Y", "Z"} for qubit, pauli in values)
    ):
        raise MathematicalEvidenceError(
            "Pauli words require sorted unique non-negative qubits and X/Y/Z labels"
        )
    return values


@dataclass(frozen=True)
class ExactPauliOperator:
    terms: tuple[tuple[PauliWord, ExactComplex], ...]

    def __post_init__(self) -> None:
        words = tuple(word for word, _ in self.terms)
        if words != tuple(sorted(words)) or len(words) != len(set(words)):
            raise MathematicalEvidenceError(
                "exact Pauli terms must be sorted and unique"
            )
        for word, coefficient in self.terms:
            if _canonical_word(word) != word or not isinstance(
                coefficient,
                ExactComplex,
            ):
                raise MathematicalEvidenceError(
                    "exact Pauli operator is not canonical"
                )
            if coefficient.is_zero:
                raise MathematicalEvidenceError(
                    "exact Pauli operator cannot retain zero terms"
                )

    @classmethod
    def create(
        cls,
        terms: Mapping[
            Iterable[tuple[int, str]],
            tuple[int | str | Fraction, int | str | Fraction],
        ],
    ) -> "ExactPauliOperator":
        combined: dict[PauliWord, ExactComplex] = {}
        for raw_word, (real, imag) in terms.items():
            word = _canonical_word(raw_word)
            combined[word] = combined.get(word, ExactComplex()) + ExactComplex.create(
                real,
                imag,
            )
        return cls(
            tuple(
                sorted(
                    (
                        (word, coefficient)
                        for word, coefficient in combined.items()
                        if not coefficient.is_zero
                    ),
                    key=lambda item: item[0],
                )
            )
        )

    @property
    def mapping(self) -> dict[PauliWord, ExactComplex]:
        return dict(self.terms)

    def scale(self, value: Fraction) -> "ExactPauliOperator":
        return ExactPauliOperator(
            tuple(
                (word, coefficient.scale(value))
                for word, coefficient in self.terms
                if not coefficient.scale(value).is_zero
            )
        )

    def __add__(self, other: "ExactPauliOperator") -> "ExactPauliOperator":
        combined = self.mapping
        for word, coefficient in other.terms:
            combined[word] = combined.get(word, ExactComplex()) + coefficient
        return ExactPauliOperator(
            tuple(
                sorted(
                    (
                        (word, coefficient)
                        for word, coefficient in combined.items()
                        if not coefficient.is_zero
                    ),
                    key=lambda item: item[0],
                )
            )
        )

    def to_dict(self) -> list[dict[str, Any]]:
        return [
            {
                "word": [[qubit, pauli] for qubit, pauli in word],
                "coefficient": coefficient.to_dict(),
            }
            for word, coefficient in self.terms
        ]


def _multiply_words(left: PauliWord, right: PauliWord) -> tuple[PauliWord, ExactComplex]:
    left_map = dict(left)
    right_map = dict(right)
    result: list[tuple[int, str]] = []
    phase = ExactComplex.create(real=1)
    for qubit in sorted(set(left_map) | set(right_map)):
        a = left_map.get(qubit)
        b = right_map.get(qubit)
        if a is None:
            result.append((qubit, b or ""))
        elif b is None:
            result.append((qubit, a))
        elif a == b:
            continue
        else:
            pauli, local_phase = _PAULI_PRODUCT[(a, b)]
            result.append((qubit, pauli))
            phase = phase * local_phase
    return tuple(result), phase


def _multiply_operators(
    left: ExactPauliOperator,
    right: ExactPauliOperator,
) -> ExactPauliOperator:
    combined: dict[PauliWord, ExactComplex] = {}
    for left_word, left_coefficient in left.terms:
        for right_word, right_coefficient in right.terms:
            word, phase = _multiply_words(left_word, right_word)
            coefficient = (left_coefficient * right_coefficient) * phase
            combined[word] = combined.get(word, ExactComplex()) + coefficient
    return ExactPauliOperator(
        tuple(
            sorted(
                (
                    (word, coefficient)
                    for word, coefficient in combined.items()
                    if not coefficient.is_zero
                ),
                key=lambda item: item[0],
            )
        )
    )


def exact_operators_commute(
    left: ExactPauliOperator,
    right: ExactPauliOperator,
) -> bool:
    """Return exact commutation in rational Pauli algebra."""
    commutator = _multiply_operators(left, right) + _multiply_operators(
        right,
        left,
    ).scale(Fraction(-1))
    return not commutator.terms


@dataclass(frozen=True)
class AlgebraicProofRecord:
    proof_type: str
    method_id: str
    input_digest: str
    output_digest: str
    details: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not self.proof_type or not self.method_id:
            raise MathematicalEvidenceError(
                "proof type and method ID must be explicit"
            )
        for name, digest in (
            ("input_digest", self.input_digest),
            ("output_digest", self.output_digest),
        ):
            if len(digest) != 64 or any(
                character not in "0123456789abcdef"
                for character in digest
            ):
                raise MathematicalEvidenceError(
                    f"{name} must be a lowercase SHA-256 digest"
                )
        canonical = json.loads(
            canonical_json_bytes(dict(self.details)).decode("utf-8")
        )
        object.__setattr__(self, "details", _freeze_json(canonical))

    @property
    def proof_id(self) -> str:
        return "v6-proof-v1:" + sha256_hex(self.to_dict(include_id=False))

    def to_dict(self, *, include_id: bool = True) -> dict[str, Any]:
        result = {
            "schema_version": "1.0.0",
            "proof_type": self.proof_type,
            "method_id": self.method_id,
            "input_digest": self.input_digest,
            "output_digest": self.output_digest,
            "details": _thaw_json(self.details),
        }
        if include_id:
            result["proof_id"] = self.proof_id
        return result


def prove_generator_relation_and_commutation(
    parameter_map: ParameterMapIR,
    source_generators: Sequence[ExactPauliOperator],
    target_generators: Sequence[ExactPauliOperator],
    *,
    source_semantic_id: str,
    target_semantic_id: str,
) -> tuple[EvidenceRecord, AlgebraicProofRecord]:
    """Prove exact generator identities and pairwise source commutation."""
    validate_affine_parameter_map(parameter_map)
    if any(Fraction(value) != 0 for value in parameter_map.offset):
        raise MathematicalEvidenceError(
            "generator-relation proof supports only zero-offset affine maps"
        )
    if (
        len(source_generators) != parameter_map.source_dimension
        or len(target_generators) != parameter_map.target_dimension
    ):
        raise MathematicalEvidenceError(
            "generator count does not match parameter-map dimensions"
        )
    for left, right in itertools.combinations(source_generators, 2):
        if not exact_operators_commute(left, right):
            raise MathematicalEvidenceError(
                "source generators do not commute exactly"
            )
    for target_index, target in enumerate(target_generators):
        reconstructed = ExactPauliOperator(())
        for source_index, source in enumerate(source_generators):
            reconstructed = reconstructed + source.scale(
                Fraction(parameter_map.jacobian[source_index][target_index])
            )
        if reconstructed != target:
            raise MathematicalEvidenceError(
                f"target generator {target_index} has an exact relation mismatch"
            )
    inputs = {
        "parameter_map": parameter_map.to_dict(),
        "source_generators": [item.to_dict() for item in source_generators],
        "target_generators": [item.to_dict() for item in target_generators],
    }
    relation_details = {
        "identity": "target_generators = source_generators * jacobian",
        "exact_arithmetic": "fractions.Fraction",
        "target_count": len(target_generators),
    }
    commutation_details = {
        "identity": "[G_i,G_j]=0",
        "exact_arithmetic": "rational Pauli algebra",
        "pair_count": len(source_generators) * (len(source_generators) - 1) // 2,
    }
    common = {
        "status": EvidenceStatus.PASSED,
        "strength": EvidenceStrength.ALGEBRAICALLY_PROVEN,
        "semantic_scope": SemanticScope.FAMILYWISE_UNITARY,
        "context_scope": ContextScope.LOCAL_BLOCK,
        "source_semantic_id": source_semantic_id,
        "target_semantic_id": target_semantic_id,
        "input_digest": sha256_hex(inputs),
    }
    return (
        EvidenceRecord(
            evidence_type=EvidenceType.TARGET_EMBEDDING,
            method_id="v6-exact-pauli-generator-relation-v1",
            output_digest=sha256_hex(relation_details),
            details=relation_details,
            **common,
        ),
        AlgebraicProofRecord(
            proof_type="PAIRWISE_SOURCE_GENERATOR_COMMUTATION",
            method_id="v6-exact-pauli-commutation-v1",
            input_digest=sha256_hex(inputs),
            output_digest=sha256_hex(commutation_details),
            details=commutation_details,
        ),
    )


def _finite_complex_array(name: str, value: Any) -> ComplexArray:
    result = np.asarray(value, dtype=np.complex128)
    if not np.all(np.isfinite(result)):
        raise MathematicalEvidenceError(f"{name} must be finite")
    return result


def _global_phase_residual(
    source: ComplexArray,
    target: ComplexArray,
) -> tuple[float, complex]:
    overlap = np.vdot(target.reshape(-1), source.reshape(-1))
    if abs(overlap) <= np.finfo(np.float64).tiny:
        return math.inf, complex(1)
    phase = overlap / abs(overlap)
    return float(np.linalg.norm(source - phase * target)), complex(phase)


def _numerical_equivalence_record(
    *,
    evidence_type: EvidenceType,
    semantic_scope: SemanticScope,
    context_scope: ContextScope,
    source: ComplexArray,
    target: ComplexArray,
    source_semantic_id: str,
    target_semantic_id: str,
    tolerance: float,
    method_id: str,
    extra_details: Mapping[str, Any] | None = None,
) -> EvidenceRecord:
    if not math.isfinite(tolerance) or tolerance <= 0:
        raise MathematicalEvidenceError(
            "numerical tolerance must be positive and finite"
        )
    if source.shape != target.shape or source.size == 0:
        raise MathematicalEvidenceError(
            "source and target numerical objects must have one nonempty shape"
        )
    residual, phase = _global_phase_residual(source, target)
    details = {
        "shape": list(source.shape),
        "global_phase_real": phase.real,
        "global_phase_imag": phase.imag,
        "residual_l2": residual,
        **dict(extra_details or {}),
    }
    inputs = {
        "source_float64_hex": list(
            canonical_float64_hex(
                np.column_stack((source.real.reshape(-1), source.imag.reshape(-1))).reshape(-1)
            )
        ),
        "target_float64_hex": list(
            canonical_float64_hex(
                np.column_stack((target.real.reshape(-1), target.imag.reshape(-1))).reshape(-1)
            )
        ),
    }
    return EvidenceRecord(
        evidence_type=evidence_type,
        status=(
            EvidenceStatus.PASSED
            if residual <= tolerance
            else EvidenceStatus.FAILED
        ),
        strength=EvidenceStrength.NUMERICALLY_VALIDATED,
        semantic_scope=semantic_scope,
        context_scope=context_scope,
        method_id=method_id,
        source_semantic_id=source_semantic_id,
        target_semantic_id=target_semantic_id,
        input_digest=sha256_hex(inputs),
        output_digest=sha256_hex(details),
        tolerance=tolerance,
        details=details,
    )


def validate_pointwise_unitary(
    source_unitary: Any,
    target_unitary: Any,
    *,
    source_semantic_id: str,
    target_semantic_id: str,
    tolerance: float = 1e-10,
    evidence_type: EvidenceType = EvidenceType.SOURCE_UNITARY_EQUIVALENCE,
) -> EvidenceRecord:
    source = _finite_complex_array("source unitary", source_unitary)
    target = _finite_complex_array("target unitary", target_unitary)
    if (
        source.ndim != 2
        or source.shape[0] != source.shape[1]
        or target.ndim != 2
        or target.shape[0] != target.shape[1]
        or source.shape != target.shape
    ):
        raise MathematicalEvidenceError(
            "unitaries must be equally sized square matrices"
        )
    identity = np.eye(source.shape[0], dtype=np.complex128)
    if (
        np.linalg.norm(source.conj().T @ source - identity) > tolerance
        or np.linalg.norm(target.conj().T @ target - identity) > tolerance
    ):
        raise MathematicalEvidenceError("unitary validation received a nonunitary matrix")
    return _numerical_equivalence_record(
        evidence_type=evidence_type,
        semantic_scope=SemanticScope.POINTWISE_UNITARY,
        context_scope=ContextScope.LOCAL_BLOCK,
        source=source,
        target=target,
        source_semantic_id=source_semantic_id,
        target_semantic_id=target_semantic_id,
        tolerance=tolerance,
        method_id="v6-global-phase-unitary-validation-v1",
    )


def validate_pointwise_state(
    source_unitary: Any,
    target_unitary: Any,
    reference_state: Any,
    *,
    source_semantic_id: str,
    target_semantic_id: str,
    reference_state_id: str,
    tolerance: float = 1e-10,
) -> EvidenceRecord:
    source = _finite_complex_array("source unitary", source_unitary)
    target = _finite_complex_array("target unitary", target_unitary)
    reference = _finite_complex_array("reference state", reference_state).reshape(-1)
    if (
        source.ndim != 2
        or target.ndim != 2
        or source.shape != target.shape
        or source.shape[0] != source.shape[1]
        or source.shape[1] != reference.size
    ):
        raise MathematicalEvidenceError(
            "state validator dimensions are incompatible"
        )
    norm = float(np.linalg.norm(reference))
    if abs(norm - 1.0) > tolerance:
        raise MathematicalEvidenceError("reference state must be normalized")
    if not reference_state_id:
        raise MathematicalEvidenceError("reference state ID must be explicit")
    identity = np.eye(source.shape[0], dtype=np.complex128)
    if (
        np.linalg.norm(source.conj().T @ source - identity) > tolerance
        or np.linalg.norm(target.conj().T @ target - identity) > tolerance
    ):
        raise MathematicalEvidenceError(
            "state validation received a nonunitary matrix"
        )
    return _numerical_equivalence_record(
        evidence_type=EvidenceType.SOURCE_STATE_EQUIVALENCE,
        semantic_scope=SemanticScope.POINTWISE_STATE,
        context_scope=ContextScope.CHECKPOINT_FULL_STATE,
        source=source @ reference,
        target=target @ reference,
        source_semantic_id=source_semantic_id,
        target_semantic_id=target_semantic_id,
        tolerance=tolerance,
        method_id="v6-global-phase-state-validation-v1",
        extra_details={"reference_state_id": reference_state_id},
    )


def native_synthesis_evidence(
    *,
    source_semantic_id: str,
    target_semantic_id: str,
    native_synthesis_scope: NativeSynthesisScope,
    strength: EvidenceStrength,
    method_id: str,
    proof_input_digest: str,
    proof_output_digest: str,
    tolerance: float | None = None,
) -> EvidenceRecord:
    """Create native-synthesis evidence without scope promotion."""
    if (
        native_synthesis_scope is NativeSynthesisScope.FAMILYWISE
        and strength
        not in {
            EvidenceStrength.ALGEBRAICALLY_PROVEN,
            EvidenceStrength.SYMBOLICALLY_PROVEN,
        }
    ):
        raise MathematicalEvidenceError(
            "familywise native synthesis requires algebraic or symbolic proof"
        )
    if strength is EvidenceStrength.NOT_ESTABLISHED:
        raise MathematicalEvidenceError(
            "established native synthesis cannot use NOT_ESTABLISHED strength"
        )
    numerical = strength is EvidenceStrength.NUMERICALLY_VALIDATED
    if numerical:
        if tolerance is None or not math.isfinite(tolerance) or tolerance <= 0:
            raise MathematicalEvidenceError(
                "numerical native synthesis requires an explicit tolerance"
            )
    elif tolerance is not None:
        raise MathematicalEvidenceError(
            "only numerical native synthesis may carry a tolerance"
        )
    return EvidenceRecord(
        evidence_type=EvidenceType.NATIVE_SYNTHESIS,
        status=EvidenceStatus.PASSED,
        strength=strength,
        semantic_scope=(
            SemanticScope.FAMILYWISE_UNITARY
            if native_synthesis_scope is NativeSynthesisScope.FAMILYWISE
            else SemanticScope.POINTWISE_UNITARY
        ),
        context_scope=ContextScope.LOCAL_BLOCK,
        method_id=method_id,
        source_semantic_id=source_semantic_id,
        target_semantic_id=target_semantic_id,
        input_digest=proof_input_digest,
        output_digest=proof_output_digest,
        tolerance=tolerance,
        details={"native_synthesis_scope": native_synthesis_scope.value},
    )


def require_context_scope(
    evidence: EvidenceRecord,
    required: ContextScope,
) -> None:
    """Reject reuse outside the exact recorded context.

    Only evidence explicitly proven for arbitrary circuit context may be
    reused in a narrower context without an additional contextual proof.
    """
    if (
        evidence.context_scope is not required
        and evidence.context_scope is not ContextScope.ARBITRARY_CIRCUIT_CONTEXT
    ):
        raise EvidenceError(
            f"{evidence.context_scope.value} evidence does not establish "
            f"{required.value} behavior"
        )

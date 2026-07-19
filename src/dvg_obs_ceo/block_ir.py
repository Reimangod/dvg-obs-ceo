"""Recover actual DVG-CEO circuit blocks and enumerate semantic candidates."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import itertools
import math
import struct
from typing import Any, Callable, Iterable, Mapping, Sequence

import numpy as np
from numpy.typing import NDArray
from scipy.linalg import expm

from .identity import canonical_json_bytes
from .quadratic import ConstraintTargetIR


FloatArray = NDArray[np.float64]
ComplexArray = NDArray[np.complex128]
BLOCK_IR_VERSION = "dvg-block-ir-v1"
CANDIDATE_CATALOG_VERSION = "dvg-candidate-catalog-v1"


class BlockIRError(ValueError):
    """Raised when upstream ansatz semantics cannot be recovered unambiguously."""


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _float_hex(value: float) -> str:
    number = float(value)
    if not math.isfinite(number):
        raise BlockIRError("generator coefficients must be finite")
    if number == 0.0:
        number = 0.0
    return struct.pack(">d", number).hex()


def canonical_operator_payload(operator: Any) -> list[dict[str, Any]]:
    """Serialize an OpenFermion-like ``.terms`` mapping without importing it."""
    if not hasattr(operator, "terms"):
        raise BlockIRError("pool operator has no canonical terms mapping")
    terms: list[dict[str, Any]] = []
    for pauli_term, coefficient in operator.terms.items():
        key = [[int(qubit), str(pauli)] for qubit, pauli in pauli_term]
        number = complex(coefficient)
        terms.append(
            {
                "pauli": key,
                "real_float64_hex": _float_hex(number.real),
                "imag_float64_hex": _float_hex(number.imag),
            }
        )
    return sorted(terms, key=lambda item: canonical_json_bytes(item["pauli"]))


def operator_digest(operator: Any) -> str:
    return _digest(canonical_operator_payload(operator))


def _support(pool: Any, index: int) -> tuple[int, ...]:
    return tuple(sorted(int(qubit) for qubit in pool.get_qubits(index)))


def _operator_symmetry(operator: Any) -> tuple[str, ...]:
    sources = operator.source_orbs
    targets = operator.target_orbs
    if sources is None or targets is None:
        raise BlockIRError("source and target orbitals are required for symmetry checks")
    if sources and isinstance(sources[0], (list, tuple)):
        pairs = zip(sources, targets)
    else:
        pairs = ((sources, targets),)
    labels: set[str] = set()
    for source, target in pairs:
        delta_particles = len(target) - len(source)
        delta_alpha = sum(index % 2 == 0 for index in target) - sum(
            index % 2 == 0 for index in source
        )
        delta_beta = sum(index % 2 == 1 for index in target) - sum(
            index % 2 == 1 for index in source
        )
        labels.add(
            f"delta_particles={delta_particles};delta_alpha={delta_alpha};delta_beta={delta_beta}"
        )
    if labels != {"delta_particles=0;delta_alpha=0;delta_beta=0"}:
        raise BlockIRError(f"candidate violates registered particle/spin symmetry: {sorted(labels)}")
    return tuple(sorted(labels))


@dataclass(frozen=True)
class DVGBlock:
    block_id: str
    family: str
    ansatz_positions: tuple[int, ...]
    pool_indices: tuple[int, ...]
    coefficients: tuple[float, ...]
    selection_iterations: tuple[int, ...]
    tetris_layer_positions: tuple[int, ...]
    constituent_qe_ids: tuple[str, ...]
    generator_digests: tuple[str, ...]
    support_qubits: tuple[int, ...]
    normalization: str
    orientation: str
    circuit_implementation_id: str
    symmetry_quantum_numbers: tuple[str, ...]
    numerical_context_digest: str


@dataclass(frozen=True)
class CompressionCandidate:
    candidate_id: str
    equivalence_class_id: str
    kind: str
    source_block_id: str
    source_pool_indices: tuple[int, ...]
    target_family: str
    target_pool_indices: tuple[int, ...]
    removed_source_slots: tuple[int, ...]
    transformation: ConstraintTargetIR
    target_operator_digests: tuple[str, ...]
    semantic_conflict_positions: tuple[int, ...]
    numerical_context_digest: str


def _iteration_assignment(
    parameter_count: int,
    cumulative_parameter_counts: Sequence[int],
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    counts = tuple(int(value) for value in cumulative_parameter_counts)
    if not counts or counts[-1] != parameter_count:
        raise BlockIRError("iteration parameter counts must terminate at ansatz length")
    if counts[0] < 0 or any(right < left for left, right in zip(counts, counts[1:])):
        raise BlockIRError("iteration parameter counts must be non-decreasing")
    iterations: list[int] = []
    layers: list[int] = []
    start = 0
    for iteration, stop in enumerate(counts, 1):
        for position in range(start, stop):
            iterations.append(iteration)
            layers.append(position - start)
        start = stop
    return tuple(iterations), tuple(layers)


def recover_dvg_blocks(
    pool: Any,
    ansatz_indices: Sequence[int],
    coefficients: Sequence[float],
    cumulative_parameter_counts: Sequence[int],
) -> tuple[DVGBlock, ...]:
    if len(ansatz_indices) != len(coefficients):
        raise BlockIRError("ansatz indices and coefficients have different lengths")
    if any(not math.isfinite(float(value)) for value in coefficients):
        raise BlockIRError("ansatz coefficients must be finite")
    iterations, layers = _iteration_assignment(len(ansatz_indices), cumulative_parameter_counts)
    parent_range = set(int(index) for index in pool.parent_range)
    groups: list[tuple[int, ...]] = []
    position = 0
    while position < len(ansatz_indices):
        index = int(ansatz_indices[position])
        if index not in parent_range:
            groups.append((position,))
            position += 1
            continue
        support = _support(pool, index)
        stop = position + 1
        while (
            stop < len(ansatz_indices)
            and int(ansatz_indices[stop]) in parent_range
            and _support(pool, int(ansatz_indices[stop])) == support
            and iterations[stop] == iterations[position]
        ):
            stop += 1
        groups.append(tuple(range(position, stop)))
        position = stop

    blocks: list[DVGBlock] = []
    for positions in groups:
        indices = tuple(int(ansatz_indices[item]) for item in positions)
        operators = tuple(pool.operators[index] for index in indices)
        supports = tuple(_support(pool, index) for index in indices)
        if len(set(supports)) != 1:
            raise BlockIRError("one recovered circuit block has inconsistent support")
        in_parent = tuple(index in parent_range for index in indices)
        if all(in_parent):
            family = "MVP" if len(indices) > 1 else "single-QE"
            orientation = "independent-qe-parameters"
        elif not any(in_parent) and len(indices) == 1:
            ceo_type = operators[0].ceo_type
            if ceo_type in {"sum", "diff"}:
                family = "OVP"
                orientation = str(ceo_type)
            elif ceo_type is None:
                family = "single-QE"
                orientation = "canonical-qe"
            else:
                raise BlockIRError(f"unknown CEO orientation: {ceo_type}")
        else:
            raise BlockIRError("parent and non-parent indices were mixed in one block")
        digests = tuple(operator_digest(pool.get_q_op(index)) for index in indices)
        if family == "OVP":
            parent_indices = tuple(int(index) for index in (operators[0].parents or ()))
            if not parent_indices:
                raise BlockIRError("OVP block lacks parent-QE provenance")
            parent_operators = tuple(pool.get_q_op(index) for index in parent_indices)
            parent_weights = _relation_weights(parent_operators, pool.get_q_op(indices[0]))
            constituent_digests = tuple(
                operator_digest(pool.get_q_op(index))
                for index, weight in zip(parent_indices, parent_weights)
                if weight != 0.0
            )
            if not constituent_digests:
                raise BlockIRError("OVP block has no resolved constituent QE")
        else:
            constituent_digests = digests
        symmetry = tuple(sorted(set(itertools.chain.from_iterable(_operator_symmetry(op) for op in operators))))
        structure = {
            "version": BLOCK_IR_VERSION,
            "family": family,
            "ansatz_positions": list(positions),
            "pool_indices": list(indices),
            "generator_digests": list(digests),
            "support_qubits": list(supports[0]),
            "orientation": orientation,
        }
        coefficient_tuple = tuple(float(coefficients[item]) for item in positions)
        numerical = _digest(
            {
                "structure": structure,
                "coefficient_float64_hex": [_float_hex(value) for value in coefficient_tuple],
            }
        )
        implementation = {
            "OVP": "paper-era-ovp-ceo-circuit-v1",
            "MVP": "paper-era-mvp-ceo-circuit-v1",
            "single-QE": "paper-era-qe-circuit-v1",
        }[family]
        blocks.append(
            DVGBlock(
                block_id="block-v1:" + _digest(structure),
                family=family,
                ansatz_positions=positions,
                pool_indices=indices,
                coefficients=coefficient_tuple,
                selection_iterations=tuple(iterations[item] for item in positions),
                tetris_layer_positions=tuple(layers[item] for item in positions),
                constituent_qe_ids=tuple(f"qe:{digest}" for digest in constituent_digests),
                generator_digests=digests,
                support_qubits=supports[0],
                normalization="paper-era-pool-arrange-v1",
                orientation=orientation,
                circuit_implementation_id=implementation,
                symmetry_quantum_numbers=symmetry,
                numerical_context_digest=numerical,
            )
        )
    return tuple(blocks)


def _operator_vector(operator: Any, basis: tuple[Any, ...]) -> ComplexArray:
    terms: Mapping[Any, complex] = operator.terms
    return np.asarray([complex(terms.get(term, 0.0)) for term in basis], dtype=np.complex128)


def _relation_weights(
    source_operators: Sequence[Any],
    target_operator: Any,
    tolerance: float = 1e-10,
) -> FloatArray:
    term_basis = tuple(
        sorted(
            set(itertools.chain.from_iterable(operator.terms.keys() for operator in (*source_operators, target_operator))),
            key=repr,
        )
    )
    source = np.column_stack([_operator_vector(operator, term_basis) for operator in source_operators])
    target = _operator_vector(target_operator, term_basis)
    real_system = np.vstack((source.real, source.imag))
    real_target = np.concatenate((target.real, target.imag))
    weights, _, rank, _ = np.linalg.lstsq(real_system, real_target, rcond=None)
    residual = np.linalg.norm(real_system @ weights - real_target)
    scale = max(np.linalg.norm(real_target), np.finfo(np.float64).tiny)
    condition = float(np.linalg.cond(real_system))
    if (
        rank != len(source_operators)
        or not math.isfinite(condition)
        or condition > 1e12
        or residual / scale > tolerance
    ):
        raise BlockIRError("target generator is outside the source generator span")
    weights[np.abs(weights) < tolerance] = 0.0
    return np.asarray(weights, dtype=np.float64)


def _constraint_for_jacobian(jacobian: FloatArray) -> FloatArray:
    source_dimension, target_dimension = jacobian.shape
    if target_dimension == 0:
        return np.eye(source_dimension, dtype=np.float64)
    if target_dimension > 1:
        nonzero_rows: list[int] = []
        for column in range(target_dimension):
            rows = np.flatnonzero(np.abs(jacobian[:, column]) > 1e-12)
            if len(rows) != 1 or jacobian[rows[0], column] != 1.0:
                raise BlockIRError(
                    "multi-target Jacobian must be a canonical ordered source subset"
                )
            nonzero_rows.append(int(rows[0]))
        if len(nonzero_rows) != len(set(nonzero_rows)):
            raise BlockIRError("multi-target Jacobian maps two targets to one source slot")
        removed = [index for index in range(source_dimension) if index not in nonzero_rows]
        return np.eye(source_dimension, dtype=np.float64)[removed]
    weights = jacobian[:, 0]
    pivot = int(np.argmax(np.abs(weights)))
    if weights[pivot] == 0.0:
        raise BlockIRError("target Jacobian has no nonzero pivot")
    rows = []
    for index in range(source_dimension):
        if index == pivot:
            continue
        row = np.zeros(source_dimension, dtype=np.float64)
        row[index] = 1.0
        row[pivot] = -weights[index] / weights[pivot]
        rows.append(row)
    return np.asarray(rows, dtype=np.float64)


def _candidate(
    block: DVGBlock,
    kind: str,
    jacobian: FloatArray,
    target_family: str,
    target_pool_indices: tuple[int, ...],
    target_digests: tuple[str, ...],
    removed_slots: tuple[int, ...],
    orientation: str,
) -> CompressionCandidate:
    source_dimension, target_dimension = jacobian.shape
    constraint = _constraint_for_jacobian(jacobian)
    transform = ConstraintTargetIR.create(
        constraint_matrix=constraint,
        constraint_rhs=np.zeros(constraint.shape[0]),
        offset=np.zeros(source_dimension),
        jacobian=jacobian,
        source_slots=tuple(f"{block.block_id}:slot:{index}" for index in range(source_dimension)),
        target_slots=tuple(f"target:{index}" for index in range(target_dimension)),
        generator_normalization=block.normalization,
        orientation=orientation,
    )
    structural = {
        "version": CANDIDATE_CATALOG_VERSION,
        "source_block_id": block.block_id,
        "jacobian": [[_float_hex(value) for value in row] for row in jacobian],
        "target_family": target_family,
        "target_pool_indices": list(target_pool_indices),
        "target_operator_digests": list(target_digests),
    }
    equivalence = "transform-v1:" + _digest(structural)
    return CompressionCandidate(
        candidate_id="candidate-v1:" + _digest({**structural, "kind": kind}),
        equivalence_class_id=equivalence,
        kind=kind,
        source_block_id=block.block_id,
        source_pool_indices=block.pool_indices,
        target_family=target_family,
        target_pool_indices=target_pool_indices,
        removed_source_slots=removed_slots,
        transformation=transform,
        target_operator_digests=target_digests,
        semantic_conflict_positions=block.ansatz_positions,
        numerical_context_digest=block.numerical_context_digest,
    )


def enumerate_candidates(pool: Any, blocks: Sequence[DVGBlock]) -> tuple[CompressionCandidate, ...]:
    result: list[CompressionCandidate] = []
    parent_range = set(int(index) for index in pool.parent_range)
    for block in blocks:
        dimension = len(block.pool_indices)
        empty = np.zeros((dimension, 0), dtype=np.float64)
        deletion_kind = "mvp-whole-deletion" if block.family == "MVP" else "block-deletion"
        result.append(_candidate(block, deletion_kind, empty, "empty", (), (), tuple(range(dimension)), "deletion"))
        if block.family != "MVP":
            continue
        source_operators = tuple(pool.get_q_op(index) for index in block.pool_indices)
        for removed in range(dimension):
            kept = tuple(index for index in range(dimension) if index != removed)
            jacobian = np.zeros((dimension, len(kept)), dtype=np.float64)
            for target_slot, source_slot in enumerate(kept):
                jacobian[source_slot, target_slot] = 1.0
            target_indices = tuple(block.pool_indices[index] for index in kept)
            target_digests = tuple(block.generator_digests[index] for index in kept)
            family = "single-QE" if len(kept) == 1 else "MVP"
            result.append(
                _candidate(
                    block,
                    "mvp-constituent-deletion",
                    jacobian,
                    family,
                    target_indices,
                    target_digests,
                    (removed,),
                    "ordered-subset",
                )
            )
        for kept in range(dimension):
            jacobian = np.zeros((dimension, 1), dtype=np.float64)
            jacobian[kept, 0] = 1.0
            result.append(
                _candidate(
                    block,
                    "mvp-to-single-qe",
                    jacobian,
                    "single-QE",
                    (block.pool_indices[kept],),
                    (block.generator_digests[kept],),
                    tuple(index for index in range(dimension) if index != kept),
                    "canonical-qe",
                )
            )
        for target_index, target in enumerate(pool.operators):
            if target_index in parent_range or target.ceo_type not in {"sum", "diff"}:
                continue
            if _support(pool, target_index) != block.support_qubits:
                continue
            _operator_symmetry(target)
            try:
                weights = _relation_weights(source_operators, pool.get_q_op(target_index))
            except BlockIRError:
                continue
            jacobian = weights.reshape(dimension, 1)
            result.append(
                _candidate(
                    block,
                    f"mvp-to-ovp-{target.ceo_type}",
                    jacobian,
                    "OVP",
                    (target_index,),
                    (operator_digest(pool.get_q_op(target_index)),),
                    tuple(index for index, value in enumerate(weights) if value == 0.0),
                    str(target.ceo_type),
                )
            )
    identifiers = [candidate.candidate_id for candidate in result]
    if len(identifiers) != len(set(identifiers)):
        raise BlockIRError("candidate IDs are not unique")
    return tuple(result)


def validate_candidate_semantics(
    candidate: CompressionCandidate,
    source_generator_matrices: Sequence[ComplexArray],
    target_generator_matrices: Sequence[ComplexArray],
    *,
    samples: int = 5,
    seed: int = 0,
    tolerance: float = 1e-10,
) -> None:
    source = tuple(np.asarray(value, dtype=np.complex128) for value in source_generator_matrices)
    target = tuple(np.asarray(value, dtype=np.complex128) for value in target_generator_matrices)
    jacobian = candidate.transformation.jacobian
    if len(source) != jacobian.shape[0] or len(target) != jacobian.shape[1]:
        raise BlockIRError("generator matrices do not match candidate slot dimensions")
    if not source:
        raise BlockIRError("candidate requires at least one source generator")
    dimension = source[0].shape[0]
    if any(matrix.shape != (dimension, dimension) for matrix in (*source, *target)):
        raise BlockIRError("generator matrices must be equally sized and square")
    for matrix in (*source, *target):
        if np.linalg.norm(matrix + matrix.conj().T) > tolerance:
            raise BlockIRError("generator is not anti-Hermitian")
    for left, right in itertools.combinations(source, 2):
        if np.linalg.norm(left @ right - right @ left) > tolerance:
            raise BlockIRError("source block generators do not commute exactly enough")
    for target_slot, target_matrix in enumerate(target):
        reconstructed = sum(
            (jacobian[source_slot, target_slot] * source[source_slot] for source_slot in range(len(source))),
            np.zeros_like(source[0]),
        )
        if np.linalg.norm(reconstructed - target_matrix) > tolerance:
            raise BlockIRError("source-to-target generator identity failed")
    rng = np.random.default_rng(seed)
    for _ in range(samples):
        coordinates = rng.uniform(-0.7, 0.7, size=len(target))
        source_parameters = jacobian @ coordinates
        source_unitary = np.eye(dimension, dtype=np.complex128)
        for parameter, generator in zip(source_parameters, source):
            source_unitary = expm(parameter * generator) @ source_unitary
        target_unitary = np.eye(dimension, dtype=np.complex128)
        for parameter, generator in zip(coordinates, target):
            target_unitary = expm(parameter * generator) @ target_unitary
        if np.linalg.norm(source_unitary - target_unitary) > tolerance:
            raise BlockIRError("source and target unitaries differ")
        state = rng.normal(size=dimension) + 1j * rng.normal(size=dimension)
        state /= np.linalg.norm(state)
        if np.linalg.norm(source_unitary @ state - target_unitary @ state) > tolerance:
            raise BlockIRError("source and target random-state outputs differ")


def validate_target_circuit_semantics(
    target_generator_matrices: Sequence[ComplexArray],
    circuit_unitary_factory: Callable[[FloatArray], ComplexArray],
    *,
    samples: int = 5,
    seed: int = 0,
    tolerance: float = 1e-10,
) -> tuple[complex, ...]:
    """Compare a native target circuit with its generators up to global phase."""
    target = tuple(np.asarray(value, dtype=np.complex128) for value in target_generator_matrices)
    if not target:
        raise BlockIRError("circuit validation requires at least one target generator")
    dimension = target[0].shape[0]
    if any(matrix.shape != (dimension, dimension) for matrix in target):
        raise BlockIRError("target generators must be equally sized and square")
    rng = np.random.default_rng(seed)
    phases: list[complex] = []
    for _ in range(samples):
        coordinates = rng.uniform(-0.7, 0.7, size=len(target))
        expected = np.eye(dimension, dtype=np.complex128)
        for parameter, generator in zip(coordinates, target):
            expected = expm(parameter * generator) @ expected
        observed = np.asarray(circuit_unitary_factory(coordinates), dtype=np.complex128)
        if observed.shape != expected.shape:
            raise BlockIRError("target circuit has the wrong unitary dimension")
        overlap = np.vdot(expected.ravel(), observed.ravel())
        if abs(overlap) <= np.finfo(np.float64).tiny:
            raise BlockIRError("target circuit has no resolvable global phase alignment")
        phase = overlap / abs(overlap)
        if np.linalg.norm(observed - phase * expected) > tolerance:
            raise BlockIRError("native target circuit disagrees with target generator unitary")
        state = rng.normal(size=dimension) + 1j * rng.normal(size=dimension)
        state /= np.linalg.norm(state)
        if np.linalg.norm(observed @ state - phase * expected @ state) > tolerance:
            raise BlockIRError("native target circuit random-state output disagrees")
        phases.append(complex(phase))
    return tuple(phases)


def block_to_dict(block: DVGBlock) -> dict[str, Any]:
    return {
        "block_id": block.block_id,
        "family": block.family,
        "ansatz_positions": list(block.ansatz_positions),
        "pool_indices": list(block.pool_indices),
        "coefficients": list(block.coefficients),
        "selection_iterations": list(block.selection_iterations),
        "tetris_layer_positions": list(block.tetris_layer_positions),
        "constituent_qe_ids": list(block.constituent_qe_ids),
        "generator_digests": list(block.generator_digests),
        "support_qubits": list(block.support_qubits),
        "normalization": block.normalization,
        "orientation": block.orientation,
        "circuit_implementation_id": block.circuit_implementation_id,
        "symmetry_quantum_numbers": list(block.symmetry_quantum_numbers),
        "numerical_context_digest": block.numerical_context_digest,
    }


def candidate_to_dict(candidate: CompressionCandidate) -> dict[str, Any]:
    transformation = candidate.transformation
    return {
        "candidate_id": candidate.candidate_id,
        "equivalence_class_id": candidate.equivalence_class_id,
        "kind": candidate.kind,
        "source_block_id": candidate.source_block_id,
        "source_pool_indices": list(candidate.source_pool_indices),
        "target_family": candidate.target_family,
        "target_pool_indices": list(candidate.target_pool_indices),
        "removed_source_slots": list(candidate.removed_source_slots),
        "constraint_matrix": transformation.constraint_matrix.tolist(),
        "constraint_rhs": transformation.constraint_rhs.tolist(),
        "offset": transformation.offset.tolist(),
        "jacobian": transformation.jacobian.tolist(),
        "source_slots": list(transformation.source_slots),
        "target_slots": list(transformation.target_slots),
        "generator_normalization": transformation.generator_normalization,
        "orientation": transformation.orientation,
        "units": transformation.units,
        "target_operator_digests": list(candidate.target_operator_digests),
        "semantic_conflict_positions": list(candidate.semantic_conflict_positions),
        "numerical_context_digest": candidate.numerical_context_digest,
    }

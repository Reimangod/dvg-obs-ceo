"""Full-ansatz paper-era resource reconstruction without global compilation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import math
from typing import Any, Callable, Sequence

from .block_ir import (
    CompressionCandidate,
    DVGBlock,
    recover_dvg_blocks,
)
from .identity import canonical_json_bytes
from .telemetry import ResourceSnapshot


RESOURCE_EVALUATOR_VERSION = "paper-era-full-circuit-resource-v1"


class ResourceEvaluationError(RuntimeError):
    """Raised when a transformed ansatz cannot be recounted exactly."""


@dataclass(frozen=True)
class AnsatzStructure:
    indices: tuple[int, ...]
    coefficients: tuple[float, ...]
    cumulative_parameter_counts: tuple[int, ...]

    @classmethod
    def create(
        cls,
        indices: Sequence[int],
        coefficients: Sequence[float],
        cumulative_parameter_counts: Sequence[int],
    ) -> "AnsatzStructure":
        result = cls(
            tuple(int(value) for value in indices),
            tuple(float(value) for value in coefficients),
            tuple(int(value) for value in cumulative_parameter_counts),
        )
        result.validate()
        return result

    def validate(self) -> None:
        if len(self.indices) != len(self.coefficients):
            raise ResourceEvaluationError("indices and coefficients differ in length")
        if any(index < 0 for index in self.indices):
            raise ResourceEvaluationError("pool indices must be non-negative")
        if any(not math.isfinite(value) for value in self.coefficients):
            raise ResourceEvaluationError("coefficients must be finite")
        counts = self.cumulative_parameter_counts
        if not counts or counts[-1] != len(self.indices):
            raise ResourceEvaluationError("iteration counts must end at ansatz size")
        if counts[0] < 0 or any(right < left for left, right in zip(counts, counts[1:])):
            raise ResourceEvaluationError("iteration counts must be non-decreasing")


@dataclass(frozen=True)
class ResourceBackend:
    version: str
    empty_circuit_factory: Callable[[int], Any]
    get_qasm: Callable[[Any], str]
    cnot_count: Callable[[str], int]
    cnot_depth: Callable[[str, int], int]


@dataclass(frozen=True)
class SegmentResource:
    adapt_iteration: int
    parameter_count: int
    cumulative_cnot_count: int
    cumulative_cnot_depth: int
    cumulative_total_depth: int


@dataclass(frozen=True)
class FullCircuitResources:
    evaluator_version: str
    coefficient_policy: str
    snapshot: ResourceSnapshot
    circuit_qasm_digest: str
    segments: tuple[SegmentResource, ...]
    cnot_count_by_iteration: tuple[int, ...]
    cnot_depth_by_iteration: tuple[int, ...]
    total_depth_by_iteration: tuple[int, ...]


def paper_era_backend() -> ResourceBackend:
    try:
        from qiskit import QuantumCircuit
        from adaptvqe.circuits import cnot_count, cnot_depth
        from adaptvqe.op_conv import get_qasm
    except ImportError as error:
        raise ResourceEvaluationError("paper-era baseline dependencies are unavailable") from error
    return ResourceBackend(
        "paper-era-qasm-counter-a3f89d0",
        QuantumCircuit,
        get_qasm,
        cnot_count,
        cnot_depth,
    )


def _segments(structure: AnsatzStructure) -> tuple[tuple[tuple[int, ...], tuple[float, ...]], ...]:
    result = []
    start = 0
    for stop in structure.cumulative_parameter_counts:
        result.append((structure.indices[start:stop], structure.coefficients[start:stop]))
        start = stop
    return tuple(result)


def _structural_coefficients(length: int, offset: int) -> tuple[float, ...]:
    return tuple(0.2718281828459045 + 0.137035999084 * (offset + index + 1) for index in range(length))


def evaluate_full_circuit_resources(
    pool: Any,
    structure: AnsatzStructure,
    backend: ResourceBackend,
    *,
    coefficient_policy: str = "physical",
) -> FullCircuitResources:
    structure.validate()
    if coefficient_policy not in {"physical", "deterministic-structural"}:
        raise ResourceEvaluationError("unknown resource coefficient policy")
    full_circuit = backend.empty_circuit_factory(pool.n)
    accumulated_count = 0
    offset = 0
    segment_results: list[SegmentResource] = []
    qasm_segments: list[str] = []
    total_depths = [0]
    cnot_depths = [0]
    cnot_counts = [0]
    for iteration, (indices, physical_coefficients) in enumerate(_segments(structure), 1):
        coefficients = (
            physical_coefficients
            if coefficient_policy == "physical"
            else _structural_coefficients(len(indices), offset)
        )
        try:
            segment_circuit = pool.get_circuit(list(indices), list(coefficients))
            segment_qasm = backend.get_qasm(segment_circuit)
            full_circuit = full_circuit.compose(segment_circuit)
            full_qasm = backend.get_qasm(full_circuit)
        except Exception as error:
            raise ResourceEvaluationError(
                f"paper-era circuit reconstruction failed at ADAPT iteration {iteration}: {error}"
            ) from error
        accumulated_count += int(backend.cnot_count(segment_qasm))
        cnot_depth_value = int(backend.cnot_depth(full_qasm, pool.n))
        total_depth_value = int(full_circuit.depth())
        qasm_segments.append(segment_qasm)
        cnot_counts.append(accumulated_count)
        cnot_depths.append(cnot_depth_value)
        total_depths.append(total_depth_value)
        segment_results.append(
            SegmentResource(
                iteration,
                len(indices),
                accumulated_count,
                cnot_depth_value,
                total_depth_value,
            )
        )
        offset += len(indices)
    blocks = recover_dvg_blocks(
        pool,
        structure.indices,
        structure.coefficients,
        structure.cumulative_parameter_counts,
    )
    structural_payload = {
        "evaluator_version": RESOURCE_EVALUATOR_VERSION,
        "backend_version": backend.version,
        "indices": list(structure.indices),
        "iteration_counts": list(structure.cumulative_parameter_counts),
        "block_ids": [block.block_id for block in blocks],
        "circuit_implementation_ids": [block.circuit_implementation_id for block in blocks],
    }
    structure_digest = hashlib.sha256(canonical_json_bytes(structural_payload)).hexdigest()
    full_qasm = backend.get_qasm(full_circuit)
    qasm_digest = hashlib.sha256(full_qasm.encode("utf-8")).hexdigest()
    snapshot = ResourceSnapshot(
        accumulated_count,
        cnot_depths[-1],
        total_depths[-1],
        len(structure.indices),
        len(blocks),
        f"{RESOURCE_EVALUATOR_VERSION}:{backend.version}",
        structure_digest,
    )
    return FullCircuitResources(
        RESOURCE_EVALUATOR_VERSION,
        coefficient_policy,
        snapshot,
        qasm_digest,
        tuple(segment_results),
        tuple(cnot_counts),
        tuple(cnot_depths),
        tuple(total_depths),
    )


def apply_candidate_structure(
    pool: Any,
    source: AnsatzStructure,
    candidate: CompressionCandidate,
    target_coordinates: Sequence[float],
) -> AnsatzStructure:
    source.validate()
    blocks = recover_dvg_blocks(
        pool,
        source.indices,
        source.coefficients,
        source.cumulative_parameter_counts,
    )
    matches = [block for block in blocks if block.block_id == candidate.source_block_id]
    if len(matches) != 1:
        raise ResourceEvaluationError("candidate source block is absent or ambiguous")
    block = matches[0]
    if block.numerical_context_digest != candidate.numerical_context_digest:
        raise ResourceEvaluationError("candidate numerical context is stale")
    if block.pool_indices != candidate.source_pool_indices:
        raise ResourceEvaluationError("candidate source indices differ from recovered block")
    target = tuple(float(value) for value in target_coordinates)
    if len(target) != candidate.transformation.jacobian.shape[1]:
        raise ResourceEvaluationError("target coordinate dimension differs from candidate Jacobian")
    if len(target) != len(candidate.target_pool_indices) or any(not math.isfinite(value) for value in target):
        raise ResourceEvaluationError("native target indices and coordinates are incompatible")
    positions = block.ansatz_positions
    if positions != tuple(range(positions[0], positions[-1] + 1)):
        raise ResourceEvaluationError("candidate source block is not contiguous")
    if len(set(block.selection_iterations)) != 1:
        raise ResourceEvaluationError("candidate source block crosses an iteration boundary")
    first = positions[0]
    source_positions = set(positions)
    new_indices: list[int] = []
    new_coefficients: list[float] = []
    for position, (index, coefficient) in enumerate(zip(source.indices, source.coefficients)):
        if position == first:
            new_indices.extend(candidate.target_pool_indices)
            new_coefficients.extend(target)
        if position in source_positions:
            continue
        new_indices.append(index)
        new_coefficients.append(coefficient)
    source_iteration = block.selection_iterations[0]
    delta = len(target) - len(positions)
    new_counts = tuple(
        count if iteration < source_iteration else count + delta
        for iteration, count in enumerate(source.cumulative_parameter_counts, 1)
    )
    return AnsatzStructure.create(new_indices, new_coefficients, new_counts)


def resources_to_dict(resources: FullCircuitResources) -> dict[str, Any]:
    return {
        "evaluator_version": resources.evaluator_version,
        "coefficient_policy": resources.coefficient_policy,
        "snapshot": asdict(resources.snapshot),
        "circuit_qasm_digest": resources.circuit_qasm_digest,
        "segments": [asdict(segment) for segment in resources.segments],
        "cnot_count_by_iteration": list(resources.cnot_count_by_iteration),
        "cnot_depth_by_iteration": list(resources.cnot_depth_by_iteration),
        "total_depth_by_iteration": list(resources.total_depth_by_iteration),
    }

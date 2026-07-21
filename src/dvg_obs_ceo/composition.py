"""Global composition and compatibility validation for registered CEO rewrites."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Callable, Iterable, Mapping, Sequence

import numpy as np

from .block_ir import CompressionCandidate, DVGBlock
from .constraint_state import (
    CanonicalConstraintState,
    ConstraintStateError,
    ExactConstraintSystem,
    exact_atomic_constraint,
)
from .quadratic import ConstraintTargetIR
from .resources import AnsatzStructure


class GlobalCompatibilityError(RuntimeError):
    """Raised when a completed candidate batch is not globally valid."""


@dataclass(frozen=True)
class PairwiseCompatibility:
    compatible: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class JointConstraintPlan:
    state: CanonicalConstraintState
    transformation: ConstraintTargetIR
    candidate_ids: tuple[str, ...]
    equivalence_class_ids: tuple[str, ...]
    source_block_ids: tuple[str, ...]
    target_indices: tuple[int, ...]
    target_iteration_counts: tuple[int, ...]
    target_selection_iterations: tuple[int, ...]
    audit_provenance: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_ids": list(self.candidate_ids),
            "equivalence_class_ids": list(self.equivalence_class_ids),
            "source_block_ids": list(self.source_block_ids),
            "target_indices": list(self.target_indices),
            "target_iteration_counts": list(self.target_iteration_counts),
            "target_selection_iterations": list(self.target_selection_iterations),
            "state": self.state.to_dict(),
            "audit_provenance": list(self.audit_provenance),
        }


def pairwise_compatibility(
    left_candidate: CompressionCandidate,
    left_block: DVGBlock,
    right_candidate: CompressionCandidate,
    right_block: DVGBlock,
) -> PairwiseCompatibility:
    reasons: list[str] = []
    if left_candidate.source_block_id == right_candidate.source_block_id:
        reasons.append("mutually-exclusive-target-family")
    if set(left_candidate.semantic_conflict_positions) & set(
        right_candidate.semantic_conflict_positions
    ):
        reasons.append("overlapping-semantic-conflict-position")
    if set(left_block.ansatz_positions) & set(right_block.ansatz_positions):
        reasons.append("overlapping-source-block")
    if left_candidate.source_block_id != left_block.block_id:
        reasons.append("left-block-provenance-mismatch")
    if right_candidate.source_block_id != right_block.block_id:
        reasons.append("right-block-provenance-mismatch")
    return PairwiseCompatibility(not reasons, tuple(sorted(set(reasons))))


def combine_exact_systems(
    source_slots: Iterable[str],
    systems: Sequence[ExactConstraintSystem],
    *,
    require_independent: bool = True,
) -> ExactConstraintSystem:
    """Stack exact subsystem equations and compute one global exact RREF."""

    global_slots = tuple(str(slot) for slot in source_slots)
    if len(set(global_slots)) != len(global_slots):
        raise GlobalCompatibilityError("global source slots must be unique")
    rows: list[list[Fraction]] = []
    rhs: list[Fraction] = []
    requested_rank = 0
    for system in systems:
        if not set(system.source_slots).issubset(global_slots):
            raise GlobalCompatibilityError("exact subsystem uses an unknown source slot")
        local_rows, local_rhs = system.rational_matrix()
        for local_row, value in zip(local_rows, local_rhs):
            by_slot = dict(zip(system.source_slots, local_row))
            rows.append([by_slot.get(slot, Fraction(0)) for slot in global_slots])
            rhs.append(value)
        requested_rank += system.rank
    try:
        combined = ExactConstraintSystem.create(global_slots, rows, rhs)
    except ConstraintStateError as error:
        raise GlobalCompatibilityError("global exact constraints are infeasible") from error
    if require_independent and combined.rank != requested_rank:
        raise GlobalCompatibilityError("global exact constraints are rank redundant")
    return combined


def exact_matrix_in_source_order(
    system: ExactConstraintSystem,
    source_slots: Sequence[str],
) -> tuple[np.ndarray, np.ndarray]:
    """Materialize canonical exact rows in an explicitly requested slot order."""

    requested = tuple(str(slot) for slot in source_slots)
    if len(set(requested)) != len(requested) or set(requested) != set(system.source_slots):
        raise GlobalCompatibilityError("requested exact-matrix source order is incompatible")
    rows, rhs = system.rational_matrix()
    reordered = []
    for row in rows:
        by_slot = dict(zip(system.source_slots, row))
        reordered.append([float(by_slot[slot]) for slot in requested])
    return np.asarray(reordered, dtype=np.float64), np.asarray(
        [float(value) for value in rhs], dtype=np.float64
    )


def _selection_iterations(source: AnsatzStructure) -> tuple[int, ...]:
    result: list[int] = []
    start = 0
    for iteration, stop in enumerate(source.cumulative_parameter_counts, 1):
        result.extend([iteration] * (stop - start))
        start = stop
    if len(result) != len(source.indices):
        raise GlobalCompatibilityError("source iteration boundaries are invalid")
    return tuple(result)


def compose_registered_candidates(
    source: AnsatzStructure,
    blocks: Sequence[DVGBlock],
    candidates: Sequence[CompressionCandidate],
    *,
    circuit_validator: Callable[[Sequence[int]], None] | None = None,
) -> JointConstraintPlan:
    """Compose disjoint atomic rewrites into one ordered global target map."""

    if not candidates:
        raise GlobalCompatibilityError("joint composition requires at least one candidate")
    block_by_id = {block.block_id: block for block in blocks}
    if len(block_by_id) != len(blocks):
        raise GlobalCompatibilityError("source blocks are not uniquely identified")
    selected: list[tuple[DVGBlock, CompressionCandidate]] = []
    seen_equivalence: set[str] = set()
    for candidate in candidates:
        block = block_by_id.get(candidate.source_block_id)
        if block is None:
            raise GlobalCompatibilityError("candidate source block is absent")
        if candidate.equivalence_class_id in seen_equivalence:
            raise GlobalCompatibilityError("duplicate equivalence class in one joint batch")
        seen_equivalence.add(candidate.equivalence_class_id)
        selected.append((block, candidate))
    for index, (left_block, left) in enumerate(selected):
        for right_block, right in selected[index + 1 :]:
            screen = pairwise_compatibility(left, left_block, right, right_block)
            if not screen.compatible:
                raise GlobalCompatibilityError(
                    "pairwise compatibility failed: " + ",".join(screen.reasons)
                )
    selected.sort(key=lambda pair: pair[0].ansatz_positions)
    if any(
        not block.ansatz_positions
        or block.ansatz_positions != tuple(range(block.ansatz_positions[0], block.ansatz_positions[-1] + 1))
        for block, _ in selected
    ):
        raise GlobalCompatibilityError("selected block positions must be contiguous")
    position_to_pair = {
        position: (block, candidate)
        for block, candidate in selected
        for position in block.ansatz_positions
    }
    source_slots = tuple(f"ansatz-position:{index}" for index in range(len(source.indices)))
    source_iteration = _selection_iterations(source)
    exact_systems: list[ExactConstraintSystem] = []
    primitives: list[dict[str, Any]] = []
    provenance: list[dict[str, Any]] = []
    target_indices: list[int] = []
    target_slots: list[str] = []
    target_iterations: list[int] = []
    offset = np.zeros(len(source.indices), dtype=np.float64)
    columns: list[np.ndarray] = []
    consumed: set[int] = set()

    for position in range(len(source.indices)):
        if position in consumed:
            continue
        pair = position_to_pair.get(position)
        if pair is None:
            column = np.zeros(len(source.indices), dtype=np.float64)
            column[position] = 1.0
            columns.append(column)
            target_indices.append(source.indices[position])
            target_slots.append(source_slots[position])
            target_iterations.append(source_iteration[position])
            continue
        block, candidate = pair
        if position != block.ansatz_positions[0]:
            raise GlobalCompatibilityError("selected block traversal began inside a block")
        consumed.update(block.ansatz_positions)
        exact = exact_atomic_constraint(candidate)
        local_rows, local_rhs = exact.system.rational_matrix()
        local_slot_to_position = dict(zip(candidate.transformation.source_slots, block.ansatz_positions))
        global_rows: list[list[Fraction]] = []
        for row in local_rows:
            by_slot = dict(zip(exact.system.source_slots, row))
            global_row = [Fraction(0)] * len(source.indices)
            for slot, value in by_slot.items():
                global_row[local_slot_to_position[slot]] = value
            global_rows.append(global_row)
        exact_systems.append(ExactConstraintSystem.create(source_slots, global_rows, local_rhs))
        primitives.append(exact.primitive)
        provenance.append(exact.audit_provenance)
        local_jacobian = candidate.transformation.jacobian
        for local_target in range(local_jacobian.shape[1]):
            column = np.zeros(len(source.indices), dtype=np.float64)
            for local_source, source_position in enumerate(block.ansatz_positions):
                column[source_position] = local_jacobian[local_source, local_target]
            columns.append(column)
            target_index = candidate.target_pool_indices[local_target]
            target_indices.append(target_index)
            target_slots.append(
                f"{block.block_id}:target:{local_target}:pool:{target_index}"
            )
            if len(set(block.selection_iterations)) != 1:
                raise GlobalCompatibilityError("one source block spans multiple ADAPT iterations")
            target_iterations.append(block.selection_iterations[0])
    global_exact = combine_exact_systems(source_slots, exact_systems)
    jacobian = np.column_stack(columns) if columns else np.zeros((len(source.indices), 0))
    constraint_matrix, constraint_rhs = exact_matrix_in_source_order(
        global_exact, source_slots
    )
    transformation = ConstraintTargetIR.create(
        constraint_matrix=constraint_matrix,
        constraint_rhs=constraint_rhs,
        offset=offset,
        jacobian=jacobian,
        source_slots=source_slots,
        target_slots=target_slots,
        generator_normalization="composed-registered-ceo-v1",
        orientation="ordered-global-composition-v1",
    )
    state = CanonicalConstraintState.create(global_exact, transformation, primitives)
    if circuit_validator is not None:
        try:
            circuit_validator(tuple(target_indices))
        except Exception as error:
            raise GlobalCompatibilityError("actual target circuit construction failed") from error
    maximum_iteration = len(source.cumulative_parameter_counts)
    counts = tuple(
        sum(iteration <= current for iteration in target_iterations)
        for current in range(1, maximum_iteration + 1)
    )
    if not counts or counts[-1] != len(target_indices):
        raise GlobalCompatibilityError("target iteration boundaries do not terminate at target dimension")
    return JointConstraintPlan(
        state,
        transformation,
        tuple(candidate.candidate_id for _, candidate in selected),
        tuple(candidate.equivalence_class_id for _, candidate in selected),
        tuple(block.block_id for block, _ in selected),
        tuple(target_indices),
        counts,
        tuple(target_iterations),
        tuple(provenance),
    )

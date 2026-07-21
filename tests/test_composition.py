from dataclasses import replace

import numpy as np
import pytest

from dvg_obs_ceo.block_ir import CompressionCandidate, DVGBlock
from dvg_obs_ceo.composition import (
    GlobalCompatibilityError,
    combine_exact_systems,
    compose_registered_candidates,
    pairwise_compatibility,
    exact_matrix_in_source_order,
)
from dvg_obs_ceo.constraint_state import ExactConstraintSystem
from dvg_obs_ceo.quadratic import ConstraintTargetIR
from dvg_obs_ceo.resources import AnsatzStructure


def _block(name: str, positions, iteration=1) -> DVGBlock:
    size = len(positions)
    return DVGBlock(
        name, "single-QE", tuple(positions), tuple(10 + p for p in positions),
        tuple(0.1 for _ in positions), tuple(iteration for _ in positions),
        tuple(range(size)), tuple(f"qe:{p}" for p in positions),
        tuple(f"g:{p}" for p in positions), tuple(range(2 * size)),
        "paper-era-pool-arrange-v1", "canonical", "test-circuit-v1",
        ("delta_particles=0;delta_alpha=0;delta_beta=0",), "a" * 64,
    )


def _deletion(block: DVGBlock) -> CompressionCandidate:
    size = len(block.ansatz_positions)
    ir = ConstraintTargetIR.create(
        constraint_matrix=np.eye(size), constraint_rhs=np.zeros(size),
        offset=np.zeros(size), jacobian=np.zeros((size, 0)),
        source_slots=[f"{block.block_id}:slot:{i}" for i in range(size)],
        target_slots=[], generator_normalization=block.normalization,
        orientation="deletion",
    )
    return CompressionCandidate(
        "candidate:" + block.block_id, "equivalence:" + block.block_id,
        "block-deletion", block.block_id, block.pool_indices, "empty", (),
        tuple(range(size)), ir, (), block.ansatz_positions, "b" * 64,
    )


def test_disjoint_deletions_compose_in_original_ansatz_order() -> None:
    first = _block("block:a", (0,))
    second = _block("block:b", (2,), iteration=2)
    source = AnsatzStructure.create([10, 11, 12], [0.1, 0.2, 0.3], [2, 3])
    validated = []
    plan = compose_registered_candidates(
        source, [first, second], [_deletion(second), _deletion(first)],
        circuit_validator=lambda indices: validated.append(tuple(indices)),
    )
    assert plan.target_indices == (11,)
    assert plan.target_iteration_counts == (1, 1)
    assert validated == [(11,)]
    assert plan.transformation.jacobian.shape == (3, 1)
    np.testing.assert_array_equal(plan.transformation.jacobian[:, 0], [0.0, 1.0, 0.0])


def test_two_digit_source_slots_are_reordered_back_to_numeric_ansatz_order() -> None:
    block = _block("block:eleven", (11,))
    source = AnsatzStructure.create(
        list(range(12)), [0.1] * 12, [12]
    )
    plan = compose_registered_candidates(source, [block], [_deletion(block)])
    assert plan.transformation.constraint_matrix.shape == (1, 12)
    np.testing.assert_array_equal(
        plan.transformation.constraint_matrix[0], [0.0] * 11 + [1.0]
    )
    np.testing.assert_allclose(
        plan.transformation.constraint_matrix @ plan.transformation.jacobian,
        0.0,
        rtol=0.0,
        atol=0.0,
    )


def test_exact_matrix_order_helper_rejects_missing_or_duplicate_slots() -> None:
    slots = [f"ansatz-position:{index}" for index in range(12)]
    row = [0] * 12
    row[11] = 1
    system = ExactConstraintSystem.create(slots, [row], [0])
    matrix, _ = exact_matrix_in_source_order(system, slots)
    np.testing.assert_array_equal(matrix[0], row)
    with pytest.raises(GlobalCompatibilityError, match="source order"):
        exact_matrix_in_source_order(system, slots[:-1])


def test_same_block_candidates_fail_pairwise_and_global() -> None:
    block = _block("block:a", (0,))
    first = _deletion(block)
    second = replace(first, candidate_id="candidate:alternative", equivalence_class_id="eq:alternative")
    screen = pairwise_compatibility(first, block, second, block)
    assert not screen.compatible
    assert "mutually-exclusive-target-family" in screen.reasons
    with pytest.raises(GlobalCompatibilityError, match="pairwise"):
        compose_registered_candidates(
            AnsatzStructure.create([10], [0.1], [1]), [block], [first, second]
        )


def test_pairwise_feasible_exact_systems_can_fail_as_a_triple() -> None:
    x_zero = ExactConstraintSystem.create(["x", "y"], [[1, 0]], [0])
    y_zero = ExactConstraintSystem.create(["x", "y"], [[0, 1]], [0])
    sum_one = ExactConstraintSystem.create(["x", "y"], [[1, 1]], [1])
    systems = (x_zero, y_zero, sum_one)
    for left in range(3):
        for right in range(left + 1, 3):
            assert combine_exact_systems(["x", "y"], [systems[left], systems[right]]).rank == 2
    with pytest.raises(GlobalCompatibilityError, match="infeasible"):
        combine_exact_systems(["x", "y"], list(systems))


def test_redundant_global_constraints_fail_closed() -> None:
    first = ExactConstraintSystem.create(["x", "y"], [[1, -1]], [0])
    scaled = ExactConstraintSystem.create(["x", "y"], [[-2, 2]], [0])
    with pytest.raises(GlobalCompatibilityError, match="rank redundant"):
        combine_exact_systems(["x", "y"], [first, scaled])


def test_actual_circuit_construction_failure_blocks_plan() -> None:
    block = _block("block:a", (0,))
    with pytest.raises(GlobalCompatibilityError, match="circuit construction"):
        compose_registered_candidates(
            AnsatzStructure.create([10], [0.1], [1]), [block], [_deletion(block)],
            circuit_validator=lambda _indices: (_ for _ in ()).throw(RuntimeError("bad circuit")),
        )

from dataclasses import dataclass

import numpy as np
import pytest

from dvg_obs_ceo.block_ir import (
    BlockIRError,
    enumerate_candidates,
    recover_dvg_blocks,
    validate_candidate_semantics,
    validate_target_circuit_semantics,
)


class FakeQubitOperator:
    def __init__(self, terms):
        self.terms = terms


@dataclass
class FakeOperator:
    q_operator: FakeQubitOperator
    qubits: set[int]
    source_orbs: object
    target_orbs: object
    ceo_type: str | None = None
    parents: list[int] | None = None


class FakePool:
    def __init__(self):
        q0 = FakeQubitOperator({((0, "X"), (2, "Y")): 0.5j})
        q1 = FakeQubitOperator({((0, "Y"), (2, "X")): -0.5j})
        plus = FakeQubitOperator({**q0.terms, **q1.terms})
        minus = FakeQubitOperator({next(iter(q0.terms)): 0.5j, next(iter(q1.terms)): 0.5j})
        self.operators = [
            FakeOperator(q0, {0, 2}, [2], [0]),
            FakeOperator(q1, {0, 2}, [3], [1]),
            FakeOperator(plus, {0, 2}, [[2], [3]], [[0], [1]], "sum", [0, 1]),
            FakeOperator(minus, {0, 2}, [[2], [3]], [[0], [1]], "diff", [0, 1]),
        ]
        self.parent_range = range(0, 2)

    def get_qubits(self, index):
        return self.operators[index].qubits

    def get_q_op(self, index):
        return self.operators[index].q_operator


class FakeThreeParentPool(FakePool):
    def __init__(self):
        generators = [
            FakeQubitOperator({((0, pauli), (2, "Y")): coefficient})
            for pauli, coefficient in (("X", 0.5j), ("Y", -0.5j), ("Z", 0.25j))
        ]
        self.operators = [
            FakeOperator(generator, {0, 2}, [2 + index], [index])
            for index, generator in enumerate(generators)
        ]
        plus = FakeQubitOperator({**generators[0].terms, **generators[1].terms})
        diff = FakeQubitOperator(
            {
                **generators[0].terms,
                next(iter(generators[1].terms)): -next(iter(generators[1].terms.values())),
            }
        )
        self.operators.extend(
            [
                FakeOperator(plus, {0, 2}, [[2], [3]], [[0], [1]], "sum", [0, 1, 2]),
                FakeOperator(diff, {0, 2}, [[2], [3]], [[0], [1]], "diff", [0, 1, 2]),
            ]
        )
        self.parent_range = range(0, 3)


def test_recover_actual_grouping_and_iteration_metadata() -> None:
    pool = FakePool()
    blocks = recover_dvg_blocks(pool, [2, 0, 1, 3], [0.2, 0.3, -0.1, 0.4], [3, 4])
    assert [block.family for block in blocks] == ["OVP", "MVP", "OVP"]
    assert blocks[1].pool_indices == (0, 1)
    assert blocks[1].selection_iterations == (1, 1)
    assert blocks[2].selection_iterations == (2,)
    assert len(blocks[0].constituent_qe_ids) == 2
    assert len({block.block_id for block in blocks}) == 3


def test_parent_qes_are_never_grouped_across_paper_counter_iteration_boundary() -> None:
    pool = FakePool()
    blocks = recover_dvg_blocks(pool, [0, 1], [0.3, -0.1], [1, 2])
    assert [block.family for block in blocks] == ["single-QE", "single-QE"]
    assert [block.selection_iterations for block in blocks] == [(1,), (2,)]


def test_empty_iteration_segments_are_retained_without_inventing_blocks() -> None:
    pool = FakePool()
    blocks = recover_dvg_blocks(pool, [2], [0.3], [0, 1, 1])
    assert len(blocks) == 1
    assert blocks[0].selection_iterations == (2,)


def test_candidate_catalog_marks_equivalent_two_qe_transforms() -> None:
    pool = FakePool()
    block = recover_dvg_blocks(pool, [0, 1], [0.3, -0.1], [2])[0]
    candidates = enumerate_candidates(pool, [block])
    kinds = [candidate.kind for candidate in candidates]
    assert kinds.count("mvp-whole-deletion") == 1
    assert kinds.count("mvp-constituent-deletion") == 2
    assert kinds.count("mvp-to-single-qe") == 2
    assert kinds.count("mvp-to-ovp-sum") == 1
    assert kinds.count("mvp-to-ovp-diff") == 1
    assert len(candidates) == 7
    constituent = next(
        candidate for candidate in candidates
        if candidate.kind == "mvp-constituent-deletion" and candidate.target_pool_indices == (0,)
    )
    single = next(
        candidate for candidate in candidates
        if candidate.kind == "mvp-to-single-qe" and candidate.target_pool_indices == (0,)
    )
    assert constituent.equivalence_class_id == single.equivalence_class_id


def test_three_constituent_mvp_supports_multi_target_subset_jacobians() -> None:
    pool = FakeThreeParentPool()
    block = recover_dvg_blocks(pool, [0, 1, 2], [0.3, -0.1, 0.2], [3])[0]
    candidates = enumerate_candidates(pool, [block])
    constituent = [candidate for candidate in candidates if candidate.kind == "mvp-constituent-deletion"]
    assert len(constituent) == 3
    assert all(candidate.transformation.jacobian.shape == (3, 2) for candidate in constituent)
    assert all(candidate.transformation.constraint_matrix.shape == (1, 3) for candidate in constituent)
    ovp = [candidate for candidate in candidates if "mvp-to-ovp" in candidate.kind]
    assert {candidate.exact_generator_relation for candidate in ovp} == {
        (1, 1, 0),
        (1, -1, 0),
    }
    assert all(candidate.transformation.jacobian.shape == (3, 1) for candidate in ovp)


def test_registered_ovp_relation_follows_source_pool_permutation() -> None:
    pool = FakeThreeParentPool()
    block = recover_dvg_blocks(pool, [2, 0, 1], [0.2, 0.3, -0.1], [3])[0]
    candidates = enumerate_candidates(pool, [block])
    relations = {
        candidate.kind: candidate.exact_generator_relation
        for candidate in candidates
        if "mvp-to-ovp" in candidate.kind
    }
    assert relations == {
        "mvp-to-ovp-sum": (0, 1, 1),
        "mvp-to-ovp-diff": (0, 1, -1),
    }


def test_generator_unitary_and_random_state_validation() -> None:
    pool = FakePool()
    block = recover_dvg_blocks(pool, [0, 1], [0.3, -0.1], [2])[0]
    plus = next(candidate for candidate in enumerate_candidates(pool, [block]) if candidate.kind == "mvp-to-ovp-sum")
    source = [np.diag([1j, -1j]), np.diag([2j, -2j])]
    target = [source[0] + source[1]]
    validate_candidate_semantics(plus, source, target, samples=8, seed=17)
    with pytest.raises(BlockIRError, match="identity failed"):
        validate_candidate_semantics(plus, source, [source[0] - source[1]])


def test_invalid_iteration_boundaries_and_noncommuting_sources_fail_closed() -> None:
    pool = FakePool()
    with pytest.raises(BlockIRError, match="terminate"):
        recover_dvg_blocks(pool, [0, 1], [0.1, 0.2], [1])
    block = recover_dvg_blocks(pool, [0, 1], [0.1, 0.2], [2])[0]
    plus = next(candidate for candidate in enumerate_candidates(pool, [block]) if candidate.kind == "mvp-to-ovp-sum")
    x = np.array([[0, 1j], [1j, 0]], dtype=complex)
    z = np.array([[1j, 0], [0, -1j]], dtype=complex)
    with pytest.raises(BlockIRError, match="do not commute"):
        validate_candidate_semantics(plus, [x, z], [x + z])


def test_pinned_upstream_dvg_pool_semantics_when_baseline_extra_is_available() -> None:
    try:
        from dvg_obs_ceo.baseline import _load_upstream

        _, dvg_ceo, _, _ = _load_upstream()
        pool = dvg_ceo(n=4)
        from openfermion import get_sparse_operator
        from qiskit.quantum_info import Operator
    except (ImportError, ModuleNotFoundError):
        pytest.skip("baseline scientific dependencies are not installed")

    blocks = recover_dvg_blocks(pool, [4, 2, 3, 0], [0.2, 0.3, -0.1, 0.4], [3, 4])
    assert [block.family for block in blocks] == ["OVP", "MVP", "single-QE"]
    mvp = blocks[1]
    candidates = enumerate_candidates(pool, [mvp])
    for kind in ("mvp-to-ovp-sum", "mvp-to-ovp-diff"):
        candidate = next(value for value in candidates if value.kind == kind)
        sources = [get_sparse_operator(pool.get_q_op(index), n_qubits=4).toarray() for index in mvp.pool_indices]
        targets = [get_sparse_operator(pool.get_q_op(candidate.target_pool_indices[0]), n_qubits=4).toarray()]
        validate_candidate_semantics(candidate, sources, targets, samples=5, seed=11)
        target_index = candidate.target_pool_indices[0]
        phases = validate_target_circuit_semantics(
            targets,
            lambda coordinates, index=target_index: Operator(
                pool.get_circuit([index], [float(coordinates[0])])
            ).data,
            samples=5,
            seed=23,
        )
        assert all(abs(abs(phase) - 1.0) < 1e-12 for phase in phases)


def test_pinned_upstream_mvp_constrained_coefficients_require_native_rebuild() -> None:
    try:
        from dvg_obs_ceo.baseline import _load_upstream

        _, dvg_ceo, _, _ = _load_upstream()
        pool = dvg_ceo(n=4)
    except (ImportError, ModuleNotFoundError):
        pytest.skip("baseline scientific dependencies are not installed")
    with pytest.raises(ValueError, match="is not in list"):
        pool.get_circuit([2, 3], [0.3, 0.3])
    # The equivalent native OVP circuit is well-defined and is the required target.
    assert pool.get_circuit([4], [0.3]).num_qubits == 4

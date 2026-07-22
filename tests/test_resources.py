from dataclasses import dataclass
import json
from pathlib import Path

import pytest

from dvg_obs_ceo.block_ir import enumerate_candidates, recover_dvg_blocks
from dvg_obs_ceo.resources import (
    AnsatzStructure,
    ResourceBackend,
    ResourceEvaluationError,
    apply_candidate_structure,
    evaluate_full_circuit_resources,
    paper_era_backend,
)
from dvg_obs_ceo.resource_pool import ResourceOnlyDVGPool


ROOT = Path(__file__).resolve().parents[1]


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


class FakeCircuit:
    def __init__(self, count=0, cnot_depth=0, total_depth=0, label="empty"):
        self.count = count
        self.cnot_depth_value = cnot_depth
        self.total_depth = total_depth
        self.labels = [label]

    def compose(self, other):
        result = FakeCircuit(
            self.count + other.count,
            self.cnot_depth_value + other.cnot_depth_value,
            self.total_depth + other.total_depth,
            "compose",
        )
        result.labels = self.labels + other.labels
        return result

    def depth(self):
        return self.total_depth


class FakePool:
    n = 4

    def __init__(self):
        q0 = FakeQubitOperator({((0, "X"), (2, "Y")): 0.5j})
        q1 = FakeQubitOperator({((0, "Y"), (2, "X")): -0.5j})
        plus = FakeQubitOperator({**q0.terms, **q1.terms})
        diff = FakeQubitOperator({next(iter(q0.terms)): 0.5j, next(iter(q1.terms)): 0.5j})
        self.operators = [
            FakeOperator(q0, {0, 2}, [2], [0]),
            FakeOperator(q1, {0, 2}, [3], [1]),
            FakeOperator(plus, {0, 2}, [[2], [3]], [[0], [1]], "sum", [0, 1]),
            FakeOperator(diff, {0, 2}, [[2], [3]], [[0], [1]], "diff", [0, 1]),
        ]
        self.parent_range = range(0, 2)

    def get_qubits(self, index):
        return self.operators[index].qubits

    def get_q_op(self, index):
        return self.operators[index].q_operator

    def get_circuit(self, indices, coefficients):
        count = 0
        depth = 0
        position = 0
        while position < len(indices):
            if indices[position] >= 2:
                count += 9
                depth += 7
                position += 1
            elif position + 1 < len(indices) and indices[position + 1] < 2:
                count += 13
                depth += 11
                position += 2
            else:
                count += 13
                depth += 11
                position += 1
        return FakeCircuit(count, depth, depth + len(indices), repr((indices, coefficients)))


FAKE_BACKEND = ResourceBackend(
    "fake-paper-counter-v1",
    lambda n: FakeCircuit(),
    lambda circuit: json.dumps(
        {
            "count": circuit.count,
            "cnot_depth": circuit.cnot_depth_value,
            "total_depth": circuit.total_depth,
            "labels": circuit.labels,
        },
        sort_keys=True,
    ),
    lambda qasm: json.loads(qasm)["count"],
    lambda qasm, n: json.loads(qasm)["cnot_depth"],
)


def test_full_recount_and_native_candidate_rebuild_reduce_real_structure() -> None:
    pool = FakePool()
    source = AnsatzStructure.create([2, 0, 1], [0.2, 0.3, -0.1], [3])
    before = evaluate_full_circuit_resources(pool, source, FAKE_BACKEND)
    blocks = recover_dvg_blocks(pool, source.indices, source.coefficients, source.cumulative_parameter_counts)
    mvp = next(block for block in blocks if block.family == "MVP")
    candidate = next(value for value in enumerate_candidates(pool, [mvp]) if value.kind == "mvp-to-ovp-sum")
    transformed = apply_candidate_structure(pool, source, candidate, [0.1])
    after = evaluate_full_circuit_resources(pool, transformed, FAKE_BACKEND)
    assert transformed.indices == (2, 2)
    assert before.snapshot.cnot_count == 22
    assert after.snapshot.cnot_count == 18
    assert before.snapshot.parameter_count == 3
    assert after.snapshot.parameter_count == 2
    assert after.snapshot.structure_digest != before.snapshot.structure_digest


def test_physical_and_deterministic_structural_policy_match_when_topology_is_stable() -> None:
    pool = FakePool()
    source = AnsatzStructure.create([2, 0, 1], [0.2, 0.3, -0.1], [1, 3])
    physical = evaluate_full_circuit_resources(pool, source, FAKE_BACKEND, coefficient_policy="physical")
    structural = evaluate_full_circuit_resources(
        pool, source, FAKE_BACKEND, coefficient_policy="deterministic-structural"
    )
    assert physical.snapshot == structural.snapshot
    assert physical.cnot_count_by_iteration == structural.cnot_count_by_iteration
    assert physical.circuit_qasm_digest != structural.circuit_qasm_digest


def test_empty_iteration_is_preserved_and_stale_candidate_fails_closed() -> None:
    pool = FakePool()
    source = AnsatzStructure.create([0, 1], [0.2, -0.1], [2])
    block = recover_dvg_blocks(pool, source.indices, source.coefficients, source.cumulative_parameter_counts)[0]
    candidate = next(value for value in enumerate_candidates(pool, [block]) if value.kind == "mvp-whole-deletion")
    empty = apply_candidate_structure(pool, source, candidate, [])
    assert empty.indices == ()
    assert empty.cumulative_parameter_counts == (0,)
    empty_resources = evaluate_full_circuit_resources(pool, empty, FAKE_BACKEND)
    assert empty_resources.snapshot.cnot_count == 0
    assert empty_resources.snapshot.parameter_count == 0
    changed = AnsatzStructure.create([0, 1], [0.25, -0.1], [2])
    with pytest.raises(ResourceEvaluationError, match="stale"):
        apply_candidate_structure(pool, changed, candidate, [])


def test_pinned_paper_counter_h2_and_mvp_to_ovp_when_baseline_extra_available() -> None:
    try:
        from dvg_obs_ceo.baseline import _load_upstream

        _, dvg_ceo, _, _ = _load_upstream()
        pool = dvg_ceo(n=4)
        backend = paper_era_backend()
        from adaptvqe.algorithms.adapt_data import AdaptData
    except (ImportError, ModuleNotFoundError, ResourceEvaluationError):
        pytest.skip("baseline scientific dependencies are not installed")
    h2 = AnsatzStructure.create([4], [-0.18820719206269798], [1])
    resources = evaluate_full_circuit_resources(pool, h2, backend)
    assert resources.snapshot.cnot_count == 9
    assert resources.snapshot.cnot_depth == 7

    source = AnsatzStructure.create([4, 2, 3, 0], [0.2, 0.3, -0.1, 0.4], [3, 4])
    physical = evaluate_full_circuit_resources(pool, source, backend)
    structural = evaluate_full_circuit_resources(
        pool, source, backend, coefficient_policy="deterministic-structural"
    )
    assert physical.snapshot == structural.snapshot
    official = AdaptData(0.0, pool, None, None, "probe", -1.0, 4, None)
    official.process_iteration(
        [4, 2, 3],
        -0.5,
        1.0,
        None,
        [0.4],
        [0.2, 0.3, -0.1],
        None,
        None,
        [],
        [],
        [],
        [0, 1, 2, 3],
        0,
    )
    official.process_iteration(
        [4, 2, 3, 0],
        -0.6,
        0.5,
        None,
        [0.2],
        [0.2, 0.3, -0.1, 0.4],
        None,
        None,
        [],
        [],
        [],
        [0, 1, 2, 3],
        0,
    )
    assert physical.cnot_count_by_iteration == tuple(official.acc_cnot_counts(pool))
    assert physical.cnot_depth_by_iteration == tuple(official.acc_cnot_depths(pool))
    assert physical.total_depth_by_iteration == tuple(official.acc_depths(pool))
    blocks = recover_dvg_blocks(pool, source.indices, source.coefficients, source.cumulative_parameter_counts)
    mvp = next(block for block in blocks if block.family == "MVP")
    candidate = next(value for value in enumerate_candidates(pool, [mvp]) if value.kind == "mvp-to-ovp-sum")
    transformed = apply_candidate_structure(pool, source, candidate, [0.1])
    reduced = evaluate_full_circuit_resources(pool, transformed, backend)
    assert reduced.snapshot.cnot_count < physical.snapshot.cnot_count
    assert reduced.snapshot.parameter_count < physical.snapshot.parameter_count


def test_registered_lih_resource_trajectory_with_memory_bounded_pool() -> None:
    try:
        from dvg_obs_ceo.baseline import _load_upstream

        _load_upstream()
        backend = paper_era_backend()
    except (ImportError, ModuleNotFoundError, ResourceEvaluationError):
        pytest.skip("baseline scientific dependencies are not installed")
    reference = json.loads(
        (ROOT / "artifacts" / "s1" / "lih-3a-baseline-rerun.json").read_text()
    )
    structure = AnsatzStructure.create(
        reference["ansatz_indices"],
        reference["ansatz_coefficients"],
        [row["parameter_count"] for row in reference["trajectory"]],
    )
    observed = evaluate_full_circuit_resources(
        ResourceOnlyDVGPool(12), structure, backend
    )
    assert list(observed.cnot_count_by_iteration) == reference["cnot_counts_by_iteration"]
    assert list(observed.cnot_depth_by_iteration) == reference["cnot_depths_by_iteration"]
    assert observed.snapshot.parameter_count == reference["parameter_count"]

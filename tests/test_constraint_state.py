from dataclasses import replace
from fractions import Fraction

import numpy as np
import pytest

from dvg_obs_ceo.block_ir import CompressionCandidate
from dvg_obs_ceo.constraint_state import (
    CanonicalConstraintState,
    ConstraintStateError,
    ExactConstraintSystem,
    exact_atomic_constraint,
)
from dvg_obs_ceo.quadratic import ConstraintTargetIR


def _numerical(source_slots=("b", "a"), rows=((1.0, -1.0),), rhs=(0.0,)):
    return ConstraintTargetIR.create(
        constraint_matrix=rows,
        constraint_rhs=rhs,
        offset=[0.0, 0.0],
        jacobian=[[1.0], [1.0]],
        source_slots=source_slots,
        target_slots=["phi"],
        generator_normalization="paper-era-pool-arrange-v1",
        orientation="sum",
    )


def _candidate(kind: str, jacobian, removed=()) -> CompressionCandidate:
    source = len(jacobian)
    target = len(jacobian[0]) if source else 0
    if target == 0:
        matrix = np.eye(source)
    elif kind.endswith("sum"):
        matrix = [[1.0, -1.0]]
    elif kind.endswith("diff"):
        matrix = [[1.0, 1.0]]
    else:
        matrix = np.eye(source)[list(removed)]
    ir = ConstraintTargetIR.create(
        constraint_matrix=matrix,
        constraint_rhs=[0.0] * len(matrix),
        offset=[0.0] * source,
        jacobian=jacobian,
        source_slots=[f"s:{index}" for index in range(source)],
        target_slots=[f"t:{index}" for index in range(target)],
        generator_normalization="paper-era-pool-arrange-v1",
        orientation=kind,
    )
    exact_relation = None
    if kind.endswith("sum"):
        exact_relation = tuple(1 if index < 2 else 0 for index in range(source))
    elif kind.endswith("diff"):
        exact_relation = tuple((1, -1)[index] if index < 2 else 0 for index in range(source))
    return CompressionCandidate(
        "candidate:" + kind,
        "equivalence:" + kind,
        kind,
        "block:" + kind,
        tuple(range(source)),
        "empty" if target == 0 else ("OVP" if "ovp" in kind else "single-QE"),
        tuple(range(target)),
        tuple(removed),
        ir,
        tuple("a" * 64 for _ in range(target)),
        tuple(range(source)),
        "b" * 64,
        exact_relation,
    )


def test_exact_rref_is_invariant_to_row_order_scaling_and_slot_permutation() -> None:
    first = ExactConstraintSystem.create(
        ["x", "y", "z"], [[1, 2, -1], [0, 2, 2]], [3, 4]
    )
    second = ExactConstraintSystem.create(
        ["z", "x", "y"], [[-2, 0, -2], [-3, 3, 6]], [-4, 9]
    )
    assert first == second


def test_exact_constraints_reject_float_inference_and_inconsistency() -> None:
    with pytest.raises(ConstraintStateError, match="cannot be inferred"):
        ExactConstraintSystem.create(["x"], [[1.0]], [0])
    with pytest.raises(ConstraintStateError, match="inconsistent"):
        ExactConstraintSystem.create(["x"], [[1], [1]], [0, 1])


@pytest.mark.parametrize(
    "candidate",
    [
        _candidate("block-deletion", [[]], (0,)),
        _candidate("mvp-whole-deletion", [[], []], (0, 1)),
        _candidate("mvp-constituent-deletion", [[1.0], [0.0]], (1,)),
        _candidate("mvp-to-single-qe", [[0.0], [1.0]], (0,)),
        _candidate("mvp-to-ovp-sum", [[1.0 - 2e-16], [1.0 - 2e-16]]),
        _candidate("mvp-to-ovp-diff", [[1.0 - 2e-16], [-1.0 + 2e-16]]),
    ],
)
def test_supported_atomic_families_have_registered_exact_semantics(candidate) -> None:
    exact = exact_atomic_constraint(candidate)
    assert exact.system.rank == len(candidate.transformation.source_slots) - len(
        candidate.transformation.target_slots
    )
    assert exact.audit_provenance["kind"] == candidate.kind
    assert exact.primitive["generator_relation"] in {
        "empty", "identity-subset", "existing-ovp-sum", "existing-ovp-difference"
    }


def test_atomic_semantics_reject_unregistered_approximation() -> None:
    candidate = _candidate("mvp-to-ovp-sum", [[1.0], [0.999999]])
    with pytest.raises(ConstraintStateError, match="disagrees"):
        exact_atomic_constraint(candidate)


@pytest.mark.parametrize(
    ("kind", "jacobian", "expected_rows"),
    [
        ("mvp-to-ovp-sum", [[1.0], [1.0], [0.0]], [[1, -1, 0], [0, 0, 1]]),
        ("mvp-to-ovp-diff", [[1.0], [-1.0], [0.0]], [[1, 1, 0], [0, 0, 1]]),
    ],
)
def test_three_constituent_ovp_has_exact_tie_and_zero_constraint(
    kind, jacobian, expected_rows
) -> None:
    candidate = _candidate(kind, jacobian, (2,))
    exact = exact_atomic_constraint(candidate)
    matrix, rhs = exact.system.rational_matrix()
    assert [[int(value) for value in row] for row in matrix] == expected_rows
    assert [int(value) for value in rhs] == [0, 0]
    expected_relation = [1, 1, 0] if kind.endswith("sum") else [1, -1, 0]
    assert exact.primitive["exact_generator_relation"] == expected_relation


def test_ovp_semantics_reject_missing_or_invented_exact_provenance() -> None:
    candidate = _candidate("mvp-to-ovp-sum", [[1.0], [1.0], [0.0]], (2,))
    with pytest.raises(ConstraintStateError, match="explicit exact"):
        exact_atomic_constraint(replace(candidate, exact_generator_relation=None))
    with pytest.raises(ConstraintStateError, match="exactly two"):
        exact_atomic_constraint(replace(candidate, exact_generator_relation=(1, 1, 1)))


def test_zero_target_deletion_has_zero_jacobian_residual() -> None:
    candidate = _candidate("mvp-whole-deletion", [[], []], (0, 1))
    exact = exact_atomic_constraint(candidate)
    state = CanonicalConstraintState.create(
        exact.system, candidate.transformation, [exact.primitive]
    )
    assert state.diagnostics["target_dimension"] == 0
    assert state.diagnostics["jacobian_constraint_residual_infinity"] == 0.0


def test_equivalent_candidate_construction_paths_share_semantic_primitive() -> None:
    constituent = exact_atomic_constraint(
        _candidate("mvp-constituent-deletion", [[1.0], [0.0]], (1,))
    )
    single_candidate = replace(
        _candidate("mvp-constituent-deletion", [[1.0], [0.0]], (1,)),
        candidate_id="candidate:mvp-to-single-qe",
        kind="mvp-to-single-qe",
    )
    single = exact_atomic_constraint(single_candidate)
    assert constituent.system == single.system
    assert constituent.primitive == single.primitive
    assert constituent.audit_provenance != single.audit_provenance


def test_semantic_and_numerical_ids_are_separate_and_application_order_is_canonical() -> None:
    exact = ExactConstraintSystem.create(["b", "a"], [[1, -1]], [0])
    left = {"kind": "tie", "token": "exact:+1"}
    right = {"kind": "delete", "slot": "unused"}
    first = CanonicalConstraintState.create(exact, _numerical(), [left, right])
    second = CanonicalConstraintState.create(exact, _numerical(), [right, left])
    assert first.constraint_semantic_id == second.constraint_semantic_id
    assert first.constraint_numerical_id == second.constraint_numerical_id

    perturbed = ConstraintTargetIR.create(
        constraint_matrix=[[1.0, -1.0]],
        constraint_rhs=[0.0],
        offset=[0.0, 0.0],
        jacobian=[[1.0 + 1e-12], [1.0 + 1e-12]],
        source_slots=["b", "a"],
        target_slots=["phi"],
        generator_normalization="paper-era-pool-arrange-v1",
        orientation="sum",
    )
    third = CanonicalConstraintState.create(exact, perturbed, [left, right])
    assert third.constraint_semantic_id == first.constraint_semantic_id
    assert third.constraint_numerical_id != first.constraint_numerical_id


def test_distinct_exact_rhs_produces_distinct_semantic_id() -> None:
    zero = ExactConstraintSystem.create(["x", "y"], [[1, -1]], [0])
    one = ExactConstraintSystem.create(["x", "y"], [[1, -1]], [1])
    primitives = [{"kind": "registered-affine-test"}]
    zero_ir = ConstraintTargetIR.create(
        constraint_matrix=[[1.0, -1.0]], constraint_rhs=[0.0], offset=[0.0, 0.0],
        jacobian=[[1.0], [1.0]], source_slots=["x", "y"], target_slots=["p"],
        generator_normalization="test", orientation="test",
    )
    one_ir = ConstraintTargetIR.create(
        constraint_matrix=[[1.0, -1.0]], constraint_rhs=[1.0], offset=[1.0, 0.0],
        jacobian=[[1.0], [1.0]], source_slots=["x", "y"], target_slots=["p"],
        generator_normalization="test", orientation="test",
    )
    assert CanonicalConstraintState.create(zero, zero_ir, primitives).constraint_semantic_id != (
        CanonicalConstraintState.create(one, one_ir, primitives).constraint_semantic_id
    )

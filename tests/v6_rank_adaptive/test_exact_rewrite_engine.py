import json
from dataclasses import dataclass

import pytest

from dvg_obs_ceo.resources import AnsatzStructure
from dvg_obs_ceo.v6_rank_adaptive.exact_rewrite_engine import (
    DEFAULT_OUTPUT,
    ExactRewriteEngineError,
    ExactRewriteRegistry,
    RewriteLimits,
    RewriteRuleDefinition,
    RewriteRuleKind,
    RewriteRuleStatus,
    apply_proposal,
    default_registry,
    enumerate_proposals,
    state_digest,
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
        minus = FakeQubitOperator(
            {
                next(iter(q0.terms)): 0.5j,
                next(iter(q1.terms)): 0.5j,
            }
        )
        self.operators = [
            FakeOperator(q0, {0, 2}, [2], [0]),
            FakeOperator(q1, {0, 2}, [3], [1]),
            FakeOperator(
                plus,
                {0, 2},
                [[2], [3]],
                [[0], [1]],
                "sum",
                [0, 1],
            ),
            FakeOperator(
                minus,
                {0, 2},
                [[2], [3]],
                [[0], [1]],
                "diff",
                [0, 1],
            ),
        ]
        self.parent_range = range(0, 2)

    def get_qubits(self, index):
        return self.operators[index].qubits

    def get_q_op(self, index):
        return self.operators[index].q_operator


def _disjoint_operator(pool):
    operator = type(pool.operators[0])(
        type(pool.get_q_op(0))({((1, "X"), (3, "Y")): 0.5j}),
        {1, 3},
        [3],
        [1],
    )
    pool.operators.append(operator)
    return len(pool.operators) - 1


def test_zero_coordinate_requires_exact_zero_and_removes_whole_block():
    pool = FakePool()
    source = AnsatzStructure.create([0, 1], [0.0, -0.0], [2])
    registry, _ = default_registry()
    proposals = enumerate_proposals(pool, source, registry)
    zero = [
        item
        for item in proposals
        if item.kind is RewriteRuleKind.ZERO_COORDINATE
    ]
    assert len(zero) == 1
    target = apply_proposal(pool, source, zero[0])
    assert target.indices == ()
    assert target.coefficients == ()
    assert target.cumulative_parameter_counts == (0,)
    near = AnsatzStructure.create([0], [1e-16], [1])
    assert not any(
        item.kind is RewriteRuleKind.ZERO_COORDINATE
        for item in enumerate_proposals(pool, near, registry)
    )


def test_identical_fusion_and_cancellation_cross_only_disjoint_corridor():
    pool = FakePool()
    disjoint = _disjoint_operator(pool)
    registry, _ = default_registry(maximum_corridor_blocks=1)
    fusion_source = AnsatzStructure.create(
        [0, disjoint, 0],
        [0.2, 0.4, 0.3],
        [1, 2, 3],
    )
    fusion = next(
        item
        for item in enumerate_proposals(
            pool,
            fusion_source,
            registry,
        )
        if item.kind is RewriteRuleKind.IDENTICAL_FUSION
    )
    fused = apply_proposal(pool, fusion_source, fusion)
    assert fused.indices == (disjoint, 0)
    assert fused.coefficients == pytest.approx((0.4, 0.5))

    cancellation_source = AnsatzStructure.create(
        [0, disjoint, 0],
        [0.2, 0.4, -0.2],
        [1, 2, 3],
    )
    cancellation = next(
        item
        for item in enumerate_proposals(
            pool,
            cancellation_source,
            registry,
        )
        if item.kind is RewriteRuleKind.IDENTICAL_CANCELLATION
    )
    cancelled = apply_proposal(
        pool,
        cancellation_source,
        cancellation,
    )
    assert cancelled.indices == (disjoint,)
    assert cancelled.coefficients == (0.4,)

    overlapping = AnsatzStructure.create(
        [0, 1, 0],
        [0.2, 0.4, 0.3],
        [1, 2, 3],
    )
    assert not any(
        item.kind
        in {
            RewriteRuleKind.IDENTICAL_FUSION,
            RewriteRuleKind.IDENTICAL_CANCELLATION,
        }
        for item in enumerate_proposals(pool, overlapping, registry)
    )


def test_identical_multigenerator_fusion_requires_exact_commutation():
    pool = FakePool()
    pool.operators[0].q_operator = FakeQubitOperator(
        {((0, "X"),): 1j}
    )
    pool.operators[1].q_operator = FakeQubitOperator(
        {((0, "Z"),): 1j}
    )
    source = AnsatzStructure.create(
        [0, 1, 0, 1],
        [0.2, 0.3, 0.4, 0.5],
        [2, 4],
    )
    registry, _ = default_registry()
    assert not any(
        item.kind
        in {
            RewriteRuleKind.IDENTICAL_FUSION,
            RewriteRuleKind.IDENTICAL_CANCELLATION,
        }
        for item in enumerate_proposals(pool, source, registry)
    )


def test_v51_absorption_is_available_only_through_verified_registry():
    pool = FakePool()
    source = AnsatzStructure.create(
        [2, 0, 1],
        [0.2, 0.3, -0.1],
        [1, 3],
    )
    registry, _ = default_registry()
    absorption = next(
        item
        for item in enumerate_proposals(pool, source, registry)
        if item.kind is RewriteRuleKind.OVP_MVP_ABSORPTION
    )
    target = apply_proposal(pool, source, absorption)
    assert target.indices == (0, 1)
    assert target.coefficients == pytest.approx((0.5, 0.1))

    unverified = ExactRewriteRegistry()
    unverified.register(
        RewriteRuleDefinition(
            rule_id="v6-rewrite:unverified-v1",
            kind=RewriteRuleKind.OVP_MVP_ABSORPTION,
            proof_method_id="test",
            evidence_id=None,
            maximum_corridor_blocks=1,
            status=RewriteRuleStatus.PROPOSED,
        )
    )
    unverified.freeze()
    with pytest.raises(ExactRewriteEngineError, match="non-verified"):
        enumerate_proposals(pool, source, unverified)


def test_registry_and_proposals_are_deterministic_under_definition_order():
    source = AnsatzStructure.create([2, 0, 1], [0.2, 0.3, -0.1], [1, 3])
    pool = FakePool()
    forward, _ = default_registry(
        definition_order=tuple(RewriteRuleKind)
    )
    reverse, _ = default_registry(
        definition_order=tuple(reversed(tuple(RewriteRuleKind)))
    )
    assert forward.registry_digest == reverse.registry_digest
    assert [
        item.proposal_id
        for item in enumerate_proposals(pool, source, forward)
    ] == [
        item.proposal_id
        for item in enumerate_proposals(pool, source, reverse)
    ]


def test_limits_reject_nonterminating_configuration():
    with pytest.raises(ExactRewriteEngineError, match="limits"):
        RewriteLimits(maximum_steps=2, maximum_states=2)


def test_stale_proposal_fails_closed():
    pool = FakePool()
    source = AnsatzStructure.create([0], [0.0], [1])
    registry, _ = default_registry()
    proposal = enumerate_proposals(pool, source, registry)[0]
    changed = AnsatzStructure.create([0], [0.1], [1])
    assert state_digest(source) != state_digest(changed)
    with pytest.raises(ExactRewriteEngineError, match="stale"):
        apply_proposal(pool, changed, proposal)


def test_committed_s6_trace_is_complete_and_work_accounted():
    report = json.loads(DEFAULT_OUTPUT.read_text(encoding="utf-8"))
    digest = report.pop("report_digest")
    from dvg_obs_ceo.identity import sha256_hex

    assert digest == sha256_hex(report)
    assert report["complete"] is True
    assert report["stop_reason"] == "SATURATED"
    assert report["work"]["energy_evaluations"] == 0
    assert report["work"]["full_resource_recounts"] > 0
    assert report["work"]["rewrite_proposals_accepted"] == 2
    assert (
        report["target"]["resources"]["cnot_count"]
        < report["source"]["resources"]["cnot_count"]
    )
    assert report["paper_measurement_cost"] is None

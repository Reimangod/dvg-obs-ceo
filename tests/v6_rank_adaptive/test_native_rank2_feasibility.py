import json

import numpy as np
import pytest

from dvg_obs_ceo.v6_rank_adaptive.evidence import (
    EvidenceStatus,
    EvidenceStrength,
    SemanticScope,
)
from dvg_obs_ceo.v6_rank_adaptive.native_rank2_feasibility import (
    DEFAULT_OUTPUT,
    NativeRank2FeasibilityError,
    _mathematical_evidence,
    _qasm_resources,
    _validate_native_family,
    _v41_native_comparison,
    build_native_rank2_circuit,
    derive_conditional_rotation,
    rank2_parameter_map,
)
from dvg_obs_ceo.v6_rank_adaptive.transition_registry import (
    TransitionStatus,
)


@pytest.fixture(scope="module")
def canonical_pool():
    from dvg_obs_ceo.baseline import _load_upstream

    _load_upstream()
    from adaptvqe.pools import QE_All

    return QE_All(n=4, couple_exchanges=True)


def test_three_same_spin_qes_map_to_distinct_conditional_sectors(
    canonical_pool,
):
    mappings = [
        derive_conditional_rotation(
            canonical_pool,
            index,
            (0, 1, 2, 3),
        )[0]
        for index in (6, 7, 8)
    ]
    assert [item.control_label for item in mappings] == [3, 6, 5]
    assert [item.angle_scale for item in mappings] == ["2", "-2", "2"]


@pytest.mark.parametrize("kept", [(6, 7), (6, 8), (7, 8)])
def test_native_rank2_family_matches_exact_generator_samples(
    canonical_pool,
    kept,
):
    assert _validate_native_family(
        canonical_pool,
        kept,
        samples=5,
        seed=2026,
    ) <= 1e-10


def test_native_rank2_is_a_depth_parameter_tradeoff_not_cnot_compression(
    canonical_pool,
):
    from adaptvqe.circuits import mvp_ceo_circuit
    from openfermion import QubitOperator

    source_operator = QubitOperator()
    for index, coefficient in zip((6, 7, 8), (0.2, -0.3, 0.4)):
        source_operator += coefficient * canonical_pool.get_q_op(index)
    source = mvp_ceo_circuit(
        source_operator,
        4,
        big_endian=True,
    )
    target, _ = build_native_rank2_circuit(
        canonical_pool,
        (6, 7),
        (0.2, -0.3),
    )
    source_resources = _qasm_resources(
        source,
        parameter_count=3,
        logical_block_count=1,
    )
    target_resources = _qasm_resources(
        target,
        parameter_count=2,
        logical_block_count=1,
    )
    assert source_resources["cnot_count"] == 13
    assert target_resources["cnot_count"] == 14
    assert target_resources["cnot_depth"] > source_resources["cnot_depth"]
    assert target_resources["total_depth"] < source_resources["total_depth"]


def test_symbolic_evidence_axes_remain_separate(canonical_pool):
    evidence, proof = _mathematical_evidence(canonical_pool)
    relations = evidence[:3]
    native, context = evidence[3:]
    assert len(relations) == 3
    assert all(item.status is EvidenceStatus.PASSED for item in relations)
    assert all(
        item.strength is EvidenceStrength.ALGEBRAICALLY_PROVEN
        for item in relations
    )
    assert native.strength is EvidenceStrength.SYMBOLICALLY_PROVEN
    assert native.semantic_scope is SemanticScope.FAMILYWISE_UNITARY
    assert context.evidence_id not in {
        *[item.evidence_id for item in relations],
        native.evidence_id,
    }
    assert len(proof["parameter_maps"]) == 3
    assert len(proof["commutation_proofs"]) == 3
    assert all(
        item["proof_id"].startswith("v6-proof-v1:")
        for item in proof["commutation_proofs"]
    )


def test_v41_comparison_distinguishes_parameter_rank_from_native_synthesis():
    comparison = _v41_native_comparison()
    assert comparison["v4_1_parameter_only_rank2_present"] is True
    assert comparison["v4_1_sparse_ucry_native_synthesis_absent"] is True
    assert "MVP" in comparison["observed_target_families"]


def test_invalid_rank2_requests_fail_closed(canonical_pool):
    with pytest.raises(NativeRank2FeasibilityError, match="two distinct"):
        rank2_parameter_map((0, 0))
    with pytest.raises(NativeRank2FeasibilityError, match="two generators"):
        build_native_rank2_circuit(canonical_pool, (6,), (0.2,))


def test_committed_s5_report_is_self_consistent():
    report = json.loads(DEFAULT_OUTPUT.read_text(encoding="utf-8"))
    digest = report.pop("report_digest")
    from dvg_obs_ceo.identity import sha256_hex

    assert digest == sha256_hex(report)
    assert report["decision"] == "GO"
    assert all(report["go_checks"].values())
    transition = report["transition_registry"]["transitions"][0]
    assert transition["status"] == TransitionStatus.VERIFIED.value
    candidates = report["representative_case"]["candidates"]
    assert candidates
    assert all(item["strict_cnot_gain"] is False for item in candidates)
    assert all(item["strict_total_depth_gain"] is True for item in candidates)
    assert all(item["paper_measurement_cost"] is None for item in candidates)

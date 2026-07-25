import json

import pytest

from dvg_obs_ceo.identity import sha256_hex
from dvg_obs_ceo.v6_rank_adaptive.evidence import (
    ResourceDeltaEvidence,
    ResourceVector,
)
from dvg_obs_ceo.v6_rank_adaptive.rank_candidate_catalog import (
    DEFAULT_OUTPUT,
    RankCandidateCatalogError,
    _decode_float64,
    _screen_resource_evidence,
    enumerate_native_rank_candidates,
    load_s5_registry,
    load_s6_source,
)


@pytest.fixture(scope="module")
def catalog_inputs():
    from dvg_obs_ceo.baseline import _load_upstream

    _, DVG_CEO, _, _ = _load_upstream()
    source = load_s6_source()
    registry, evidence, embeddings = load_s5_registry()
    return (
        DVG_CEO(n=12),
        source,
        registry,
        evidence,
        embeddings,
    )


@pytest.fixture(scope="module")
def candidates(catalog_inputs):
    return enumerate_native_rank_candidates(*catalog_inputs)


def test_catalog_covers_all_registered_rank3_edges(candidates):
    assert len(candidates) == 3
    by_block = {}
    for candidate in candidates:
        by_block.setdefault(candidate.source_block_id, []).append(candidate)
    assert len(by_block) == 1
    assert all(
        {item.omitted_source_slot for item in items} == {0, 1, 2}
        for items in by_block.values()
    )


def test_every_candidate_has_semantic_synthesis_and_resource_evidence(
    candidates,
):
    assert all(
        item.target_embedding_evidence_id.startswith("v6-evidence-v1:")
        and item.native_synthesis_evidence_id.startswith("v6-evidence-v1:")
        and item.contextual_rewrite_evidence_id.startswith("v6-evidence-v1:")
        and item.resources.resource_counter_version
        and item.resources.native_synthesizer_version
        for item in candidates
    )


def test_candidates_are_depth_parameter_tradeoffs(candidates):
    assert all(item.resources.effect.value == "VERIFIED_GAIN" for item in candidates)
    assert all(item.resources.after.parameter_count == 128 for item in candidates)
    assert all(
        item.resources.after.total_depth
        < item.resources.before.total_depth
        for item in candidates
    )
    assert all(
        item.resources.after.cnot_count
        > item.resources.before.cnot_count
        for item in candidates
    )


def test_candidate_order_is_independent_of_block_traversal(catalog_inputs):
    from dvg_obs_ceo.block_ir import recover_dvg_blocks

    pool, source, registry, evidence, embeddings = catalog_inputs
    reference = enumerate_native_rank_candidates(
        pool,
        source,
        registry,
        evidence,
        embeddings,
    )
    blocks = recover_dvg_blocks(
        pool,
        source.indices,
        source.coefficients,
        source.cumulative_parameter_counts,
    )
    traversal = tuple(block.block_id for block in reversed(blocks))
    observed = enumerate_native_rank_candidates(
        pool,
        source,
        registry,
        evidence,
        embeddings,
        traversal_block_ids=traversal,
        omitted_slot_order=(2, 1, 0),
    )
    assert observed == reference


def test_exact_duplicate_traversal_is_deduplicated(catalog_inputs):
    pool, source, registry, evidence, embeddings = catalog_inputs
    reference = enumerate_native_rank_candidates(
        pool,
        source,
        registry,
        evidence,
        embeddings,
    )
    traversal = tuple(
        item.source_block_id for item in reference
    )
    observed = enumerate_native_rank_candidates(
        pool,
        source,
        registry,
        evidence,
        embeddings,
        traversal_block_ids=traversal,
    )
    assert observed == reference


def test_native_resource_symmetry_does_not_merge_scientific_candidates(
    candidates,
):
    assert len({item.equivalence_class_id for item in candidates}) == 1
    assert len({item.candidate_id for item in candidates}) == 3


def test_parameter_only_reduction_is_rejected_as_no_physical_gain():
    before = ResourceVector(3, 1, 10, 5, 20)
    after = ResourceVector(2, 1, 10, 5, 20)
    evidence = ResourceDeltaEvidence(
        before=before,
        after=after,
        resource_counter_version="counter-v1",
        native_synthesizer_version="native-v1",
        compiler_configuration="config-v1",
        qubit_order=(0, 1),
        before_digest="0" * 64,
        after_digest="1" * 64,
        primary_resource="total_depth",
    )
    status, reasons = _screen_resource_evidence(evidence)
    assert status == "REJECTED_NO_PHYSICAL_GAIN"
    assert reasons == ("no-strict-physical-circuit-gain",)


def test_noncanonical_float_bytes_fail_closed():
    with pytest.raises(RankCandidateCatalogError, match="canonical"):
        _decode_float64("0")


def test_committed_s7_report_is_self_consistent():
    report = json.loads(DEFAULT_OUTPUT.read_text(encoding="utf-8"))
    digest = report.pop("report_digest")
    assert digest == sha256_hex(report)
    assert report["candidate_count"] == 3
    assert report["eligible_candidate_count"] == 3
    assert all(report["source_recount_checks"].values())
    assert report["paper_measurement_cost"] is None
    assert all(
        item["source_state_equivalence"] == "NOT_ESTABLISHED"
        and item["optimization_requirement"] == "FULL_REOPTIMIZATION"
        for item in report["candidates"]
    )

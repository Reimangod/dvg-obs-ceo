import copy
import json

import pytest

from dvg_obs_ceo.v6_rank_adaptive import legacy_replay
from dvg_obs_ceo.v6_rank_adaptive.legacy_replay import (
    DEFAULT_OUTPUT,
    LegacyReplayError,
    ReplayStrength,
    build_report,
)
from dvg_obs_ceo.identity import sha256_hex


def test_all_registered_legacy_records_replay_without_modification():
    report = build_report()
    assert report["historical_artifacts_modified"] is False
    assert report["record_count"] == 10
    assert all(record["passed"] for record in report["records"])
    assert all(
        all(record["checks"].values()) for record in report["records"]
    )
    assert report["paper_measurement_cost"] is None


def test_replay_strength_is_conservative_and_explicit():
    report = build_report()
    by_key = {
        (record["method"], record["case_id"]): record
        for record in report["records"]
    }
    assert (
        by_key[("V4.1", "lih-3.0")]["replay_strength"]
        == ReplayStrength.SEMANTIC_NORMALIZED.name
    )
    assert (
        by_key[("V4.1", "h6-3.0")]["replay_strength"]
        == ReplayStrength.DECISION_REPLAYED.name
    )
    assert (
        by_key[("V5", "h6-3.0")]["replay_strength"]
        == ReplayStrength.FULL_WORK_REPLAYED.name
    )
    assert (
        by_key[("V5.1", "h6-1.5-v4.1-source")]["replay_strength"]
        == ReplayStrength.DECISION_REPLAYED.name
    )
    assert "complete pre-fusion candidate catalog" in by_key[
        ("V5.1", "h6-1.5-v4.1-source")
    ]["unavailable_fields"]


def test_original_and_normalized_digests_remain_distinct_concepts():
    report = build_report()
    assert all(
        record["original_artifact_digest"]
        != record["normalized_ir_digest"]
        for record in report["records"]
    )
    assert all(
        len(record["original_artifact_digest"]) == 64
        and len(record["normalized_ir_digest"]) == 64
        for record in report["records"]
    )


def test_v5_work_reconciliation_fails_on_tampering():
    spec = next(
        item
        for item in legacy_replay.SPECS
        if item.method == "V5" and item.case_id == "h6-1.5"
    )
    value = json.loads((legacy_replay.ROOT / spec.path).read_text())
    value = copy.deepcopy(value)
    value["result"]["aggregate_work"]["energy_evaluations"] += 1
    checkpoint, _ = legacy_replay._checkpoint_evidence(
        spec.source_checkpoint_path
    )
    _, _, checks, _, _ = legacy_replay._normalize_v5(
        spec,
        value,
        checkpoint,
    )
    assert checks["aggregate_work_reconciled"] is False
    assert checks["nested_result_digest"] is False


def test_internal_digest_helper_rejects_missing_or_changed_digest():
    value = {"a": 1}
    assert legacy_replay._digest_without(value, "result_digest") is False
    value["result_digest"] = "0" * 64
    assert legacy_replay._digest_without(value, "result_digest") is False


def test_unknown_adapter_fails_closed():
    spec = legacy_replay.LegacyArtifactSpec(
        method="unknown",
        case_id="unknown",
        path=legacy_replay.SPECS[0].path,
        adapter="unknown",
    )
    with pytest.raises(LegacyReplayError, match="unknown legacy adapter"):
        legacy_replay.replay_one(spec)


def test_committed_replay_report_matches_code_and_digest():
    stored = json.loads(DEFAULT_OUTPUT.read_text(encoding="utf-8"))
    digest = stored.pop("report_digest")
    assert digest == sha256_hex(stored)
    rebuilt = build_report()
    rebuilt_digest = rebuilt.pop("report_digest")
    assert rebuilt_digest == digest
    assert rebuilt == stored

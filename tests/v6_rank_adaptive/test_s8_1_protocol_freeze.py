import json

from dvg_obs_ceo.identity import sha256_hex
from dvg_obs_ceo.v6_rank_adaptive.s8_1_protocol_freeze import (
    DEFAULT_OUTPUT,
    freeze_top2,
)


def test_s8_1_freeze_is_order_invariant():
    s7 = json.loads(
        DEFAULT_OUTPUT.parents[1]
        .joinpath("s7/rank-candidate-catalog-v1.json")
        .read_text(encoding="utf-8")
    )
    s8 = json.loads(
        DEFAULT_OUTPUT.parents[1]
        .joinpath("s8/predictor-candidate-freeze-v1.json")
        .read_text(encoding="utf-8")
    )
    forward = freeze_top2(s7, s8)
    reverse = freeze_top2(
        s7,
        s8,
        input_order=tuple(
            reversed(sorted(item["candidate_id"] for item in s7["candidates"]))
        ),
    )
    assert forward == reverse


def test_committed_s8_1_freeze_resolves_both_protocol_issues():
    report = json.loads(DEFAULT_OUTPUT.read_text(encoding="utf-8"))
    digest = report.pop("freeze_digest")
    assert digest == sha256_hex(report)
    assert report["circuit_primary_candidate_ids"] == []
    assert len(report["exploratory_top2_candidate_ids"]) == 2
    assert report["selector_policy"]["risk_aware_claim"] is False
    assert report["pre_outcome_attestation"] == {
        "actual_candidate_energy_observed": False,
        "fci_or_chemical_accuracy_used": False,
        "s9_artifact_absent_when_freeze_created": True,
    }
    assert all(
        not item["circuit_primary_eligible"]
        and item["exploratory_depth_parameter_eligible"]
        and item["exploratory_disclosed_regressions"]
        == ["cnot_count", "cnot_depth"]
        for item in report["assessments"]
    )

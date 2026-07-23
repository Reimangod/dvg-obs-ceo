import json

from dvg_obs_ceo.v5_s11b_s9_fusion import MANIFEST


def test_s11b_is_explicitly_outcome_informed_and_frozen_without_retuning():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["classification"] == "outcome-informed-exploratory-integration"
    assert manifest["status"] == "frozen-after-feasibility-inspection-before-audited-execution"
    assert len(manifest["frozen_candidate_ids"]) == 2
    assert manifest["execution"]["optimizer_starts"] == 0
    assert manifest["execution"]["retuning"] is False
    assert manifest["acceptance"]["all_guarded_resources_nonincrease_from_s9"]


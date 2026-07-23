import json

from dvg_obs_ceo.v5_s11_h6_fusion import MANIFEST


def test_s11_protocol_is_frozen_to_two_s10_candidates_and_no_optimizer():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["status"] == "frozen-before-execution"
    assert len(manifest["frozen_candidate_ids"]) == 2
    assert manifest["execution"]["apply_jointly_against_one_immutable_source"]
    assert manifest["execution"]["optimizer_starts"] == 0
    assert manifest["execution"]["threshold_tuning"] is False
    assert manifest["execution"]["generic_compilation"] is False
    assert manifest["acceptance"]["cnot_reduction_required"] is True
    assert manifest["acceptance"]["parameter_reduction_required"] is True


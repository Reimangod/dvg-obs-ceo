from dvg_obs_ceo.v4_1_s6_regression import h2_h4_regression


def test_h2_h4_semantics_and_source_resources_remain_exact() -> None:
    result = h2_h4_regression()
    assert result["passed"]
    assert result["single_candidate_replays"] == 17
    assert result["stored_joint_batch_replays"] == 420
    assert result["cases"]["h2-1.5-iteration-1"]["source_resources"]["cnot_count"] == 9
    assert result["cases"]["h4-1.5-first-chemical-accuracy"]["source_resources"]["cnot_count"] == 80

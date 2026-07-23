from dvg_obs_ceo.v5_s8_protocol import audit_manifest


def test_v5_s8_protocol_and_all_input_sets_are_bound() -> None:
    result = audit_manifest()
    assert result["passed"]
    assert all(result["checks"].values())
    assert result["inputs"]["h2-1.5-iteration-1"]["row_count"] == 1
    assert result["inputs"]["h4-1.5-first-chemical-accuracy"]["row_count"] == 16
    assert result["inputs"]["h4-1.5-iteration-12-or-convergence"]["row_count"] == 62

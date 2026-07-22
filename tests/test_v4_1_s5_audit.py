from dvg_obs_ceo.v4_1_s5_audit import run


def test_final_s5_bundles_pass_independent_selection_replay() -> None:
    result = run()
    assert result["passed"]
    assert not result["failed_checks"]
    assert set(result["cases"]) == {"h6-1.5", "h6-3.0", "beh2-3.0"}
    assert all(
        case["search_status"] == "budget-truncated"
        and case["sentinel_count"] == 4
        for case in result["cases"].values()
    )

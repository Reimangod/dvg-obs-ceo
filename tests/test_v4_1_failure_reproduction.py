from dvg_obs_ceo.v4_1_failure_reproduction import (
    EXPECTED_SEMANTIC_REASON,
    classify_semantic_reason,
    reproduce,
)


def test_v4_1_reproduces_every_stored_failure_without_unknowns() -> None:
    result = reproduce()
    assert result["passed"]
    assert result["read_only"]
    assert result["unknown_failure_count"] == 0
    assert [case["case_id"] for case in result["cases"]] == [
        "h6-1.5",
        "h6-3.0",
        "beh2-3.0",
    ]


def test_v4_1_reproduces_h6_three_constituent_failure_boundary() -> None:
    cases = {case["case_id"]: case for case in reproduce()["cases"]}
    for case_id in ("h6-1.5", "h6-3.0"):
        case = cases[case_id]
        assert case["catalog"]["registered_source_dimension_gt2_to_ovp_count"] > 0
        assert (
            case["semantic_failure"]["with_registered_source_dimension_gt2_to_ovp"]
            == case["semantic_failure"]["count"]
        )
        assert case["semantic_failure"]["count"] > 0
    assert cases["beh2-3.0"]["semantic_failure"]["count"] == 0


def test_v4_1_failure_classifier_fails_unknown_closed() -> None:
    assert classify_semantic_reason(EXPECTED_SEMANTIC_REASON) != "unknown"
    assert classify_semantic_reason("unexpected") == "unknown"

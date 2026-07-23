from dvg_obs_ceo.v5_s8_lih_polishing_probe_audit import run_audit


def test_polishing_probe_remains_fail_closed():
    result = run_audit()
    assert result["passed"]
    assert result["scientific_result"]["accepted"] is False
    assert result["checks"]["diagnostic_gradient_not_misreported_as_success"]

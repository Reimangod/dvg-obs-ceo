from dvg_obs_ceo.v5_s8_lih_cp_integration_audit import run_audit


def test_lih_cp_static_audit():
    result = run_audit(recompute_quantum=False)
    assert result["passed"]
    assert result["checks"]["polishing_only_when_triggered"]
    assert result["checks"]["finite_difference_hvp_work_counted"]

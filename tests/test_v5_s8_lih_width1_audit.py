from dvg_obs_ceo.v5_s8_lih_width1_audit import run_audit


def test_lih_static_negative_result_audit():
    result = run_audit(recompute_quantum=False)
    assert result["passed"]
    assert result["failed_acceptance_checks"] == ["kkt"]
    assert result["checks"]["rejected_work_not_erased"]

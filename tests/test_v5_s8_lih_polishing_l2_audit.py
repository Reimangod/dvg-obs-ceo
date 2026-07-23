from dvg_obs_ceo.v5_s8_lih_polishing_l2_audit import run_audit


def test_l2_alignment_probe_audit():
    result = run_audit()
    assert result["passed"]
    assert result["checks"]["l2_implies_infinity_certificate"]
    assert result["checks"]["all_independent_acceptance_checks_pass"]

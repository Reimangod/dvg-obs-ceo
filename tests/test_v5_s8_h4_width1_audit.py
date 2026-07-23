from dvg_obs_ceo.v5_s8_h4_width1_audit import run_audit


def test_h4_width1_static_evidence_audit():
    result = run_audit(recompute_quantum=False)
    assert result["passed"]
    assert result["checks"]["screening_information_firewall"]
    assert result["checks"]["pilot_and_amended_scientific_results_match"]
    assert result["paper_measurement_cost"] is None

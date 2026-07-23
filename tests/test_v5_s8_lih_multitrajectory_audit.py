from dvg_obs_ceo.v5_s8_lih_multitrajectory_audit import run_audit


def test_width_two_result_passes_nonquantum_independent_audit():
    audit = run_audit(recompute_quantum=False)
    assert audit["passed"] is True
    assert audit["scientific_result"]["status"] == (
        "valid-negative-width-two-calibration"
    )

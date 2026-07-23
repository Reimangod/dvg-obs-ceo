from dvg_obs_ceo.v5_s8_lih_energy_aware_round3_audit import audit_round3


def test_round3_nonquantum_audit_passes():
    audit = audit_round3(recompute_quantum=False)
    assert audit["passed"] is True
    assert audit["scientific_result"]["status"] == (
        "valid-round3-no-endpoint-improvement-structural-floor-indicated"
    )

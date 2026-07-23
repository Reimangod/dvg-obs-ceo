from dvg_obs_ceo.v5_s8_lih_energy_aware_width4_audit import audit_width4


def test_width4_nonquantum_audit_passes():
    audit = audit_width4(recompute_quantum=False)
    assert audit["passed"] is True
    assert audit["scientific_result"]["status"] == (
        "valid-width4-no-endpoint-improvement-structural-floor-supported"
    )

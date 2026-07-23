from dvg_obs_ceo.v5_s8_lih_energy_aware_audit import run_audit


def test_energy_aware_v2_nonquantum_audit_passes():
    audit = run_audit(recompute_quantum=False)
    assert audit["passed"] is True
    assert audit["scientific_result"]["status"] == (
        "valid-accounting-complete-no-endpoint-improvement"
    )

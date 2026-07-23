from dvg_obs_ceo.s12_audit import audit


def test_s12_h2_and_lih_artifacts_pass_independent_audit() -> None:
    result = audit()
    assert result["passed"] is True
    assert result["raw_ledger_manifest_consistent"] is True
    assert result["cases"]["h2-1.5"]["fresh_reduction"] == 8
    assert result["cases"]["lih-3.0"]["fresh_reduction"] == 369

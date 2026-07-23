from dvg_obs_ceo.v5_s8_small_calibration import run


def test_small_system_calibration_uses_all_rows_without_lih() -> None:
    result = run()
    assert result["passed"]
    assert result["pooled_candidate_count"] == 79
    assert result["provisional_scientific_decisions"]["lih_inspected_for_choice"] is False
    assert result["provisional_scientific_decisions"]["global_empirical_energy_margin_hartree"] is None
    assert result["paper_measurement_cost"] is None

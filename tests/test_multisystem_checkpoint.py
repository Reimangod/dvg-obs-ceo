from dvg_obs_ceo.multisystem_checkpoint import registered_cases


def test_full_figure_cases_are_explicit_and_thresholds_match_qubit_counts() -> None:
    cases = registered_cases()
    assert set(cases) == {"h6-3.0", "beh2-3.0", "h6-1.5", "beh2-2.0"}
    assert all(cases[name]["gradient_threshold"] == 1e-6 for name in ("h6-3.0", "h6-1.5"))
    assert all(cases[name]["gradient_threshold"] == 1e-5 for name in ("beh2-3.0", "beh2-2.0"))

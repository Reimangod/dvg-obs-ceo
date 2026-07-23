from dvg_obs_ceo.paper_equivalent_figures import load_figure_data


def test_paper_equivalent_figure_inputs_are_audited() -> None:
    data = load_figure_data()
    assert all(data["checks"].values())
    assert len(data["gsd"]) == 6
    assert len(data["ceo"]) == 5
    assert data["v4"]["cnot_count"] == 58
    assert data["v4"]["paper_measurement_cost"] is None

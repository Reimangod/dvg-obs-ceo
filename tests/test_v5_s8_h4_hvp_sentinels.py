from dvg_obs_ceo.v5_s8_h4_hvp_sentinels import select_prediction_sentinels


def row(candidate_id, predicted, actual):
    return {
        "candidate": {"candidate_id": candidate_id},
        "predictors": {"general_constraint_obs": predicted},
        "actual_change_hartree": actual,
    }


def test_sentinel_selection_is_prediction_only_and_deterministic() -> None:
    rows = [
        row("candidate:a", 1e-6, 9.0),
        row("candidate:b", 9e-5, -9.0),
        row("candidate:c", 1.1e-4, 5.0),
        row("candidate:d", 1e-2, -5.0),
    ]
    selected = select_prediction_sentinels(rows, 1e-4)
    changed_outcomes = [{**item, "actual_change_hartree": 100.0} for item in reversed(rows)]
    assert selected == select_prediction_sentinels(changed_outcomes, 1e-4)
    assert [item["stratum"] for item in selected] == [
        "low-predicted-loss", "budget-boundary", "high-predicted-loss"
    ]

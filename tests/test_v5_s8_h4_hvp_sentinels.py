from types import SimpleNamespace

from dvg_obs_ceo.v5_s8_h4_hvp_sentinels import (
    map_versioned_rows_to_current_candidates,
    select_prediction_sentinels,
)


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


def test_versioned_ids_are_mapped_by_physical_primitive() -> None:
    stored = {
        "candidate_id": "old-id",
        "kind": "block-deletion",
        "source_pool_indices": [4],
        "target_family": "empty",
        "target_pool_indices": [],
        "removed_source_slots": [0],
        "exact_generator_relation": None,
        "target_operator_digests": [],
        "semantic_conflict_positions": [0],
    }
    current = SimpleNamespace(
        candidate_id="new-id",
        kind="block-deletion",
        source_pool_indices=(4,),
        target_family="empty",
        target_pool_indices=(),
        removed_source_slots=(0,),
        exact_generator_relation=(1,),
        target_operator_digests=(),
        semantic_conflict_positions=(0,),
    )
    mapping = map_versioned_rows_to_current_candidates([{"candidate": stored}], [current])
    assert mapping == {"old-id": current}

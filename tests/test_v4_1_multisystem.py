from types import SimpleNamespace

import pytest

from dvg_obs_ceo.global_selector import GlobalResourceCandidate
from dvg_obs_ceo.telemetry import ResourceSnapshot
from dvg_obs_ceo.v4_1_multisystem import (
    V41MultiSystemError,
    replay_selected_sentinel_evidence,
    select_v4_1_sentinels,
)


def _candidate(name, resources):
    return GlobalResourceCandidate(
        (name,), "semantic:" + name, "numerical:" + name, 5e-5,
        ResourceSnapshot(*resources, "test", name * 64),
    )


def test_four_endpoint_selection_is_bounded_and_replayable() -> None:
    source = ResourceSnapshot(100, 100, 100, 10, 10, "test", "e" * 64)
    candidates = [
        _candidate("a", (50, 90, 90, 9, 9)),
        _candidate("b", (90, 50, 80, 8, 8)),
        _candidate("c", (80, 80, 50, 7, 7)),
        _candidate("d", (70, 70, 70, 5, 5)),
    ]
    first = select_v4_1_sentinels(candidates, source, screening_budget_hartree=1e-4)
    second = select_v4_1_sentinels(list(reversed(candidates)), source, screening_budget_hartree=1e-4)
    assert first == second
    assert len(first["unique_attempt_semantic_ids"]) <= 4
    assert first["cnot_primary"][0] == "semantic:a"
    assert first["cnot_depth_primary"][0] == "semantic:b"
    assert first["total_depth_primary"][0] == "semantic:c"
    assert first["parameter_primary"][0] == "semantic:d"


def test_full_prediction_evidence_is_replayed_only_for_selected_sentinels() -> None:
    evidence = {
        "semantic:a": {
            "candidate_ids": ["a"], "constraint_numerical_id": "numerical:a"
        },
        "semantic:b": {
            "candidate_ids": ["b"], "constraint_numerical_id": "numerical:b"
        },
        "semantic:not-selected": {
            "candidate_ids": ["c"], "constraint_numerical_id": "numerical:c"
        },
    }
    calls = []

    def predictor(candidate_ids):
        calls.append(candidate_ids)
        name = candidate_ids[0]
        state = SimpleNamespace(
            constraint_semantic_id="semantic:" + name,
            constraint_numerical_id="numerical:" + name,
        )
        return SimpleNamespace(state=state), {"prediction": name}, {"passed": True}

    result = replay_selected_sentinel_evidence(
        {"unique_attempt_semantic_ids": ["semantic:b", "semantic:a"]},
        evidence,
        predictor,
    )
    assert calls == [("b",), ("a",)]
    assert [item["prediction"] for item in result] == [
        {"prediction": "b"}, {"prediction": "a"}
    ]


def test_selected_sentinel_replay_fails_closed_on_identity_drift() -> None:
    evidence = {
        "semantic:a": {
            "candidate_ids": ["a"], "constraint_numerical_id": "numerical:a"
        }
    }
    bad_state = SimpleNamespace(
        constraint_semantic_id="semantic:changed",
        constraint_numerical_id="numerical:a",
    )
    with pytest.raises(V41MultiSystemError, match="replay drift"):
        replay_selected_sentinel_evidence(
            {"unique_attempt_semantic_ids": ["semantic:a"]},
            evidence,
            lambda _ids: (
                SimpleNamespace(state=bad_state), {}, {"passed": True}
            ),
        )

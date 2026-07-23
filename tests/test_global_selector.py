import pytest

from dvg_obs_ceo.global_selector import (
    GlobalResourceCandidate,
    GlobalSelectorError,
    select_global_candidates,
)
from dvg_obs_ceo.telemetry import ResourceSnapshot


def _resource(cnot, cnot_depth, depth, parameters, digest):
    return ResourceSnapshot(cnot, cnot_depth, depth, parameters, parameters, "test", digest * 64)


def _candidate(identifier, loss, resources, numerical=None):
    return GlobalResourceCandidate(
        ("candidate:" + identifier,), "semantic:" + identifier,
        numerical or "numerical:" + identifier, loss, resources,
    )


def test_co_primary_ranking_and_componentwise_guards() -> None:
    source = _resource(100, 40, 150, 10, "a")
    candidates = [
        _candidate("circuit", 8e-5, _resource(70, 35, 120, 9, "b")),
        _candidate("parameter", 7e-5, _resource(80, 30, 110, 7, "c")),
        _candidate("regression", 1e-5, _resource(60, 41, 100, 6, "d")),
        _candidate("budget", 2e-4, _resource(50, 20, 90, 5, "e")),
    ]
    result = select_global_candidates(candidates, source)
    assert result["circuit_primary"][0] == "semantic:circuit"
    assert result["parameter_primary"][0] == "semantic:parameter"
    assert result["eligible_count"] == 2
    assert result["unique_attempt_semantic_ids"] == ["semantic:circuit", "semantic:parameter"]


def test_structure_dedup_uses_loss_then_semantic_id_and_is_replayable() -> None:
    source = _resource(100, 40, 150, 10, "a")
    shared = _resource(70, 30, 100, 7, "b")
    candidates = [_candidate("z", 5e-5, shared), _candidate("a", 4e-5, shared)]
    first = select_global_candidates(candidates, source)
    second = select_global_candidates(list(reversed(candidates)), source)
    assert first == second
    assert first["deduplicated_structure_count"] == 1
    assert first["circuit_primary"] == ["semantic:a"]
    assert first["structure_aliases"]["b" * 64] == ["semantic:a", "semantic:z"]


def test_same_digest_conflicting_resources_fails_closed() -> None:
    source = _resource(100, 40, 150, 10, "a")
    with pytest.raises(GlobalSelectorError, match="conflicting"):
        select_global_candidates(
            [_candidate("a", 1e-5, _resource(70, 30, 100, 7, "b")),
             _candidate("b", 1e-5, _resource(71, 30, 100, 7, "b"))],
            source,
        )

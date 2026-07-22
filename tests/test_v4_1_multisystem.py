from dvg_obs_ceo.global_selector import GlobalResourceCandidate
from dvg_obs_ceo.telemetry import ResourceSnapshot
from dvg_obs_ceo.v4_1_multisystem import select_v4_1_sentinels


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

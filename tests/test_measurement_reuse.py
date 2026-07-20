import hashlib

import pytest

from dvg_obs_ceo.measurement_reuse import (
    ExactPauliRequest,
    ExactPauliReuseCache,
    MeasurementReuseError,
    canonical_pauli_string,
)


def request(*, state="a", problem="b", context="c", pauli="X0 Z2", shots=None):
    return ExactPauliRequest(
        "state-v1:" + state * 64,
        "problem-v1:" + problem * 64,
        pauli,
        "exact-statevector-pauli-v1",
        hashlib.sha256(b"backend").hexdigest(),
        "measurement-v1:" + context * 64,
        shots,
    )


def test_cross_observable_context_reuse_requires_same_semantic_term() -> None:
    calls = 0

    def evaluate(_: str) -> float:
        nonlocal calls
        calls += 1
        return 0.25

    cache = ExactPauliReuseCache(enabled=True)
    assert cache.evaluate(request(context="c"), evaluate) == 0.25
    assert cache.evaluate(request(context="d", pauli="Z2 X0"), evaluate) == 0.25
    report = cache.report()
    assert calls == 1
    assert report["cache_hits"] == 1
    assert report["events"][1]["source_measurement_context_id"].endswith("c" * 64)


def test_different_state_or_problem_never_hits() -> None:
    calls = 0

    def evaluate(_: str) -> float:
        nonlocal calls
        calls += 1
        return -0.5

    cache = ExactPauliReuseCache(enabled=True)
    cache.evaluate(request(), evaluate)
    cache.evaluate(request(state="d"), evaluate)
    cache.evaluate(request(problem="e"), evaluate)
    assert calls == 3
    assert cache.report()["cache_hits"] == 0


def test_reuse_off_is_value_equivalent_and_performs_every_request() -> None:
    cache = ExactPauliReuseCache(enabled=False)
    values = [cache.evaluate(request(context=value), lambda _: 0.125) for value in ("c", "d")]
    assert values == [0.125, 0.125]
    assert cache.report()["fresh_pauli_expectation_evaluations"] == 2
    assert cache.report()["cache_hits"] == 0
    assert cache.report()["unique_cached_records"] == 0


def test_finite_shot_or_noncanonical_request_fails_closed() -> None:
    with pytest.raises(MeasurementReuseError, match="exact noiseless"):
        request(shots=100)
    with pytest.raises(MeasurementReuseError, match="invalid"):
        canonical_pauli_string("A0")
    with pytest.raises(MeasurementReuseError, match="repeats"):
        canonical_pauli_string("X0 Z0")

from copy import deepcopy
import json
from pathlib import Path

import pytest

from dvg_obs_ceo.v5_ledger import (
    V5EventContext,
    V5EventLedger,
    V5LedgerError,
    V5WorkCounters,
    audit_events,
    versioned_id,
)
from dvg_obs_ceo.v5_ledger_audit import run_audit


def context() -> V5EventContext:
    return V5EventContext(
        ledger_id=versioned_id("ledger-v5", "test"),
        run_id=versioned_id("run-v5", "test"),
        path_id=versioned_id("path-v5", "test"),
        case_id="h2-test",
        code_commit="a" * 40,
        parent_checkpoint_digest="b" * 64,
        state_preparation_id="state-v1:" + "c" * 64,
        problem_id="problem-v1:" + "d" * 64,
        measurement_context_id="measurement-v1:" + "e" * 64,
    )


def test_v5_ledger_round_trip_and_semantic_audit(tmp_path: Path) -> None:
    ledger = V5EventLedger(tmp_path / "events.jsonl", context())
    ledger.append("run_started", round_index=0, work=V5WorkCounters(), payload={})
    ledger.append(
        "round_started",
        round_index=1,
        work=V5WorkCounters(attempted_rounds=1),
        payload={"ranking_frozen": True},
    )
    ledger.append(
        "round_rolled_back",
        round_index=1,
        work=V5WorkCounters(attempted_rounds=1),
        payload={"reason": "no_candidate"},
    )
    ledger.append(
        "run_finished",
        round_index=1,
        work=V5WorkCounters(attempted_rounds=1),
        payload={"status": "no_improvement"},
    )
    result = audit_events(ledger.read_all())
    assert result["passed"]
    assert result["finished"]


def test_v5_ledger_rejects_actual_energy_in_screening(tmp_path: Path) -> None:
    ledger = V5EventLedger(tmp_path / "events.jsonl", context())
    ledger.append("run_started", round_index=0, work=V5WorkCounters(), payload={})
    ledger.append("round_started", round_index=1, work=V5WorkCounters(attempted_rounds=1), payload={})
    with pytest.raises(V5LedgerError, match="forbidden actual/FCI"):
        ledger.append(
            "candidate_screened",
            round_index=1,
            work=V5WorkCounters(attempted_rounds=1),
            candidate_id=versioned_id("candidate-v5", "candidate"),
            payload={"nested": {"fci_energy_hartree": -1.0}},
        )


def test_v5_ledger_rejects_work_regression(tmp_path: Path) -> None:
    ledger = V5EventLedger(tmp_path / "events.jsonl", context())
    ledger.append("run_started", round_index=0, work=V5WorkCounters(energy_evaluations=2), payload={})
    with pytest.raises(V5LedgerError, match="work counter regressed"):
        ledger.append("round_started", round_index=1, work=V5WorkCounters(), payload={})


def test_v5_ledger_rejects_context_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    ledger = V5EventLedger(path, context())
    ledger.append("run_started", round_index=0, work=V5WorkCounters(), payload={})
    other = deepcopy(context())
    object.__setattr__(other, "path_id", versioned_id("path-v5", "other"))
    with pytest.raises(V5LedgerError, match="context"):
        V5EventLedger(path, other).read_all()


def test_v5_ledger_detects_truncation_and_tampering(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    ledger = V5EventLedger(path, context())
    ledger.append("run_started", round_index=0, work=V5WorkCounters(), payload={})
    path.write_bytes(path.read_bytes()[:-1])
    with pytest.raises(V5LedgerError, match="partial"):
        ledger.read_all()

    path.unlink()
    ledger.append("run_started", round_index=0, work=V5WorkCounters(), payload={})
    event = json.loads(path.read_text(encoding="utf-8"))
    event["case_id"] = "other"
    path.write_text(json.dumps(event) + "\n", encoding="utf-8")
    with pytest.raises(V5LedgerError, match="digest mismatch"):
        ledger.read_all()


def test_v5_ledger_rejects_commit_without_exact_finish(tmp_path: Path) -> None:
    ledger = V5EventLedger(tmp_path / "events.jsonl", context())
    ledger.append("run_started", round_index=0, work=V5WorkCounters(), payload={})
    ledger.append("round_started", round_index=1, work=V5WorkCounters(attempted_rounds=1), payload={})
    with pytest.raises(V5LedgerError, match="without a completed exact attempt"):
        ledger.append(
            "round_committed",
            round_index=1,
            work=V5WorkCounters(attempted_rounds=1, accepted_rounds=1),
            candidate_id=versioned_id("candidate-v5", "candidate"),
            payload={"checkpoint_digest": "f" * 64},
        )


def test_v5_ledger_allows_context_change_only_after_commit(tmp_path: Path) -> None:
    ledger = V5EventLedger(tmp_path / "events.jsonl", context())
    zero = V5WorkCounters()
    started = V5WorkCounters(attempted_rounds=1)
    exact = V5WorkCounters(attempted_rounds=1, exact_vqe_attempts=1)
    accepted = V5WorkCounters(attempted_rounds=1, accepted_rounds=1, exact_vqe_attempts=1)
    candidate = versioned_id("candidate-v5", "candidate")
    ledger.append("run_started", round_index=0, work=zero, payload={})
    ledger.append("round_started", round_index=1, work=started, payload={})
    ledger.append("exact_attempt_started", round_index=1, work=started, candidate_id=candidate, payload={})
    ledger.append("exact_attempt_finished", round_index=1, work=exact, candidate_id=candidate, payload={"actual_energy_increase_hartree": 1e-5})
    ledger.append("round_committed", round_index=1, work=accepted, candidate_id=candidate, payload={"checkpoint_digest": "f" * 64})

    next_context = V5EventContext(
        **{
            **context().__dict__,
            "parent_checkpoint_digest": "f" * 64,
            "state_preparation_id": "state-v1:" + "1" * 64,
            "measurement_context_id": "measurement-v1:" + "2" * 64,
        }
    )
    ledger.append(
        "round_started",
        round_index=2,
        work=V5WorkCounters(attempted_rounds=2, accepted_rounds=1, exact_vqe_attempts=1),
        payload={},
        event_context=next_context,
    )
    assert audit_events(ledger.read_all())["passed"]


def test_v5_ledger_rejects_context_change_inside_round(tmp_path: Path) -> None:
    ledger = V5EventLedger(tmp_path / "events.jsonl", context())
    ledger.append("run_started", round_index=0, work=V5WorkCounters(), payload={})
    ledger.append("round_started", round_index=1, work=V5WorkCounters(attempted_rounds=1), payload={})
    changed = V5EventContext(
        **{
            **context().__dict__,
            "state_preparation_id": "state-v1:" + "1" * 64,
            "measurement_context_id": "measurement-v1:" + "2" * 64,
        }
    )
    with pytest.raises(V5LedgerError, match="changed inside a round"):
        ledger.append(
            "candidate_screened",
            round_index=1,
            work=V5WorkCounters(attempted_rounds=1),
            candidate_id=versioned_id("candidate-v5", "candidate"),
            payload={"predicted_energy_increase_hartree": 1e-5},
            event_context=changed,
        )


def test_v5_work_counters_reject_bool_negative_and_float() -> None:
    with pytest.raises(V5LedgerError):
        V5WorkCounters(energy_evaluations=-1)
    with pytest.raises(V5LedgerError):
        V5WorkCounters(energy_evaluations=True)
    with pytest.raises(V5LedgerError):
        V5WorkCounters(energy_evaluations=1.0)  # type: ignore[arg-type]


def test_v5_s1_independent_failure_injection_audit() -> None:
    result = run_audit()
    assert result["passed"]
    assert all(result["failure_injections"].values())

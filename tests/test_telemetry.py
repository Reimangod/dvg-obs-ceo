import json
from pathlib import Path

import pytest

from dvg_obs_ceo.telemetry import (
    EventLedger,
    OptimizerDiagnostics,
    ResourceSnapshot,
    TelemetryError,
    WorkCounters,
)


def test_append_round_trip_and_hash_chain(tmp_path: Path) -> None:
    ledger = EventLedger(tmp_path / "events.jsonl", "run-1")
    first = ledger.append("run-started", {"problem_id": "problem-v1:" + "a" * 64}, emitted_at_utc="2026-07-20T00:00:00Z")
    second = ledger.append("resource-snapshot", {"cnot_count": 9}, emitted_at_utc="2026-07-20T00:00:01Z")
    events = ledger.read_all()
    assert events == (first, second)
    assert second["previous_event_digest"] == first["event_digest"]


def test_tampering_is_detected_before_next_append(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    ledger = EventLedger(path, "run-1")
    ledger.append("energy", {"value": -1.0}, emitted_at_utc="2026-07-20T00:00:00Z")
    event = json.loads(path.read_text())
    event["payload"]["value"] = -2.0
    path.write_text(json.dumps(event) + "\n")
    with pytest.raises(TelemetryError):
        ledger.read_all()
    with pytest.raises(TelemetryError):
        ledger.append("energy", {"value": -3.0})


def test_truncated_final_record_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    ledger = EventLedger(path, "run-1")
    ledger.append("energy", {"value": -1.0}, emitted_at_utc="2026-07-20T00:00:00Z")
    path.write_bytes(path.read_bytes()[:-1])
    with pytest.raises(TelemetryError, match="partial record"):
        ledger.read_all()


def test_invalid_timestamp_is_rejected(tmp_path: Path) -> None:
    ledger = EventLedger(tmp_path / "events.jsonl", "run-1")
    with pytest.raises(TelemetryError, match="schema validation"):
        ledger.append("energy", {"value": -1.0}, emitted_at_utc="not-a-time")


def test_diagnostics_reject_invalid_values() -> None:
    WorkCounters(energy_evaluations=1)
    ResourceSnapshot(9, 7, 20, 1, 1, "paper-era-v1", "a" * 64)
    OptimizerDiagnostics("bfgs", True, "converged", "ok", 2, 3, 3, 1e-8, 1e-8, 1e-8, 1e-8, 1e-8)
    with pytest.raises(TelemetryError):
        WorkCounters(shots=-1)
    with pytest.raises(TelemetryError):
        ResourceSnapshot(9, 7, 20, 1, 1, "paper-era-v1", "A" * 64)
    with pytest.raises(TelemetryError):
        OptimizerDiagnostics("bfgs", False, "failed", "bad", 2, -1, 3, 0.0, 0.0, 0.0, None, None)
    with pytest.raises(TelemetryError):
        OptimizerDiagnostics("bfgs", False, "failed", "bad", 2, 3, 3, float("nan"), 0.0, 0.0, None, None)

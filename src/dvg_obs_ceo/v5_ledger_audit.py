"""Independent V5-S1 ledger schema and failure-injection audit."""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from typing import Any, Callable

from .v3_protocol import _write_exclusive
from .v5_ledger import (
    V5EventContext,
    V5EventLedger,
    V5LedgerError,
    V5WorkCounters,
    audit_events,
    versioned_id,
)


def _context() -> V5EventContext:
    return V5EventContext(
        ledger_id=versioned_id("ledger-v5", "s1-audit"),
        run_id=versioned_id("run-v5", "s1-audit"),
        path_id=versioned_id("path-v5", "s1-audit"),
        case_id="synthetic-s1",
        code_commit="a" * 40,
        parent_checkpoint_digest="b" * 64,
        state_preparation_id="state-v1:" + "c" * 64,
        problem_id="problem-v1:" + "d" * 64,
        measurement_context_id="measurement-v1:" + "e" * 64,
    )


def _valid_records(path: Path) -> tuple[dict[str, Any], ...]:
    ledger = V5EventLedger(path, _context())
    zero = V5WorkCounters()
    one_round = V5WorkCounters(attempted_rounds=1)
    exact = V5WorkCounters(
        energy_evaluations=2,
        gradient_vector_evaluations=1,
        gradient_component_equivalents=4,
        exact_vqe_attempts=1,
        optimizer_iterations=2,
        optimizer_starts=1,
        full_resource_recounts=1,
        attempted_rounds=1,
        statevector_evaluations=2,
    )
    accepted = V5WorkCounters(**{**exact.to_dict(), "accepted_rounds": 1})
    candidate = versioned_id("candidate-v5", "s1-candidate")
    timestamp = "2026-07-23T00:00:00Z"
    ledger.append("run_started", round_index=0, work=zero, payload={"role": "development"}, emitted_at_utc=timestamp)
    ledger.append("round_started", round_index=1, work=one_round, payload={"ranking_frozen": True}, emitted_at_utc=timestamp)
    ledger.append(
        "candidate_screened",
        round_index=1,
        work=one_round,
        candidate_id=candidate,
        payload={"predicted_energy_increase_hartree": 5e-5, "cnot_reduction": 7},
        emitted_at_utc=timestamp,
    )
    ledger.append("exact_attempt_started", round_index=1, work=one_round, candidate_id=candidate, payload={"attempt": 1}, emitted_at_utc=timestamp)
    ledger.append(
        "exact_attempt_finished",
        round_index=1,
        work=exact,
        candidate_id=candidate,
        payload={"actual_energy_increase_hartree": 6e-5, "stationarity_infinity": 1e-9},
        emitted_at_utc=timestamp,
    )
    ledger.append("round_committed", round_index=1, work=accepted, candidate_id=candidate, payload={"checkpoint_digest": "f" * 64}, emitted_at_utc=timestamp)
    ledger.append("run_finished", round_index=1, work=accepted, payload={"status": "completed"}, emitted_at_utc=timestamp)
    return ledger.read_all()


def _fails(records: tuple[dict[str, Any], ...], mutator: Callable[[list[dict[str, Any]]], None]) -> bool:
    changed = deepcopy(list(records))
    mutator(changed)
    try:
        audit_events(changed)
    except V5LedgerError:
        return True
    return False


def run_audit() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="v5-s1-audit-") as directory:
        records = _valid_records(Path(directory) / "events.jsonl")
    base = audit_events(records)

    def leak_actual(changed: list[dict[str, Any]]) -> None:
        changed[2]["payload"]["actual_energy_hartree"] = -1.0

    def regress_work(changed: list[dict[str, Any]]) -> None:
        changed[5]["work"]["energy_evaluations"] = 0

    def cross_path(changed: list[dict[str, Any]]) -> None:
        changed[3]["path_id"] = versioned_id("path-v5", "other")

    def duplicate_event(changed: list[dict[str, Any]]) -> None:
        changed[4]["event_id"] = changed[3]["event_id"]

    def break_parent(changed: list[dict[str, Any]]) -> None:
        changed[3]["parent_checkpoint_digest"] = "9" * 64

    def truncate_sequence(changed: list[dict[str, Any]]) -> None:
        changed[4]["sequence"] = 99

    injections = {
        "screening_actual_energy_leak": _fails(records, leak_actual),
        "work_counter_regression": _fails(records, regress_work),
        "cross_path_injection": _fails(records, cross_path),
        "duplicate_event_id": _fails(records, duplicate_event),
        "parent_checkpoint_tamper": _fails(records, break_parent),
        "noncontiguous_sequence": _fails(records, truncate_sequence),
    }
    checks = {
        "valid_ledger_passes": base["passed"] and base["finished"],
        "seven_events_recorded": base["event_count"] == 7,
        "all_failure_injections_detected": all(injections.values()),
        "actual_values_are_exact_only": all(
            "actual_energy_increase_hartree" not in event["payload"]
            for event in records
            if event["phase"] == "screening"
        ),
        "work_is_monotonic": base["checks"]["monotonic_work"],
        "path_is_hash_chained": base["checks"]["hash_chain"],
    }
    result = {
        "schema_version": "1.0.0",
        "artifact_kind": "v5-s1-ledger-independent-audit",
        "passed": all(checks.values()),
        "checks": checks,
        "failure_injections": injections,
        "event_count": base["event_count"],
        "last_event_digest": base["last_event_digest"],
        "claim_boundary": "Synthetic schema, information-firewall, and failure-injection evidence only; no molecular candidate or performance claim.",
    }
    if not result["passed"]:
        raise V5LedgerError("V5-S1 independent audit failed")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-path", type=Path)
    arguments = parser.parse_args()
    result = run_audit()
    if arguments.artifact_path is not None:
        _write_exclusive(arguments.artifact_path, result)
    print(json.dumps({"passed": result["passed"], "checks": len(result["checks"])}, sort_keys=True))


if __name__ == "__main__":
    main()

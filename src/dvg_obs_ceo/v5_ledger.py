"""V5 path-scoped immutable scientific ledger with semantic validation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping

from jsonschema import Draft202012Validator, FormatChecker

from .baseline import ROOT
from .identity import canonical_json_bytes


SCHEMA_VERSION = "v5-ledger-event-v1"
PROTOCOL_ID = "dvg-obs-v5-risk-aware-sequential-protocol-v1"
SCHEMA_PATH = ROOT / "schemas" / "v5-ledger-event-v1.schema.json"
GENESIS_DIGEST = "0" * 64
SCREENING_EVENT_TYPES = {"candidate_screened", "candidate_rejected"}
ACTUAL_ONLY_KEYS = {
    "actual_energy_hartree",
    "actual_energy_increase_hartree",
    "actual_preoptimization_energy_hartree",
    "actual_postoptimization_energy_hartree",
    "exact_energy_hartree",
    "fci_energy_hartree",
    "chemical_accuracy_margin_hartree",
}
EVENT_PHASE = {
    "run_started": "control",
    "round_started": "control",
    "candidate_screened": "screening",
    "candidate_rejected": "screening",
    "hvp_refinement": "refinement",
    "exact_attempt_started": "exact",
    "exact_attempt_finished": "exact",
    "round_committed": "commit",
    "round_rolled_back": "rollback",
    "run_finished": "control",
    "incident": "incident",
}
CANDIDATE_EVENT_TYPES = {
    "candidate_screened",
    "candidate_rejected",
    "hvp_refinement",
    "exact_attempt_started",
    "exact_attempt_finished",
    "round_committed",
}


class V5LedgerError(RuntimeError):
    """Raised when a V5 scientific ledger is unsafe or internally inconsistent."""


@dataclass(frozen=True)
class V5WorkCounters:
    energy_evaluations: int = 0
    gradient_vector_evaluations: int = 0
    gradient_component_equivalents: int = 0
    analytic_hvp_calls: int = 0
    finite_difference_hvp_calls: int = 0
    quadratic_solve_iterations: int = 0
    exact_vqe_attempts: int = 0
    optimizer_iterations: int = 0
    optimizer_starts: int = 0
    full_resource_recounts: int = 0
    expanded_search_states: int = 0
    attempted_rounds: int = 0
    accepted_rounds: int = 0
    statevector_evaluations: int = 0

    def __post_init__(self) -> None:
        if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in asdict(self).values()):
            raise V5LedgerError("V5 work counters must be non-negative integers")

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass(frozen=True)
class V5EventContext:
    ledger_id: str
    run_id: str
    path_id: str
    case_id: str
    code_commit: str
    parent_checkpoint_digest: str
    state_preparation_id: str
    problem_id: str
    measurement_context_id: str

    def identities(self) -> dict[str, str]:
        return {
            "state_preparation_id": self.state_preparation_id,
            "problem_id": self.problem_id,
            "measurement_context_id": self.measurement_context_id,
        }


def versioned_id(prefix: str, value: Any) -> str:
    return f"{prefix}:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _validator() -> Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(dict(value))).hexdigest()


def _recursive_keys(value: Any) -> set[str]:
    if isinstance(value, Mapping):
        result = set(str(key) for key in value)
        for item in value.values():
            result.update(_recursive_keys(item))
        return result
    if isinstance(value, (list, tuple)):
        result: set[str] = set()
        for item in value:
            result.update(_recursive_keys(item))
        return result
    return set()


def validate_event(event: Mapping[str, Any]) -> None:
    errors = sorted(
        _validator().iter_errors(dict(event)),
        key=lambda error: tuple(str(item) for item in error.absolute_path),
    )
    if errors:
        details = "; ".join(
            f"{'/'.join(str(item) for item in error.absolute_path) or '<root>'}: {error.message}"
            for error in errors
        )
        raise V5LedgerError("V5 event schema validation failed: " + details)
    timestamp = event["emitted_at_utc"]
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as error:
        raise V5LedgerError("V5 event timestamp is invalid") from error
    if not timestamp.endswith("Z") or parsed.tzinfo != timezone.utc:
        raise V5LedgerError("V5 event timestamp must be UTC with a Z suffix")
    content = dict(event)
    observed = content.pop("event_digest")
    if _digest(content) != observed:
        raise V5LedgerError("V5 event digest mismatch")
    if EVENT_PHASE[event["event_type"]] != event["phase"]:
        raise V5LedgerError("V5 event type and phase disagree")
    candidate_id = event["candidate_id"]
    if (event["event_type"] in CANDIDATE_EVENT_TYPES) != (candidate_id is not None):
        raise V5LedgerError("V5 candidate event identity is missing or misplaced")
    if event["event_type"] in SCREENING_EVENT_TYPES:
        leaked = ACTUAL_ONLY_KEYS.intersection(_recursive_keys(event["payload"]))
        if leaked:
            raise V5LedgerError("screening event contains forbidden actual/FCI fields: " + ", ".join(sorted(leaked)))


def audit_events(events: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    records = tuple(dict(event) for event in events)
    if not records:
        raise V5LedgerError("V5 ledger must contain at least one event")
    previous_digest = GENESIS_DIGEST
    stable_fields = ("protocol_id", "ledger_id", "run_id", "path_id", "case_id", "code_commit")
    expected_stable = {field: records[0].get(field) for field in stable_fields}
    problem_id = records[0].get("identities", {}).get("problem_id")
    event_ids: set[str] = set()
    previous_work: dict[str, int] | None = None
    current_round = 0
    round_open = False
    active_parent_checkpoint: str | None = None
    active_state_id: str | None = None
    active_measurement_id: str | None = None
    expected_next_parent: str | None = records[0]["parent_checkpoint_digest"]
    exact_started: set[tuple[int, str]] = set()
    exact_finished: set[tuple[int, str]] = set()
    finished = False

    for sequence, event in enumerate(records):
        validate_event(event)
        if event["sequence"] != sequence:
            raise V5LedgerError("V5 ledger sequence is not contiguous")
        if event["previous_event_digest"] != previous_digest:
            raise V5LedgerError("V5 ledger hash chain is broken")
        previous_digest = event["event_digest"]
        if any(event[field] != expected_stable[field] for field in stable_fields):
            raise V5LedgerError("V5 run/path/case/protocol identity changed inside ledger")
        if event["identities"]["problem_id"] != problem_id:
            raise V5LedgerError("ProblemID changed inside a V5 path ledger")
        if event["event_id"] in event_ids:
            raise V5LedgerError("V5 event ID is duplicated")
        event_ids.add(event["event_id"])
        if finished:
            raise V5LedgerError("V5 ledger contains an event after run_finished")

        work = event["work"]
        if previous_work is not None and any(work[key] < previous_work[key] for key in work):
            raise V5LedgerError("V5 work counter regressed")
        previous_work = dict(work)

        event_type = event["event_type"]
        round_index = event["round_index"]
        if sequence == 0:
            if event_type != "run_started" or round_index != 0:
                raise V5LedgerError("V5 ledger must begin with round-zero run_started")
            continue
        if event_type == "run_started":
            raise V5LedgerError("V5 ledger contains a duplicate run_started event")
        if event_type == "round_started":
            if round_open or round_index != current_round + 1:
                raise V5LedgerError("V5 round_started is out of order")
            if expected_next_parent is not None and event["parent_checkpoint_digest"] != expected_next_parent:
                raise V5LedgerError("V5 round parent checkpoint does not match the prior commit/rollback")
            current_round = round_index
            round_open = True
            active_parent_checkpoint = event["parent_checkpoint_digest"]
            active_state_id = event["identities"]["state_preparation_id"]
            active_measurement_id = event["identities"]["measurement_context_id"]
            continue
        if event_type == "run_finished":
            if round_open or round_index != current_round:
                raise V5LedgerError("V5 run_finished occurred with an open or wrong round")
            finished = True
            continue
        if event_type == "incident":
            if round_index not in {current_round, 0}:
                raise V5LedgerError("V5 incident has the wrong round index")
            continue
        if not round_open or round_index != current_round:
            raise V5LedgerError("V5 round event occurred outside its open round")
        if (
            event["parent_checkpoint_digest"] != active_parent_checkpoint
            or event["identities"]["state_preparation_id"] != active_state_id
            or event["identities"]["measurement_context_id"] != active_measurement_id
        ):
            raise V5LedgerError("V5 parent/state/measurement context changed inside a round")

        candidate_id = event["candidate_id"]
        key = (round_index, candidate_id) if candidate_id is not None else None
        if event_type == "exact_attempt_started":
            if key in exact_started:
                raise V5LedgerError("V5 exact attempt was started twice")
            exact_started.add(key)
        elif event_type == "exact_attempt_finished":
            if key not in exact_started or key in exact_finished:
                raise V5LedgerError("V5 exact attempt finished without one matching start")
            exact_finished.add(key)
        elif event_type == "round_committed":
            if key not in exact_finished:
                raise V5LedgerError("V5 round committed a candidate without a completed exact attempt")
            checkpoint_digest = event["payload"].get("checkpoint_digest")
            if not isinstance(checkpoint_digest, str) or len(checkpoint_digest) != 64 or any(
                character not in "0123456789abcdef" for character in checkpoint_digest
            ):
                raise V5LedgerError("V5 round commit requires a lowercase checkpoint digest")
            expected_next_parent = checkpoint_digest
            round_open = False
        elif event_type == "round_rolled_back":
            expected_next_parent = active_parent_checkpoint
            round_open = False

    checks = {
        "schema_and_digest": True,
        "hash_chain": True,
        "stable_run_path_case_protocol": True,
        "stable_problem_id": True,
        "unique_event_ids": True,
        "monotonic_work": True,
        "round_state_machine": True,
        "screening_information_firewall": True,
        "exact_attempt_pairing": True,
    }
    return {
        "event_count": len(records),
        "last_event_digest": records[-1]["event_digest"],
        "finished": finished,
        "checks": checks,
        "passed": all(checks.values()),
    }


def build_event(
    *,
    context: V5EventContext,
    sequence: int,
    previous_event_digest: str,
    event_type: str,
    round_index: int,
    work: V5WorkCounters,
    payload: Mapping[str, Any],
    candidate_id: str | None = None,
    emitted_at_utc: str | None = None,
) -> dict[str, Any]:
    if event_type not in EVENT_PHASE:
        raise V5LedgerError(f"unsupported V5 event type: {event_type}")
    canonical_json_bytes(dict(payload))
    content_without_id = {
        "schema_version": SCHEMA_VERSION,
        "protocol_id": PROTOCOL_ID,
        "ledger_id": context.ledger_id,
        "run_id": context.run_id,
        "path_id": context.path_id,
        "case_id": context.case_id,
        "code_commit": context.code_commit,
        "sequence": sequence,
        "event_type": event_type,
        "phase": EVENT_PHASE[event_type],
        "round_index": round_index,
        "candidate_id": candidate_id,
        "emitted_at_utc": emitted_at_utc
        or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "previous_event_digest": previous_event_digest,
        "parent_checkpoint_digest": context.parent_checkpoint_digest,
        "identities": context.identities(),
        "work": work.to_dict(),
        "payload": dict(payload),
    }
    event_id = versioned_id("event-v5", content_without_id)
    content = {**content_without_id, "event_id": event_id}
    event = {**content, "event_digest": _digest(content)}
    validate_event(event)
    return event


class V5EventLedger:
    def __init__(self, path: Path, context: V5EventContext) -> None:
        self.path = path
        self.context = context
        self.lock_path = path.with_suffix(path.suffix + ".lock")

    def read_all(self) -> tuple[dict[str, Any], ...]:
        if not self.path.exists():
            return ()
        raw = self.path.read_bytes()
        if raw and not raw.endswith(b"\n"):
            raise V5LedgerError("V5 ledger ends with a partial record")
        try:
            records = tuple(json.loads(line) for line in raw.decode("utf-8").splitlines())
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise V5LedgerError("V5 ledger is not canonical UTF-8 JSONL") from error
        if not records:
            raise V5LedgerError("V5 ledger file is empty")
        audit_events(records)
        expected = self.context
        first = records[0]
        if (
            first["ledger_id"] != expected.ledger_id
            or first["run_id"] != expected.run_id
            or first["path_id"] != expected.path_id
            or first["case_id"] != expected.case_id
            or first["code_commit"] != expected.code_commit
            or first["identities"]["problem_id"] != expected.problem_id
        ):
            raise V5LedgerError("V5 ledger context does not match its reader")
        return records

    def append(
        self,
        event_type: str,
        *,
        round_index: int,
        work: V5WorkCounters,
        payload: Mapping[str, Any],
        candidate_id: str | None = None,
        event_context: V5EventContext | None = None,
        emitted_at_utc: str | None = None,
    ) -> dict[str, Any]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            records = self.read_all()
            selected_context = event_context or self.context
            if (
                selected_context.ledger_id != self.context.ledger_id
                or selected_context.run_id != self.context.run_id
                or selected_context.path_id != self.context.path_id
                or selected_context.case_id != self.context.case_id
                or selected_context.code_commit != self.context.code_commit
                or selected_context.problem_id != self.context.problem_id
            ):
                raise V5LedgerError("V5 append context changed a stable run/path/problem field")
            event = build_event(
                context=selected_context,
                sequence=len(records),
                previous_event_digest=records[-1]["event_digest"] if records else GENESIS_DIGEST,
                event_type=event_type,
                round_index=round_index,
                work=work,
                payload=payload,
                candidate_id=candidate_id,
                emitted_at_utc=emitted_at_utc,
            )
            audit_events((*records, event))
            encoded = canonical_json_bytes(event) + b"\n"
            descriptor = os.open(self.path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o644)
            try:
                offset = 0
                while offset < len(encoded):
                    written = os.write(descriptor, encoded[offset:])
                    if written <= 0:
                        raise V5LedgerError("V5 ledger append made no progress")
                    offset += written
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        return event

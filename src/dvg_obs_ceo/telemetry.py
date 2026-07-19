"""Hash-chained append-only telemetry with explicit work and optimizer semantics."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker

from .identity import canonical_json_bytes


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "schemas" / "telemetry-event-v1.schema.json"
SCHEMA_VERSION = "1.0.0"
GENESIS_DIGEST = "0" * 64


class TelemetryError(RuntimeError):
    """Raised when telemetry is malformed, altered, or non-append-only."""


@dataclass(frozen=True)
class WorkCounters:
    energy_evaluations: int = 0
    gradient_vector_evaluations: int = 0
    gradient_component_evaluations: int = 0
    optimizer_iterations: int = 0
    statevector_kernels: int = 0
    screening_rounds: int = 0
    compression_attempts: int = 0
    circuit_executions: int = 0
    shots: int = 0

    def __post_init__(self) -> None:
        if any(value < 0 for value in asdict(self).values()):
            raise TelemetryError("work counters must be non-negative")


@dataclass(frozen=True)
class ResourceSnapshot:
    cnot_count: int
    cnot_depth: int
    total_depth: int
    parameter_count: int
    logical_block_count: int
    counter_version: str
    structure_digest: str

    def __post_init__(self) -> None:
        numerical = (
            self.cnot_count,
            self.cnot_depth,
            self.total_depth,
            self.parameter_count,
            self.logical_block_count,
        )
        if any(value < 0 for value in numerical) or not self.counter_version:
            raise TelemetryError("resource snapshot is invalid")
        if len(self.structure_digest) != 64 or any(
            character not in "0123456789abcdef" for character in self.structure_digest
        ):
            raise TelemetryError("resource structure digest must be lowercase SHA-256")


@dataclass(frozen=True)
class OptimizerDiagnostics:
    implementation: str
    success: bool
    status: str
    message: str
    iterations: int
    function_evaluations: int
    gradient_evaluations: int
    gradient_l2: float
    gradient_rms: float
    gradient_infinity: float
    projected_gradient_l2: float | None
    kkt_residual: float | None

    def __post_init__(self) -> None:
        if (
            not self.implementation
            or not self.status
            or self.iterations < 0
            or self.function_evaluations < 0
            or self.gradient_evaluations < 0
        ):
            raise TelemetryError("optimizer diagnostics are incomplete")
        values = (
            self.gradient_l2,
            self.gradient_rms,
            self.gradient_infinity,
            self.projected_gradient_l2,
            self.kkt_residual,
        )
        if any(value is not None and (not math.isfinite(value) or value < 0) for value in values):
            raise TelemetryError("optimizer norm diagnostics must be finite and non-negative")


def _event_digest(event_without_digest: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(dict(event_without_digest))).hexdigest()


def _validator() -> Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def validate_event(event: Mapping[str, Any]) -> None:
    errors = sorted(
        _validator().iter_errors(dict(event)),
        key=lambda error: tuple(str(item) for item in error.absolute_path),
    )
    if errors:
        raise TelemetryError(
            "event schema validation failed: "
            + "; ".join(error.message for error in errors)
        )
    emitted_at = event["emitted_at_utc"]
    try:
        parsed_time = datetime.fromisoformat(emitted_at.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as error:
        raise TelemetryError("event schema validation failed: invalid UTC timestamp") from error
    if not emitted_at.endswith("Z") or parsed_time.tzinfo != timezone.utc:
        raise TelemetryError("event schema validation failed: timestamp must be UTC with Z suffix")
    content = dict(event)
    observed = content.pop("event_digest")
    expected = _event_digest(content)
    if observed != expected:
        raise TelemetryError("event digest mismatch")


class EventLedger:
    def __init__(self, path: Path, ledger_id: str) -> None:
        if not ledger_id:
            raise TelemetryError("ledger ID must be non-empty")
        self.path = path
        self.ledger_id = ledger_id
        self.lock_path = path.with_suffix(path.suffix + ".lock")

    def read_all(self) -> tuple[dict[str, Any], ...]:
        if not self.path.exists():
            return ()
        raw = self.path.read_bytes()
        if raw and not raw.endswith(b"\n"):
            raise TelemetryError("telemetry ledger ends with a partial record")
        events: list[dict[str, Any]] = []
        previous = GENESIS_DIGEST
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as error:
            raise TelemetryError("telemetry ledger is not valid UTF-8") from error
        for line_number, line in enumerate(text.splitlines(), 1):
            if not line:
                raise TelemetryError(f"blank telemetry record at line {line_number}")
            try:
                event = json.loads(line)
            except json.JSONDecodeError as error:
                raise TelemetryError(f"invalid JSON at line {line_number}") from error
            validate_event(event)
            if event["ledger_id"] != self.ledger_id:
                raise TelemetryError("ledger ID changed inside event stream")
            if event["sequence"] != len(events):
                raise TelemetryError("telemetry sequence is not contiguous")
            if event["previous_event_digest"] != previous:
                raise TelemetryError("telemetry hash chain is broken")
            previous = event["event_digest"]
            events.append(event)
        return tuple(events)

    def append(
        self,
        event_type: str,
        payload: Mapping[str, Any],
        *,
        emitted_at_utc: str | None = None,
    ) -> dict[str, Any]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            events = self.read_all()
            event_without_digest = {
                "schema_version": SCHEMA_VERSION,
                "ledger_id": self.ledger_id,
                "sequence": len(events),
                "event_type": event_type,
                "emitted_at_utc": emitted_at_utc
                or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "previous_event_digest": events[-1]["event_digest"] if events else GENESIS_DIGEST,
                "payload": dict(payload),
            }
            event = {
                **event_without_digest,
                "event_digest": _event_digest(event_without_digest),
            }
            validate_event(event)
            encoded = canonical_json_bytes(event) + b"\n"
            descriptor = os.open(self.path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o644)
            try:
                written = 0
                while written < len(encoded):
                    count = os.write(descriptor, encoded[written:])
                    if count <= 0:
                        raise TelemetryError("telemetry append made no forward progress")
                    written += count
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        return event

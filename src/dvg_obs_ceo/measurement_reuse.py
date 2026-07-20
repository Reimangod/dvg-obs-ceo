"""Fail-closed exact Pauli-expectation reuse with three-level identities.

This module deliberately does not estimate paper-equivalent measurement cost.
It reuses an exact Pauli expectation only when state preparation, physical
problem, Pauli observable, estimator, and backend are identical. Parent
measurement contexts may differ so an energy term can serve a later OGM
gradient context; both contexts remain in the audit ledger.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
import struct
from typing import Callable, Any

from .identity import canonical_float64_hex, sha256_hex


POLICY_VERSION = "exact-pauli-cross-context-reuse-v1"


class MeasurementReuseError(RuntimeError):
    """Raised when reuse semantics are ambiguous or unsafe."""


def canonical_pauli_string(value: str) -> str:
    tokens = value.strip().split()
    if not tokens or tokens == ["I"]:
        return "I"
    parsed: list[tuple[int, str]] = []
    for token in tokens:
        if len(token) < 2 or token[0] not in "XYZ" or not token[1:].isdigit():
            raise MeasurementReuseError(f"invalid OpenFermion Pauli token: {token!r}")
        parsed.append((int(token[1:]), token[0]))
    if len({index for index, _ in parsed}) != len(parsed):
        raise MeasurementReuseError("Pauli string repeats a qubit index")
    parsed.sort()
    return " ".join(f"{axis}{index}" for index, axis in parsed)


@dataclass(frozen=True)
class ExactPauliRequest:
    state_preparation_id: str
    problem_id: str
    pauli_string: str
    estimator_version: str
    backend_context_digest: str
    measurement_context_id: str
    shots: None = None

    def __post_init__(self) -> None:
        if not self.state_preparation_id.startswith("state-v1:"):
            raise MeasurementReuseError("request requires a versioned StatePreparationID")
        if not self.problem_id.startswith("problem-v1:"):
            raise MeasurementReuseError("request requires a versioned ProblemID")
        if not self.measurement_context_id.startswith("measurement-v1:"):
            raise MeasurementReuseError("request requires a versioned MeasurementContextID")
        if len(self.backend_context_digest) != 64 or any(
            character not in "0123456789abcdef" for character in self.backend_context_digest
        ):
            raise MeasurementReuseError("backend context must be a lowercase SHA-256 digest")
        if self.estimator_version != "exact-statevector-pauli-v1" or self.shots is not None:
            raise MeasurementReuseError("v1 reuse accepts exact noiseless Pauli expectations only")
        object.__setattr__(self, "pauli_string", canonical_pauli_string(self.pauli_string))

    @property
    def semantic_key(self) -> str:
        return "pauli-expectation-v1:" + sha256_hex({
            "state_preparation_id": self.state_preparation_id,
            "problem_id": self.problem_id,
            "pauli_string": self.pauli_string,
            "estimator_version": self.estimator_version,
            "backend_context_digest": self.backend_context_digest,
            "shots": self.shots,
        })


@dataclass(frozen=True)
class ExactPauliRecord:
    semantic_key: str
    value_float64_hex: str
    pauli_string: str
    source_measurement_context_id: str

    @property
    def value(self) -> float:
        return struct.unpack(">d", bytes.fromhex(self.value_float64_hex))[0]


class ExactPauliReuseCache:
    """In-memory exact cache with a deterministic request/hit ledger."""

    def __init__(self, *, enabled: bool) -> None:
        self.enabled = bool(enabled)
        self._records: dict[str, ExactPauliRecord] = {}
        self._events: list[dict[str, Any]] = []
        self._fresh_evaluations = 0
        self._cache_hits = 0

    def evaluate(
        self,
        request: ExactPauliRequest,
        evaluator: Callable[[str], float],
    ) -> float:
        key = request.semantic_key
        record = self._records.get(key) if self.enabled else None
        if record is not None:
            value = record.value
            self._cache_hits += 1
            disposition = "reused"
            source_context = record.source_measurement_context_id
        else:
            value = float(evaluator(request.pauli_string))
            if not math.isfinite(value):
                raise MeasurementReuseError("Pauli evaluator returned a non-finite value")
            value_hex = canonical_float64_hex((value,))[0]
            record = ExactPauliRecord(
                key,
                value_hex,
                request.pauli_string,
                request.measurement_context_id,
            )
            self._fresh_evaluations += 1
            disposition = "fresh"
            source_context = request.measurement_context_id
            if self.enabled:
                self._records[key] = record
        self._events.append({
            "sequence": len(self._events),
            "semantic_key": key,
            "pauli_string": request.pauli_string,
            "requested_measurement_context_id": request.measurement_context_id,
            "source_measurement_context_id": source_context,
            "disposition": disposition,
            "value_float64_hex": canonical_float64_hex((value,))[0],
        })
        return value

    def report(self, *, include_events: bool = True) -> dict[str, Any]:
        value = {
            "policy_version": POLICY_VERSION,
            "enabled": self.enabled,
            "exact_noiseless_only": True,
            "requests": len(self._events),
            "fresh_pauli_expectation_evaluations": self._fresh_evaluations,
            "cache_hits": self._cache_hits,
            "unique_cached_records": len(self._records),
            "event_ledger_digest": sha256_hex(self._events),
            "paper_measurement_cost": None,
        }
        if include_events:
            value["events"] = list(self._events)
        return value

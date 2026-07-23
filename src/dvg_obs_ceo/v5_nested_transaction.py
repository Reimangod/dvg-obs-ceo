"""V5 immutable path checkpoints and round-scoped nested transactions."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import threading
from typing import Any, Mapping
import uuid

from .identity import canonical_json_bytes
from .telemetry import ResourceSnapshot
from .transaction import (
    ACCEPTANCE_VERSION,
    AcceptanceDecision,
    CompressionRuntime,
    RuntimeSnapshot,
    TransactionError,
)
from .v5_ledger import PROTOCOL_ID, V5WorkCounters


CHECKPOINT_VERSION = "v5-path-checkpoint-v1"
ROUND_TRANSACTION_VERSION = "v5-nested-round-transaction-v1"
GENESIS_CHECKPOINT = "0" * 64
_PROCESS_NESTED_LOCK = threading.Lock()


class V5NestedTransactionError(TransactionError):
    """Raised when a V5 path checkpoint or nested round is unsafe."""


def _digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(dict(value))).hexdigest()


def _write_exclusive_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(dict(value), sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n"
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise V5NestedTransactionError("checkpoint write made no progress")
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _require_digest(name: str, value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise V5NestedTransactionError(f"{name} must be a lowercase SHA-256 digest")


@dataclass(frozen=True)
class PathCheckpoint:
    path_id: str
    round_index: int
    parent_checkpoint_digest: str
    parent_runtime_snapshot_digest: str
    runtime_snapshot: dict[str, Any]
    work: dict[str, int]
    state_preparation_id: str
    problem_id: str
    measurement_context_id: str
    catalog_digest: str
    resource_snapshot: dict[str, Any]
    acceptance_evidence_digest: str | None
    checkpoint_digest: str

    @classmethod
    def create(
        cls,
        *,
        path_id: str,
        round_index: int,
        parent_checkpoint_digest: str,
        parent_runtime_snapshot_digest: str,
        runtime_snapshot: RuntimeSnapshot,
        work: V5WorkCounters,
        state_preparation_id: str,
        problem_id: str,
        measurement_context_id: str,
        catalog_digest: str,
        resource_snapshot: ResourceSnapshot,
        acceptance_evidence_digest: str | None,
    ) -> "PathCheckpoint":
        payload = {
            "version": CHECKPOINT_VERSION,
            "protocol_id": PROTOCOL_ID,
            "path_id": path_id,
            "round_index": round_index,
            "parent_checkpoint_digest": parent_checkpoint_digest,
            "parent_runtime_snapshot_digest": parent_runtime_snapshot_digest,
            "runtime_snapshot": runtime_snapshot.to_dict(),
            "work": work.to_dict(),
            "state_preparation_id": state_preparation_id,
            "problem_id": problem_id,
            "measurement_context_id": measurement_context_id,
            "catalog_digest": catalog_digest,
            "resource_snapshot": asdict(resource_snapshot),
            "acceptance_evidence_digest": acceptance_evidence_digest,
        }
        result = cls(
            path_id=path_id,
            round_index=round_index,
            parent_checkpoint_digest=parent_checkpoint_digest,
            parent_runtime_snapshot_digest=parent_runtime_snapshot_digest,
            runtime_snapshot=deepcopy(payload["runtime_snapshot"]),
            work=deepcopy(payload["work"]),
            state_preparation_id=state_preparation_id,
            problem_id=problem_id,
            measurement_context_id=measurement_context_id,
            catalog_digest=catalog_digest,
            resource_snapshot=deepcopy(payload["resource_snapshot"]),
            acceptance_evidence_digest=acceptance_evidence_digest,
            checkpoint_digest=_digest(payload),
        )
        result.validate()
        return result

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PathCheckpoint":
        if value.get("version") != CHECKPOINT_VERSION or value.get("protocol_id") != PROTOCOL_ID:
            raise V5NestedTransactionError("path checkpoint version or protocol is unsupported")
        result = cls(
            path_id=value["path_id"],
            round_index=int(value["round_index"]),
            parent_checkpoint_digest=value["parent_checkpoint_digest"],
            parent_runtime_snapshot_digest=value["parent_runtime_snapshot_digest"],
            runtime_snapshot=deepcopy(value["runtime_snapshot"]),
            work=deepcopy(value["work"]),
            state_preparation_id=value["state_preparation_id"],
            problem_id=value["problem_id"],
            measurement_context_id=value["measurement_context_id"],
            catalog_digest=value["catalog_digest"],
            resource_snapshot=deepcopy(value["resource_snapshot"]),
            acceptance_evidence_digest=value.get("acceptance_evidence_digest"),
            checkpoint_digest=value["checkpoint_digest"],
        )
        result.validate()
        payload = result.to_dict()
        observed = payload.pop("checkpoint_digest")
        if _digest(payload) != observed:
            raise V5NestedTransactionError("path checkpoint digest mismatch")
        return result

    def validate(self) -> None:
        if not self.path_id.startswith("path-v5:") or self.round_index < 0:
            raise V5NestedTransactionError("path checkpoint identity or round is invalid")
        for name, value in (
            ("parent checkpoint", self.parent_checkpoint_digest),
            ("parent runtime snapshot", self.parent_runtime_snapshot_digest),
            ("catalog", self.catalog_digest),
            ("checkpoint", self.checkpoint_digest),
        ):
            _require_digest(name, value)
        if self.round_index == 0:
            if self.parent_checkpoint_digest != GENESIS_CHECKPOINT:
                raise V5NestedTransactionError("source checkpoint must have the genesis parent")
            if self.acceptance_evidence_digest is not None:
                raise V5NestedTransactionError("source checkpoint cannot have acceptance evidence")
        else:
            _require_digest("acceptance evidence", str(self.acceptance_evidence_digest))
        if not self.state_preparation_id.startswith("state-v1:"):
            raise V5NestedTransactionError("checkpoint StatePreparationID is invalid")
        if not self.problem_id.startswith("problem-v1:"):
            raise V5NestedTransactionError("checkpoint ProblemID is invalid")
        if not self.measurement_context_id.startswith("measurement-v1:"):
            raise V5NestedTransactionError("checkpoint MeasurementContextID is invalid")
        snapshot = RuntimeSnapshot.from_dict(self.runtime_snapshot)
        if self.round_index == 0:
            if self.parent_runtime_snapshot_digest != snapshot.snapshot_digest:
                raise V5NestedTransactionError("source parent runtime digest must self-bind")
        V5WorkCounters(**self.work)
        ResourceSnapshot(**self.resource_snapshot)

    def runtime(self) -> RuntimeSnapshot:
        return RuntimeSnapshot.from_dict(self.runtime_snapshot)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": CHECKPOINT_VERSION,
            "protocol_id": PROTOCOL_ID,
            "path_id": self.path_id,
            "round_index": self.round_index,
            "parent_checkpoint_digest": self.parent_checkpoint_digest,
            "parent_runtime_snapshot_digest": self.parent_runtime_snapshot_digest,
            "runtime_snapshot": deepcopy(self.runtime_snapshot),
            "work": deepcopy(self.work),
            "state_preparation_id": self.state_preparation_id,
            "problem_id": self.problem_id,
            "measurement_context_id": self.measurement_context_id,
            "catalog_digest": self.catalog_digest,
            "resource_snapshot": deepcopy(self.resource_snapshot),
            "acceptance_evidence_digest": self.acceptance_evidence_digest,
            "checkpoint_digest": self.checkpoint_digest,
        }


class PathCheckpointStore:
    def __init__(self, root: Path, path_id: str) -> None:
        self.root = root
        self.path_id = path_id
        self.rounds = root / "rounds"
        self.failed = root / "failed"
        self.staging = root / ".staging"
        self.lock_path = root / "path.lock"

    def _round_directories(self) -> list[Path]:
        if not self.rounds.exists():
            return []
        return sorted(path for path in self.rounds.iterdir() if path.is_dir())

    def checkpoints(self) -> tuple[PathCheckpoint, ...]:
        checkpoints: list[PathCheckpoint] = []
        for directory in self._round_directories():
            checkpoint_path = directory / "checkpoint.json"
            commit_path = directory / "commit.json"
            if not checkpoint_path.is_file() or not commit_path.is_file():
                raise V5NestedTransactionError("committed round directory is incomplete")
            try:
                checkpoint = PathCheckpoint.from_dict(json.loads(checkpoint_path.read_text(encoding="utf-8")))
                commit = json.loads(commit_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
                raise V5NestedTransactionError("committed round evidence is unreadable") from error
            if commit.get("version") != ROUND_TRANSACTION_VERSION or commit.get("checkpoint_digest") != checkpoint.checkpoint_digest:
                raise V5NestedTransactionError("round commit marker does not bind its checkpoint")
            checkpoints.append(checkpoint)
        for index, checkpoint in enumerate(checkpoints):
            if checkpoint.path_id != self.path_id or checkpoint.round_index != index:
                raise V5NestedTransactionError("checkpoint path or round chain is not contiguous")
            if index > 0:
                parent = checkpoints[index - 1]
                if checkpoint.parent_checkpoint_digest != parent.checkpoint_digest:
                    raise V5NestedTransactionError("checkpoint parent digest chain is broken")
                if checkpoint.parent_runtime_snapshot_digest != parent.runtime().snapshot_digest:
                    raise V5NestedTransactionError("checkpoint parent runtime digest chain is broken")
                if checkpoint.problem_id != parent.problem_id:
                    raise V5NestedTransactionError("ProblemID changed inside checkpoint chain")
                if any(checkpoint.work[key] < parent.work[key] for key in checkpoint.work):
                    raise V5NestedTransactionError("checkpoint work counter regressed")
                source_budget = float(checkpoints[0].runtime().metadata["budget_reference_energy_hartree"])
                current_budget = float(checkpoint.runtime().metadata["budget_reference_energy_hartree"])
                if current_budget != source_budget:
                    raise V5NestedTransactionError("checkpoint budget reference changed")
        return tuple(checkpoints)

    def latest(self) -> PathCheckpoint:
        checkpoints = self.checkpoints()
        if not checkpoints:
            raise V5NestedTransactionError("path has no committed source checkpoint")
        return checkpoints[-1]

    def initialize(
        self,
        runtime: CompressionRuntime,
        *,
        work: V5WorkCounters,
        state_preparation_id: str,
        problem_id: str,
        measurement_context_id: str,
        catalog_digest: str,
        resource_snapshot: ResourceSnapshot,
    ) -> PathCheckpoint:
        if self.root.exists() and any(self.root.iterdir()):
            raise V5NestedTransactionError("path checkpoint store already exists")
        snapshot = runtime.snapshot()
        checkpoint = PathCheckpoint.create(
            path_id=self.path_id,
            round_index=0,
            parent_checkpoint_digest=GENESIS_CHECKPOINT,
            parent_runtime_snapshot_digest=snapshot.snapshot_digest,
            runtime_snapshot=snapshot,
            work=work,
            state_preparation_id=state_preparation_id,
            problem_id=problem_id,
            measurement_context_id=measurement_context_id,
            catalog_digest=catalog_digest,
            resource_snapshot=resource_snapshot,
            acceptance_evidence_digest=None,
        )
        directory = self.rounds / f"round-0000-{checkpoint.checkpoint_digest}"
        directory.mkdir(parents=True)
        _write_exclusive_json(directory / "checkpoint.json", checkpoint.to_dict())
        _write_exclusive_json(
            directory / "commit.json",
            {"version": ROUND_TRANSACTION_VERSION, "round_index": 0, "checkpoint_digest": checkpoint.checkpoint_digest, "role": "source"},
        )
        _fsync_directory(directory)
        _fsync_directory(self.rounds)
        return self.latest()


class NestedRoundTransaction:
    def __init__(self, runtime: CompressionRuntime, store: PathCheckpointStore, round_index: int, *, transaction_id: str | None = None) -> None:
        self.runtime = runtime
        self.store = store
        self.round_index = round_index
        self.transaction_id = transaction_id or f"round-tx-{uuid.uuid4().hex}"
        if not self.transaction_id or "/" in self.transaction_id or ".." in self.transaction_id:
            raise V5NestedTransactionError("nested transaction ID is unsafe")
        self.staging = store.staging / self.transaction_id
        self.parent: PathCheckpoint | None = None
        self.parent_snapshot: RuntimeSnapshot | None = None
        self._process_locked = False
        self._file_lock: Any = None
        self._committed = False
        self._rolled_back = False

    def __enter__(self) -> "NestedRoundTransaction":
        if not _PROCESS_NESTED_LOCK.acquire(blocking=False):
            raise V5NestedTransactionError("another V5 nested round is active in this process")
        self._process_locked = True
        try:
            self.store.root.mkdir(parents=True, exist_ok=True)
            self._file_lock = self.store.lock_path.open("a+")
            try:
                fcntl.flock(self._file_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise V5NestedTransactionError("another process owns the V5 path lock") from error
            self.parent = self.store.latest()
            self.parent_snapshot = self.parent.runtime()
            if self.round_index != self.parent.round_index + 1:
                raise V5NestedTransactionError("nested round index does not follow latest checkpoint")
            if self.runtime.snapshot().snapshot_digest != self.parent_snapshot.snapshot_digest:
                raise V5NestedTransactionError("runtime does not match latest committed checkpoint")
            self.staging.mkdir(parents=True)
            _write_exclusive_json(
                self.staging / "attempt.json",
                {
                    "version": ROUND_TRANSACTION_VERSION,
                    "transaction_id": self.transaction_id,
                    "round_index": self.round_index,
                    "parent_checkpoint_digest": self.parent.checkpoint_digest,
                    "parent_runtime_snapshot": self.parent_snapshot.to_dict(),
                },
            )
            _fsync_directory(self.staging)
            return self
        except Exception:
            self._release_locks()
            raise

    def _release_locks(self) -> None:
        if self._file_lock is not None:
            try:
                fcntl.flock(self._file_lock.fileno(), fcntl.LOCK_UN)
            finally:
                self._file_lock.close()
                self._file_lock = None
        if self._process_locked:
            _PROCESS_NESTED_LOCK.release()
            self._process_locked = False

    def commit(
        self,
        decision: AcceptanceDecision,
        *,
        work: V5WorkCounters,
        state_preparation_id: str,
        problem_id: str,
        measurement_context_id: str,
        catalog_digest: str,
        resource_snapshot: ResourceSnapshot,
    ) -> PathCheckpoint:
        if self.parent is None or self.parent_snapshot is None or self._committed or self._rolled_back:
            raise V5NestedTransactionError("nested round is not active")
        if not decision.accepted or decision.version != ACCEPTANCE_VERSION or not all(decision.checks.values()):
            raise V5NestedTransactionError("nested round cannot commit an invalid acceptance decision")
        self.runtime.validate()
        current_snapshot = self.runtime.snapshot()
        if decision.source_energy_hartree != self.parent_snapshot.energy_hartree or decision.candidate_energy_hartree != current_snapshot.energy_hartree:
            raise V5NestedTransactionError("nested acceptance energy is not bound to runtime")
        if len(self.parent_snapshot.ansatz.indices) != decision.before_parameter_count or len(current_snapshot.ansatz.indices) != decision.after_parameter_count:
            raise V5NestedTransactionError("nested acceptance parameters are not bound to runtime")
        if problem_id != self.parent.problem_id:
            raise V5NestedTransactionError("ProblemID cannot change at round commit")
        work_payload = work.to_dict()
        if any(work_payload[key] < self.parent.work[key] for key in work_payload):
            raise V5NestedTransactionError("nested round work counter regressed")
        if work.accepted_rounds != self.parent.work["accepted_rounds"] + 1:
            raise V5NestedTransactionError("nested round must increment accepted-round work exactly once")
        if work.attempted_rounds < self.parent.work["attempted_rounds"] + 1:
            raise V5NestedTransactionError("nested round did not account for its attempted-round work")
        if (
            decision.before_structure_digest != self.parent.resource_snapshot["structure_digest"]
            or decision.after_structure_digest != resource_snapshot.structure_digest
        ):
            raise V5NestedTransactionError("nested acceptance resources are not bound to checkpoint recounts")
        source_budget = float(self.parent_snapshot.metadata["budget_reference_energy_hartree"])
        current_budget = float(current_snapshot.metadata["budget_reference_energy_hartree"])
        if source_budget != current_budget or current_budget != decision.budget_reference_energy_hartree:
            raise V5NestedTransactionError("nested round changed its source-relative energy reference")
        checkpoint = PathCheckpoint.create(
            path_id=self.store.path_id,
            round_index=self.round_index,
            parent_checkpoint_digest=self.parent.checkpoint_digest,
            parent_runtime_snapshot_digest=self.parent_snapshot.snapshot_digest,
            runtime_snapshot=current_snapshot,
            work=work,
            state_preparation_id=state_preparation_id,
            problem_id=problem_id,
            measurement_context_id=measurement_context_id,
            catalog_digest=catalog_digest,
            resource_snapshot=resource_snapshot,
            acceptance_evidence_digest=decision.evidence_digest,
        )
        _write_exclusive_json(self.staging / "checkpoint.json", checkpoint.to_dict())
        _write_exclusive_json(
            self.staging / "commit.json",
            {"version": ROUND_TRANSACTION_VERSION, "transaction_id": self.transaction_id, "round_index": self.round_index, "checkpoint_digest": checkpoint.checkpoint_digest, "acceptance_evidence_digest": decision.evidence_digest},
        )
        _fsync_directory(self.staging)
        destination = self.store.rounds / f"round-{self.round_index:04d}-{checkpoint.checkpoint_digest}"
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise V5NestedTransactionError("nested committed round already exists")
        os.replace(self.staging, destination)
        # After atomic promotion the round is no longer rollback-able.  A later
        # fsync/audit failure is an incident requiring recovery, not permission
        # to mutate the already promoted evidence or an earlier checkpoint.
        self._committed = True
        _fsync_directory(destination.parent)
        latest = self.store.latest()
        if latest.checkpoint_digest != checkpoint.checkpoint_digest:
            raise V5NestedTransactionError("committed checkpoint did not become the audited path head")
        return latest

    def rollback(self, reason: str) -> Path:
        if self.parent_snapshot is None or self._committed or self._rolled_back:
            raise V5NestedTransactionError("nested round cannot roll back in its current state")
        self.runtime.restore(self.parent_snapshot)
        _write_exclusive_json(
            self.staging / "rollback.json",
            {"version": ROUND_TRANSACTION_VERSION, "transaction_id": self.transaction_id, "round_index": self.round_index, "reason": str(reason), "restored_runtime_snapshot_digest": self.runtime.snapshot().snapshot_digest},
        )
        destination = self.store.failed / self.transaction_id
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise V5NestedTransactionError("nested failed-round evidence already exists")
        _fsync_directory(self.staging)
        os.replace(self.staging, destination)
        _fsync_directory(destination.parent)
        self._rolled_back = True
        return destination

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        try:
            if not self._committed and not self._rolled_back:
                reason = "scope-exited-without-commit" if exc_value is None else f"{exc_type.__name__}: {exc_value}"
                self.rollback(reason)
        finally:
            self._release_locks()


def recover_orphaned_round(runtime: CompressionRuntime, store: PathCheckpointStore, transaction_id: str) -> Path:
    if not _PROCESS_NESTED_LOCK.acquire(blocking=False):
        raise V5NestedTransactionError("another V5 nested round is active during recovery")
    lock_file = None
    try:
        store.root.mkdir(parents=True, exist_ok=True)
        lock_file = store.lock_path.open("a+")
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        staging = store.staging / transaction_id
        if not staging.is_dir():
            raise V5NestedTransactionError("orphan nested staging directory is absent")
        attempt_path = staging / "attempt.json"
        try:
            attempt = json.loads(attempt_path.read_text(encoding="utf-8"))
            parent_snapshot = RuntimeSnapshot.from_dict(attempt["parent_runtime_snapshot"])
        except (OSError, json.JSONDecodeError, KeyError, TypeError, TransactionError) as error:
            raise V5NestedTransactionError("orphan nested parent snapshot is unreadable") from error
        latest = store.latest()
        if attempt.get("parent_checkpoint_digest") != latest.checkpoint_digest:
            raise V5NestedTransactionError("orphan nested transaction does not descend from current head")
        runtime.restore(parent_snapshot)
        _write_exclusive_json(
            staging / "recovery-rollback.json",
            {"version": ROUND_TRANSACTION_VERSION, "transaction_id": transaction_id, "restored_runtime_snapshot_digest": runtime.snapshot().snapshot_digest},
        )
        destination = store.failed / transaction_id
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging, destination)
        _fsync_directory(destination.parent)
        return destination
    finally:
        if lock_file is not None:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            lock_file.close()
        _PROCESS_NESTED_LOCK.release()

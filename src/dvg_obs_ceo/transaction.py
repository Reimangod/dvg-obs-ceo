"""Crash-auditable compression transactions and independent acceptance gates."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import random
import struct
import threading
import time
from typing import Any, Mapping
import uuid

import numpy as np
from numpy.typing import ArrayLike, NDArray

from .identity import canonical_float64_hex, canonical_json_bytes
from .resources import AnsatzStructure
from .telemetry import ResourceSnapshot, WorkCounters


FloatArray = NDArray[np.float64]
ComplexArray = NDArray[np.complex128]
TRANSACTION_VERSION = "compression-transaction-v2"
ACCEPTANCE_VERSION = "runtime-kkt-cumulative-resource-guard-v2"


class TransactionError(RuntimeError):
    """Raised when a transaction or acceptance decision is unsafe."""


class TransactionDeadlineExceeded(TransactionError):
    """Raised at a cooperative transaction deadline checkpoint."""


def _float_array(value: ArrayLike, *, ndim: int) -> FloatArray:
    result = np.array(value, dtype=np.float64, copy=True)
    if result.ndim != ndim or not np.all(np.isfinite(result)):
        raise TransactionError("runtime numeric array is non-finite or has wrong rank")
    result.flags.writeable = False
    return result


def _complex_array(value: ArrayLike) -> ComplexArray:
    result = np.array(value, dtype=np.complex128, copy=True)
    if result.ndim != 1 or not np.all(np.isfinite(result.real)) or not np.all(np.isfinite(result.imag)):
        raise TransactionError("runtime statevector is non-finite or has wrong rank")
    norm = float(np.linalg.norm(result))
    if abs(norm - 1.0) > 1e-10:
        raise TransactionError("runtime statevector must be normalized")
    result.flags.writeable = False
    return result


def _array_payload(value: NDArray[Any]) -> dict[str, Any]:
    if np.iscomplexobj(value):
        return {
            "real": list(canonical_float64_hex(value.real.ravel())),
            "imag": list(canonical_float64_hex(value.imag.ravel())),
            "shape": list(value.shape),
        }
    return {
        "float64": list(canonical_float64_hex(value.ravel())),
        "shape": list(value.shape),
    }


def _numpy_rng_payload(state: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "algorithm": state[0],
        "keys": [int(value) for value in state[1]],
        "position": int(state[2]),
        "has_gauss": int(state[3]),
        "cached_gaussian_float64": canonical_float64_hex((float(state[4]),))[0],
    }


def _decode_float64(value: str) -> float:
    if len(value) != 16:
        raise TransactionError("serialized float64 value has the wrong width")
    try:
        return struct.unpack(">d", bytes.fromhex(value))[0]
    except (ValueError, struct.error) as error:
        raise TransactionError("serialized float64 value is invalid") from error


def _tuple_tree(value: Any) -> Any:
    if isinstance(value, list):
        return tuple(_tuple_tree(item) for item in value)
    return value


@dataclass
class CompressionRuntime:
    ansatz: AnsatzStructure
    energy_hartree: float
    gradient: FloatArray
    inverse_hessian: FloatArray
    statevector: ComplexArray
    work: WorkCounters
    adapt_iteration: int
    metadata: dict[str, Any]

    @classmethod
    def create(
        cls,
        *,
        ansatz: AnsatzStructure,
        energy_hartree: float,
        gradient: ArrayLike,
        inverse_hessian: ArrayLike,
        statevector: ArrayLike,
        work: WorkCounters,
        adapt_iteration: int,
        metadata: Mapping[str, Any] | None = None,
    ) -> "CompressionRuntime":
        result = cls(
            ansatz,
            float(energy_hartree),
            _float_array(gradient, ndim=1),
            _float_array(inverse_hessian, ndim=2),
            _complex_array(statevector),
            work,
            int(adapt_iteration),
            deepcopy(dict(metadata or {})),
        )
        result.validate()
        return result

    def validate(self) -> None:
        self.ansatz.validate()
        if not math.isfinite(self.energy_hartree):
            raise TransactionError("runtime energy must be finite")
        dimension = len(self.ansatz.indices)
        if self.gradient.shape != (dimension,):
            raise TransactionError("runtime gradient dimension differs from ansatz")
        if self.inverse_hessian.shape != (dimension, dimension):
            raise TransactionError("runtime inverse Hessian dimension differs from ansatz")
        if not np.all(np.isfinite(self.gradient)) or not np.all(np.isfinite(self.inverse_hessian)):
            raise TransactionError("runtime gradient or inverse Hessian is non-finite")
        if self.adapt_iteration < 0:
            raise TransactionError("ADAPT iteration cannot be negative")
        canonical_json_bytes(self.metadata)
        resource_digest = self.metadata.get("resource_structure_digest")
        if (
            not isinstance(resource_digest, str)
            or len(resource_digest) != 64
            or any(character not in "0123456789abcdef" for character in resource_digest)
        ):
            raise TransactionError("runtime metadata requires a lowercase resource structure digest")
        budget_reference = self.metadata.get("budget_reference_energy_hartree")
        if not isinstance(budget_reference, (float, int)) or not math.isfinite(
            float(budget_reference)
        ):
            raise TransactionError("runtime metadata requires a finite immutable budget reference energy")

    def snapshot(self) -> "RuntimeSnapshot":
        self.validate()
        return RuntimeSnapshot.create(self)

    def restore(self, snapshot: "RuntimeSnapshot") -> None:
        self.ansatz = snapshot.ansatz
        self.energy_hartree = snapshot.energy_hartree
        self.gradient = _float_array(snapshot.gradient, ndim=1)
        self.inverse_hessian = _float_array(snapshot.inverse_hessian, ndim=2)
        self.statevector = _complex_array(snapshot.statevector)
        self.work = snapshot.work
        self.adapt_iteration = snapshot.adapt_iteration
        self.metadata = deepcopy(snapshot.metadata)
        random.setstate(deepcopy(snapshot.python_rng_state))
        np.random.set_state(deepcopy(snapshot.numpy_rng_state))
        self.validate()
        observed = self.snapshot().snapshot_digest
        if observed != snapshot.snapshot_digest:
            raise TransactionError("rollback did not restore the bitwise-equivalent snapshot")


@dataclass(frozen=True)
class RuntimeSnapshot:
    ansatz: AnsatzStructure
    energy_hartree: float
    gradient: FloatArray
    inverse_hessian: FloatArray
    statevector: ComplexArray
    work: WorkCounters
    adapt_iteration: int
    metadata: dict[str, Any]
    python_rng_state: tuple[Any, ...]
    numpy_rng_state: tuple[Any, ...]
    snapshot_digest: str

    @classmethod
    def create(cls, runtime: CompressionRuntime) -> "RuntimeSnapshot":
        python_state = deepcopy(random.getstate())
        numpy_state = deepcopy(np.random.get_state())
        gradient = _float_array(runtime.gradient, ndim=1)
        hessian = _float_array(runtime.inverse_hessian, ndim=2)
        statevector = _complex_array(runtime.statevector)
        metadata = deepcopy(runtime.metadata)
        payload = {
            "ansatz": {
                "indices": list(runtime.ansatz.indices),
                "coefficients": list(canonical_float64_hex(runtime.ansatz.coefficients)),
                "iteration_counts": list(runtime.ansatz.cumulative_parameter_counts),
            },
            "energy_float64": canonical_float64_hex((runtime.energy_hartree,))[0],
            "gradient": _array_payload(gradient),
            "inverse_hessian": _array_payload(hessian),
            "statevector": _array_payload(statevector),
            "work": asdict(runtime.work),
            "adapt_iteration": runtime.adapt_iteration,
            "metadata": metadata,
            "python_rng_repr": repr(python_state),
            "numpy_rng": _numpy_rng_payload(numpy_state),
        }
        digest = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
        return cls(
            runtime.ansatz,
            runtime.energy_hartree,
            gradient,
            hessian,
            statevector,
            runtime.work,
            runtime.adapt_iteration,
            metadata,
            python_state,
            numpy_state,
            digest,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": TRANSACTION_VERSION,
            "snapshot_digest": self.snapshot_digest,
            "ansatz": {
                "indices": list(self.ansatz.indices),
                "coefficient_float64": list(canonical_float64_hex(self.ansatz.coefficients)),
                "iteration_counts": list(self.ansatz.cumulative_parameter_counts),
            },
            "energy_float64": canonical_float64_hex((self.energy_hartree,))[0],
            "gradient_float64": list(canonical_float64_hex(self.gradient)),
            "inverse_hessian_float64": [
                list(canonical_float64_hex(row)) for row in self.inverse_hessian
            ],
            "statevector_real_float64": list(canonical_float64_hex(self.statevector.real)),
            "statevector_imag_float64": list(canonical_float64_hex(self.statevector.imag)),
            "work": asdict(self.work),
            "adapt_iteration": self.adapt_iteration,
            "metadata": deepcopy(self.metadata),
            "python_rng_state": deepcopy(self.python_rng_state),
            "numpy_rng_state": _numpy_rng_payload(self.numpy_rng_state),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RuntimeSnapshot":
        if value.get("version") != TRANSACTION_VERSION:
            raise TransactionError("snapshot transaction version is unsupported")
        ansatz_value = value["ansatz"]
        ansatz = AnsatzStructure.create(
            ansatz_value["indices"],
            [_decode_float64(item) for item in ansatz_value["coefficient_float64"]],
            ansatz_value["iteration_counts"],
        )
        gradient = _float_array(
            [_decode_float64(item) for item in value["gradient_float64"]], ndim=1
        )
        hessian = _float_array(
            [
                [_decode_float64(item) for item in row]
                for row in value["inverse_hessian_float64"]
            ],
            ndim=2,
        )
        statevector = _complex_array(
            [
                complex(_decode_float64(real), _decode_float64(imag))
                for real, imag in zip(
                    value["statevector_real_float64"],
                    value["statevector_imag_float64"],
                )
            ]
        )
        work = WorkCounters(**dict(value["work"]))
        python_state = _tuple_tree(value["python_rng_state"])
        numpy_value = value["numpy_rng_state"]
        numpy_state = (
            numpy_value["algorithm"],
            np.asarray(numpy_value["keys"], dtype=np.uint32),
            int(numpy_value["position"]),
            int(numpy_value["has_gauss"]),
            _decode_float64(numpy_value["cached_gaussian_float64"]),
        )
        runtime = CompressionRuntime.create(
            ansatz=ansatz,
            energy_hartree=_decode_float64(value["energy_float64"]),
            gradient=gradient,
            inverse_hessian=hessian,
            statevector=statevector,
            work=work,
            adapt_iteration=int(value["adapt_iteration"]),
            metadata=value["metadata"],
        )
        # Compute the digest with the serialized RNG states, not the reader's current RNG.
        random_before = random.getstate()
        numpy_before = np.random.get_state()
        try:
            random.setstate(deepcopy(python_state))
            np.random.set_state(deepcopy(numpy_state))
            rebuilt = cls.create(runtime)
        finally:
            random.setstate(random_before)
            np.random.set_state(numpy_before)
        if rebuilt.snapshot_digest != value.get("snapshot_digest"):
            raise TransactionError("serialized runtime snapshot digest mismatch")
        return rebuilt


@dataclass(frozen=True)
class OptimizerOutcome:
    success: bool
    status: str
    message: str
    completed: bool

    def __post_init__(self) -> None:
        if not self.status or not self.message:
            raise TransactionError("optimizer status and message must be explicit")
        if self.success and not self.completed:
            raise TransactionError("a successful optimizer outcome must be completed")


@dataclass(frozen=True)
class AcceptanceCriteria:
    cumulative_energy_budget_hartree: float = 1e-4
    independent_energy_tolerance_hartree: float = 1e-10
    minimum_state_fidelity: float = 1.0 - 1e-10
    maximum_constraint_residual: float = 1e-10
    maximum_kkt_residual: float = 1e-8
    guard_logical_block_count: bool = True

    def __post_init__(self) -> None:
        values = (
            self.cumulative_energy_budget_hartree,
            self.independent_energy_tolerance_hartree,
            self.minimum_state_fidelity,
            self.maximum_constraint_residual,
            self.maximum_kkt_residual,
        )
        if any(not math.isfinite(value) or value < 0 for value in values):
            raise TransactionError("acceptance criteria must be finite and non-negative")
        if self.minimum_state_fidelity > 1.0:
            raise TransactionError("minimum state fidelity cannot exceed one")
        if not isinstance(self.guard_logical_block_count, bool):
            raise TransactionError("logical-block guard flag must be boolean")


@dataclass(frozen=True)
class AcceptanceEvidence:
    source_energy_hartree: float
    budget_reference_energy_hartree: float
    candidate_energy_hartree: float
    independent_energy_hartree: float
    independent_state_fidelity: float
    constraint_residual: float
    kkt_residual: float
    before_resources: ResourceSnapshot
    after_resources: ResourceSnapshot
    full_resource_recount_succeeded: bool
    transformation_semantics_validated: bool
    primary_optimizer: OptimizerOutcome
    fallback_optimizer: OptimizerOutcome | None


@dataclass(frozen=True)
class AcceptanceDecision:
    version: str
    accepted: bool
    checks: dict[str, bool]
    rejection_reasons: tuple[str, ...]
    evidence_digest: str
    source_energy_hartree: float
    budget_reference_energy_hartree: float
    candidate_energy_hartree: float
    before_parameter_count: int
    after_parameter_count: int
    before_structure_digest: str
    after_structure_digest: str


def evaluate_acceptance(
    evidence: AcceptanceEvidence,
    criteria: AcceptanceCriteria = AcceptanceCriteria(),
) -> AcceptanceDecision:
    scalar_values = (
        evidence.source_energy_hartree,
        evidence.budget_reference_energy_hartree,
        evidence.candidate_energy_hartree,
        evidence.independent_energy_hartree,
        evidence.independent_state_fidelity,
        evidence.constraint_residual,
        evidence.kkt_residual,
    )
    finite = all(math.isfinite(value) for value in scalar_values)
    physical_domain = bool(
        finite
        and 0.0 <= evidence.independent_state_fidelity <= 1.0 + 1e-12
        and evidence.constraint_residual >= 0.0
        and evidence.kkt_residual >= 0.0
    )
    before = evidence.before_resources
    after = evidence.after_resources
    before_values = (
        before.cnot_count,
        before.cnot_depth,
        before.total_depth,
        before.parameter_count,
    )
    after_values = (
        after.cnot_count,
        after.cnot_depth,
        after.total_depth,
        after.parameter_count,
    )
    if criteria.guard_logical_block_count:
        before_values = (*before_values, before.logical_block_count)
        after_values = (*after_values, after.logical_block_count)
    pareto_nonworse = all(new <= old for old, new in zip(before_values, after_values))
    resource_improved = any(new < old for old, new in zip(before_values, after_values))
    fallback_attempted = evidence.fallback_optimizer is not None
    fallback_completed = bool(
        evidence.fallback_optimizer is not None and evidence.fallback_optimizer.completed
    )
    optimizer_path_reviewed = bool(
        evidence.primary_optimizer.success
        and evidence.primary_optimizer.completed
        or (
            not evidence.primary_optimizer.success
            and fallback_attempted
            and fallback_completed
        )
    )
    checks = {
        "finite": finite,
        "physical_scalar_domain": physical_domain,
        "cumulative_energy_budget": finite
        and evidence.candidate_energy_hartree - evidence.budget_reference_energy_hartree
        <= criteria.cumulative_energy_budget_hartree,
        "independent_energy_agreement": finite
        and abs(evidence.candidate_energy_hartree - evidence.independent_energy_hartree)
        <= criteria.independent_energy_tolerance_hartree,
        "independent_state_fidelity": finite
        and evidence.independent_state_fidelity >= criteria.minimum_state_fidelity,
        "constraint": finite
        and evidence.constraint_residual <= criteria.maximum_constraint_residual,
        "kkt": finite and evidence.kkt_residual <= criteria.maximum_kkt_residual,
        "resource_recount": evidence.full_resource_recount_succeeded,
        "transformation_semantics": evidence.transformation_semantics_validated,
        "pareto_nonworse": pareto_nonworse,
        "resource_improved": resource_improved,
        "optimizer_path_reviewed": optimizer_path_reviewed,
    }
    reasons = tuple(name for name, passed in checks.items() if not passed)
    evidence_payload = {
        "version": ACCEPTANCE_VERSION,
        "criteria": asdict(criteria),
        "evidence": {
            **{
                key: value
                for key, value in asdict(evidence).items()
                if key not in {"before_resources", "after_resources"}
            },
            "before_resources": asdict(before),
            "after_resources": asdict(after),
        },
        "checks": checks,
    }
    digest = hashlib.sha256(canonical_json_bytes(evidence_payload)).hexdigest()
    return AcceptanceDecision(
        ACCEPTANCE_VERSION,
        not reasons,
        checks,
        reasons,
        digest,
        evidence.source_energy_hartree,
        evidence.budget_reference_energy_hartree,
        evidence.candidate_energy_hartree,
        before.parameter_count,
        after.parameter_count,
        before.structure_digest,
        after.structure_digest,
    )


# Python's and NumPy's legacy RNG states are process-global.  A per-runtime lock
# would therefore permit one transaction's rollback to alter another transaction.
# Serialize compression transactions until RNGs become runtime-owned generators.
_PROCESS_TRANSACTION_LOCK = threading.Lock()


def _write_exclusive(path: Path, payload: bytes) -> None:
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        written = 0
        while written < len(payload):
            count = os.write(descriptor, payload[written:])
            if count <= 0:
                raise TransactionError("artifact write made no forward progress")
            written += count
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class CompressionTransaction:
    def __init__(
        self,
        runtime: CompressionRuntime,
        artifact_root: Path,
        *,
        transaction_id: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self.runtime = runtime
        self.artifact_root = artifact_root
        self.transaction_id = transaction_id or f"tx-{uuid.uuid4().hex}"
        if not self.transaction_id or "/" in self.transaction_id or ".." in self.transaction_id:
            raise TransactionError("transaction ID is unsafe")
        if timeout_seconds is not None and (not math.isfinite(timeout_seconds) or timeout_seconds <= 0):
            raise TransactionError("transaction timeout must be finite and positive")
        self.timeout_seconds = timeout_seconds
        self.started = 0.0
        self.snapshot: RuntimeSnapshot | None = None
        self.staging = artifact_root / ".staging" / self.transaction_id
        self.committed_path = artifact_root / "committed" / self.transaction_id
        self.failed_path = artifact_root / "failed" / self.transaction_id
        self._lock = _PROCESS_TRANSACTION_LOCK
        self._committed = False
        self._rolled_back = False

    def __enter__(self) -> "CompressionTransaction":
        if not self._lock.acquire(blocking=False):
            raise TransactionError("another compression transaction is active in this process")
        try:
            self.runtime.validate()
            self.snapshot = self.runtime.snapshot()
            self.started = time.monotonic()
            self.artifact_root.mkdir(parents=True, exist_ok=True)
            self.staging.parent.mkdir(parents=True, exist_ok=True)
            _fsync_directory(self.artifact_root)
            self.staging.mkdir()
            _fsync_directory(self.staging.parent)
            self.stage_json(
                "attempt.json",
                {
                    "version": TRANSACTION_VERSION,
                    "transaction_id": self.transaction_id,
                    "before_snapshot_digest": self.snapshot.snapshot_digest,
                },
            )
            self.stage_json("snapshot.json", self.snapshot.to_dict())
            return self
        except Exception:
            self._lock.release()
            raise

    def check_deadline(self) -> None:
        if self.timeout_seconds is not None and time.monotonic() - self.started > self.timeout_seconds:
            raise TransactionDeadlineExceeded("compression transaction deadline exceeded")

    def stage_json(self, relative_path: str, value: Mapping[str, Any]) -> Path:
        self.check_deadline()
        pure = PurePosixPath(relative_path)
        if pure.is_absolute() or ".." in pure.parts or not pure.parts:
            raise TransactionError("artifact path escapes transaction directory")
        destination = self.staging.joinpath(*pure.parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            dict(value), sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8") + b"\n"
        _write_exclusive(destination, payload)
        _fsync_directory(destination.parent)
        return destination

    def commit(self, decision: AcceptanceDecision) -> Path:
        self.check_deadline()
        if self.snapshot is None or self._committed or self._rolled_back:
            raise TransactionError("transaction is not active")
        if not decision.accepted:
            raise TransactionError("cannot commit a rejected acceptance decision")
        if (
            decision.version != ACCEPTANCE_VERSION
            or not decision.checks
            or not all(decision.checks.values())
            or decision.rejection_reasons
            or len(decision.evidence_digest) != 64
        ):
            raise TransactionError("acceptance decision integrity check failed")
        self.runtime.validate()
        if (
            len(self.snapshot.ansatz.indices) != decision.before_parameter_count
            or len(self.runtime.ansatz.indices) != decision.after_parameter_count
        ):
            raise TransactionError("acceptance resources are not bound to runtime parameter counts")
        if (
            self.snapshot.energy_hartree != decision.source_energy_hartree
            or self.runtime.energy_hartree != decision.candidate_energy_hartree
        ):
            raise TransactionError("acceptance energies are not bound to runtime state")
        if (
            float(self.snapshot.metadata["budget_reference_energy_hartree"])
            != decision.budget_reference_energy_hartree
            or float(self.runtime.metadata["budget_reference_energy_hartree"])
            != decision.budget_reference_energy_hartree
        ):
            raise TransactionError("acceptance budget reference is not immutable across the transaction")
        if (
            self.snapshot.metadata["resource_structure_digest"]
            != decision.before_structure_digest
            or self.runtime.metadata["resource_structure_digest"]
            != decision.after_structure_digest
        ):
            raise TransactionError("acceptance resource digests are not bound to runtime state")
        self.stage_json(
            "commit.json",
            {
                "version": TRANSACTION_VERSION,
                "transaction_id": self.transaction_id,
                "before_snapshot_digest": self.snapshot.snapshot_digest,
                "after_snapshot_digest": self.runtime.snapshot().snapshot_digest,
                "acceptance": asdict(decision),
            },
        )
        self.committed_path.parent.mkdir(parents=True, exist_ok=True)
        _fsync_directory(self.artifact_root)
        if self.committed_path.exists():
            raise TransactionError("committed transaction directory already exists")
        _fsync_directory(self.staging)
        os.replace(self.staging, self.committed_path)
        _fsync_directory(self.committed_path.parent)
        self._committed = True
        return self.committed_path

    def rollback(self, reason: str) -> Path:
        if self.snapshot is None or self._rolled_back:
            raise TransactionError("transaction is not active or already rolled back")
        self.runtime.restore(self.snapshot)
        failure = {
            "version": TRANSACTION_VERSION,
            "transaction_id": self.transaction_id,
            "before_snapshot_digest": self.snapshot.snapshot_digest,
            "restored_snapshot_digest": self.runtime.snapshot().snapshot_digest,
            "reason": str(reason),
        }
        try:
            self.stage_json("rollback.json", failure)
        except (FileExistsError, TransactionDeadlineExceeded):
            fallback = self.staging / "rollback-fallback.json"
            if not fallback.exists():
                _write_exclusive(
                    fallback,
                    json.dumps(failure, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n",
                )
        self.failed_path.parent.mkdir(parents=True, exist_ok=True)
        _fsync_directory(self.artifact_root)
        if self.failed_path.exists():
            raise TransactionError("failed transaction directory already exists")
        _fsync_directory(self.staging)
        os.replace(self.staging, self.failed_path)
        _fsync_directory(self.failed_path.parent)
        self._rolled_back = True
        return self.failed_path

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        try:
            if not self._committed and not self._rolled_back:
                reason = "scope-exited-without-commit" if exc_value is None else f"{exc_type.__name__}: {exc_value}"
                self.rollback(reason)
        finally:
            self._lock.release()


def recover_orphaned_transaction(
    runtime: CompressionRuntime,
    artifact_root: Path,
    transaction_id: str,
) -> Path:
    """Restore a runtime from a fsynced orphan staging directory after process loss."""
    lock = _PROCESS_TRANSACTION_LOCK
    if not lock.acquire(blocking=False):
        raise TransactionError("another compression transaction is active during recovery")
    try:
        staging = artifact_root / ".staging" / transaction_id
        failed = artifact_root / "failed" / transaction_id
        if not staging.is_dir() or failed.exists():
            raise TransactionError("orphan staging directory is absent or already recovered")
        snapshot_path = staging / "snapshot.json"
        if not snapshot_path.is_file():
            raise TransactionError("orphan transaction has no durable snapshot")
        try:
            value = json.loads(snapshot_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise TransactionError("orphan snapshot is unreadable") from error
        snapshot = RuntimeSnapshot.from_dict(value)
        runtime.restore(snapshot)
        recovery = {
            "version": TRANSACTION_VERSION,
            "transaction_id": transaction_id,
            "recovery": "orphan-staging-fail-closed-rollback",
            "restored_snapshot_digest": runtime.snapshot().snapshot_digest,
        }
        _write_exclusive(
            staging / "recovery-rollback.json",
            json.dumps(recovery, sort_keys=True, separators=(",", ":")).encode("utf-8")
            + b"\n",
        )
        _fsync_directory(staging)
        failed.parent.mkdir(parents=True, exist_ok=True)
        _fsync_directory(artifact_root)
        os.replace(staging, failed)
        _fsync_directory(failed.parent)
        return failed
    finally:
        lock.release()

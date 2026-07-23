"""Crash-safe, auditable bundle lifecycle for V4.1 case execution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
from typing import Any
import uuid

from .baseline import ROOT
from .identity import canonical_json_bytes


BUNDLE_VERSION = "v4.1-case-bundle-v1"
CASE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.-]*$")


class BundleLifecycleError(RuntimeError):
    """Raised when execution state is ambiguous or unsafe."""


class CaseAlreadyLocked(BundleLifecycleError):
    """Raised when a second writer requests the same case."""


class ExistingBundleError(BundleLifecycleError):
    """Raised when canonical output already exists."""


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_json_exclusive(path: Path, value: Any) -> None:
    payload = canonical_json_bytes(value) + b"\n"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)
    _fsync_directory(path.parent)


def _git_head() -> str:
    return subprocess.check_output(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True
    ).strip()


def _validate_case_id(case_id: str) -> str:
    value = str(case_id)
    if not CASE_PATTERN.fullmatch(value):
        raise BundleLifecycleError(f"invalid case ID: {value!r}")
    return value


def _process_is_active(record: dict[str, Any]) -> bool:
    if record.get("host") != socket.gethostname():
        return False
    try:
        os.kill(int(record["pid"]), 0)
    except (ProcessLookupError, ValueError, TypeError):
        return False
    except PermissionError:
        return True
    return True


def _bundle_files(bundle: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(bundle.rglob("*")):
        if not path.is_file() or path.name == "bundle-manifest.json":
            continue
        relative = str(path.relative_to(bundle))
        records.append({"path": relative, "sha256": _sha256(path), "size": path.stat().st_size})
    return records


def validate_complete_bundle(bundle: Path) -> dict[str, Any]:
    marker = bundle / "bundle-manifest.json"
    if not marker.is_file():
        raise BundleLifecycleError(f"bundle has no completion manifest: {bundle}")
    manifest = json.loads(marker.read_text(encoding="utf-8"))
    stored_digest = manifest.get("bundle_digest")
    payload = dict(manifest)
    payload.pop("bundle_digest", None)
    checks = {
        "version": manifest.get("version") == BUNDLE_VERSION,
        "bundle_digest": isinstance(stored_digest, str) and _digest(payload) == stored_digest,
        "file_inventory": _bundle_files(bundle) == manifest.get("files"),
    }
    failures = [name for name, passed in checks.items() if not passed]
    if failures:
        raise BundleLifecycleError(
            f"bundle completion evidence failed ({bundle}): {', '.join(failures)}"
        )
    return manifest


@dataclass
class CaseRunLease:
    """One exclusive writer and its run-UUID staging directory."""

    output_root: Path
    case_id: str
    protocol_digest: str
    checkpoint_digest: str
    run_uuid: str | None = None

    def __post_init__(self) -> None:
        self.output_root = Path(self.output_root).resolve()
        self.case_id = _validate_case_id(self.case_id)
        if not re.fullmatch(r"[0-9a-f]{64}", self.protocol_digest):
            raise BundleLifecycleError("protocol digest must be lowercase SHA-256")
        if not re.fullmatch(r"[0-9a-f]{64}", self.checkpoint_digest):
            raise BundleLifecycleError("checkpoint digest must be lowercase SHA-256")
        self.run_uuid = str(uuid.UUID(self.run_uuid)) if self.run_uuid else str(uuid.uuid4())
        self.lock_path = self.output_root / ".locks" / f"{self.case_id}.lock"
        self.staging = self.output_root / ".staging" / self.case_id / self.run_uuid
        self.canonical = self.output_root / self.case_id
        self.acquired = False
        self.finalized = False

    def acquire(self) -> "CaseRunLease":
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        (self.output_root / ".staging" / self.case_id).mkdir(parents=True, exist_ok=True)
        _fsync_directory(self.output_root)
        if self.canonical.exists():
            raise ExistingBundleError(f"canonical bundle already exists: {self.canonical}")
        record = {
            "version": BUNDLE_VERSION,
            "run_uuid": self.run_uuid,
            "case_id": self.case_id,
            "host": socket.gethostname(),
            "pid": os.getpid(),
            "started_at_utc": datetime.now(timezone.utc).isoformat(),
            "git_commit": _git_head(),
            "protocol_digest": self.protocol_digest,
            "checkpoint_digest": self.checkpoint_digest,
            "intended_canonical_output": str(self.canonical),
            "staging": str(self.staging),
        }
        try:
            _write_json_exclusive(self.lock_path, record)
        except FileExistsError as error:
            raise CaseAlreadyLocked(f"case lock already exists: {self.lock_path}") from error
        try:
            self.staging.mkdir()
            _fsync_directory(self.staging.parent)
        except Exception:
            self._release_lock()
            raise
        self.acquired = True
        return self

    def finalize(self) -> dict[str, Any]:
        if not self.acquired or not self.staging.is_dir():
            raise BundleLifecycleError("cannot finalize an unacquired case lease")
        if self.finalized:
            raise BundleLifecycleError("case bundle was already finalized")
        files = _bundle_files(self.staging)
        if not files:
            raise BundleLifecycleError("refusing to finalize an empty bundle")
        payload: dict[str, Any] = {
            "version": BUNDLE_VERSION,
            "case_id": self.case_id,
            "run_uuid": self.run_uuid,
            "protocol_digest": self.protocol_digest,
            "checkpoint_digest": self.checkpoint_digest,
            "git_commit": _git_head(),
            "files": files,
        }
        manifest = {**payload, "bundle_digest": _digest(payload)}
        _write_json_exclusive(self.staging / "bundle-manifest.json", manifest)
        self.finalized = True
        return manifest

    def promote(self) -> Path:
        if not self.acquired or not self.finalized:
            raise BundleLifecycleError("promotion requires an acquired finalized lease")
        validate_complete_bundle(self.staging)
        if self.canonical.exists():
            raise ExistingBundleError(f"canonical bundle appeared before promotion: {self.canonical}")
        self.staging.rename(self.canonical)
        _fsync_directory(self.output_root)
        self._release_lock()
        self.acquired = False
        return self.canonical

    def _release_lock(self) -> None:
        if not self.lock_path.exists():
            return
        try:
            record = json.loads(self.lock_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise BundleLifecycleError("cannot safely identify owned case lock") from error
        if record.get("run_uuid") != self.run_uuid:
            raise BundleLifecycleError("refusing to remove a lock owned by another run")
        self.lock_path.unlink()
        _fsync_directory(self.lock_path.parent)

    def close(self) -> None:
        """Release this process's lock while deliberately retaining staging."""

        if self.acquired:
            self._release_lock()
            self.acquired = False

    def __enter__(self) -> "CaseRunLease":
        return self.acquire()

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()


def audit_case_state(output_root: Path, case_id: str) -> dict[str, Any]:
    """Classify canonical, lock, and orphan staging without modifying any of them."""

    root = Path(output_root).resolve()
    case = _validate_case_id(case_id)
    canonical = root / case
    lock_path = root / ".locks" / f"{case}.lock"
    staging_parent = root / ".staging" / case
    lock: dict[str, Any] | None = None
    lock_status = "absent"
    if lock_path.exists():
        try:
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
            lock_status = "active" if _process_is_active(lock) else "stale"
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            lock_status = "invalid"
    canonical_manifest = None
    canonical_status = "absent"
    if canonical.exists():
        try:
            canonical_manifest = validate_complete_bundle(canonical)
            canonical_status = "complete"
        except BundleLifecycleError:
            canonical_status = "inconsistent"
    staging_records: list[dict[str, Any]] = []
    if staging_parent.is_dir():
        for staging in sorted(path for path in staging_parent.iterdir() if path.is_dir()):
            record: dict[str, Any] = {"path": str(staging), "run_uuid": staging.name}
            try:
                manifest = validate_complete_bundle(staging)
                record["bundle_digest"] = manifest["bundle_digest"]
                if canonical_manifest is None:
                    record["status"] = "complete-unpromoted"
                elif manifest["bundle_digest"] == canonical_manifest["bundle_digest"]:
                    record["status"] = "complete-duplicate"
                else:
                    record["status"] = "inconsistent-with-canonical"
            except BundleLifecycleError:
                record["status"] = "incomplete"
            staging_records.append(record)
    ambiguous = bool(
        lock_status in {"invalid", "stale"}
        or canonical_status == "inconsistent"
        or any(
            item["status"] in {"incomplete", "complete-unpromoted", "inconsistent-with-canonical"}
            for item in staging_records
        )
    )
    return {
        "schema_version": "1.0.0",
        "artifact_kind": "v4.1-case-state-audit",
        "case_id": case,
        "read_only": True,
        "canonical_status": canonical_status,
        "canonical_bundle_digest": (
            canonical_manifest["bundle_digest"] if canonical_manifest else None
        ),
        "lock_status": lock_status,
        "lock": lock,
        "staging": staging_records,
        "ambiguous": ambiguous,
        "safe_to_start": canonical_status == "absent"
        and lock_status == "absent"
        and not staging_records,
    }

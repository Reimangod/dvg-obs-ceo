"""Crash-safe publication primitives for immutable scientific artifacts."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
from typing import Any, Mapping
import uuid


class ArtifactPublicationError(RuntimeError):
    pass


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_fsynced(path: Path, payload: bytes) -> None:
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise ArtifactPublicationError("artifact write made no progress")
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def json_payload(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            dict(value), indent=2, sort_keys=True, allow_nan=False
        )
        + "\n"
    ).encode("utf-8")


def atomic_write_new_json(path: Path, value: Mapping[str, Any]) -> None:
    """Publish one immutable JSON file without exposing partial contents."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise ArtifactPublicationError(f"refusing to overwrite artifact: {path}")
    temporary = path.parent / f".{path.name}.staging-{uuid.uuid4().hex}"
    try:
        _write_fsynced(temporary, json_payload(value))
        if path.exists():
            raise ArtifactPublicationError(
                f"artifact appeared during publication: {path}"
            )
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    except BaseException:
        if temporary.exists():
            temporary.unlink()
        raise


def atomic_publish_json_directory(
    output: Path,
    value: Mapping[str, Any],
    *,
    filename: str = "summary.json",
) -> None:
    """Publish a one-file immutable result bundle by atomic directory rename."""
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise ArtifactPublicationError(f"refusing to overwrite bundle: {output}")
    staging = output.parent / f".{output.name}.staging-{uuid.uuid4().hex}"
    staging.mkdir()
    try:
        _write_fsynced(staging / filename, json_payload(value))
        _fsync_directory(staging)
        if output.exists():
            raise ArtifactPublicationError(
                f"bundle appeared during publication: {output}"
            )
        os.replace(staging, output)
        _fsync_directory(output.parent)
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging)
        raise

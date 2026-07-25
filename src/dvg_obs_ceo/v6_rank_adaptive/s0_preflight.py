"""Fail-closed preflight for the immutable V6 parent release."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
from typing import Any, Mapping

from dvg_obs_ceo.baseline import ROOT
from dvg_obs_ceo.v5_release_audit import audit as audit_v5_release


MANIFEST = ROOT / "manifests/v6-s0-parent-freeze-v1.json"
THREAD_VARIABLES = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "NUMEXPR_NUM_THREADS",
)


class V6S0PreflightError(RuntimeError):
    """Raised when the V6 parent or execution environment is not frozen."""


def _run(*arguments: str) -> str:
    completed = subprocess.run(
        arguments,
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _tagged_blob(tag: str, relative_path: str) -> bytes:
    return subprocess.run(
        ("git", "show", f"{tag}:{relative_path}"),
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout


def _parent_artifact_inventory(tag: str) -> str:
    paths = _run(
        "git",
        "ls-tree",
        "-r",
        "--name-only",
        tag,
        "artifacts",
    ).splitlines()
    records = bytearray()
    for relative_path in sorted(path for path in paths if path):
        content = _tagged_blob(tag, relative_path)
        records.extend(
            f"{hashlib.sha256(content).hexdigest()}  {relative_path}\n".encode()
        )
    return hashlib.sha256(records).hexdigest()


def collect_observations(*, require_clean: bool = True) -> dict[str, Any]:
    """Collect only local, reproducible evidence needed by the preflight."""
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    parent = manifest["parent"]
    tag = parent["annotated_tag"]
    status = _run("git", "status", "--porcelain=v1", "--untracked-files=all")
    observations: dict[str, Any] = {
        "parent_commit": _run("git", "rev-list", "-n", "1", tag),
        "tag_type": _run("git", "cat-file", "-t", tag),
        "submodule_commit": _run(
            "git",
            "rev-parse",
            f"{tag}:{parent['submodule_path']}",
        ),
        "artifact_inventory_sha256": _parent_artifact_inventory(tag),
        "dependency_sha256": {
            path: hashlib.sha256(_tagged_blob(tag, path)).hexdigest()
            for path in manifest["dependencies"]
        },
        "python": platform.python_version(),
        "thread_environment": {
            name: os.environ.get(name) for name in THREAD_VARIABLES
        },
        "clean_check_required": require_clean,
        "working_tree_clean": status == "",
        "working_tree_status": status,
        "v5_release_passed": audit_v5_release()["passed"] is True,
    }
    return observations


def validate(
    manifest: Mapping[str, Any],
    observations: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate collected observations without weakening any frozen check."""
    parent = manifest["parent"]
    checks = {
        "parent_commit": observations["parent_commit"] == parent["commit"],
        "annotated_tag": observations["tag_type"] == "tag",
        "submodule_commit": (
            observations["submodule_commit"] == parent["submodule_commit"]
        ),
        "artifact_inventory": (
            observations["artifact_inventory_sha256"]
            == manifest["artifact_inventory"]["sha256"]
        ),
        "dependencies": (
            observations["dependency_sha256"] == manifest["dependencies"]
        ),
        "python": observations["python"] == manifest["environment"]["python"],
        "thread_environment": (
            observations["thread_environment"]
            == manifest["environment"]["thread_environment"]
        ),
        "clean_working_tree": (
            observations["working_tree_clean"] is True
            or observations["clean_check_required"] is False
        ),
        "v5_release_audit": observations["v5_release_passed"] is True,
    }
    failed = sorted(name for name, passed in checks.items() if not passed)
    result = {
        "schema_version": "1.0.0",
        "artifact_kind": "v6-s0-parent-preflight",
        "manifest": str(MANIFEST.relative_to(ROOT)),
        "checks": checks,
        "passed": not failed,
        "failed_checks": failed,
        "observations": dict(observations),
        "paper_measurement_cost": None,
    }
    if failed:
        raise V6S0PreflightError(
            "V6 S0 preflight failed: " + ", ".join(failed)
        )
    return result


def audit(*, require_clean: bool = True) -> dict[str, Any]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return validate(
        manifest,
        collect_observations(require_clean=require_clean),
    )


def main() -> None:
    try:
        result = audit()
    except (
        OSError,
        KeyError,
        TypeError,
        ValueError,
        subprocess.SubprocessError,
        V6S0PreflightError,
    ) as error:
        print(f"V6 S0 preflight failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()

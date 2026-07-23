"""Immutable V3 protocol-input validation and freeze checks."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any, Mapping

from .baseline import ROOT, verify_upstream


PROTOCOL_ID = "dvg-obs-v3-stationarity-protocol-v1"
PROTOCOL_TAG = PROTOCOL_ID
DEFAULT_MANIFEST = ROOT / "manifests" / "v3-stationarity-protocol-v1.json"
REQUIRED_THREADS = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
}


class V3ProtocolError(RuntimeError):
    """Raised when V3 input provenance or the execution freeze is invalid."""


def _git(*arguments: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(ROOT), *arguments], text=True
    ).strip()


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise V3ProtocolError(f"cannot read JSON object: {path}") from error
    if not isinstance(value, dict):
        raise V3ProtocolError(f"JSON artifact is not an object: {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_path(relative: str) -> Path:
    candidate = (ROOT / relative).resolve()
    try:
        candidate.relative_to(ROOT.resolve())
    except ValueError as error:
        raise V3ProtocolError(f"source path escapes repository: {relative}") from error
    return candidate


def _check_equal(checks: dict[str, bool], name: str, left: Any, right: Any) -> None:
    checks[name] = left == right


def audit_inputs(manifest_path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    manifest = _read_object(manifest_path)
    checks: dict[str, bool] = {}
    _check_equal(checks, "protocol_id", manifest.get("protocol_id"), PROTOCOL_ID)
    _check_equal(checks, "execution_tag", manifest.get("execution_tag"), PROTOCOL_TAG)

    sources: Mapping[str, Any] = manifest.get("source_files", {})
    resolved: dict[str, Path] = {}
    source_hashes: dict[str, str] = {}
    for name, record in sources.items():
        if not isinstance(record, dict):
            checks[f"source_record:{name}"] = False
            continue
        path = _source_path(str(record.get("path", "")))
        resolved[name] = path
        checks[f"source_exists:{name}"] = path.is_file()
        if path.is_file():
            observed = _sha256(path)
            source_hashes[name] = observed
            checks[f"source_sha256:{name}"] = observed == record.get("sha256")

    required = {
        "plan",
        "s10_protocol",
        "checkpoint",
        "selected_trial",
        "summary",
        "selector_decision",
        "candidate_catalog",
    }
    checks["required_source_set"] = set(sources) == required
    if not required.issubset(resolved) or not all(
        resolved[name].is_file() for name in required if name in resolved
    ):
        failures = [name for name, passed in checks.items() if not passed]
        raise V3ProtocolError("V3 input audit failed: " + ", ".join(failures))

    checkpoint = _read_object(resolved["checkpoint"])
    trial = _read_object(resolved["selected_trial"])
    summary = _read_object(resolved["summary"])
    selector = _read_object(resolved["selector_decision"])
    catalog = json.loads(resolved["candidate_catalog"].read_text(encoding="utf-8"))
    if not isinstance(catalog, list):
        raise V3ProtocolError("candidate catalog is not a list")

    expected_checkpoint = manifest["immutable_checkpoint"]
    snapshot = checkpoint["resources"]["snapshot"]
    _check_equal(
        checks,
        "checkpoint_digest",
        checkpoint["checkpoint_digest"],
        expected_checkpoint["checkpoint_digest"],
    )
    _check_equal(
        checks,
        "checkpoint_iteration",
        checkpoint["adapt_iteration"],
        expected_checkpoint["adapt_iteration"],
    )
    _check_equal(
        checks,
        "checkpoint_energy",
        checkpoint["energy_hartree"],
        expected_checkpoint["energy_hartree"],
    )
    for field in (
        "parameter_count",
        "logical_block_count",
        "cnot_count",
        "cnot_depth",
        "total_depth",
        "structure_digest",
    ):
        _check_equal(
            checks,
            f"checkpoint_resource:{field}",
            snapshot[field],
            expected_checkpoint[field],
        )

    expected_candidate = manifest["immutable_candidate"]
    candidate = trial["candidate"]
    for field in (
        "candidate_id",
        "equivalence_class_id",
        "source_block_id",
        "source_pool_indices",
        "kind",
        "target_family",
    ):
        _check_equal(
            checks,
            f"candidate_identity:{field}",
            candidate[field],
            expected_candidate[field],
        )
    physical = trial["physical_resources"]["snapshot"]
    for field in (
        "parameter_count",
        "logical_block_count",
        "cnot_count",
        "cnot_depth",
        "total_depth",
        "structure_digest",
    ):
        _check_equal(
            checks,
            f"candidate_resource:{field}",
            physical[field],
            expected_candidate[field],
        )
    _check_equal(
        checks,
        "candidate_rejected_only_by_kkt",
        trial["acceptance"]["rejection_reasons"],
        expected_candidate["s10_rejection_reasons"],
    )
    _check_equal(
        checks,
        "selector_chose_immutable_candidate",
        selector["chosen_candidate_id"],
        expected_candidate["candidate_id"],
    )
    catalog_ids = [entry["candidate_id"] for entry in catalog]
    checks["candidate_occurs_once_in_catalog"] = (
        catalog_ids.count(expected_candidate["candidate_id"]) == 1
    )
    checks["v2_remains_rolled_back"] = (
        summary["dvg_obs_ceo"]["status"] == "rolled-back"
        and summary["dvg_obs_ceo"]["accepted"] is False
    )

    criteria = manifest["acceptance"]
    checks["criteria_unchanged"] = criteria == {
        "cumulative_energy_budget_hartree": 1e-4,
        "independent_energy_tolerance_hartree": 1e-10,
        "minimum_independent_state_recomputation_fidelity": 1.0 - 1e-10,
        "maximum_constraint_residual": 1e-10,
        "maximum_stationarity_residual": 1e-8,
        "resource_fields_must_be_nonworse": [
            "parameter_count",
            "logical_block_count",
            "cnot_count",
            "cnot_depth",
            "total_depth",
        ],
        "at_least_one_resource_must_improve": True,
        "fci_is_runtime_input": False,
    }
    scope = manifest["scope_limits"]
    checks["scope_is_bounded"] = (
        scope["candidate_count"] == 1
        and scope["solver_family_count"] == 1
        and scope["lih_execution_count"] == 1
        and scope["candidate_reselection"] is False
        and scope["threshold_relaxation"] is False
        and scope["ordinary_gsd_adapt_reexecution"] is False
        and scope["ceo_star_reexecution"] is False
        and scope["paper_measurement_cost"] is None
    )
    checks["problem_is_diagnostic"] = (
        manifest["problem"]["development_or_validation"]
        == "diagnostic-development"
    )

    try:
        upstream = verify_upstream()
        checks["upstream_commit"] = (
            upstream["commit"] == manifest["upstream_commit"]
        )
    except Exception:
        checks["upstream_commit"] = False

    predecessor = manifest["predecessor"]
    for kind in ("protocol", "result"):
        try:
            observed = _git("rev-parse", f"{predecessor[f'{kind}_tag']}^{{}}")
        except subprocess.CalledProcessError:
            observed = None
        checks[f"predecessor_{kind}_tag"] = observed == predecessor[f"{kind}_commit"]

    failures = [name for name, passed in checks.items() if not passed]
    result = {
        "schema_version": "1.0.0",
        "artifact_kind": "v3-s0-immutable-input-audit",
        "protocol_id": PROTOCOL_ID,
        "manifest_sha256": _sha256(manifest_path),
        "source_sha256": source_hashes,
        "passed": not failures,
        "checks": checks,
        "failed_checks": failures,
        "claim_boundary": (
            "Input provenance and scope validation only; no VQE, polishing, "
            "candidate selection, or performance claim was executed."
        ),
    }
    if failures:
        raise V3ProtocolError("V3 input audit failed: " + ", ".join(failures))
    return result


def verify_freeze() -> dict[str, Any]:
    head = _git("rev-parse", "HEAD")
    try:
        tagged = _git("rev-parse", f"{PROTOCOL_TAG}^{{}}")
    except subprocess.CalledProcessError as error:
        raise V3ProtocolError(f"missing protocol tag: {PROTOCOL_TAG}") from error
    dirty = _git("status", "--porcelain")
    threads = {name: os.environ.get(name) for name in REQUIRED_THREADS}
    if head != tagged or dirty or threads != REQUIRED_THREADS:
        raise V3ProtocolError(
            "V3 requires clean tagged code and canonical threads: "
            f"head={head}, tag={tagged}, dirty={bool(dirty)}, threads={threads}"
        )
    return {"head": head, "protocol_tag": PROTOCOL_TAG, "threads": threads}


def _write_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    payload = json.dumps(value, indent=2, sort_keys=True, allow_nan=False).encode() + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise V3ProtocolError("artifact write made no progress")
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--require-freeze", action="store_true")
    arguments = parser.parse_args()
    freeze = verify_freeze() if arguments.require_freeze else None
    result = audit_inputs(arguments.manifest)
    if freeze is not None:
        result["execution_freeze"] = freeze
    if arguments.artifact is not None:
        _write_exclusive(arguments.artifact, result)
    print(
        json.dumps(
            {"passed": result["passed"], "checks": len(result["checks"])},
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()

"""V4-S0 preregistration and immutable-source audit."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any

from .baseline import ROOT, verify_upstream
from .v3_protocol import _write_exclusive


PROTOCOL_ID = "dvg-obs-v4-global-obs-protocol-v1"
PROTOCOL_TAG = PROTOCOL_ID
DEFAULT_MANIFEST = ROOT / "manifests" / "v4-global-obs-protocol-v1.json"
REQUIRED_THREADS = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
}


class V4ProtocolError(RuntimeError):
    """Raised when the Global OBS preregistration is inconsistent."""


def _git(*arguments: str) -> str:
    return subprocess.check_output(["git", "-C", str(ROOT), *arguments], text=True).strip()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _path(relative: str) -> Path:
    result = (ROOT / relative).resolve()
    try:
        result.relative_to(ROOT.resolve())
    except ValueError as error:
        raise V4ProtocolError(f"source path escapes repository: {relative}") from error
    return result


def audit_manifest(manifest_path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    checks: dict[str, bool] = {
        "protocol_id": manifest.get("protocol_id") == PROTOCOL_ID,
        "execution_tag": manifest.get("execution_tag") == PROTOCOL_TAG,
        "upstream": verify_upstream()["commit"] == manifest.get("upstream_commit"),
        "null_result_valid": manifest.get("null_result_is_valid") is True,
    }
    hashes: dict[str, str] = {}
    for name, record in manifest.get("source_files", {}).items():
        path = _path(record["path"])
        checks[f"source_exists:{name}"] = path.is_file()
        if path.is_file():
            hashes[name] = _sha256(path)
            checks[f"source_sha256:{name}"] = hashes[name] == record["sha256"]
    checks["source_set"] = set(manifest.get("source_files", {})) == {
        "h2_checkpoint",
        "h4_checkpoint",
        "h2_h4_candidate_rows",
        "lih_checkpoint",
        "v2_selected_trial",
        "v2_summary",
        "v3_gradient_result",
        "v3_polishing_result",
        "v3_result_document",
    }
    summary = json.loads(_path(manifest["source_files"]["v2_summary"]["path"]).read_text())
    v3_polishing = json.loads(
        _path(manifest["source_files"]["v3_polishing_result"]["path"]).read_text()
    )
    lih = json.loads(_path(manifest["source_files"]["lih_checkpoint"]["path"]).read_text())
    checks["v2_remains_rolled_back"] = bool(
        summary["dvg_obs_ceo"]["status"] == "rolled-back"
        and summary["dvg_obs_ceo"]["accepted"] is False
    )
    checks["v3_calibration_unsuccessful"] = v3_polishing["passed"] is False
    snapshot = lih["resources"]["snapshot"]
    checks["lih_reference_frozen"] = bool(
        lih["energy_hartree"] == -7.797909682469515
        and snapshot["parameter_count"] == 15
        and snapshot["cnot_count"] == 107
        and snapshot["cnot_depth"] == 30
        and snapshot["total_depth"] == 171
    )
    endpoints = manifest["co_primary_endpoints"]
    checks["endpoint_orders_distinct"] = (
        endpoints["circuit_primary_order"] != endpoints["parameter_primary_order"]
    )
    checks["hard_guards"] = endpoints["componentwise_nonworse_guards"] == [
        "parameter_count",
        "cnot_count",
        "cnot_depth",
        "total_depth",
    ] and endpoints["require_at_least_one_strict_resource_improvement"] is True
    budget = manifest["exact_vqe_budget"]
    checks["bounded_exact_attempts"] = bool(
        budget["top_k_per_endpoint"] == 2
        and budget["maximum_unique_exact_attempts"] == 4
        and budget["duplicate_structure_is_executed_once"] is True
        and budget["actual_energy_is_pass_fail_only"] is True
    )
    acceptance = manifest["acceptance"]
    checks["acceptance_unchanged"] = acceptance == {
        "cumulative_energy_budget_hartree": 1e-4,
        "independent_energy_tolerance_hartree": 1e-10,
        "minimum_independent_state_recomputation_fidelity": 1.0 - 1e-10,
        "maximum_constraint_residual": 1e-10,
        "maximum_stationarity_residual": 1e-8,
        "two_path_gradient_audit_required": True,
        "full_resource_recount_required": True,
        "transformation_semantics_required": True,
        "fci_is_runtime_input": False,
    }
    roles = manifest["data_roles"]
    checks["data_roles"] = bool(
        len(roles["calibration"]) == 2
        and len(roles["development"]) == 1
        and roles["confirmatory_validation"] is None
    )
    stops = manifest["stop_rules"]
    checks["stop_rules_fail_closed"] = all(stops.values())
    checks["identity_layers"] = manifest["identity_layers"] == [
        "StatePreparationID",
        "ProblemID",
        "MeasurementContextID",
        "ConstraintSemanticID",
        "ConstraintNumericalID",
    ]
    failures = [name for name, passed in checks.items() if not passed]
    result = {
        "schema_version": "1.0.0",
        "artifact_kind": "v4-s0-preregistration-audit",
        "protocol_id": PROTOCOL_ID,
        "manifest_sha256": _sha256(manifest_path),
        "source_sha256": hashes,
        "passed": not failures,
        "checks": checks,
        "failed_checks": failures,
        "claim_boundary": "Preregistration and source audit only; no Global OBS search or VQE execution.",
    }
    if failures:
        raise V4ProtocolError("V4-S0 audit failed: " + ", ".join(failures))
    return result


def verify_freeze() -> dict[str, Any]:
    head = _git("rev-parse", "HEAD")
    tagged = _git("rev-parse", f"{PROTOCOL_TAG}^{{}}")
    dirty = _git("status", "--porcelain")
    threads = {name: os.environ.get(name) for name in REQUIRED_THREADS}
    if head != tagged or dirty or threads != REQUIRED_THREADS:
        raise V4ProtocolError(
            f"V4-S0 requires clean tagged code and canonical threads: head={head}, "
            f"tag={tagged}, dirty={bool(dirty)}, threads={threads}"
        )
    return {"head": head, "protocol_tag": PROTOCOL_TAG, "threads": threads}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-path", type=Path)
    parser.add_argument("--require-freeze", action="store_true")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    arguments = parser.parse_args()
    freeze = verify_freeze() if arguments.require_freeze else None
    result = audit_manifest(arguments.manifest)
    if freeze is not None:
        result["execution_freeze"] = freeze
    if arguments.artifact_path is not None:
        _write_exclusive(arguments.artifact_path, result)
    print(json.dumps({"passed": result["passed"], "checks": len(result["checks"])}, sort_keys=True))


if __name__ == "__main__":
    main()

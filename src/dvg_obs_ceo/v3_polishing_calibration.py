"""Run the preregistered V3-S2 H2/H4 polishing calibration."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import importlib
import inspect
import json
import math
import os
from pathlib import Path
import subprocess
from typing import Any

import numpy as np
import scipy

from .baseline import ROOT, verify_upstream
from .block_ir import enumerate_candidates, recover_dvg_blocks
from .calibration import embed_block_transformation
from .polishing import POLISHER_VERSION, TrustNCGConfig, polish_trust_ncg
from .resources import AnsatzStructure, apply_candidate_structure
from .s8_probe import _algorithm
from .v3_gradient_audit import _energy, _gradient, _load_and_verify
from .v3_protocol import _write_exclusive


PROTOCOL_ID = "dvg-obs-v3-s2-polishing-protocol-v1"
PROTOCOL_TAG = PROTOCOL_ID
DEFAULT_MANIFEST = ROOT / "manifests" / "v3-s2-polishing-protocol-v1.json"
REQUIRED_THREADS = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
}


class V3PolishingCalibrationError(RuntimeError):
    """Raised when S2 provenance, replay, or calibration fails."""


def _git(*arguments: str) -> str:
    return subprocess.check_output(["git", "-C", str(ROOT), *arguments], text=True).strip()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _path(relative: str) -> Path:
    result = (ROOT / relative).resolve()
    try:
        result.relative_to(ROOT.resolve())
    except ValueError as error:
        raise V3PolishingCalibrationError(f"input path escapes repository: {relative}") from error
    return result


def verify_freeze() -> dict[str, Any]:
    head = _git("rev-parse", "HEAD")
    tagged = _git("rev-parse", f"{PROTOCOL_TAG}^{{}}")
    threads = {name: os.environ.get(name) for name in REQUIRED_THREADS}
    dirty = _git("status", "--porcelain")
    if head != tagged or dirty or threads != REQUIRED_THREADS:
        raise V3PolishingCalibrationError(
            f"S2 requires clean tagged code and canonical threads: head={head}, "
            f"tag={tagged}, dirty={bool(dirty)}, threads={threads}"
        )
    return {"head": head, "protocol_tag": PROTOCOL_TAG, "threads": threads}


def _load_manifest(path: Path) -> tuple[dict[str, Any], TrustNCGConfig]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("protocol_id") != PROTOCOL_ID or manifest.get("execution_tag") != PROTOCOL_TAG:
        raise V3PolishingCalibrationError("S2 protocol identity mismatch")
    if verify_upstream()["commit"] != manifest["upstream_commit"]:
        raise V3PolishingCalibrationError("pinned upstream mismatch")
    for record in manifest["inputs"].values():
        if _sha256(_path(record["path"])) != record["sha256"]:
            raise V3PolishingCalibrationError(f"S2 input hash mismatch: {record['path']}")
    if scipy.__version__ != manifest["solver"]["scipy_version"]:
        raise V3PolishingCalibrationError("SciPy version mismatch")
    source_modules = {
        "scipy.optimize._trustregion": importlib.import_module("scipy.optimize._trustregion"),
        "scipy.optimize._trustregion_ncg": importlib.import_module("scipy.optimize._trustregion_ncg"),
        "scipy.optimize._numdiff": importlib.import_module("scipy.optimize._numdiff"),
    }
    for name, module in source_modules.items():
        source_path = Path(inspect.getsourcefile(module) or "")
        if not source_path.is_file() or _sha256(source_path) != manifest["local_primary_sources"][name]:
            raise V3PolishingCalibrationError(f"SciPy implementation source mismatch: {name}")
    config = TrustNCGConfig()
    normalized = json.loads(json.dumps(asdict(config)))
    expected = dict(manifest["solver"])
    expected.pop("version")
    expected.pop("scipy_version")
    expected.pop("hvp_step_rule")
    if normalized != expected or manifest["solver"]["version"] != POLISHER_VERSION:
        raise V3PolishingCalibrationError("runtime polishing configuration differs from manifest")
    return manifest, config


def _work_reconciles(result: dict[str, Any]) -> bool:
    scipy_work = result["scipy_reported"]
    ledger = result["work"]
    if scipy_work is None:
        return False
    return bool(
        scipy_work["function_evaluations"] == ledger["energy_evaluations"]
        and scipy_work["dummy_hessian_initializations"] == 1
        and scipy_work["hessian_evaluations_including_dummy"]
        == ledger["hessian_vector_products"] + 1
        and scipy_work["gradient_evaluations_excluding_hvp"]
        + ledger["hessian_vector_gradient_evaluations"]
        == ledger["gradient_vector_evaluations"]
        and ledger["hessian_vector_gradient_evaluations"]
        == 2 * ledger["hessian_vector_products"]
    )


def run(artifact_path: Path, manifest_path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    freeze = verify_freeze()
    manifest, config = _load_manifest(manifest_path)
    s1_manifest = _path(manifest["inputs"]["s1_manifest"]["path"])
    _, rows, checkpoints = _load_and_verify(s1_manifest)
    records: list[dict[str, Any]] = []
    cases: Counter[str] = Counter()

    for case_id in sorted(checkpoints):
        checkpoint = checkpoints[case_id]
        algorithm, pool = _algorithm(case_id)
        source = AnsatzStructure.create(
            checkpoint["ansatz_indices"], checkpoint["ansatz_coefficients"], checkpoint["iteration_counts"]
        )
        blocks = recover_dvg_blocks(
            pool, source.indices, source.coefficients, source.cumulative_parameter_counts
        )
        block_by_id = {block.block_id: block for block in blocks}
        candidates = {
            candidate.candidate_id: candidate for candidate in enumerate_candidates(pool, blocks)
        }
        case_rows = sorted(
            (row for row in rows if row["case_id"] == case_id),
            key=lambda row: row["candidate"]["candidate_id"],
        )
        for row in case_rows:
            candidate_id = row["candidate"]["candidate_id"]
            candidate = candidates[candidate_id]
            block = block_by_id[candidate.source_block_id]
            embedded = embed_block_transformation(len(source.indices), block, candidate)
            initial = np.asarray(row["paths"]["projection_on"]["coordinates"], dtype=np.float64)
            target = apply_candidate_structure(
                pool, source, candidate, initial[embedded.local_target_slice]
            )
            target = AnsatzStructure.create(target.indices, initial, target.cumulative_parameter_counts)
            energy = lambda value, indices=target.indices: _energy(algorithm, value, indices)
            gradient = lambda value, indices=target.indices: _gradient(algorithm, value, indices)
            first = polish_trust_ncg(initial, energy, gradient, config=config)
            second = polish_trust_ncg(initial, energy, gradient, config=config)
            replay_identical = first == second
            final = np.asarray(first["coordinates"], dtype=np.float64)
            independent_energy = float(energy(final))
            independent_gradient = np.asarray(gradient(final), dtype=np.float64)
            independent_gradient_inf = (
                float(np.max(np.abs(independent_gradient))) if independent_gradient.size else 0.0
            )
            initial_energy = float(row["paths"]["projection_on"]["independent_energy_hartree"])
            criteria = manifest["calibration_acceptance"]
            checks = {
                "optimizer_success": first["success"] is True,
                "permitted_status": first["status"] in config.permitted_success_statuses,
                "finite": bool(
                    math.isfinite(float(first["energy_hartree"]))
                    and np.all(np.isfinite(final))
                    and np.all(np.isfinite(independent_gradient))
                ),
                "stationarity": independent_gradient_inf
                <= criteria["maximum_final_gradient_infinity"],
                "independent_energy": abs(independent_energy - float(first["energy_hartree"]))
                <= criteria["maximum_independent_energy_difference_hartree"],
                "energy_nonworse": independent_energy - initial_energy
                <= criteria["maximum_energy_increase_from_stored_endpoint_hartree"],
                "work_reconciles": _work_reconciles(first),
                "replay_identical": replay_identical,
            }
            passed = all(checks.values())
            records.append(
                {
                    "case_id": case_id,
                    "candidate_id": candidate_id,
                    "kind": candidate.kind,
                    "target_dimension": len(target.indices),
                    "initial_energy_hartree": initial_energy,
                    "initial_gradient_infinity": row["paths"]["projection_on"]["gradient_infinity"],
                    "result": first,
                    "independent_final_energy_hartree": independent_energy,
                    "independent_final_gradient": independent_gradient.tolist(),
                    "independent_final_gradient_infinity": independent_gradient_inf,
                    "checks": checks,
                    "passed": passed,
                }
            )
            cases[case_id] += 1

    injection_input = np.array([10.0, -5.0])
    injection_before = injection_input.copy()
    injection = polish_trust_ncg(
        injection_input,
        lambda value: float(value @ value),
        lambda value: 2.0 * value,
        config=TrustNCGConfig(maximum_gradient_vector_evaluations=1),
    )
    failure_injection = {
        "passed": bool(
            not injection["success"]
            and injection["failure_reason"] == "EvaluationBudgetExceeded"
            and np.array_equal(injection_input, injection_before)
            and np.array_equal(np.asarray(injection["coordinates"]), injection_before)
        ),
        "failure_reason": injection["failure_reason"],
        "input_unchanged": bool(np.array_equal(injection_input, injection_before)),
    }
    failed = [record["candidate_id"] for record in records if not record["passed"]]
    passed = bool(
        len(records) == manifest["scope"]["candidate_count"]
        and not failed
        and failure_injection["passed"]
    )
    artifact = {
        "schema_version": "1.0.0",
        "artifact_kind": "v3-s2-polishing-calibration",
        "protocol_id": PROTOCOL_ID,
        "manifest_sha256": _sha256(manifest_path),
        "execution_freeze": freeze,
        "passed": passed,
        "case_counts": dict(sorted(cases.items())),
        "failed_candidate_ids": failed,
        "maximum_final_gradient_infinity": max(
            record["independent_final_gradient_infinity"] for record in records
        ),
        "total_polishing_work_first_replay": {
            "energy_evaluations": sum(record["result"]["work"]["energy_evaluations"] for record in records),
            "gradient_vector_evaluations": sum(record["result"]["work"]["gradient_vector_evaluations"] for record in records),
            "hessian_vector_products": sum(record["result"]["work"]["hessian_vector_products"] for record in records),
            "ordinary_gsd_adapt_iterations": 0,
            "ceo_star_adapt_iterations": 0,
            "paper_measurement_cost": None,
        },
        "failure_injection": failure_injection,
        "claim_boundary": (
            "H2/H4 calibration of one fixed polishing configuration only; no LiH evaluation, "
            "new ansatz discovery, validation, or paper Measurement Cost claim."
        ),
        "records": records,
    }
    if not passed:
        raise V3PolishingCalibrationError(
            f"S2 calibration failed closed: failed={failed}, injection={failure_injection}"
        )
    _write_exclusive(artifact_path, artifact)
    return artifact


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-path", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    arguments = parser.parse_args()
    result = run(arguments.artifact_path, arguments.manifest)
    print(json.dumps({
        "passed": result["passed"],
        "maximum_final_gradient_infinity": result["maximum_final_gradient_infinity"],
        "work": result["total_polishing_work_first_replay"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()

"""Run the preregistered ordinary GSD-ADAPT-VQE LiH comparator."""

from __future__ import annotations

import argparse
import importlib
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import time
from typing import Any

from jsonschema import Draft202012Validator
import numpy as np

from .baseline import ROOT, _environment, _load_upstream, _nested_sum, verify_upstream
from .resources import AnsatzStructure, evaluate_full_circuit_resources, paper_era_backend, resources_to_dict


PROTOCOL_ID = "dvg-obs-s11-gsd-lih-protocol-v1"
PROTOCOL_TAG = "dvg-obs-s11-gsd-lih-protocol-v1"
REQUIRED_THREADS = {"OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
PAPER_REFERENCE = {"cnot_count": 392, "cnot_depth": 384, "measurement_cost": 50468}
CHEMICAL_ACCURACY_HARTREE = 0.0015936
SUMMARY_SCHEMA = ROOT / "schemas" / "s11-gsd-summary-v1.schema.json"


class S11GSDError(RuntimeError):
    """Raised when the GSD comparison would not be reproducible."""


def _git(*arguments: str) -> str:
    return subprocess.check_output(["git", "-C", str(ROOT), *arguments], text=True).strip()


def verify_freeze() -> dict[str, Any]:
    head = _git("rev-parse", "HEAD")
    try:
        tagged = _git("rev-parse", f"{PROTOCOL_TAG}^{{}}")
    except subprocess.CalledProcessError as error:
        raise S11GSDError("missing S11 execution tag") from error
    dirty = _git("status", "--porcelain")
    threads = {name: os.environ.get(name) for name in REQUIRED_THREADS}
    if head != tagged or dirty or threads != REQUIRED_THREADS:
        raise S11GSDError(
            f"S11 requires clean tagged code and canonical threads: head={head}, tag={tagged}, dirty={bool(dirty)}, threads={threads}"
        )
    return {"head": head, "tag": PROTOCOL_TAG, "threads": threads}


def _write_json(path: Path, value: Any) -> None:
    payload = json.dumps(value, indent=2, sort_keys=True, allow_nan=False).encode("utf-8") + b"\n"
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise S11GSDError("artifact write made no progress")
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


def _append_jsonl(path: Path, value: Any) -> None:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"
    descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o644)
    try:
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise S11GSDError("trajectory write made no progress")
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def validate_summary(value: dict[str, Any]) -> None:
    schema = json.loads(SUMMARY_SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(value)


def run(bundle: Path) -> dict[str, Any]:
    freeze = verify_freeze()
    provenance = verify_upstream()
    if bundle.exists():
        raise FileExistsError(f"refusing to overwrite S11 GSD bundle: {bundle}")
    staging = bundle.with_name(f".{bundle.name}.staging")
    if staging.exists():
        raise FileExistsError(f"orphan S11 staging requires audit: {staging}")
    staging.mkdir(parents=True)
    _fsync_directory(staging.parent)
    random.seed(0)
    np.random.seed(0)
    LinAlgAdapt, _, creators, chemical_accuracy = _load_upstream()
    if float(chemical_accuracy) != CHEMICAL_ACCURACY_HARTREE:
        raise S11GSDError("pinned upstream chemical-accuracy constant changed")
    _, create_lih = creators
    pools = importlib.import_module("adaptvqe.pools")
    molecule = create_lih(3.0)
    pool = pools.GSD(molecule)
    algorithm = LinAlgAdapt(
        pool=pool,
        molecule=molecule,
        verbose=False,
        max_adapt_iter=200,
        max_opt_iter=10000,
        full_opt=True,
        threshold=1e-6,
        convergence_criterion="total_g_norm",
        tetris=False,
        progressive_opt=False,
        candidates=1,
        sel_criterion="gradient",
        recycle_hessian=False,
        penalize_cnots=False,
        rand_degenerate=False,
        shots=None,
    )
    backend = paper_era_backend()
    started = time.perf_counter()
    algorithm.initialize()
    rows: list[dict[str, Any]] = []
    cumulative_parameter_counts: list[int] = []
    while algorithm.data.iteration_counter < algorithm.max_adapt_iter:
        previous = int(algorithm.data.iteration_counter)
        previous_parameters = len(algorithm.indices)
        finished = bool(algorithm.run_iteration())
        iteration = int(algorithm.data.iteration_counter)
        if iteration == previous:
            raise S11GSDError("GSD ADAPT iteration made no progress")
        if len(algorithm.indices) != previous_parameters + 1:
            raise S11GSDError("ordinary non-TETRIS GSD added other than one operator in an iteration")
        cumulative_parameter_counts.append(len(algorithm.indices))
        structure = AnsatzStructure.create(
            algorithm.indices, algorithm.coefficients, cumulative_parameter_counts
        )
        resources = evaluate_full_circuit_resources(pool, structure, backend)
        row = {
            "adapt_iteration": iteration,
            "energy_hartree": float(algorithm.energy),
            "fci_error_hartree": abs(float(algorithm.energy) - float(algorithm.exact_energy)),
            "parameter_count": len(algorithm.coefficients),
            "cnot_count": resources.snapshot.cnot_count,
            "cnot_depth": resources.snapshot.cnot_depth,
            "total_depth": resources.snapshot.total_depth,
            "cumulative_wall_time_seconds": time.perf_counter() - started,
            "cumulative_optimizer_energy_evaluations": _nested_sum(algorithm.data.evolution.nfevs),
            "cumulative_gradient_component_equivalent": _nested_sum(algorithm.data.evolution.ngevs),
            "finished": finished,
            "paper_measurement_cost": None,
        }
        rows.append(row)
        _append_jsonl(staging / "trajectory.jsonl", row)
        print(json.dumps(row, sort_keys=True), flush=True)
        if row["fci_error_hartree"] < float(chemical_accuracy):
            break
        if finished:
            raise S11GSDError("GSD converged before chemical accuracy")
    if not rows:
        raise S11GSDError("GSD produced no completed ADAPT iteration")
    final_structure = AnsatzStructure.create(
        algorithm.indices, algorithm.coefficients, cumulative_parameter_counts
    )
    final_resources = evaluate_full_circuit_resources(pool, final_structure, backend)
    reached = rows[-1]["fci_error_hartree"] < float(chemical_accuracy)
    result = {
        "schema_version": "1.0.0",
        "artifact_kind": "s11-direct-pinned-gsd-adapt-lih",
        "protocol_id": PROTOCOL_ID,
        "execution_freeze": freeze,
        "upstream": provenance,
        "environment": _environment(),
        "algorithm": {
            "name": "GSD-ADAPT-VQE",
            "pool": "GSD",
            "tetris": False,
            "hessian_recycling": False,
            "optimized_gradient_measurements": False,
            "gradient_threshold": 1e-6,
            "seed": 0,
        },
        "trajectory": rows,
        "reached_chemical_accuracy": reached,
        "first_chemical_accuracy_iteration": rows[-1]["adapt_iteration"] if reached else None,
        "energy_hartree": rows[-1]["energy_hartree"],
        "fci_energy_hartree": float(algorithm.exact_energy),
        "fci_error_hartree": rows[-1]["fci_error_hartree"],
        "ansatz_indices": list(final_structure.indices),
        "ansatz_coefficients": list(final_structure.coefficients),
        "resources": resources_to_dict(final_resources),
        "work": {
            "optimizer_energy_evaluations": _nested_sum(algorithm.data.evolution.nfevs),
            "gradient_component_equivalent": _nested_sum(algorithm.data.evolution.ngevs),
            "wall_time_seconds": time.perf_counter() - started,
            "paper_measurement_cost": None,
        },
        "paper_reference": PAPER_REFERENCE,
        "paper_resource_parity": {
            "cnot_count": final_resources.snapshot.cnot_count == PAPER_REFERENCE["cnot_count"],
            "cnot_depth": final_resources.snapshot.cnot_depth == PAPER_REFERENCE["cnot_depth"],
            "measurement_cost": None,
        },
        "claim_boundary": [
            "This is a direct run of pinned GSD-ADAPT-VQE under the paper's stated original-protocol contrast.",
            "Local evaluation counters are not paper-equivalent measurement cost.",
            "The paper measurement value is reference-only and is not a reproduced result.",
        ],
    }
    validate_summary(result)
    _write_json(staging / "summary.json", result)
    _fsync_directory(staging)
    os.replace(staging, bundle)
    _fsync_directory(bundle.parent)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    arguments = parser.parse_args()
    sys.argv[:] = [sys.argv[0]]
    result = run(arguments.bundle)
    print(json.dumps({"bundle": str(arguments.bundle), "iteration": result["first_chemical_accuracy_iteration"], "paper_resource_parity": result["paper_resource_parity"]}, sort_keys=True))


if __name__ == "__main__":
    main()

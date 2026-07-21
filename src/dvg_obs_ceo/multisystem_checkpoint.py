"""Create resumability-audited CEO* first-accuracy checkpoints for full figures."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import importlib
import json
import os
from pathlib import Path
import random
import subprocess
import time
from typing import Any

import numpy as np

from .baseline import ROOT, _environment, _nested_sum, verify_upstream
from .hessian import HessianCaptureSession, capture_to_dict
from .identity import canonical_json_bytes
from .resources import AnsatzStructure, evaluate_full_circuit_resources, paper_era_backend, resources_to_dict
from .s8_probe import _state_vector


PROTOCOL_TAG = "dvg-obs-full-figures-checkpoint-protocol-v1"
MANIFEST_PATH = ROOT / "manifests" / "full-figures-ceo-star-v4-v1.json"
CHEMICAL_ACCURACY_HARTREE = 0.0015936
REQUIRED_THREADS = {"OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}


class MultiSystemCheckpointError(RuntimeError):
    """Raised when a CEO* checkpoint cannot be certified."""


def _git(*arguments: str) -> str:
    return subprocess.check_output(["git", "-C", str(ROOT), *arguments], text=True).strip()


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def registered_cases() -> dict[str, dict[str, Any]]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return {item["case_id"]: item for item in manifest["cases"]}


def verify_freeze(case_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    cases = registered_cases()
    if case_id not in cases:
        raise MultiSystemCheckpointError(f"unregistered case: {case_id}")
    head = _git("rev-parse", "HEAD")
    tag = _git("rev-parse", f"{PROTOCOL_TAG}^{{}}")
    dirty = _git("status", "--porcelain")
    threads = {name: os.environ.get(name) for name in REQUIRED_THREADS}
    if head != tag or dirty or threads != REQUIRED_THREADS:
        raise MultiSystemCheckpointError(
            f"checkpoint run requires clean tagged code and canonical threads: head={head}, tag={tag}, dirty={bool(dirty)}, threads={threads}"
        )
    return {
        "head": head,
        "protocol_tag": PROTOCOL_TAG,
        "manifest_sha256": hashlib.sha256(MANIFEST_PATH.read_bytes()).hexdigest(),
        "threads": threads,
    }, cases[case_id]


def _algorithm(case: dict[str, Any]) -> tuple[Any, Any]:
    verify_upstream()
    molecules = importlib.import_module("adaptvqe.molecules")
    pools = importlib.import_module("adaptvqe.pools")
    algorithms = importlib.import_module("adaptvqe.algorithms.adapt_vqe")
    if case["molecule"] == "H6":
        molecule = molecules.create_h6(case["distance_angstrom"])
    elif case["molecule"] == "BeH2":
        molecule = molecules.create_beh2(case["distance_angstrom"])
    else:
        raise MultiSystemCheckpointError(f"unsupported molecule: {case['molecule']}")
    pool = pools.DVG_CEO(molecule)
    algorithm = algorithms.LinAlgAdapt(
        pool=pool,
        molecule=molecule,
        verbose=False,
        max_adapt_iter=100,
        max_opt_iter=10000,
        full_opt=True,
        threshold=float(case["gradient_threshold"]),
        convergence_criterion="total_g_norm",
        tetris=True,
        progressive_opt=False,
        candidates=1,
        sel_criterion="gradient",
        recycle_hessian=True,
        penalize_cnots=False,
        rand_degenerate=False,
        shots=None,
    )
    return algorithm, pool


def _append_progress(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, sort_keys=True, allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _write_exclusive(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    payload = json.dumps(value, indent=2, sort_keys=True, allow_nan=False).encode() + b"\n"
    try:
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise MultiSystemCheckpointError("artifact write made no progress")
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def run(case_id: str, output: Path) -> dict[str, Any]:
    freeze, case = verify_freeze(case_id)
    if output.exists():
        raise FileExistsError(output)
    progress = output.with_suffix(".progress.jsonl")
    if progress.exists():
        raise FileExistsError(f"prior progress ledger requires audit: {progress}")
    random.seed(0)
    np.random.seed(0)
    started = time.perf_counter()
    algorithm, pool = _algorithm(case)
    adapt_module = importlib.import_module("adaptvqe.algorithms.adapt_vqe")
    algorithm.initialize()
    trajectory: list[dict[str, Any]] = []
    counts: list[int] = []
    with HessianCaptureSession(adapt_module) as capture:
        while algorithm.data.iteration_counter < algorithm.max_adapt_iter:
            before = int(algorithm.data.iteration_counter)
            finished = bool(algorithm.run_iteration())
            iteration = int(algorithm.data.iteration_counter)
            if iteration == before:
                raise MultiSystemCheckpointError("CEO* terminated before strict chemical accuracy")
            counts.append(len(algorithm.indices))
            structure = AnsatzStructure.create(algorithm.indices, algorithm.coefficients, counts)
            resources = evaluate_full_circuit_resources(pool, structure, paper_era_backend())
            error = abs(float(algorithm.energy) - float(algorithm.exact_energy))
            record = {
                "adapt_iteration": iteration,
                "energy_hartree": float(algorithm.energy),
                "absolute_error_hartree": error,
                "parameter_count": len(algorithm.coefficients),
                "cnot_count": resources.snapshot.cnot_count,
                "cnot_depth": resources.snapshot.cnot_depth,
                "total_depth": resources.snapshot.total_depth,
                "finished": finished,
                "elapsed_seconds": time.perf_counter() - started,
            }
            trajectory.append(record)
            _append_progress(progress, record)
            if error < CHEMICAL_ACCURACY_HARTREE:
                break
            if finished:
                raise MultiSystemCheckpointError("CEO* converged before strict chemical accuracy")
    if not trajectory or trajectory[-1]["absolute_error_hartree"] >= CHEMICAL_ACCURACY_HARTREE:
        raise MultiSystemCheckpointError("maximum iterations reached before chemical accuracy")
    if not capture.records:
        raise MultiSystemCheckpointError("no optimizer Hessian capture")
    structure = AnsatzStructure.create(algorithm.indices, algorithm.coefficients, counts)
    inverse = np.asarray(algorithm.inv_hessian, dtype=np.float64)
    gradient = np.asarray(algorithm.gradients, dtype=np.float64)
    last_capture = capture.records[-1]
    if inverse.shape != (len(structure.indices), len(structure.indices)) or gradient.shape != (len(structure.indices),):
        raise MultiSystemCheckpointError("optimizer state dimensions are invalid")
    if not np.array_equal(inverse, last_capture.final_inverse_hessian):
        raise MultiSystemCheckpointError("captured/live inverse Hessians differ")
    independent_energy = float(algorithm.evaluate_energy(list(structure.coefficients), list(structure.indices)))
    if abs(independent_energy - float(algorithm.energy)) > 1e-10:
        raise MultiSystemCheckpointError("independent checkpoint energy mismatch")
    state = _state_vector(algorithm, structure.coefficients, structure.indices)
    physical = evaluate_full_circuit_resources(pool, structure, paper_era_backend())
    structural = evaluate_full_circuit_resources(
        pool, structure, paper_era_backend(), coefficient_policy="deterministic-structural"
    )
    if physical.snapshot != structural.snapshot:
        raise MultiSystemCheckpointError("physical/structural resource mismatch")
    checkpoint = {
        "schema_version": "1.0.0",
        "artifact_kind": "multisystem-ceo-star-first-accuracy-checkpoint",
        "execution_freeze": freeze,
        "upstream": verify_upstream(),
        "environment": _environment(),
        "case": case,
        "chemical_accuracy_hartree": CHEMICAL_ACCURACY_HARTREE,
        "adapt_iteration": trajectory[-1]["adapt_iteration"],
        "trajectory": trajectory,
        "ansatz_indices": list(structure.indices),
        "ansatz_coefficients": list(structure.coefficients),
        "iteration_counts": list(structure.cumulative_parameter_counts),
        "energy_hartree": float(algorithm.energy),
        "exact_energy_hartree": float(algorithm.exact_energy),
        "independent_energy_hartree": independent_energy,
        "gradient": gradient.tolist(),
        "recycled_inverse_hessian": inverse.tolist(),
        "hessian_capture": capture_to_dict(last_capture),
        "resources": resources_to_dict(physical),
        "statevector_sha256": hashlib.sha256(np.asarray(state, dtype=">c16").tobytes()).hexdigest(),
        "work": {
            "baseline_optimizer_energy_evaluations": _nested_sum(algorithm.data.evolution.nfevs),
            "baseline_gradient_component_equivalent": _nested_sum(algorithm.data.evolution.ngevs),
            "wall_time_seconds": time.perf_counter() - started,
            "paper_measurement_cost": None,
        },
        "claim_boundary": "Exploratory CEO* first-accuracy source for requested full figures; not paper trajectory reproduction or confirmatory validation.",
    }
    checkpoint["checkpoint_digest"] = _digest(checkpoint)
    _write_exclusive(output, checkpoint)
    return checkpoint


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("case_id", choices=sorted(registered_cases()))
    parser.add_argument("output", type=Path)
    arguments = parser.parse_args()
    result = run(arguments.case_id, arguments.output)
    print(json.dumps({
        "case": arguments.case_id,
        "iteration": result["adapt_iteration"],
        "error": result["trajectory"][-1]["absolute_error_hartree"],
        "resources": result["resources"]["snapshot"],
        "wall_time_seconds": result["work"]["wall_time_seconds"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()

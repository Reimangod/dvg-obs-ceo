"""Run the unmodified, pinned paper-era CEO-ADAPT-VQE* baseline."""

from __future__ import annotations

import argparse
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import platform
import random
import subprocess
import sys
import time
from typing import Any

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
UPSTREAM = ROOT / "vendor" / "ceo-adapt-vqe"
EXPECTED_COMMIT = "a3f89d03e6a03c89767d3cf8ee7657a57653dda0"
EXPECTED_TREE = "794d847f5c1be1590d93da81b905a915dfa17d13"


class BaselineError(RuntimeError):
    """Raised when provenance or baseline execution is unsafe."""


def _git(*arguments: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(UPSTREAM), *arguments], text=True
    ).strip()


def verify_upstream() -> dict[str, str]:
    commit = _git("rev-parse", "HEAD")
    tree = _git("rev-parse", "HEAD^{tree}")
    dirty = _git("status", "--porcelain")
    if commit != EXPECTED_COMMIT or tree != EXPECTED_TREE or dirty:
        raise BaselineError(
            "pinned upstream provenance failed: "
            f"commit={commit}, tree={tree}, dirty={bool(dirty)}"
        )
    return {"commit": commit, "git_tree": tree, "worktree_clean": "true"}


def _load_upstream() -> tuple[Any, Any, Any, float]:
    sys.path.insert(0, str(UPSTREAM))
    from adaptvqe.algorithms.adapt_vqe import LinAlgAdapt
    from adaptvqe.chemistry import chemical_accuracy
    from adaptvqe.molecules import create_h2, create_lih
    from adaptvqe.pools import DVG_CEO
    import adaptvqe

    module_path = Path(adaptvqe.__file__).resolve()
    if UPSTREAM.resolve() not in module_path.parents:
        raise BaselineError(f"adaptvqe imported from unexpected path: {module_path}")
    return LinAlgAdapt, DVG_CEO, (create_h2, create_lih), float(chemical_accuracy)


def _nested_sum(values: Any) -> int:
    if isinstance(values, (list, tuple)):
        return sum(_nested_sum(value) for value in values)
    return 0 if values is None else int(values)


def _sha256(payload: Any) -> str:
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _environment() -> dict[str, Any]:
    packages = (
        "numpy",
        "scipy",
        "qiskit",
        "pyscf",
        "openfermion",
        "openfermionpyscf",
    )
    return {
        "python": platform.python_version(),
        "packages": {name: version(name) for name in packages},
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "blas_threads": {
            name: os.environ.get(name)
            for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")
        },
    }


def _write_once(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():
        raise BaselineError(f"refusing to overwrite artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def run_case(case: str, output: Path) -> dict[str, Any]:
    provenance = verify_upstream()
    if case not in {"h2-smoke", "lih-3a"}:
        raise BaselineError(f"unsupported registered baseline case: {case}")
    LinAlgAdapt, DVG_CEO, creators, chemical_accuracy = _load_upstream()
    create_h2, create_lih = creators
    random.seed(0)
    np.random.seed(0)

    if case == "h2-smoke":
        molecule = create_h2(1.5)
        max_adapt_iter = 1
        threshold = 0.1
        problem = {"molecule": "H2", "distance_angstrom": 1.5, "basis": "sto-3g"}
        stop_at_accuracy = False
    else:
        assert case == "lih-3a"
        molecule = create_lih(3.0)
        max_adapt_iter = 50
        threshold = 1e-6
        problem = {"molecule": "LiH", "distance_angstrom": 3.0, "basis": "sto-3g"}
        stop_at_accuracy = True

    pool = DVG_CEO(molecule)
    algorithm = LinAlgAdapt(
        pool=pool,
        molecule=molecule,
        verbose=False,
        max_adapt_iter=max_adapt_iter,
        max_opt_iter=10000,
        full_opt=True,
        threshold=threshold,
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

    started = time.perf_counter()
    algorithm.initialize()
    trajectory: list[dict[str, Any]] = []
    crossing: int | None = None
    while algorithm.data.iteration_counter < algorithm.max_adapt_iter:
        finished = bool(algorithm.run_iteration())
        iteration = int(algorithm.data.iteration_counter)
        error = abs(float(algorithm.energy) - float(algorithm.exact_energy))
        row = {
            "adapt_iteration": iteration,
            "energy_hartree": float(algorithm.energy),
            "absolute_error_hartree": error,
            "parameter_count": len(algorithm.coefficients),
            "finished": finished,
        }
        trajectory.append(row)
        print(json.dumps(row, sort_keys=True), flush=True)
        if error < chemical_accuracy:
            crossing = iteration
            if stop_at_accuracy:
                break
        if finished:
            break

    cnot_counts = [int(value) for value in algorithm.data.acc_cnot_counts(pool)]
    cnot_depths = [int(value) for value in algorithm.data.acc_cnot_depths(pool)]
    scientific_state = {
        "ansatz_indices": [int(value) for value in algorithm.indices],
        "ansatz_coefficients": [float(value) for value in algorithm.coefficients],
        "energy_hartree": float(algorithm.energy),
        "fci_energy_hartree": float(algorithm.exact_energy),
    }
    result = {
        "schema_version": "1.0.0",
        "artifact_kind": "direct-unmodified-upstream-baseline",
        "case_id": case,
        "upstream": provenance,
        "problem": {
            **problem,
            "qubits": int(molecule.n_qubits),
            "electrons": int(molecule.n_electrons),
        },
        "algorithm": {
            "name": "CEO-ADAPT-VQE*",
            "pool": "DVG_CEO",
            "tetris": True,
            "hessian_recycling": True,
            "selection": "gradient",
            "gradient_threshold": threshold,
            "seed": 0,
            "max_adapt_iter": max_adapt_iter,
            "max_opt_iter": 10000,
        },
        "environment": _environment(),
        "trajectory": trajectory,
        "first_chemical_accuracy_iteration": crossing,
        **scientific_state,
        "absolute_error_hartree": abs(
            scientific_state["energy_hartree"] - scientific_state["fci_energy_hartree"]
        ),
        "parameter_count": len(algorithm.coefficients),
        "cnot_count": cnot_counts[-1],
        "cnot_depth": cnot_depths[-1],
        "cnot_counts_by_iteration": cnot_counts,
        "cnot_depths_by_iteration": cnot_depths,
        "work": {
            "nfev": _nested_sum(algorithm.data.evolution.nfevs),
            "ngev_component_equivalent": _nested_sum(algorithm.data.evolution.ngevs),
            "wall_time_seconds": time.perf_counter() - started,
            "paper_measurement_cost": None,
        },
        "scientific_state_digest": _sha256(scientific_state),
        "claim_boundary": [
            "This is a direct run of the pinned unmodified upstream implementation.",
            "Work counters are not paper-equivalent measurement cost.",
        ],
    }
    _write_once(output, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", choices=("h2-smoke", "lih-3a"), required=True)
    # PySCF parses process-wide argv and reserves --output for its own log file.
    parser.add_argument("--artifact", type=Path, required=True)
    arguments = parser.parse_args()
    # PySCF also scans unknown process-wide options. Preserve parsed values and
    # remove extension CLI arguments before importing or invoking PySCF.
    sys.argv[:] = [sys.argv[0]]
    result = run_case(arguments.case, arguments.artifact)
    print(json.dumps({"artifact": str(arguments.artifact), "digest": result["scientific_state_digest"]}, sort_keys=True))


if __name__ == "__main__":
    main()

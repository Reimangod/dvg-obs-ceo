"""Frozen H6 trust-region scalability ablation after V6-NS9."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
from typing import Any, Mapping, Sequence

import numpy as np
from qiskit.quantum_info import Statevector

from dvg_obs_ceo.artifact_io import atomic_write_new_json
from dvg_obs_ceo.baseline import ROOT
from dvg_obs_ceo.block_ir import recover_dvg_blocks
from dvg_obs_ceo.identity import canonical_float64_hex, sha256_hex

from .native_rank2_feasibility import _qasm_resources
from .native_synthesis_pipeline import (
    CONTEXTS,
    NS1_OUTPUT,
    _load_context_structure,
)
from .ns7_energy_certification import (
    DEFAULT_OUTPUT as NS7_OUTPUT,
    _algorithm_for,
    _native_circuit,
    affine_embedding,
    projected_initial_coordinates,
)
from .ns9_sequential_pilot import RESULT_OUTPUT as NS9_OUTPUT


FREEZE_OUTPUT = ROOT / "artifacts/v6/ns10/queue-freeze-v1.json"
RESULT_OUTPUT = ROOT / "artifacts/v6/ns10/h6-optimizer-ablation-v1.json"
FREEZE_VERSION = "v6-ns10-h6-trust-region-freeze-v1"
RUNNER_VERSION = "v6-ns10-h6-trust-region-ablation-v1"
ENERGY_BUDGET_HARTREE = 1e-4
STATIONARITY_TOLERANCE = 1e-8
MAXIMUM_ITERATIONS = 200
FINITE_DIFFERENCE_STEP = 1e-6
WORK_CAP = {
    "optimizer_starts": 6,
    "optimizer_iterations": 1200,
    "energy_evaluations": 1500,
    "gradient_vector_evaluations": 1500,
    "finite_difference_energy_evaluations": 60,
    "full_resource_recounts": 4,
}
REQUIRED_THREADS = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
}


class NS10AblationError(RuntimeError):
    """Raised when the NS10 ablation violates its freeze."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _clean() -> None:
    if _git("status", "--porcelain"):
        raise NS10AblationError("NS10 requires a clean committed worktree")


def _threads() -> dict[str, str | None]:
    values = {name: os.environ.get(name) for name in REQUIRED_THREADS}
    if values != REQUIRED_THREADS:
        raise NS10AblationError(
            f"NS10 requires canonical threads: {values}"
        )
    return values


def build_freeze() -> dict[str, Any]:
    if FREEZE_OUTPUT.exists():
        raise NS10AblationError("NS10 freeze already exists")
    _clean()
    ns7 = json.loads(NS7_OUTPUT.read_text(encoding="utf-8"))
    ns9 = json.loads(NS9_OUTPUT.read_text(encoding="utf-8"))
    if ns9["summary"]["h6_optimizer_ablation_authorized"] is not True:
        raise NS10AblationError("NS9 did not authorize H6 ablation")
    candidates = [
        {
            "kind": "rank2-trust-region",
            "context_id": item["queue_item"]["context_id"],
            "family_id": item["family_id"],
            "normal": item["normal"],
            "source_block_id": item["queue_item"]["source_block_id"],
            "ns7_attempt_id": item["attempt_id"],
            "ns7_initial_energy_hartree": item["initialization"][
                "initial_energy_hartree"
            ],
            "ns7_final_gradient_infinity": item["certification"][
                "target_gradient_infinity"
            ],
            "ns7_iterations": item["optimizer"]["iterations"],
        }
        for item in ns7["attempts"]
        if item["queue_item"]["context_id"] in {"h6-1.5-s6", "h6-3.0"}
    ]
    candidates.sort(
        key=lambda item: (item["context_id"], item["family_id"])
    )
    controls = [
        {
            "kind": "same-structure-trust-region-control",
            "context_id": context_id,
        }
        for context_id in ("h6-1.5-s6", "h6-3.0")
    ]
    queue = [*candidates, *controls]
    if len(candidates) != 4 or len(queue) != 6:
        raise NS10AblationError("NS10 queue cardinality is incorrect")
    for item in queue:
        item["queue_id"] = "v6-ns10-queue:" + sha256_hex(item)
    freeze = {
        "schema_version": "1.0.0",
        "artifact_kind": "v6-ns10-h6-optimizer-ablation-freeze",
        "freeze_version": FREEZE_VERSION,
        "development_only": True,
        "creation_commit": _git("rev-parse", "HEAD"),
        "inputs": {
            "ns1": {
                "path": str(NS1_OUTPUT.relative_to(ROOT)),
                "sha256": _sha256(NS1_OUTPUT),
            },
            "ns7": {
                "path": str(NS7_OUTPUT.relative_to(ROOT)),
                "sha256": _sha256(NS7_OUTPUT),
            },
            "ns9": {
                "path": str(NS9_OUTPUT.relative_to(ROOT)),
                "sha256": _sha256(NS9_OUTPUT),
            },
        },
        "queue": queue,
        "queue_count": len(queue),
        "protocol": {
            "optimizer": "scipy-trust-constr",
            "hessian_update": "scipy-BFGS-init-scale-1.0",
            "maximum_iterations": MAXIMUM_ITERATIONS,
            "gtol": STATIONARITY_TOLERANCE,
            "xtol": 1e-12,
            "barrier_tol": 1e-12,
            "energy_budget_hartree": ENERGY_BUDGET_HARTREE,
            "initialization": "same-euclidean-projection-as-ns7",
            "fallback": None,
            "same_policy_all_contexts": True,
            "outcomes_may_change_queue": False,
            "work_cap": WORK_CAP,
            "fci_or_chemical_accuracy_used": False,
            "paper_measurement_cost": None,
        },
    }
    freeze["freeze_digest"] = sha256_hex(freeze)
    return freeze


def freeze_main() -> None:
    try:
        freeze = build_freeze()
        atomic_write_new_json(FREEZE_OUTPUT, freeze)
    except (
        KeyError,
        OSError,
        subprocess.CalledProcessError,
        TypeError,
        ValueError,
        NS10AblationError,
    ) as error:
        print(f"V6-NS10 freeze failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    print(
        json.dumps(
            {
                "freeze_digest": freeze["freeze_digest"],
                "queue_count": freeze["queue_count"],
            },
            indent=2,
            sort_keys=True,
        )
    )


def _optimize(
    energy: Any,
    gradient: Any,
    initial: np.ndarray,
) -> Any:
    from scipy.optimize import BFGS, minimize

    return minimize(
        energy,
        initial,
        jac=gradient,
        hess=BFGS(init_scale=1.0),
        method="trust-constr",
        options={
            "maxiter": MAXIMUM_ITERATIONS,
            "gtol": STATIONARITY_TOLERANCE,
            "xtol": 1e-12,
            "barrier_tol": 1e-12,
            "verbose": 0,
        },
    )


def _finite_difference(
    energy: Any,
    final: np.ndarray,
    analytic: np.ndarray,
) -> dict[str, Any]:
    selected = sorted(
        set(
            np.linspace(
                0, final.size - 1, min(4, final.size), dtype=int
            ).tolist()
            + [int(np.argmax(np.abs(analytic)))]
        )
    )
    result = {}
    for index in selected:
        plus = final.copy()
        minus = final.copy()
        plus[index] += FINITE_DIFFERENCE_STEP
        minus[index] -= FINITE_DIFFERENCE_STEP
        estimate = (
            energy(plus) - energy(minus)
        ) / (2.0 * FINITE_DIFFERENCE_STEP)
        result[str(index)] = {
            "analytic": float(analytic[index]),
            "finite_difference": float(estimate),
            "absolute_error": float(abs(analytic[index] - estimate)),
        }
    return result


def _context(context_id: str) -> Mapping[str, Any]:
    return next(item for item in CONTEXTS if item["case_id"] == context_id)


def evaluate_candidate(
    item: Mapping[str, Any],
    family: Mapping[str, Any],
) -> dict[str, Any]:
    started = time.perf_counter()
    algorithm, pool = _algorithm_for(item["context_id"])
    source = _load_context_structure(_context(item["context_id"]))
    blocks = recover_dvg_blocks(
        pool,
        source.indices,
        source.coefficients,
        source.cumulative_parameter_counts,
    )
    block = next(
        value for value in blocks
        if value.block_id == item["source_block_id"]
    )
    parameter_map = np.asarray(
        family["parameter_map"], dtype=np.float64
    )
    embedding, slots = affine_embedding(
        len(source.indices), block.ansatz_positions, parameter_map
    )
    initial = projected_initial_coordinates(
        np.asarray(source.coefficients, dtype=np.float64), embedding
    )
    indices = list(source.indices)
    counters = {"energy": 0, "gradient": 0}

    def energy(value: np.ndarray) -> float:
        counters["energy"] += 1
        return float(
            algorithm.evaluate_energy(
                list(embedding @ np.asarray(value)), indices
            )
        )

    def gradient(value: np.ndarray) -> np.ndarray:
        counters["gradient"] += 1
        source_gradient = np.asarray(
            algorithm.estimate_gradients(
                list(embedding @ np.asarray(value)),
                indices,
                method="an",
            ),
            dtype=np.float64,
        )
        return embedding.T @ source_gradient

    initial_energy = energy(initial)
    if abs(initial_energy - item["ns7_initial_energy_hartree"]) > 1e-12:
        raise NS10AblationError("NS10 start differs from NS7 start")
    result = _optimize(energy, gradient, initial)
    final = np.asarray(result.x, dtype=np.float64)
    mapped = embedding @ final
    final_gradient = gradient(final)
    finite_difference = _finite_difference(
        energy, final, final_gradient
    )
    counters["energy"] += 1
    source_energy = float(
        algorithm.evaluate_energy(list(source.coefficients), indices)
    )
    semantic_energy = energy(final)
    semantic_state = np.asarray(
        algorithm.compute_state(list(mapped), indices).toarray()
    ).ravel()
    semantic_state /= np.linalg.norm(semantic_state)
    local = np.asarray(
        [
            final[index]
            for index, slot in enumerate(slots)
            if slot.startswith("block-phi-")
        ],
        dtype=np.float64,
    )
    circuit, parameter_count = _native_circuit(
        pool,
        source,
        mapped,
        block.block_id,
        parameter_map,
        local,
    )
    resources = _qasm_resources(
        circuit,
        parameter_count=parameter_count,
        logical_block_count=len(blocks),
    )
    reference = np.asarray(algorithm.ref_state.toarray()).ravel()
    native_state = np.asarray(
        Statevector(reference).evolve(circuit).data,
        dtype=np.complex128,
    )
    native_state /= np.linalg.norm(native_state)
    native_energy = float(
        np.real(np.vdot(native_state, algorithm.hamiltonian @ native_state))
    )
    fidelity = float(abs(np.vdot(semantic_state, native_state)) ** 2)
    gradient_infinity = float(np.max(np.abs(final_gradient)))
    normal = np.asarray(family["normal"], dtype=np.float64)
    constraint = float(
        abs(normal @ mapped[list(block.ansatz_positions)])
    )
    ns7 = json.loads(NS7_OUTPUT.read_text(encoding="utf-8"))
    prior = next(
        value for value in ns7["attempts"]
        if value["attempt_id"] == item["ns7_attempt_id"]
    )
    resource_match = all(
        resources[field] == prior["resources"]["observed"][field]
        for field in (
            "cnot_count",
            "cnot_depth",
            "total_depth",
            "parameter_count",
            "logical_block_count",
            "counter_version",
        )
    )
    checks = {
        "finite": all(
            np.isfinite(value)
            for value in (
                result.fun,
                native_energy,
                gradient_infinity,
                constraint,
                fidelity,
            )
        ),
        "energy_budget": native_energy - source_energy
        <= ENERGY_BUDGET_HARTREE,
        "stationarity": gradient_infinity <= STATIONARITY_TOLERANCE,
        "optimizer_success": bool(result.success),
        "constraint": constraint <= 1e-10,
        "semantic_native_energy": abs(semantic_energy - native_energy)
        <= 1e-10,
        "semantic_native_state": fidelity >= 1.0 - 1e-10,
        "finite_difference": max(
            value["absolute_error"]
            for value in finite_difference.values()
        )
        <= 1e-6,
        "resource_match_ns7": resource_match,
    }
    return {
        "queue_item": dict(item),
        "kind": item["kind"],
        "initial_energy_hartree": initial_energy,
        "optimizer": {
            "success": bool(result.success),
            "status": int(result.status),
            "message": str(result.message),
            "iterations": int(result.nit),
            "energy_evaluations_reported": int(result.nfev),
            "gradient_evaluations_reported": int(result.njev),
        },
        "certification": {
            "source_energy_hartree": source_energy,
            "semantic_energy_hartree": semantic_energy,
            "native_energy_hartree": native_energy,
            "source_relative_loss_hartree": native_energy - source_energy,
            "target_gradient_infinity": gradient_infinity,
            "constraint_residual": constraint,
            "semantic_native_state_fidelity": fidelity,
            "finite_difference": finite_difference,
            "resources": resources,
        },
        "checks": checks,
        "certified": all(checks.values()),
        "final_target_coordinates_float64_hex": list(
            canonical_float64_hex(final)
        ),
        "work": {
            "optimizer_iterations": int(result.nit),
            "energy_evaluations": counters["energy"],
            "gradient_vector_evaluations": counters["gradient"],
            "finite_difference_energy_evaluations": (
                2 * len(finite_difference)
            ),
            "full_resource_recounts": 1,
            "wall_time_seconds": time.perf_counter() - started,
        },
    }


def evaluate_control(item: Mapping[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    algorithm, _ = _algorithm_for(item["context_id"])
    source = _load_context_structure(_context(item["context_id"]))
    indices = list(source.indices)
    initial = np.asarray(source.coefficients, dtype=np.float64)
    counters = {"energy": 0, "gradient": 0}

    def energy(value: np.ndarray) -> float:
        counters["energy"] += 1
        return float(algorithm.evaluate_energy(list(value), indices))

    def gradient(value: np.ndarray) -> np.ndarray:
        counters["gradient"] += 1
        return np.asarray(
            algorithm.estimate_gradients(
                list(value), indices, method="an"
            ),
            dtype=np.float64,
        )

    initial_energy = energy(initial)
    initial_gradient = gradient(initial)
    result = _optimize(energy, gradient, initial)
    final = np.asarray(result.x, dtype=np.float64)
    final_gradient = gradient(final)
    finite_difference = _finite_difference(
        energy, final, final_gradient
    )
    final_energy = energy(final)
    checks = {
        "finite": bool(
            np.isfinite(final_energy)
            and np.all(np.isfinite(final_gradient))
        ),
        "energy_nonworse": final_energy <= initial_energy + 1e-10,
        "stationarity": float(np.max(np.abs(final_gradient)))
        <= STATIONARITY_TOLERANCE,
        "optimizer_success": bool(result.success),
        "finite_difference": max(
            value["absolute_error"]
            for value in finite_difference.values()
        )
        <= 1e-6,
    }
    return {
        "queue_item": dict(item),
        "kind": item["kind"],
        "initial": {
            "energy_hartree": initial_energy,
            "gradient_infinity": float(
                np.max(np.abs(initial_gradient))
            ),
        },
        "final": {
            "energy_hartree": final_energy,
            "gradient_infinity": float(
                np.max(np.abs(final_gradient))
            ),
            "finite_difference": finite_difference,
        },
        "optimizer": {
            "success": bool(result.success),
            "status": int(result.status),
            "message": str(result.message),
            "iterations": int(result.nit),
            "energy_evaluations_reported": int(result.nfev),
            "gradient_evaluations_reported": int(result.njev),
        },
        "checks": checks,
        "certified": all(checks.values()),
        "work": {
            "optimizer_iterations": int(result.nit),
            "energy_evaluations": counters["energy"],
            "gradient_vector_evaluations": counters["gradient"],
            "finite_difference_energy_evaluations": (
                2 * len(finite_difference)
            ),
            "full_resource_recounts": 0,
            "wall_time_seconds": time.perf_counter() - started,
        },
    }


def _work(results: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    return {
        "optimizer_starts": len(results),
        "optimizer_iterations": sum(
            item["work"]["optimizer_iterations"] for item in results
        ),
        "energy_evaluations": sum(
            item["work"]["energy_evaluations"] for item in results
        ),
        "gradient_vector_evaluations": sum(
            item["work"]["gradient_vector_evaluations"]
            for item in results
        ),
        "finite_difference_energy_evaluations": sum(
            item["work"]["finite_difference_energy_evaluations"]
            for item in results
        ),
        "full_resource_recounts": sum(
            item["work"]["full_resource_recounts"] for item in results
        ),
    }


def build_report() -> dict[str, Any]:
    if RESULT_OUTPUT.exists():
        raise NS10AblationError("NS10 result already exists")
    _clean()
    threads = _threads()
    freeze = json.loads(FREEZE_OUTPUT.read_text(encoding="utf-8"))
    content = dict(freeze)
    digest = content.pop("freeze_digest")
    if digest != sha256_hex(content):
        raise NS10AblationError("NS10 freeze digest mismatch")
    for value in freeze["inputs"].values():
        if _sha256(ROOT / value["path"]) != value["sha256"]:
            raise NS10AblationError("NS10 input hash mismatch")
    families = {
        item["family_id"]: item
        for item in json.loads(NS1_OUTPUT.read_text(encoding="utf-8"))[
            "families"
        ]
    }
    results = []
    for item in freeze["queue"]:
        if item["kind"] == "rank2-trust-region":
            results.append(
                evaluate_candidate(item, families[item["family_id"]])
            )
        else:
            results.append(evaluate_control(item))
    work = _work(results)
    work_checks = {
        name: work[name] <= maximum
        for name, maximum in WORK_CAP.items()
    }
    if not all(work_checks.values()):
        raise NS10AblationError(f"NS10 work cap exceeded: {work_checks}")
    candidates = [
        item for item in results if item["kind"] == "rank2-trust-region"
    ]
    controls = [
        item for item in results
        if item["kind"] == "same-structure-trust-region-control"
    ]
    passed_candidates = [
        item for item in candidates if item["certified"]
    ]
    report = {
        "schema_version": "1.0.0",
        "artifact_kind": "v6-ns10-h6-optimizer-scalability-ablation",
        "runner_version": RUNNER_VERSION,
        "development_only": True,
        "execution": {
            "git_commit": _git("rev-parse", "HEAD"),
            "git_describe": _git("describe", "--always", "--dirty"),
            "threads": threads,
            "python": sys.version,
            "platform": platform.platform(),
            "dependencies": {
                name: importlib.metadata.version(name)
                for name in ("numpy", "scipy", "qiskit", "openfermion")
            },
        },
        "freeze": {
            "path": str(FREEZE_OUTPUT.relative_to(ROOT)),
            "sha256": _sha256(FREEZE_OUTPUT),
            "freeze_digest": freeze["freeze_digest"],
            "queue": freeze["queue"],
        },
        "results": results,
        "work": {
            "observed": work,
            "cap": WORK_CAP,
            "checks": work_checks,
        },
        "summary": {
            "candidate_attempts": len(candidates),
            "candidate_certified": len(passed_candidates),
            "control_attempts": len(controls),
            "control_certified": sum(
                item["certified"] for item in controls
            ),
            "optimizer_sensitive_contexts": sorted(
                {
                    item["queue_item"]["context_id"]
                    for item in passed_candidates
                }
            ),
            "decision": (
                "TRUST_REGION_RECOVERS_AT_LEAST_ONE_NS7_H6_CANDIDATE"
                if passed_candidates
                else "NO_TRUST_REGION_RECOVERY_WITHIN_FROZEN_CAP"
            ),
            "ns7_decisions_modified": False,
            "pra_performance_claim_established": False,
        },
        "claim_boundary": (
            "Outcome-informed H6 optimizer scalability ablation after NS9. "
            "It does not revise NS7, select a production optimizer, establish "
            "matched-work superiority, or support a PRA performance claim."
        ),
        "paper_measurement_cost": None,
    }
    report["report_digest"] = sha256_hex(report)
    return report


def main() -> None:
    try:
        report = build_report()
        atomic_write_new_json(RESULT_OUTPUT, report)
    except (
        ImportError,
        KeyError,
        OSError,
        subprocess.CalledProcessError,
        TypeError,
        ValueError,
        NS10AblationError,
    ) as error:
        print(f"V6-NS10 ablation failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    print(json.dumps(report["summary"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

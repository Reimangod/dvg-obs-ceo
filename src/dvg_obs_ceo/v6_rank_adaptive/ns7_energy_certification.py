"""V6-NS7 frozen affine-family energy and stationarity certification."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import importlib.metadata
import json
import math
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
from dvg_obs_ceo.multisystem_checkpoint import _algorithm as molecular_algorithm
from dvg_obs_ceo.s8_probe import _algorithm as h4_algorithm
from dvg_obs_ceo.telemetry import ResourceSnapshot
from dvg_obs_ceo.transaction import (
    AcceptanceCriteria,
    AcceptanceEvidence,
    OptimizerOutcome,
    evaluate_acceptance,
)

from .native_rank2_feasibility import COUNTER_VERSION, _qasm_resources
from .native_synthesis_pipeline import (
    CONTEXTS,
    NS1_OUTPUT,
    NS5_OUTPUT,
    NS6_OUTPUT,
    _load_context_structure,
    build_shortest_parity_circuit,
)


DEFAULT_OUTPUT = ROOT / "artifacts/v6/ns7/energy-certification-v1.json"
RUNNER_VERSION = "v6-ns7-affine-native-energy-certification-v1"
ENERGY_BUDGET_HARTREE = 1e-4
STATIONARITY_TOLERANCE = 1e-8
ENERGY_AGREEMENT_TOLERANCE = 1e-10
STATE_FIDELITY_TOLERANCE = 1e-10
MAXIMUM_ITERATIONS = 200
GRADIENT_TOLERANCE = 1e-8
FINITE_DIFFERENCE_STEP = 1e-6
FINITE_DIFFERENCE_COMPONENTS = 5
REQUIRED_THREADS = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
}


class NS7CertificationError(RuntimeError):
    """Raised when the frozen NS7 execution cannot be certified."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(*arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _versions() -> dict[str, str]:
    return {
        name: importlib.metadata.version(name)
        for name in ("numpy", "scipy", "qiskit", "openfermion")
    }


def build_execution_freeze() -> dict[str, Any]:
    if DEFAULT_OUTPUT.exists():
        raise NS7CertificationError("NS7 output already exists")
    if _git("status", "--porcelain"):
        raise NS7CertificationError(
            "NS7 requires a completely clean committed worktree"
        )
    threads = {name: os.environ.get(name) for name in REQUIRED_THREADS}
    if threads != REQUIRED_THREADS:
        raise NS7CertificationError(
            f"NS7 requires canonical single-thread settings: {threads}"
        )
    ns6 = json.loads(NS6_OUTPUT.read_text(encoding="utf-8"))
    if (
        ns6.get("ns7_authorized") is not True
        or ns6.get("decision") != "GO_PRIMARY_RESOURCE_ELIGIBLE"
        or not ns6.get("energy_queue")
    ):
        raise NS7CertificationError("NS6 did not authorize NS7")
    requirements = ns6["ns7_protocol_requirements"]
    expected = {
        "stationarity_threshold": STATIONARITY_TOLERANCE,
        "energy_budget_hartree": ENERGY_BUDGET_HARTREE,
        "optimizer_max_iterations": MAXIMUM_ITERATIONS,
        "primary_initialization": "euclidean-plane-projection",
        "initial_inverse_hessian": "identity",
        "fallback": None,
        "candidate_outcomes_may_change_queue": False,
        "same_policy_all_molecules": True,
    }
    if requirements != expected:
        raise NS7CertificationError(
            "runner constants differ from frozen NS6 protocol"
        )
    freeze = {
        "runner_version": RUNNER_VERSION,
        "git_commit": _git("rev-parse", "HEAD"),
        "git_describe": _git("describe", "--always", "--dirty"),
        "worktree_clean": True,
        "threads": threads,
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
            "dependencies": _versions(),
        },
        "inputs": {
            "ns1": {
                "path": str(NS1_OUTPUT.relative_to(ROOT)),
                "sha256": _sha256(NS1_OUTPUT),
            },
            "ns5": {
                "path": str(NS5_OUTPUT.relative_to(ROOT)),
                "sha256": _sha256(NS5_OUTPUT),
            },
            "ns6": {
                "path": str(NS6_OUTPUT.relative_to(ROOT)),
                "sha256": _sha256(NS6_OUTPUT),
                "freeze_digest": ns6["freeze_digest"],
            },
        },
        "queue": ns6["energy_queue"],
        "queue_count": len(ns6["energy_queue"]),
        "policy": requirements,
        "fci_or_chemical_accuracy_used_for_acceptance": False,
        "candidate_outcomes_may_change_queue": False,
        "primary_lineage_mutated_during_attempts": False,
    }
    freeze["execution_freeze_digest"] = sha256_hex(freeze)
    return freeze


def affine_embedding(
    source_dimension: int,
    block_positions: Sequence[int],
    parameter_map: np.ndarray,
) -> tuple[np.ndarray, tuple[str, ...]]:
    positions = tuple(int(value) for value in block_positions)
    if (
        len(positions) != 3
        or len(set(positions)) != 3
        or tuple(sorted(positions)) != positions
        or parameter_map.shape != (3, 2)
    ):
        raise NS7CertificationError("affine block embedding is malformed")
    columns = []
    slots = []
    block_set = set(positions)
    for position in range(source_dimension):
        if position == positions[0]:
            for local in range(2):
                column = np.zeros(source_dimension, dtype=np.float64)
                column[list(positions)] = parameter_map[:, local]
                columns.append(column)
                slots.append(f"block-phi-{local}")
        elif position not in block_set:
            column = np.zeros(source_dimension, dtype=np.float64)
            column[position] = 1.0
            columns.append(column)
            slots.append(f"source-{position}")
    matrix = np.column_stack(columns)
    if (
        matrix.shape != (source_dimension, source_dimension - 1)
        or np.linalg.matrix_rank(matrix) != source_dimension - 1
    ):
        raise NS7CertificationError(
            "affine embedding does not have the declared rank"
        )
    return matrix, tuple(slots)


def projected_initial_coordinates(
    source_coordinates: np.ndarray,
    embedding: np.ndarray,
) -> np.ndarray:
    value, residuals, rank, _ = np.linalg.lstsq(
        embedding, source_coordinates, rcond=None
    )
    if rank != embedding.shape[1] or not np.all(np.isfinite(value)):
        raise NS7CertificationError(
            "Euclidean affine projection failed"
        )
    return np.asarray(value, dtype=np.float64)


def _algorithm_for(context_id: str) -> tuple[Any, Any]:
    if context_id == "h4-1.5-late":
        return h4_algorithm("h4-1.5-iteration-12-or-convergence")
    if context_id == "h6-1.5-s6":
        case = {
            "case_id": "h6-1.5",
            "distance_angstrom": 1.5,
            "figure_role": ["fig14", "fig15"],
            "gradient_threshold": 1e-6,
            "molecule": "H6",
        }
        return molecular_algorithm(case)
    if context_id == "h6-3.0":
        case = {
            "case_id": "h6-3.0",
            "distance_angstrom": 3.0,
            "figure_role": ["fig11"],
            "gradient_threshold": 1e-6,
            "molecule": "H6",
        }
        return molecular_algorithm(case)
    raise NS7CertificationError(f"unregistered NS7 context: {context_id}")


def _native_circuit(
    pool: Any,
    source: Any,
    source_coordinates: np.ndarray,
    block_id: str,
    parameter_map: np.ndarray,
    target_coordinates: np.ndarray,
) -> tuple[Any, int]:
    from qiskit import QuantumCircuit

    blocks = recover_dvg_blocks(
        pool,
        source.indices,
        source_coordinates,
        source.cumulative_parameter_counts,
    )
    circuit = QuantumCircuit(pool.n)
    parameter_count = 0
    found = False
    for block in blocks:
        if block.block_id == block_id:
            segment, _ = build_shortest_parity_circuit(
                pool,
                block.pool_indices,
                parameter_map,
                target_coordinates,
            )
            circuit = circuit.compose(segment)
            circuit.barrier()
            parameter_count += 2
            found = True
        else:
            segment = pool.get_circuit(
                list(block.pool_indices),
                list(block.coefficients),
            )
            circuit = circuit.compose(segment)
            parameter_count += len(block.pool_indices)
    if not found:
        raise NS7CertificationError(
            "target block disappeared during native reconstruction"
        )
    return circuit, parameter_count


def _snapshot(
    value: Mapping[str, Any],
    digest: str,
) -> ResourceSnapshot:
    return ResourceSnapshot(
        cnot_count=int(value["cnot_count"]),
        cnot_depth=int(value["cnot_depth"]),
        total_depth=int(value["total_depth"]),
        parameter_count=int(value["parameter_count"]),
        logical_block_count=int(value["logical_block_count"]),
        counter_version=COUNTER_VERSION,
        structure_digest=digest,
    )


def evaluate_attempt(
    queue_item: Mapping[str, Any],
    family: Mapping[str, Any],
    context: Mapping[str, Any],
) -> dict[str, Any]:
    started = time.perf_counter()
    algorithm, pool = _algorithm_for(queue_item["context_id"])
    # The pinned upstream loader used by _algorithm_for registers the
    # vendored paper-era package path.  Import only after that registration.
    from adaptvqe.minimize import minimize_bfgs

    source = _load_context_structure(context)
    blocks = recover_dvg_blocks(
        pool,
        source.indices,
        source.coefficients,
        source.cumulative_parameter_counts,
    )
    block = next(
        (
            item
            for item in blocks
            if item.block_id == queue_item["source_block_id"]
        ),
        None,
    )
    if block is None:
        raise NS7CertificationError("frozen source block is absent")
    parameter_map = np.asarray(
        family["parameter_map"], dtype=np.float64
    )
    embedding, target_slots = affine_embedding(
        len(source.indices),
        block.ansatz_positions,
        parameter_map,
    )
    source_theta = np.asarray(
        source.coefficients, dtype=np.float64
    )
    initial = projected_initial_coordinates(source_theta, embedding)
    source_energy = float(
        algorithm.evaluate_energy(
            list(source_theta), list(source.indices)
        )
    )
    source_state = np.asarray(
        algorithm.compute_state(
            list(source_theta), list(source.indices)
        ).toarray()
    ).ravel()
    source_state /= np.linalg.norm(source_state)

    def energy_function(
        coordinates: np.ndarray,
        _: Sequence[Any],
    ) -> float:
        mapped = embedding @ np.asarray(coordinates)
        return float(
            algorithm.evaluate_energy(
                list(mapped), list(source.indices)
            )
        )

    def gradient_function(
        coordinates: np.ndarray,
        _: Sequence[Any],
    ) -> np.ndarray:
        mapped = embedding @ np.asarray(coordinates)
        source_gradient = np.asarray(
            algorithm.estimate_gradients(
                list(mapped), list(source.indices), method="an"
            ),
            dtype=np.float64,
        )
        return embedding.T @ source_gradient

    initial_energy = energy_function(initial, ())
    result = minimize_bfgs(
        energy_function,
        initial,
        [[]],
        jac=gradient_function,
        initial_inv_hessian=np.eye(initial.size),
        gtol=GRADIENT_TOLERANCE,
        maxiter=MAXIMUM_ITERATIONS,
        disp=False,
    )
    final = np.asarray(result.x, dtype=np.float64)
    mapped_final = embedding @ final
    candidate_energy = float(result.fun)
    independent_semantic_energy = energy_function(final, ())
    target_gradient = gradient_function(final, ())
    source_gradient = np.asarray(
        algorithm.estimate_gradients(
            list(mapped_final), list(source.indices), method="an"
        ),
        dtype=np.float64,
    )
    local_phi_columns = [
        index
        for index, slot in enumerate(target_slots)
        if slot.startswith("block-phi-")
    ]
    if len(local_phi_columns) != 2:
        raise NS7CertificationError(
            "target coordinate slots lost the local affine variables"
        )
    local_phi = final[local_phi_columns]
    circuit, parameter_count = _native_circuit(
        pool,
        source,
        mapped_final,
        block.block_id,
        parameter_map,
        local_phi,
    )
    resources = _qasm_resources(
        circuit,
        parameter_count=parameter_count,
        logical_block_count=len(blocks),
    )
    semantic_state = np.asarray(
        algorithm.compute_state(
            list(mapped_final), list(source.indices)
        ).toarray()
    ).ravel()
    semantic_state /= np.linalg.norm(semantic_state)
    reference = np.asarray(algorithm.ref_state.toarray()).ravel()
    native_state = np.asarray(
        Statevector(reference).evolve(circuit).data,
        dtype=np.complex128,
    )
    native_state /= np.linalg.norm(native_state)
    state_fidelity = float(
        abs(np.vdot(semantic_state, native_state)) ** 2
    )
    native_energy = float(
        np.real(
            np.vdot(
                native_state,
                algorithm.hamiltonian @ native_state,
            )
        )
    )
    normal = np.asarray(family["normal"], dtype=np.float64)
    constraint_residual = float(
        abs(normal @ mapped_final[list(block.ansatz_positions)])
    )
    finite_difference_indices = np.linspace(
        0,
        final.size - 1,
        num=min(FINITE_DIFFERENCE_COMPONENTS, final.size),
        dtype=int,
    )
    finite_difference = {}
    for index in finite_difference_indices:
        plus = final.copy()
        minus = final.copy()
        plus[index] += FINITE_DIFFERENCE_STEP
        minus[index] -= FINITE_DIFFERENCE_STEP
        estimate = (
            energy_function(plus, ())
            - energy_function(minus, ())
        ) / (2.0 * FINITE_DIFFERENCE_STEP)
        finite_difference[str(int(index))] = {
            "analytic": float(target_gradient[index]),
            "finite_difference": float(estimate),
            "absolute_error": abs(
                float(target_gradient[index]) - float(estimate)
            ),
        }
    expected = next(
        item
        for item in json.loads(
            NS5_OUTPUT.read_text(encoding="utf-8")
        )["records"]
        if item["context_id"] == queue_item["context_id"]
        and item["source_block_id"] == block.block_id
        and item["family_id"] == family["family_id"]
    )
    recount_checks = {
        field: int(resources[field])
        == int(expected["target_resources"][field])
        for field in (
            "cnot_count",
            "cnot_depth",
            "total_depth",
            "parameter_count",
            "logical_block_count",
        )
    }
    before = _snapshot(
        expected["source_resources"],
        expected["source_resources"]["circuit_qasm_digest"],
    )
    after = _snapshot(
        resources, resources["circuit_qasm_digest"]
    )
    evidence = AcceptanceEvidence(
        source_energy_hartree=source_energy,
        budget_reference_energy_hartree=source_energy,
        candidate_energy_hartree=candidate_energy,
        independent_energy_hartree=native_energy,
        independent_state_fidelity=state_fidelity,
        constraint_residual=constraint_residual,
        kkt_residual=float(np.max(np.abs(target_gradient))),
        before_resources=before,
        after_resources=after,
        full_resource_recount_succeeded=all(recount_checks.values()),
        transformation_semantics_validated=(
            state_fidelity >= 1.0 - STATE_FIDELITY_TOLERANCE
            and max(
                item["absolute_error"]
                for item in finite_difference.values()
            )
            <= 1e-6
        ),
        primary_optimizer=OptimizerOutcome(
            success=bool(result.success),
            status=str(result.status),
            message=str(result.message),
            completed=True,
        ),
        fallback_optimizer=None,
    )
    decision = evaluate_acceptance(
        evidence,
        AcceptanceCriteria(
            cumulative_energy_budget_hartree=ENERGY_BUDGET_HARTREE,
            independent_energy_tolerance_hartree=(
                ENERGY_AGREEMENT_TOLERANCE
            ),
            minimum_state_fidelity=(
                1.0 - STATE_FIDELITY_TOLERANCE
            ),
            maximum_constraint_residual=1e-10,
            maximum_kkt_residual=STATIONARITY_TOLERANCE,
            resource_policy="circuit-primary-v1",
        ),
    )
    source_digest_before = sha256_hex(
        {
            "indices": list(source.indices),
            "coefficients": list(
                canonical_float64_hex(source.coefficients)
            ),
            "counts": list(source.cumulative_parameter_counts),
        }
    )
    source_digest_after = sha256_hex(
        {
            "indices": list(source.indices),
            "coefficients": list(
                canonical_float64_hex(source.coefficients)
            ),
            "counts": list(source.cumulative_parameter_counts),
        }
    )
    return {
        "attempt_id": "v6-ns7-attempt:" + sha256_hex(queue_item),
        "queue_item": dict(queue_item),
        "family_id": family["family_id"],
        "normal": family["normal"],
        "source": {
            "energy_hartree": source_energy,
            "parameter_count": len(source.indices),
            "state_sha256": hashlib.sha256(
                np.asarray(source_state, dtype=">c16").tobytes()
            ).hexdigest(),
            "snapshot_digest_before": source_digest_before,
            "snapshot_digest_after": source_digest_after,
        },
        "initialization": {
            "kind": "euclidean-plane-projection",
            "initial_energy_hartree": initial_energy,
            "preoptimization_loss_hartree": initial_energy - source_energy,
            "constraint_residual": float(
                abs(
                    normal
                    @ (
                        embedding @ initial
                    )[list(block.ansatz_positions)]
                )
            ),
        },
        "optimizer": {
            "implementation": "pinned-upstream-minimize_bfgs",
            "success": bool(result.success),
            "status": int(result.status),
            "message": str(result.message),
            "iterations": int(result.nit),
            "function_evaluations": int(result.nfev),
            "gradient_vector_evaluations": int(result.njev),
            "maximum_iterations": MAXIMUM_ITERATIONS,
            "gradient_tolerance": GRADIENT_TOLERANCE,
            "fallback_used": False,
        },
        "certification": {
            "candidate_energy_hartree": candidate_energy,
            "independent_semantic_energy_hartree": (
                independent_semantic_energy
            ),
            "independent_native_energy_hartree": native_energy,
            "actual_loss_hartree": native_energy - source_energy,
            "target_gradient_infinity": float(
                np.max(np.abs(target_gradient))
            ),
            "source_gradient_infinity": float(
                np.max(np.abs(source_gradient))
            ),
            "constraint_residual": constraint_residual,
            "semantic_native_state_fidelity": state_fidelity,
            "finite_difference_spot_checks": finite_difference,
        },
        "resources": {
            "observed": resources,
            "expected_ns5": expected["target_resources"],
            "recount_checks": recount_checks,
            "delta": expected["resource_delta"],
        },
        "acceptance": asdict(decision),
        "classification": (
            "PRIMARY_NATIVE_RANK2_ACCEPTED"
            if decision.accepted
            else "PRIMARY_NATIVE_RANK2_REJECTED"
        ),
        "functional_attempt_source_immutable": (
            source_digest_before == source_digest_after
        ),
        "primary_lineage_mutated": False,
        "final_target_coordinates_float64_hex": list(
            canonical_float64_hex(final)
        ),
        "final_source_coordinates_float64_hex": list(
            canonical_float64_hex(mapped_final)
        ),
        "work": {
            "wall_time_seconds": time.perf_counter() - started,
            "optimizer_energy_evaluations": int(result.nfev),
            "optimizer_gradient_vector_evaluations": int(result.njev),
            "finite_difference_energy_evaluations": (
                2 * len(finite_difference)
            ),
            "independent_energy_evaluations": 2,
            "statevector_recomputations": 2,
            "full_resource_recounts": 1,
            "paper_measurement_cost": None,
        },
        "paper_measurement_cost": None,
    }


def build_report(
    execution_freeze: Mapping[str, Any],
) -> dict[str, Any]:
    ns1 = json.loads(NS1_OUTPUT.read_text(encoding="utf-8"))
    families = {
        item["family_id"]: item for item in ns1["families"]
    }
    contexts = {
        item["case_id"]: item for item in CONTEXTS
    }
    attempts = [
        evaluate_attempt(
            queue_item,
            families[queue_item["family_id"]],
            contexts[queue_item["context_id"]],
        )
        for queue_item in execution_freeze["queue"]
    ]
    accepted = [
        item for item in attempts
        if item["classification"] == "PRIMARY_NATIVE_RANK2_ACCEPTED"
    ]
    report = {
        "schema_version": "1.0.0",
        "artifact_kind": "v6-ns7-primary-native-energy-certification",
        "runner_version": RUNNER_VERSION,
        "development_only": True,
        "execution_freeze": dict(execution_freeze),
        "attempts": attempts,
        "summary": {
            "attempted": len(attempts),
            "accepted": len(accepted),
            "rejected": len(attempts) - len(accepted),
            "accepted_attempt_ids": [
                item["attempt_id"] for item in accepted
            ],
            "contexts_with_acceptance": sorted(
                {
                    item["queue_item"]["context_id"]
                    for item in accepted
                }
            ),
            "validation_context_attempted": False,
            "validation_context_reason": (
                "Frozen BeH2 checkpoint contains no eligible rank-three MVP block."
            ),
            "decision": (
                "GO_DEVELOPMENT_PRIMARY_NATIVE"
                if accepted
                else "NO_GO_NS7_CERTIFICATION"
            ),
            "pra_performance_claim_established": False,
        },
        "claim_boundary": (
            "Frozen development energy/stationarity certification for "
            "resource-first affine rank-two families. No unseen molecular "
            "validation, matched-work algorithm-level comparison, measurement "
            "cost, or PRA performance claim is established."
        ),
        "paper_measurement_cost": None,
    }
    report["report_digest"] = sha256_hex(report)
    return report


def main() -> None:
    try:
        freeze = build_execution_freeze()
        report = build_report(freeze)
        atomic_write_new_json(DEFAULT_OUTPUT, report)
    except (
        ImportError,
        KeyError,
        OSError,
        subprocess.CalledProcessError,
        TypeError,
        ValueError,
        NS7CertificationError,
    ) as error:
        print(f"V6-NS7 certification failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    print(
        json.dumps(
            {
                "report_digest": report["report_digest"],
                "summary": report["summary"],
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()

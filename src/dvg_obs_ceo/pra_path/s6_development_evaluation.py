"""PRA S6 frozen independent development evaluation."""

from __future__ import annotations

from dataclasses import asdict
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from typing import Any, Mapping, Sequence

import numpy as np
from qiskit.quantum_info import Statevector

from dvg_obs_ceo.artifact_io import atomic_write_new_json
from dvg_obs_ceo.baseline import ROOT
from dvg_obs_ceo.block_ir import recover_dvg_blocks
from dvg_obs_ceo.identity import canonical_float64_hex, sha256_hex
from dvg_obs_ceo.resources import AnsatzStructure
from dvg_obs_ceo.telemetry import ResourceSnapshot
from dvg_obs_ceo.transaction import (
    AcceptanceCriteria,
    AcceptanceEvidence,
    OptimizerOutcome,
    evaluate_acceptance,
)
from dvg_obs_ceo.v6_rank_adaptive.native_rank2_feasibility import (
    COUNTER_VERSION,
    _qasm_resources,
)
from dvg_obs_ceo.v6_rank_adaptive.native_synthesis_pipeline import (
    NS1_OUTPUT,
    NS3_OUTPUT,
    NS4_OUTPUT,
    _compose_context,
    build_shortest_parity_circuit,
)
from dvg_obs_ceo.v6_rank_adaptive.ns7_energy_certification import (
    affine_embedding,
    projected_initial_coordinates,
)

from .s5_applicability_census import (
    CENSUS_OUTPUT as S5_OUTPUT,
    DEVELOPMENT_CASES,
    REQUIRED_THREADS,
    _algorithm,
    _source_path,
)


OUTPUT_ROOT = ROOT / "artifacts/pra_path/s6"
FREEZE_OUTPUT = OUTPUT_ROOT / "queue-freeze-v1.json"
RESULT_OUTPUT = OUTPUT_ROOT / "independent-development-evaluation-v1.json"
RUNNER_VERSION = "pra-s6-independent-development-v1"
ENERGY_BUDGET_HARTREE = 1e-4
STATIONARITY_TOLERANCE = 1e-8
ENERGY_AGREEMENT_TOLERANCE = 1e-10
STATE_FIDELITY_TOLERANCE = 1e-10
CONSTRAINT_TOLERANCE = 1e-10
FINITE_DIFFERENCE_TOLERANCE = 1e-6
FINITE_DIFFERENCE_STEP = 1e-6
FINITE_DIFFERENCE_COMPONENTS = 5
MAXIMUM_ITERATIONS = 200
GRADIENT_TOLERANCE = 1e-8


class S6DevelopmentError(RuntimeError):
    """Raised when S6 violates its frozen protocol or evidence checks."""


def _git(*arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _clean_and_threads() -> dict[str, Any]:
    if _git("status", "--porcelain"):
        raise S6DevelopmentError("S6 requires a clean committed worktree")
    threads = {name: os.environ.get(name) for name in REQUIRED_THREADS}
    if threads != REQUIRED_THREADS:
        raise S6DevelopmentError(f"noncanonical thread environment: {threads}")
    return {"git_commit": _git("rev-parse", "HEAD"), "threads": threads}


def _load_source(case_id: str) -> tuple[dict[str, Any], AnsatzStructure]:
    payload = json.loads(_source_path(case_id).read_text(encoding="utf-8"))
    content = dict(payload)
    digest = content.pop("report_digest", None)
    if digest != sha256_hex(content):
        raise S6DevelopmentError(f"source digest mismatch: {case_id}")
    structure = AnsatzStructure.create(
        payload["ansatz_indices"],
        payload["ansatz_coefficients"],
        payload["iteration_counts"],
    )
    return payload, structure


def _certified_families() -> dict[str, dict[str, Any]]:
    registry = json.loads(NS1_OUTPUT.read_text(encoding="utf-8"))
    synthesis = json.loads(NS3_OUTPUT.read_text(encoding="utf-8"))
    certification = json.loads(NS4_OUTPUT.read_text(encoding="utf-8"))
    candidates = {item["candidate_id"]: item for item in synthesis["candidates"]}
    family_ids = {
        candidates[item["candidate_id"]]["family_id"]
        for item in certification["certifications"]
        if item["familywise_certified"]
    }
    return {
        item["family_id"]: item
        for item in registry["families"]
        if item["family_id"] in family_ids
    }


def build_queue_freeze() -> dict[str, Any]:
    if FREEZE_OUTPUT.exists():
        raise S6DevelopmentError("refusing to overwrite S6 queue freeze")
    execution = _clean_and_threads()
    census = json.loads(S5_OUTPUT.read_text(encoding="utf-8"))
    if census["authorization"]["s6"] is not True:
        raise S6DevelopmentError("S5 did not authorize S6")
    families = _certified_families()
    if len(families) != 4:
        raise S6DevelopmentError("expected four familywise-native families")
    queue = []
    sources = []
    for case in DEVELOPMENT_CASES:
        source_payload, structure = _load_source(case["case_id"])
        _, pool = _algorithm(case)
        blocks = sorted(
            (
                block
                for block in recover_dvg_blocks(
                    pool,
                    structure.indices,
                    structure.coefficients,
                    structure.cumulative_parameter_counts,
                )
                if block.family == "MVP" and len(block.pool_indices) == 3
            ),
            key=lambda block: block.block_id,
        )
        sources.append(
            {
                "case_id": case["case_id"],
                "path": str(_source_path(case["case_id"]).relative_to(ROOT)),
                "sha256": _sha256(_source_path(case["case_id"])),
                "report_digest": source_payload["report_digest"],
                "rank_three_mvp_block_count": len(blocks),
            }
        )
        for block in blocks:
            for family_id in sorted(families):
                item = {
                    "case_id": case["case_id"],
                    "source_block_id": block.block_id,
                    "source_pool_indices": list(block.pool_indices),
                    "family_id": family_id,
                    "normal": families[family_id]["normal"],
                }
                item["queue_id"] = "pra-s6-queue:" + sha256_hex(item)
                queue.append(item)
    expected = sum(item["rank_three_mvp_block_count"] for item in sources) * 4
    if len(queue) != expected or len(queue) != 24:
        raise S6DevelopmentError(
            f"unexpected S6 queue size: {len(queue)} != {expected}"
        )
    freeze: dict[str, Any] = {
        "schema": "dvg-obs-ceo.pra-path.s6-queue-freeze.v1",
        "runner_version": RUNNER_VERSION,
        "creation": execution,
        "inputs": {
            "s5": {
                "path": str(S5_OUTPUT.relative_to(ROOT)),
                "sha256": _sha256(S5_OUTPUT),
                "report_digest": census["report_digest"],
            },
            "ns1": {"path": str(NS1_OUTPUT.relative_to(ROOT)), "sha256": _sha256(NS1_OUTPUT)},
            "ns3": {"path": str(NS3_OUTPUT.relative_to(ROOT)), "sha256": _sha256(NS3_OUTPUT)},
            "ns4": {"path": str(NS4_OUTPUT.relative_to(ROOT)), "sha256": _sha256(NS4_OUTPUT)},
            "sources": sources,
        },
        "queue": queue,
        "queue_count": len(queue),
        "protocol": {
            "candidate_order": "case-order, block-id, family-id",
            "initialization": "euclidean-plane-projection",
            "initial_inverse_hessian": "identity",
            "optimizer": "pinned-upstream-minimize_bfgs",
            "maximum_iterations": MAXIMUM_ITERATIONS,
            "gradient_tolerance": GRADIENT_TOLERANCE,
            "fallback": None,
            "energy_budget_hartree": ENERGY_BUDGET_HARTREE,
            "primary_stationarity": "orthonormal-tangent-gradient-infinity",
            "stationarity_tolerance": STATIONARITY_TOLERANCE,
            "constraint_tolerance": CONSTRAINT_TOLERANCE,
            "semantic_native_fidelity_minimum": 1.0 - STATE_FIDELITY_TOLERANCE,
            "energy_agreement_tolerance": ENERGY_AGREEMENT_TOLERANCE,
            "finite_difference_tolerance": FINITE_DIFFERENCE_TOLERANCE,
            "resource_policy": "componentwise-pareto-v1",
            "outcomes_may_change_queue": False,
            "fci_or_chemical_accuracy_used": False,
            "paper_measurement_cost": None,
        },
        "authorization": {"candidate_energy_execution": True},
        "claim_boundary": (
            "Frozen development queue only. No matched-work, prospective, or "
            "cross-population performance claim."
        ),
    }
    freeze["freeze_digest"] = sha256_hex(freeze)
    return freeze


def _snapshot(value: Mapping[str, Any]) -> ResourceSnapshot:
    return ResourceSnapshot(
        cnot_count=int(value["cnot_count"]),
        cnot_depth=int(value["cnot_depth"]),
        total_depth=int(value["total_depth"]),
        parameter_count=int(value["parameter_count"]),
        logical_block_count=int(value["logical_block_count"]),
        counter_version=COUNTER_VERSION,
        structure_digest=str(value["circuit_qasm_digest"]),
    )


def _native_circuit(
    pool: Any,
    source: AnsatzStructure,
    mapped: np.ndarray,
    target_block_id: str,
    parameter_map: np.ndarray,
    local_coordinates: np.ndarray,
) -> tuple[Any, int]:
    from qiskit import QuantumCircuit

    blocks = recover_dvg_blocks(
        pool,
        source.indices,
        mapped,
        source.cumulative_parameter_counts,
    )
    circuit = QuantumCircuit(pool.n)
    parameter_count = 0
    found = False
    for block in blocks:
        if block.block_id == target_block_id:
            segment, _ = build_shortest_parity_circuit(
                pool,
                block.pool_indices,
                parameter_map,
                local_coordinates,
            )
            parameter_count += 2
            found = True
        else:
            segment = pool.get_circuit(
                list(block.pool_indices),
                list(block.coefficients),
            )
            parameter_count += len(block.pool_indices)
        circuit = circuit.compose(segment)
        if block.block_id == target_block_id:
            circuit.barrier()
    if not found:
        raise S6DevelopmentError("frozen target block disappeared")
    return circuit, parameter_count


def _orthonormal_tangent(embedding: np.ndarray) -> np.ndarray:
    q, r = np.linalg.qr(embedding, mode="reduced")
    if (
        q.shape != embedding.shape
        or np.linalg.matrix_rank(r) != embedding.shape[1]
        or not np.allclose(q.T @ q, np.eye(q.shape[1]), atol=1e-12)
    ):
        raise S6DevelopmentError("orthonormal tangent construction failed")
    return q


def evaluate_attempt(
    item: Mapping[str, Any],
    family: Mapping[str, Any],
    case: Mapping[str, Any],
    source: AnsatzStructure,
    algorithm: Any,
    pool: Any,
    source_energy: float,
    source_resources: Mapping[str, Any],
) -> dict[str, Any]:
    from adaptvqe.minimize import minimize_bfgs

    started = time.perf_counter()
    blocks = recover_dvg_blocks(
        pool,
        source.indices,
        source.coefficients,
        source.cumulative_parameter_counts,
    )
    block = next(
        (block for block in blocks if block.block_id == item["source_block_id"]),
        None,
    )
    if block is None:
        raise S6DevelopmentError("queue block is absent from source")
    parameter_map = np.asarray(family["parameter_map"], dtype=np.float64)
    embedding, slots = affine_embedding(
        len(source.indices),
        block.ansatz_positions,
        parameter_map,
    )
    q = _orthonormal_tangent(embedding)
    source_theta = np.asarray(source.coefficients, dtype=np.float64)
    initial = projected_initial_coordinates(source_theta, embedding)
    indices = list(source.indices)

    def energy(coordinates: np.ndarray, _: Sequence[Any]) -> float:
        mapped = embedding @ np.asarray(coordinates, dtype=np.float64)
        return float(algorithm.evaluate_energy(list(mapped), indices))

    def gradient(coordinates: np.ndarray, _: Sequence[Any]) -> np.ndarray:
        mapped = embedding @ np.asarray(coordinates, dtype=np.float64)
        full = np.asarray(
            algorithm.estimate_gradients(list(mapped), indices, method="an"),
            dtype=np.float64,
        )
        return embedding.T @ full

    initial_energy = energy(initial, ())
    result = minimize_bfgs(
        energy,
        initial,
        [[]],
        jac=gradient,
        initial_inv_hessian=np.eye(initial.size),
        gtol=GRADIENT_TOLERANCE,
        maxiter=MAXIMUM_ITERATIONS,
        disp=False,
    )
    final = np.asarray(result.x, dtype=np.float64)
    mapped = embedding @ final
    full_gradient = np.asarray(
        algorithm.estimate_gradients(list(mapped), indices, method="an"),
        dtype=np.float64,
    )
    target_gradient = embedding.T @ full_gradient
    tangent_gradient = q.T @ full_gradient
    normal_component = full_gradient - q @ tangent_gradient
    local_columns = [
        index for index, slot in enumerate(slots) if slot.startswith("block-phi-")
    ]
    if len(local_columns) != 2:
        raise S6DevelopmentError("target local coordinates are incomplete")
    local = final[local_columns]
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
    repeated_resources = _qasm_resources(
        circuit,
        parameter_count=parameter_count,
        logical_block_count=len(blocks),
    )
    semantic_energy = energy(final, ())
    semantic_state = np.asarray(
        algorithm.compute_state(list(mapped), indices).toarray()
    ).ravel()
    semantic_state /= np.linalg.norm(semantic_state)
    reference = np.asarray(algorithm.ref_state.toarray()).ravel()
    native_state = np.asarray(
        Statevector(reference).evolve(circuit).data,
        dtype=np.complex128,
    )
    native_state /= np.linalg.norm(native_state)
    fidelity = float(abs(np.vdot(semantic_state, native_state)) ** 2)
    native_energy = float(
        np.real(np.vdot(native_state, algorithm.hamiltonian @ native_state))
    )
    normal = np.asarray(family["normal"], dtype=np.float64)
    local_source = mapped[list(block.ansatz_positions)]
    constraint_residual = float(abs(normal @ local_source))
    finite_difference = {}
    selected = np.linspace(
        0,
        final.size - 1,
        min(FINITE_DIFFERENCE_COMPONENTS, final.size),
        dtype=int,
    )
    for index in selected:
        plus = final.copy()
        minus = final.copy()
        plus[index] += FINITE_DIFFERENCE_STEP
        minus[index] -= FINITE_DIFFERENCE_STEP
        estimate = (
            energy(plus, ()) - energy(minus, ())
        ) / (2.0 * FINITE_DIFFERENCE_STEP)
        finite_difference[str(int(index))] = {
            "analytic": float(target_gradient[index]),
            "finite_difference": float(estimate),
            "absolute_error": float(abs(estimate - target_gradient[index])),
        }
    delta = {
        field: int(resources[field]) - int(source_resources[field])
        for field in (
            "cnot_count",
            "cnot_depth",
            "total_depth",
            "parameter_count",
            "logical_block_count",
        )
    }
    source_snapshot_before = sha256_hex(
        {
            "indices": list(source.indices),
            "coefficients": list(canonical_float64_hex(source.coefficients)),
            "counts": list(source.cumulative_parameter_counts),
        }
    )
    source_snapshot_after = sha256_hex(
        {
            "indices": list(source.indices),
            "coefficients": list(canonical_float64_hex(source.coefficients)),
            "counts": list(source.cumulative_parameter_counts),
        }
    )
    semantic_valid = (
        fidelity >= 1.0 - STATE_FIDELITY_TOLERANCE
        and max(entry["absolute_error"] for entry in finite_difference.values())
        <= FINITE_DIFFERENCE_TOLERANCE
    )
    evidence = AcceptanceEvidence(
        source_energy_hartree=source_energy,
        budget_reference_energy_hartree=source_energy,
        candidate_energy_hartree=float(result.fun),
        independent_energy_hartree=native_energy,
        independent_state_fidelity=fidelity,
        constraint_residual=constraint_residual,
        kkt_residual=float(np.max(np.abs(tangent_gradient))),
        before_resources=_snapshot(source_resources),
        after_resources=_snapshot(resources),
        full_resource_recount_succeeded=resources == repeated_resources,
        transformation_semantics_validated=semantic_valid,
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
            independent_energy_tolerance_hartree=ENERGY_AGREEMENT_TOLERANCE,
            minimum_state_fidelity=1.0 - STATE_FIDELITY_TOLERANCE,
            maximum_constraint_residual=CONSTRAINT_TOLERANCE,
            maximum_kkt_residual=STATIONARITY_TOLERANCE,
            resource_policy="componentwise-pareto-v1",
        ),
    )
    return {
        "attempt_id": "pra-s6-attempt:" + sha256_hex(item),
        "queue_item": dict(item),
        "case": dict(case),
        "initialization": {
            "kind": "euclidean-plane-projection",
            "energy_hartree": initial_energy,
            "source_relative_loss_hartree": initial_energy - source_energy,
        },
        "optimizer": {
            "success": bool(result.success),
            "status": int(result.status),
            "message": str(result.message),
            "iterations": int(result.nit),
            "energy_evaluations": int(result.nfev),
            "gradient_vector_evaluations": int(result.njev),
            "fallback_used": False,
        },
        "certification": {
            "candidate_energy_hartree": float(result.fun),
            "semantic_energy_hartree": semantic_energy,
            "native_energy_hartree": native_energy,
            "source_relative_loss_hartree": native_energy - source_energy,
            "candidate_full_source_coordinate_gradient_infinity": float(
                np.max(np.abs(full_gradient))
            ),
            "candidate_target_coordinate_gradient_infinity": float(
                np.max(np.abs(target_gradient))
            ),
            "candidate_orthonormal_tangent_gradient_infinity": float(
                np.max(np.abs(tangent_gradient))
            ),
            "normal_component_l2": float(np.linalg.norm(normal_component)),
            "constraint_residual": constraint_residual,
            "semantic_native_state_fidelity": fidelity,
            "finite_difference_spot_checks": finite_difference,
        },
        "resources": {
            "source": dict(source_resources),
            "candidate": resources,
            "delta": delta,
            "independent_repeat_equal": resources == repeated_resources,
        },
        "acceptance": asdict(decision),
        "classification": (
            "PRIMARY_NATIVE_RANK2_ACCEPTED"
            if decision.accepted
            else "PRIMARY_NATIVE_RANK2_REJECTED"
        ),
        "transaction": {
            "source_snapshot_before": source_snapshot_before,
            "source_snapshot_after": source_snapshot_after,
            "source_immutable": source_snapshot_before == source_snapshot_after,
            "committed_to_primary_lineage": False,
            "rollback_complete": True,
        },
        "final_target_coordinates_float64_hex": list(
            canonical_float64_hex(final)
        ),
        "final_source_coordinates_float64_hex": list(
            canonical_float64_hex(mapped)
        ),
        "work": {
            "optimizer_iterations": int(result.nit),
            "optimizer_energy_evaluations": int(result.nfev),
            "optimizer_gradient_vector_evaluations": int(result.njev),
            "finite_difference_energy_evaluations": 2 * len(finite_difference),
            "independent_energy_evaluations": 2,
            "statevector_recomputations": 2,
            "full_resource_recounts": 2,
            "wall_time_seconds": time.perf_counter() - started,
            "paper_measurement_cost": None,
        },
        "paper_measurement_cost": None,
    }


def _verify_freeze() -> dict[str, Any]:
    freeze = json.loads(FREEZE_OUTPUT.read_text(encoding="utf-8"))
    content = dict(freeze)
    digest = content.pop("freeze_digest", None)
    if digest != sha256_hex(content):
        raise S6DevelopmentError("S6 queue freeze digest mismatch")
    if freeze["runner_version"] != RUNNER_VERSION:
        raise S6DevelopmentError("S6 runner version mismatch")
    for key in ("s5", "ns1", "ns3", "ns4"):
        value = freeze["inputs"][key]
        if _sha256(ROOT / value["path"]) != value["sha256"]:
            raise S6DevelopmentError(f"frozen input changed: {key}")
    for source in freeze["inputs"]["sources"]:
        if _sha256(ROOT / source["path"]) != source["sha256"]:
            raise S6DevelopmentError(
                f"frozen source changed: {source['case_id']}"
            )
    return freeze


def build_result() -> dict[str, Any]:
    if RESULT_OUTPUT.exists():
        raise S6DevelopmentError("refusing to overwrite S6 result")
    execution = _clean_and_threads()
    freeze = _verify_freeze()
    families = _certified_families()
    attempts = []
    case_summaries = []
    by_case = {
        case["case_id"]: case for case in DEVELOPMENT_CASES
    }
    for case_id in [case["case_id"] for case in DEVELOPMENT_CASES]:
        case = by_case[case_id]
        source_payload, source = _load_source(case_id)
        algorithm, pool = _algorithm(case)
        source_energy = float(
            algorithm.evaluate_energy(
                list(source.coefficients),
                list(source.indices),
            )
        )
        if abs(source_energy - source_payload["source_energy_hartree"]) > 1e-10:
            raise S6DevelopmentError(f"source energy mismatch: {case_id}")
        blocks = recover_dvg_blocks(
            pool,
            source.indices,
            source.coefficients,
            source.cumulative_parameter_counts,
        )
        source_circuit, source_parameter_count = _compose_context(pool, blocks)
        source_resources = _qasm_resources(
            source_circuit,
            parameter_count=source_parameter_count,
            logical_block_count=len(blocks),
        )
        case_attempts = []
        for item in freeze["queue"]:
            if item["case_id"] != case_id:
                continue
            attempt = evaluate_attempt(
                item,
                families[item["family_id"]],
                case,
                source,
                algorithm,
                pool,
                source_energy,
                source_resources,
            )
            attempts.append(attempt)
            case_attempts.append(attempt)
        accepted = [item for item in case_attempts if item["acceptance"]["accepted"]]
        case_summaries.append(
            {
                "case_id": case_id,
                "attempted": len(case_attempts),
                "accepted": len(accepted),
                "rejected": len(case_attempts) - len(accepted),
                "accepted_attempt_ids": [item["attempt_id"] for item in accepted],
                "new_energy_resource_nondominated_point": bool(accepted),
                "best_accepted_cnot_reduction": max(
                    (-item["resources"]["delta"]["cnot_count"] for item in accepted),
                    default=0,
                ),
                "best_accepted_cnot_depth_reduction": max(
                    (-item["resources"]["delta"]["cnot_depth"] for item in accepted),
                    default=0,
                ),
                "best_accepted_total_depth_reduction": max(
                    (-item["resources"]["delta"]["total_depth"] for item in accepted),
                    default=0,
                ),
                "best_accepted_parameter_reduction": max(
                    (-item["resources"]["delta"]["parameter_count"] for item in accepted),
                    default=0,
                ),
            }
        )
    if len(attempts) != freeze["queue_count"]:
        raise S6DevelopmentError("not every frozen S6 queue item was attempted")
    h4_positive = any(
        item["case_id"].startswith("h4-")
        and item["new_energy_resource_nondominated_point"]
        for item in case_summaries
    )
    non_h4_positive = any(
        not item["case_id"].startswith("h4-")
        and item["new_energy_resource_nondominated_point"]
        for item in case_summaries
    )
    decision = (
        "GO_S7_INDEPENDENT_H4_AND_CROSS_SYSTEM_POSITIVE"
        if h4_positive and non_h4_positive
        else "NO_GO_S6_REQUIRED_CROSS_SYSTEM_EVIDENCE_ABSENT"
    )
    report: dict[str, Any] = {
        "schema": "dvg-obs-ceo.pra-path.s6-development-result.v1",
        "runner_version": RUNNER_VERSION,
        "execution": execution,
        "queue_freeze_digest": freeze["freeze_digest"],
        "attempts": attempts,
        "case_summaries": case_summaries,
        "summary": {
            "attempted": len(attempts),
            "accepted": sum(item["accepted"] for item in case_summaries),
            "rejected": sum(item["rejected"] for item in case_summaries),
            "h4_reproducibility_positive": h4_positive,
            "cross_system_positive": non_h4_positive,
            "decision": decision,
            "pra_performance_claim_established": False,
        },
        "authorization": {
            "s7": decision == "GO_S7_INDEPENDENT_H4_AND_CROSS_SYSTEM_POSITIVE",
            "s8": False,
            "prospective_execution": False,
        },
        "claim_boundary": (
            "Independent development certification only. Matched-work "
            "superiority and prospective validation remain unestablished."
        ),
        "paper_measurement_cost": None,
    }
    report["report_digest"] = sha256_hex(report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("freeze", "run"))
    arguments = parser.parse_args()
    if arguments.action == "freeze":
        result = build_queue_freeze()
        atomic_write_new_json(FREEZE_OUTPUT, result)
        print(
            json.dumps(
                {
                    "queue_count": result["queue_count"],
                    "freeze_digest": result["freeze_digest"],
                },
                sort_keys=True,
            )
        )
    else:
        result = build_result()
        atomic_write_new_json(RESULT_OUTPUT, result)
        print(json.dumps(result["summary"], sort_keys=True))


if __name__ == "__main__":
    main()

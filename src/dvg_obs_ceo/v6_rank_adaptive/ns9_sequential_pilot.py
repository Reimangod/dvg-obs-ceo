"""Frozen two-round H4 native-rank sequential pilot for V6-NS9."""

from __future__ import annotations

from dataclasses import asdict
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
    _compose_context,
    _load_context_structure,
    build_shortest_parity_circuit,
)
from .ns7_energy_certification import DEFAULT_OUTPUT as NS7_OUTPUT
from .ns8_followup_audit import DEFAULT_OUTPUT as NS8_OUTPUT
from .ns8_followup_audit import _dominates


FREEZE_OUTPUT = ROOT / "artifacts/v6/ns9/queue-freeze-v1.json"
RESULT_OUTPUT = ROOT / "artifacts/v6/ns9/sequential-pilot-v1.json"
FREEZE_VERSION = "v6-ns9-h4-two-round-freeze-v1"
RUNNER_VERSION = "v6-ns9-h4-two-round-native-pilot-v1"
ENERGY_BUDGET_HARTREE = 1e-4
STATIONARITY_TOLERANCE = 1e-8
MAXIMUM_ITERATIONS = 200
GRADIENT_TOLERANCE = 1e-8
FINITE_DIFFERENCE_STEP = 1e-6
FINITE_DIFFERENCE_COMPONENTS = 5
ENERGY_AGREEMENT_TOLERANCE = 1e-10
STATE_FIDELITY_TOLERANCE = 1e-10
WORK_CAP = {
    "exact_attempts": 4,
    "optimizer_iterations": 800,
    "optimizer_energy_evaluations": 820,
    "optimizer_gradient_vector_evaluations": 820,
    "finite_difference_energy_evaluations": 40,
    "full_resource_recounts": 4,
}
REQUIRED_THREADS = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
}


class NS9PilotError(RuntimeError):
    """Raised when NS9 violates its frozen protocol or work cap."""


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
        raise NS9PilotError("NS9 stage requires a clean committed worktree")


def _threads() -> dict[str, str | None]:
    values = {name: os.environ.get(name) for name in REQUIRED_THREADS}
    if values != REQUIRED_THREADS:
        raise NS9PilotError(f"noncanonical thread settings: {values}")
    return values


def combined_embedding(
    source_dimension: int,
    blocks: Sequence[
        tuple[str, Sequence[int], np.ndarray]
    ],
) -> tuple[np.ndarray, tuple[str, ...]]:
    position_owner: dict[int, tuple[str, Sequence[int], np.ndarray]] = {}
    for block_id, positions, parameter_map in blocks:
        positions = tuple(int(value) for value in positions)
        if (
            len(positions) != 3
            or tuple(sorted(positions)) != positions
            or parameter_map.shape != (3, 2)
        ):
            raise NS9PilotError("combined embedding block is malformed")
        for position in positions:
            if position in position_owner:
                raise NS9PilotError("combined embedding blocks overlap")
            position_owner[position] = (block_id, positions, parameter_map)
    columns: list[np.ndarray] = []
    slots: list[str] = []
    handled: set[str] = set()
    for position in range(source_dimension):
        owner = position_owner.get(position)
        if owner is None:
            column = np.zeros(source_dimension, dtype=np.float64)
            column[position] = 1.0
            columns.append(column)
            slots.append(f"source:{position}")
            continue
        block_id, positions, parameter_map = owner
        if block_id in handled:
            continue
        if position != positions[0]:
            raise NS9PilotError("block positions are not encountered canonically")
        for local in range(2):
            column = np.zeros(source_dimension, dtype=np.float64)
            column[list(positions)] = parameter_map[:, local]
            columns.append(column)
            slots.append(f"block:{block_id}:phi:{local}")
        handled.add(block_id)
    matrix = np.column_stack(columns)
    expected = source_dimension - len(blocks)
    if (
        matrix.shape != (source_dimension, expected)
        or np.linalg.matrix_rank(matrix) != expected
    ):
        raise NS9PilotError("combined embedding has the wrong rank")
    return matrix, tuple(slots)


def projected_coordinates(
    source: np.ndarray, embedding: np.ndarray
) -> np.ndarray:
    value, _, rank, _ = np.linalg.lstsq(embedding, source, rcond=None)
    if rank != embedding.shape[1] or not np.all(np.isfinite(value)):
        raise NS9PilotError("NS9 Euclidean projection failed")
    return np.asarray(value, dtype=np.float64)


def build_queue_freeze() -> dict[str, Any]:
    if FREEZE_OUTPUT.exists():
        raise NS9PilotError("NS9 queue freeze already exists")
    _clean()
    ns7 = json.loads(NS7_OUTPUT.read_text(encoding="utf-8"))
    ns8 = json.loads(NS8_OUTPUT.read_text(encoding="utf-8"))
    families = {
        item["family_id"]: item
        for item in json.loads(NS1_OUTPUT.read_text(encoding="utf-8"))[
            "families"
        ]
    }
    accepted = sorted(
        (
            item
            for item in ns7["attempts"]
            if item["classification"] == "PRIMARY_NATIVE_RANK2_ACCEPTED"
            and item["queue_item"]["context_id"] == "h4-1.5-late"
        ),
        key=lambda item: item["family_id"],
    )
    if len(accepted) != 2:
        raise NS9PilotError("NS9 requires exactly two accepted H4 roots")
    algorithm, pool = h4_algorithm(
        "h4-1.5-iteration-12-or-convergence"
    )
    del algorithm
    context = next(
        item for item in CONTEXTS if item["case_id"] == "h4-1.5-late"
    )
    source = _load_context_structure(context)
    rank3 = sorted(
        (
            block
            for block in recover_dvg_blocks(
                pool,
                source.indices,
                source.coefficients,
                source.cumulative_parameter_counts,
            )
            if len(block.pool_indices) == 3
        ),
        key=lambda block: block.block_id,
    )
    if len(rank3) != 2:
        raise NS9PilotError("NS9 requires exactly two eligible H4 MVP3 blocks")
    family_ids = [item["family_id"] for item in accepted]
    queue = []
    for root in accepted:
        root_block = root["queue_item"]["source_block_id"]
        remaining = next(
            block for block in rank3 if block.block_id != root_block
        )
        for child_family_id in sorted(family_ids):
            item = {
                "context_id": "h4-1.5-late",
                "root_attempt_id": root["attempt_id"],
                "root_family_id": root["family_id"],
                "root_normal": root["normal"],
                "root_block_id": root_block,
                "root_source_coordinates_float64_hex": root[
                    "final_source_coordinates_float64_hex"
                ],
                "child_family_id": child_family_id,
                "child_normal": families[child_family_id]["normal"],
                "child_block_id": remaining.block_id,
                "child_pool_indices": list(remaining.pool_indices),
                "round_index": 2,
            }
            item["queue_id"] = "v6-ns9-queue:" + sha256_hex(item)
            queue.append(item)
    if len(queue) != WORK_CAP["exact_attempts"]:
        raise NS9PilotError("NS9 queue does not match the exact-attempt cap")
    freeze = {
        "schema_version": "1.0.0",
        "artifact_kind": "v6-ns9-h4-queue-freeze",
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
                "report_digest": ns7["report_digest"],
            },
            "ns8": {
                "path": str(NS8_OUTPUT.relative_to(ROOT)),
                "sha256": _sha256(NS8_OUTPUT),
                "report_digest": ns8["report_digest"],
            },
        },
        "queue": queue,
        "queue_count": len(queue),
        "protocol": {
            "energy_budget_hartree": ENERGY_BUDGET_HARTREE,
            "stationarity_tolerance": STATIONARITY_TOLERANCE,
            "maximum_iterations_per_attempt": MAXIMUM_ITERATIONS,
            "gradient_tolerance": GRADIENT_TOLERANCE,
            "initialization": "euclidean-projection-of-accepted-root",
            "initial_inverse_hessian": "identity",
            "fallback": None,
            "work_cap": WORK_CAP,
            "outcomes_may_change_queue": False,
            "fci_or_chemical_accuracy_used": False,
            "paper_measurement_cost": None,
        },
        "entry_boundary": {
            "ns7_mechanism_certified": True,
            "ns8_same_source_frontier_addition": ns8["frontier_audit"][
                "ns7_adds_same_source_energy_resource_pareto_point"
            ],
            "reason_to_run_despite_dominated_roots": (
                "Bounded test of whether a second native rank transition "
                "certifies and changes the cumulative frontier."
            ),
        },
    }
    freeze["freeze_digest"] = sha256_hex(freeze)
    return freeze


def freeze_main() -> None:
    try:
        freeze = build_queue_freeze()
        atomic_write_new_json(FREEZE_OUTPUT, freeze)
    except (
        KeyError,
        OSError,
        subprocess.CalledProcessError,
        TypeError,
        ValueError,
        NS9PilotError,
    ) as error:
        print(f"V6-NS9 queue freeze failed: {error}", file=sys.stderr)
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


def _native_circuit(
    pool: Any,
    source: Any,
    source_coordinates: np.ndarray,
    target_blocks: Mapping[str, tuple[np.ndarray, np.ndarray]],
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
    found: set[str] = set()
    for block in blocks:
        target = target_blocks.get(block.block_id)
        if target is None:
            segment = pool.get_circuit(
                list(block.pool_indices), list(block.coefficients)
            )
            parameter_count += len(block.pool_indices)
        else:
            parameter_map, local = target
            segment, _ = build_shortest_parity_circuit(
                pool, block.pool_indices, parameter_map, local
            )
            parameter_count += 2
            found.add(block.block_id)
        circuit = circuit.compose(segment)
        if target is not None:
            circuit.barrier()
    if found != set(target_blocks):
        raise NS9PilotError("not every frozen target block was reconstructed")
    return circuit, parameter_count


def _snapshot(value: Mapping[str, Any], digest: str) -> ResourceSnapshot:
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
    item: Mapping[str, Any],
    families: Mapping[str, Mapping[str, Any]],
    source: Any,
    algorithm: Any,
    pool: Any,
    source_resources: Mapping[str, Any],
    source_energy: float,
) -> dict[str, Any]:
    from adaptvqe.minimize import minimize_bfgs

    started = time.perf_counter()
    blocks = recover_dvg_blocks(
        pool,
        source.indices,
        source.coefficients,
        source.cumulative_parameter_counts,
    )
    by_id = {block.block_id: block for block in blocks}
    root_block = by_id[item["root_block_id"]]
    child_block = by_id[item["child_block_id"]]
    root_map = np.asarray(
        families[item["root_family_id"]]["parameter_map"],
        dtype=np.float64,
    )
    child_map = np.asarray(
        families[item["child_family_id"]]["parameter_map"],
        dtype=np.float64,
    )
    embedding, slots = combined_embedding(
        len(source.indices),
        (
            (root_block.block_id, root_block.ansatz_positions, root_map),
            (child_block.block_id, child_block.ansatz_positions, child_map),
        ),
    )
    # Decode separately to avoid platform-native byte-order ambiguity.
    import struct

    root_coordinates = np.asarray(
        [
            struct.unpack(">d", bytes.fromhex(value))[0]
            for value in item["root_source_coordinates_float64_hex"]
        ],
        dtype=np.float64,
    )
    initial = projected_coordinates(root_coordinates, embedding)
    indices = list(source.indices)

    def energy(coordinates: np.ndarray, _: Sequence[Any]) -> float:
        mapped = embedding @ np.asarray(coordinates)
        return float(algorithm.evaluate_energy(list(mapped), indices))

    def gradient(
        coordinates: np.ndarray, _: Sequence[Any]
    ) -> np.ndarray:
        mapped = embedding @ np.asarray(coordinates)
        source_gradient = np.asarray(
            algorithm.estimate_gradients(
                list(mapped), indices, method="an"
            ),
            dtype=np.float64,
        )
        return embedding.T @ source_gradient

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
    target_gradient = gradient(final, ())
    semantic_energy = energy(final, ())
    local_coordinates = {}
    for block in (root_block, child_block):
        local_coordinates[block.block_id] = np.asarray(
            [
                final[index]
                for index, slot in enumerate(slots)
                if slot.startswith(f"block:{block.block_id}:phi:")
            ],
            dtype=np.float64,
        )
        if local_coordinates[block.block_id].shape != (2,):
            raise NS9PilotError("local target coordinates are incomplete")
    circuit, parameter_count = _native_circuit(
        pool,
        source,
        mapped,
        {
            root_block.block_id: (
                root_map,
                local_coordinates[root_block.block_id],
            ),
            child_block.block_id: (
                child_map,
                local_coordinates[child_block.block_id],
            ),
        },
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
    native_energy = float(
        np.real(np.vdot(native_state, algorithm.hamiltonian @ native_state))
    )
    state_fidelity = float(
        abs(np.vdot(semantic_state, native_state)) ** 2
    )
    source_state = np.asarray(
        algorithm.compute_state(
            list(source.coefficients), indices
        ).toarray()
    ).ravel()
    source_state /= np.linalg.norm(source_state)
    source_candidate_fidelity = float(
        abs(np.vdot(source_state, semantic_state)) ** 2
    )
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
            "absolute_error": float(
                abs(estimate - target_gradient[index])
            ),
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
    constraint_residual = max(
        float(
            abs(
                np.asarray(
                    families[family_id]["normal"], dtype=np.float64
                )
                @ mapped[list(block.ansatz_positions)]
            )
        )
        for family_id, block in (
            (item["root_family_id"], root_block),
            (item["child_family_id"], child_block),
        )
    )
    evidence = AcceptanceEvidence(
        source_energy_hartree=source_energy,
        budget_reference_energy_hartree=source_energy,
        candidate_energy_hartree=float(result.fun),
        independent_energy_hartree=native_energy,
        independent_state_fidelity=state_fidelity,
        constraint_residual=constraint_residual,
        kkt_residual=float(np.max(np.abs(target_gradient))),
        before_resources=_snapshot(
            source_resources,
            source_resources["circuit_qasm_digest"],
        ),
        after_resources=_snapshot(
            resources, resources["circuit_qasm_digest"]
        ),
        full_resource_recount_succeeded=resources == repeated_resources,
        transformation_semantics_validated=(
            state_fidelity >= 1.0 - STATE_FIDELITY_TOLERANCE
            and max(
                record["absolute_error"]
                for record in finite_difference.values()
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
            minimum_state_fidelity=1.0 - STATE_FIDELITY_TOLERANCE,
            maximum_constraint_residual=1e-10,
            maximum_kkt_residual=STATIONARITY_TOLERANCE,
            resource_policy="circuit-primary-v1",
        ),
    )
    return {
        "attempt_id": "v6-ns9-attempt:" + sha256_hex(item),
        "queue_item": dict(item),
        "classification": (
            "PRIMARY_TWO_RANK_TRANSITIONS_ACCEPTED"
            if decision.accepted
            else "PRIMARY_TWO_RANK_TRANSITIONS_REJECTED"
        ),
        "initialization": {
            "initial_energy_hartree": initial_energy,
            "root_energy_hartree": float(
                algorithm.evaluate_energy(
                    list(root_coordinates), indices
                )
            ),
            "source_relative_initial_loss_hartree": (
                initial_energy - source_energy
            ),
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
            "optimizer_energy_hartree": float(result.fun),
            "semantic_energy_hartree": semantic_energy,
            "native_energy_hartree": native_energy,
            "source_relative_loss_hartree": native_energy - source_energy,
            "target_gradient_infinity": float(
                np.max(np.abs(target_gradient))
            ),
            "constraint_residual": constraint_residual,
            "semantic_native_state_fidelity": state_fidelity,
            "source_candidate_state_fidelity": source_candidate_fidelity,
            "finite_difference_spot_checks": finite_difference,
        },
        "resources": {
            "source": dict(source_resources),
            "candidate": resources,
            "delta": delta,
            "independent_repeat_equal": resources == repeated_resources,
        },
        "acceptance": asdict(decision),
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
            "finite_difference_energy_evaluations": (
                2 * len(finite_difference)
            ),
            "full_resource_recounts": 1,
            "wall_time_seconds": time.perf_counter() - started,
            "paper_measurement_cost": None,
        },
        "functional_roots_immutable": True,
        "paper_measurement_cost": None,
    }


def _aggregate_work(attempts: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    return {
        "exact_attempts": len(attempts),
        "optimizer_iterations": sum(
            item["work"]["optimizer_iterations"] for item in attempts
        ),
        "optimizer_energy_evaluations": sum(
            item["work"]["optimizer_energy_evaluations"]
            for item in attempts
        ),
        "optimizer_gradient_vector_evaluations": sum(
            item["work"]["optimizer_gradient_vector_evaluations"]
            for item in attempts
        ),
        "finite_difference_energy_evaluations": sum(
            item["work"]["finite_difference_energy_evaluations"]
            for item in attempts
        ),
        "full_resource_recounts": sum(
            item["work"]["full_resource_recounts"] for item in attempts
        ),
    }


def build_report() -> dict[str, Any]:
    if RESULT_OUTPUT.exists():
        raise NS9PilotError("NS9 result already exists")
    _clean()
    threads = _threads()
    freeze = json.loads(FREEZE_OUTPUT.read_text(encoding="utf-8"))
    content = dict(freeze)
    freeze_digest = content.pop("freeze_digest")
    if freeze_digest != sha256_hex(content):
        raise NS9PilotError("NS9 queue freeze digest mismatch")
    if freeze["protocol"]["work_cap"] != WORK_CAP:
        raise NS9PilotError("runner work cap differs from freeze")
    for value in freeze["inputs"].values():
        if _sha256(ROOT / value["path"]) != value["sha256"]:
            raise NS9PilotError("NS9 frozen input hash mismatch")
    families = {
        item["family_id"]: item
        for item in json.loads(NS1_OUTPUT.read_text(encoding="utf-8"))[
            "families"
        ]
    }
    algorithm, pool = h4_algorithm(
        "h4-1.5-iteration-12-or-convergence"
    )
    context = next(
        item for item in CONTEXTS if item["case_id"] == "h4-1.5-late"
    )
    source = _load_context_structure(context)
    source_energy = float(
        algorithm.evaluate_energy(
            list(source.coefficients), list(source.indices)
        )
    )
    source_blocks = recover_dvg_blocks(
        pool,
        source.indices,
        source.coefficients,
        source.cumulative_parameter_counts,
    )
    source_circuit, source_parameter_count = _compose_context(
        pool, source_blocks
    )
    source_resources = _qasm_resources(
        source_circuit,
        parameter_count=source_parameter_count,
        logical_block_count=len(source_blocks),
    )
    attempts = [
        evaluate_attempt(
            item,
            families,
            source,
            algorithm,
            pool,
            source_resources,
            source_energy,
        )
        for item in freeze["queue"]
    ]
    work = _aggregate_work(attempts)
    work_checks = {
        name: work[name] <= maximum
        for name, maximum in WORK_CAP.items()
    }
    if not all(work_checks.values()):
        raise NS9PilotError(f"NS9 work cap exceeded: {work_checks}")
    accepted = [
        item for item in attempts if item["acceptance"]["accepted"]
    ]
    ns8 = json.loads(NS8_OUTPUT.read_text(encoding="utf-8"))
    legacy = [
        point
        for point in ns8["frontier_audit"]["points"]
        if point["pareto_nondominated"]
    ]
    frontier_checks = []
    for attempt in accepted:
        point = {
            "energy_loss_hartree": attempt["certification"][
                "source_relative_loss_hartree"
            ],
            "resources": attempt["resources"]["candidate"],
        }
        dominated_by = [
            old["point_id"] for old in legacy if _dominates(old, point)
        ]
        frontier_checks.append(
            {
                "attempt_id": attempt["attempt_id"],
                "dominated_by_legacy": dominated_by,
                "adds_legacy_nondominated_point": not dominated_by,
            }
        )
    mechanism_go = bool(accepted)
    frontier_go = any(
        item["adds_legacy_nondominated_point"]
        for item in frontier_checks
    )
    report = {
        "schema_version": "1.0.0",
        "artifact_kind": "v6-ns9-h4-bounded-sequential-pilot",
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
        "source": {
            "energy_hartree": source_energy,
            "resources": source_resources,
        },
        "attempts": attempts,
        "work": {
            "observed": work,
            "cap": WORK_CAP,
            "checks": work_checks,
        },
        "frontier_checks": frontier_checks,
        "summary": {
            "attempted": len(attempts),
            "accepted": len(accepted),
            "rejected": len(attempts) - len(accepted),
            "mechanism_gate": (
                "PASS_ADDITIONAL_RANK_TRANSITION"
                if mechanism_go
                else "NO_GO_NO_ADDITIONAL_CERTIFIED_TRANSITION"
            ),
            "scientific_frontier_gate": (
                "PASS_NEW_LEGACY_NONDOMINATED_POINT"
                if frontier_go
                else "NO_GO_DOMINATED_BY_LEGACY_FRONTIER"
            ),
            "h6_optimizer_ablation_authorized": frontier_go,
            "pra_performance_claim_established": False,
        },
        "claim_boundary": (
            "Bounded two-round H4 development pilot. Mechanism success and "
            "legacy-frontier success are separate. No cross-molecule, "
            "matched-work superiority, Measurement Cost, or PRA claim."
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
        NS9PilotError,
    ) as error:
        print(f"V6-NS9 pilot failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    print(json.dumps(report["summary"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

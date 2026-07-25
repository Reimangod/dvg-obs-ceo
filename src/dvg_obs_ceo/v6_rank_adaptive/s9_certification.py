"""V6-S9 isolated native-rank2 feasibility and predictor certification.

This runner consumes only the immutable V6-S8.1 exploratory queue.  Successful
attempts are committed under an isolated S9 transaction root and never replace
the canonical S6/V6 primary parent.
"""

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
from dvg_obs_ceo.multisystem_checkpoint import _algorithm
from dvg_obs_ceo.quadratic import predict_constrained_optimum
from dvg_obs_ceo.resources import AnsatzStructure
from dvg_obs_ceo.s8_probe import _optimize_target, _state_vector
from dvg_obs_ceo.telemetry import ResourceSnapshot, WorkCounters
from dvg_obs_ceo.transaction import (
    AcceptanceCriteria,
    AcceptanceEvidence,
    CompressionRuntime,
    CompressionTransaction,
    OptimizerOutcome,
    evaluate_acceptance,
)

from .native_rank2_feasibility import (
    COUNTER_VERSION,
    NATIVE_SYNTHESIS_ID,
    _compose_checkpoint_circuit,
    _qasm_resources,
)
from .predictor_freeze import (
    DEFAULT_MODEL,
    DEFAULT_S6,
    DEFAULT_S7,
    _constraint_parameterization,
    _structure,
    build_pulled_back_model,
)
from .s8_1_protocol_freeze import DEFAULT_OUTPUT as DEFAULT_S8_1
from .s9_fault_audit import run_fault_audit


DEFAULT_OUTPUT = ROOT / "artifacts/v6/s9/native-rank2-top2-result-v1.json"
DEFAULT_TRANSACTION_ROOT = ROOT / "artifacts/v6/s9/transactions"
RUNNER_VERSION = "v6-s9-isolated-native-rank2-certification-v1"
PROTOCOL_VERSION = "v6-s8.1-pre-outcome-endpoint-top2-freeze-v1"
CASE = {
    "case_id": "h6-1.5",
    "distance_angstrom": 1.5,
    "figure_role": ["fig14", "fig15"],
    "gradient_threshold": 1e-6,
    "molecule": "H6",
}
ENERGY_BUDGET_HARTREE = 1e-4
STATIONARITY_TOLERANCE = 1e-8
ENERGY_AGREEMENT_TOLERANCE = 1e-10
STATE_FIDELITY_TOLERANCE = 1e-10
GRADIENT_PATH_TOLERANCE = 1e-8
MAXIMUM_FALLBACKS_PER_CANDIDATE = 1
FALLBACK_TRIGGER = (
    "primary optimizer unsuccessful or final target gradient infinity exceeds "
    "1e-8"
)
FALLBACK_INITIALIZATION = "unoptimized-demoted-s6-seed-with-identity-hessian"
REQUIRED_THREADS = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
}


class S9CertificationError(RuntimeError):
    """Raised when the frozen S9 execution contract cannot be certified."""


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


def _legacy_primary(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return next(
        item["primary"]
        for item in value["attempts"]
        if item["attempt_number"] == 1
        and item["transaction_status"] == "accepted"
    )


def _dependency_versions() -> dict[str, str]:
    names = ("numpy", "scipy", "qiskit", "openfermion", "pytest")
    return {
        name: importlib.metadata.version(name)
        for name in names
    }


def build_execution_freeze(
    *,
    s6_path: Path = DEFAULT_S6,
    s7_path: Path = DEFAULT_S7,
    s8_1_path: Path = DEFAULT_S8_1,
    model_path: Path = DEFAULT_MODEL,
) -> dict[str, Any]:
    """Fail closed before the first candidate-energy call."""
    if DEFAULT_OUTPUT.exists() or DEFAULT_TRANSACTION_ROOT.exists():
        raise S9CertificationError(
            "S9 output already exists; outcome-blind execution cannot restart"
        )
    tracked = _git("status", "--porcelain", "--untracked-files=no")
    untracked = tuple(
        line
        for line in _git("ls-files", "--others", "--exclude-standard").splitlines()
        if line
    )
    if tracked or untracked:
        raise S9CertificationError(
            "S9 execution requires a completely clean committed worktree"
        )
    threads = {name: os.environ.get(name) for name in REQUIRED_THREADS}
    if threads != REQUIRED_THREADS:
        raise S9CertificationError(
            f"S9 requires canonical single-thread settings: {threads}"
        )
    s8_1 = json.loads(s8_1_path.read_text(encoding="utf-8"))
    if (
        s8_1.get("protocol_version") != PROTOCOL_VERSION
        or s8_1.get("pre_outcome_attestation", {}).get(
            "actual_candidate_energy_observed"
        )
        is not False
        or len(s8_1.get("exploratory_top2_candidate_ids", ())) != 2
        or s8_1.get("circuit_primary_candidate_ids") != []
    ):
        raise S9CertificationError("V6-S8.1 queue is not the frozen Top-2")
    inputs = {
        name: {
            "path": str(path.relative_to(ROOT)),
            "sha256": _sha256(path),
        }
        for name, path in (
            ("s6", s6_path),
            ("s7", s7_path),
            ("s8_1", s8_1_path),
            ("legacy_quadratic_model", model_path),
        )
    }
    freeze = {
        "runner_version": RUNNER_VERSION,
        "authoritative_queue": "V6-S8.1 only",
        "git_commit": _git("rev-parse", "HEAD"),
        "git_describe": _git("describe", "--always", "--dirty"),
        "worktree_clean": True,
        "inputs": inputs,
        "candidate_order": list(s8_1["exploratory_top2_candidate_ids"]),
        "primary_lineage_mutation_allowed": False,
        "optimizer": {
            "primary_initialization": "legacy-OBS/KKT-pullback-warm-start",
            "initial_inverse_hessian": (
                "identity; direct recycled-Hessian transport was rejected in S8"
            ),
            "fallback_maximum_per_candidate": MAXIMUM_FALLBACKS_PER_CANDIDATE,
            "fallback_trigger": FALLBACK_TRIGGER,
            "fallback_initialization": FALLBACK_INITIALIZATION,
            "fallback_selection": (
                "lower final gradient infinity; energy breaks exact ties"
            ),
            "candidate_1_outcome_may_initialize_candidate_2": False,
        },
        "acceptance": {
            "energy_budget_hartree": ENERGY_BUDGET_HARTREE,
            "stationarity_tolerance": STATIONARITY_TOLERANCE,
            "energy_agreement_tolerance": ENERGY_AGREEMENT_TOLERANCE,
            "state_fidelity_tolerance": STATE_FIDELITY_TOLERANCE,
            "gradient_path_tolerance": GRADIENT_PATH_TOLERANCE,
            "exploratory_resource_policy": (
                "total_depth and parameter_count both strictly improve"
            ),
            "circuit_primary_policy": (
                "CNOT and CNOT depth nonregress and one strictly improves"
            ),
            "fci_or_chemical_accuracy_used": False,
        },
        "threads": threads,
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
            "dependencies": _dependency_versions(),
        },
    }
    freeze["execution_freeze_digest"] = sha256_hex(freeze)
    return freeze


def _target_structure(
    source: AnsatzStructure,
    candidate: Mapping[str, Any],
    coordinates: Sequence[float],
) -> tuple[AnsatzStructure, int]:
    omitted = int(
        candidate["source_ansatz_positions"][
            candidate["omitted_source_slot"]
        ]
    )
    indices = list(source.indices)
    indices.pop(omitted)
    iteration = next(
        index
        for index, count in enumerate(
            source.cumulative_parameter_counts, start=1
        )
        if omitted < count
    )
    counts = tuple(
        value - int(current >= iteration)
        for current, value in enumerate(
            source.cumulative_parameter_counts, start=1
        )
    )
    return AnsatzStructure.create(indices, coordinates, counts), omitted


def _resource_snapshot(
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


def _native_recount_and_state(
    algorithm: Any,
    pool: Any,
    source: AnsatzStructure,
    candidate: Mapping[str, Any],
    final_coordinates: np.ndarray,
) -> tuple[dict[str, Any], np.ndarray, AnsatzStructure, int]:
    target, omitted = _target_structure(source, candidate, final_coordinates)
    source_coordinates = np.insert(final_coordinates, omitted, 0.0)
    embedded = AnsatzStructure.create(
        source.indices,
        source_coordinates,
        source.cumulative_parameter_counts,
    )
    blocks = recover_dvg_blocks(
        pool,
        embedded.indices,
        embedded.coefficients,
        embedded.cumulative_parameter_counts,
    )
    circuit, parameter_count = _compose_checkpoint_circuit(
        pool,
        blocks,
        target_block_id=candidate["source_block_id"],
        omitted_pool_index=int(candidate["omitted_pool_index"]),
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
    return resources, native_state, target, omitted


def _optimizer_outcome(path: Mapping[str, Any]) -> OptimizerOutcome:
    optimizer = path["optimizer"]
    return OptimizerOutcome(
        success=bool(optimizer["success"]),
        status=str(optimizer["status"]),
        message=str(optimizer["message"]),
        completed=True,
    )


def _choose_path(
    primary: Mapping[str, Any],
    fallback: Mapping[str, Any] | None,
) -> tuple[str, Mapping[str, Any]]:
    if fallback is None:
        return "primary", primary
    primary_key = (
        float(primary["gradient_infinity"]),
        float(primary["independent_energy_hartree"]),
    )
    fallback_key = (
        float(fallback["gradient_infinity"]),
        float(fallback["independent_energy_hartree"]),
    )
    return (
        ("fallback", fallback)
        if fallback_key < primary_key
        else ("primary", primary)
    )


def _prediction_diagnostics(
    predicted: float,
    actual: float,
) -> dict[str, Any]:
    signed = actual - predicted
    if actual == 0.0:
        ratio = None
    else:
        ratio = predicted / actual
    return {
        "predicted_loss_hartree": predicted,
        "actual_postoptimization_loss_hartree": actual,
        "signed_error_actual_minus_predicted_hartree": signed,
        "absolute_error_hartree": abs(signed),
        "predicted_to_actual_ratio": ratio,
        "direction": (
            "underestimate"
            if signed > 0.0
            else "overestimate"
            if signed < 0.0
            else "exact"
        ),
        "used_to_reorder_current_queue": False,
        "used_to_recalibrate_current_queue": False,
    }


def evaluate_candidate(
    *,
    algorithm: Any,
    pool: Any,
    source: AnsatzStructure,
    source_energy: float,
    source_state: np.ndarray,
    source_gradient: np.ndarray,
    pulled_back: Any,
    candidate: Mapping[str, Any],
    predicted_loss_hartree: float,
    ordinal: int,
    transaction_root: Path = DEFAULT_TRANSACTION_ROOT,
) -> dict[str, Any]:
    candidate_id = candidate["candidate_id"]
    omitted = int(
        candidate["source_ansatz_positions"][
            candidate["omitted_source_slot"]
        ]
    )
    row = pulled_back.forward_map[omitted]
    transformation = _constraint_parameterization(
        row, candidate_id=candidate_id
    )
    prediction = predict_constrained_optimum(
        pulled_back.model, transformation
    )
    mapped = pulled_back.forward_map @ prediction.constrained_theta
    mapping_residual = float(
        np.max(np.abs(mapped - pulled_back.forward_map @ prediction.constrained_theta))
    )
    if mapping_residual != 0.0:
        raise S9CertificationError("OBS warm-start mapping is not deterministic")
    obs_initial = np.delete(mapped, omitted)
    seed_initial = np.delete(
        np.asarray(source.coefficients, dtype=np.float64), omitted
    )
    target_seed, _ = _target_structure(source, candidate, obs_initial)
    initial_energy = float(
        algorithm.evaluate_energy(
            list(obs_initial), list(target_seed.indices)
        )
    )
    before = _resource_snapshot(
        candidate["resources"]["before"],
        candidate["resources"]["before_digest"],
    )
    runtime = CompressionRuntime.create(
        ansatz=source,
        energy_hartree=source_energy,
        gradient=source_gradient,
        inverse_hessian=np.eye(len(source.indices), dtype=np.float64),
        statevector=source_state,
        work=WorkCounters(
            energy_evaluations=2,
            gradient_vector_evaluations=1,
            gradient_component_evaluations=len(source.indices),
            statevector_kernels=2,
        ),
        adapt_iteration=len(source.cumulative_parameter_counts),
        metadata={
            "run_id": RUNNER_VERSION,
            "candidate_id": candidate_id,
            "resource_structure_digest": before.structure_digest,
            "budget_reference_energy_hartree": source_energy,
            "primary_lineage": False,
        },
    )
    transaction_id = f"candidate-{ordinal:02d}-{candidate_id[-12:]}"
    started = time.perf_counter()
    with CompressionTransaction(
        runtime,
        transaction_root,
        transaction_id=transaction_id,
        timeout_seconds=7200.0,
    ) as transaction:
        primary = _optimize_target(
            algorithm,
            target_seed.indices,
            obs_initial,
            np.eye(len(obs_initial), dtype=np.float64),
            source_state,
        )
        fallback = None
        if (
            not primary["optimizer"]["success"]
            or float(primary["gradient_infinity"])
            > STATIONARITY_TOLERANCE
        ):
            fallback = _optimize_target(
                algorithm,
                target_seed.indices,
                seed_initial,
                np.eye(len(seed_initial), dtype=np.float64),
                source_state,
            )
        selected_name, selected = _choose_path(primary, fallback)
        final = np.asarray(selected["coordinates"], dtype=np.float64)
        resources, native_state, target, target_omitted = (
            _native_recount_and_state(
                algorithm, pool, source, candidate, final
            )
        )
        semantic_state = _state_vector(
            algorithm, final, target.indices
        )
        semantic_native_fidelity = float(
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
        embedded_coordinates = np.insert(final, target_omitted, 0.0)
        source_path_gradient = np.asarray(
            algorithm.estimate_gradients(
                list(embedded_coordinates),
                list(source.indices),
                method="an",
            ),
            dtype=np.float64,
        )
        selected_source_gradient = np.delete(
            source_path_gradient, target_omitted
        )
        target_gradient = np.asarray(
            selected["gradient"], dtype=np.float64
        )
        gradient_path_residual = float(
            np.max(
                np.abs(target_gradient - selected_source_gradient)
            )
        )
        constraint_residual = float(
            abs(embedded_coordinates[target_omitted])
        )
        observed_after = _resource_snapshot(
            resources,
            resources["circuit_qasm_digest"],
        )
        s7_after = candidate["resources"]["after"]
        resource_recount_checks = {
            name: int(resources[name]) == int(s7_after[name])
            for name in (
                "cnot_count",
                "cnot_depth",
                "total_depth",
                "parameter_count",
                "logical_block_count",
            )
        }
        resource_incident = not all(resource_recount_checks.values())
        semantics_validated = bool(
            semantic_native_fidelity
            >= 1.0 - STATE_FIDELITY_TOLERANCE
            and gradient_path_residual <= GRADIENT_PATH_TOLERANCE
            and candidate["native_synthesis_evidence_id"]
            and candidate["contextual_rewrite_evidence_id"]
        )
        primary_outcome = _optimizer_outcome(primary)
        fallback_outcome = (
            None if fallback is None else _optimizer_outcome(fallback)
        )
        evidence = AcceptanceEvidence(
            source_energy_hartree=source_energy,
            budget_reference_energy_hartree=source_energy,
            candidate_energy_hartree=float(
                selected["energy_hartree"]
            ),
            independent_energy_hartree=native_energy,
            independent_state_fidelity=semantic_native_fidelity,
            constraint_residual=constraint_residual,
            kkt_residual=max(
                float(selected["gradient_infinity"]),
                gradient_path_residual,
            ),
            before_resources=before,
            after_resources=observed_after,
            full_resource_recount_succeeded=(
                not resource_incident
            ),
            transformation_semantics_validated=semantics_validated,
            primary_optimizer=primary_outcome,
            fallback_optimizer=fallback_outcome,
        )
        exploratory = evaluate_acceptance(
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
                resource_policy="exploratory-depth-parameter-v1",
            ),
        )
        circuit_primary = evaluate_acceptance(
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
        actual_loss = native_energy - source_energy
        record = {
            "candidate_id": candidate_id,
            "queue_ordinal": ordinal,
            "transaction_id": transaction_id,
            "selected_optimizer_path": selected_name,
            "primary_optimizer": primary,
            "fallback_optimizer": fallback,
            "fallback_count": int(fallback is not None),
            "initialization": {
                "obs_initial_coordinate_digest": sha256_hex(
                    obs_initial.tolist()
                ),
                "seed_initial_coordinate_digest": sha256_hex(
                    seed_initial.tolist()
                ),
                "initial_energy_hartree": initial_energy,
                "actual_preoptimization_loss_hartree": (
                    initial_energy - source_energy
                ),
                "inverse_hessian_policy": "identity",
            },
            "prediction": _prediction_diagnostics(
                predicted_loss_hartree, actual_loss
            ),
            "certification": {
                "optimizer_energy_hartree": float(
                    selected["energy_hartree"]
                ),
                "independent_semantic_energy_hartree": float(
                    selected["independent_energy_hartree"]
                ),
                "independent_native_energy_hartree": native_energy,
                "semantic_native_state_fidelity": (
                    semantic_native_fidelity
                ),
                "source_candidate_state_fidelity": float(
                    abs(np.vdot(source_state, native_state)) ** 2
                ),
                "target_gradient_infinity": float(
                    selected["gradient_infinity"]
                ),
                "source_path_gradient_infinity": float(
                    np.max(np.abs(source_path_gradient))
                ),
                "two_path_gradient_residual_infinity": (
                    gradient_path_residual
                ),
                "constraint_residual_infinity": constraint_residual,
                "source_state_sha256": hashlib.sha256(
                    np.asarray(source_state, dtype=">c16").tobytes()
                ).hexdigest(),
                "native_state_sha256": hashlib.sha256(
                    np.asarray(native_state, dtype=">c16").tobytes()
                ).hexdigest(),
            },
            "resource_recount": {
                "observed": resources,
                "s7_expected": s7_after,
                "checks": resource_recount_checks,
                "incident": resource_incident,
                "delta": {
                    name: int(getattr(observed_after, name))
                    - int(getattr(before, name))
                    for name in (
                        "cnot_count",
                        "cnot_depth",
                        "total_depth",
                        "parameter_count",
                        "logical_block_count",
                    )
                },
            },
            "endpoint_decisions": {
                "exploratory_depth_parameter": asdict(exploratory),
                "circuit_primary": asdict(circuit_primary),
            },
            "classification": (
                "EXPLORATORY_NATIVE_RANK2_FEASIBILITY_ACCEPTED"
                if exploratory.accepted
                else "NATIVE_RANK2_NOT_CERTIFIED"
            ),
            "primary_lineage_mutated": False,
            "work": {
                "candidate_wall_time_seconds": (
                    time.perf_counter() - started
                ),
                "primary": primary["optimizer"],
                "fallback": (
                    None if fallback is None else fallback["optimizer"]
                ),
                "independent_energy_evaluations": 2,
                "independent_gradient_vector_evaluations": 1,
                "independent_state_recomputations": 2,
                "full_resource_recounts": 1,
                "paper_measurement_cost": None,
            },
            "final_coordinates_float64_hex": list(
                canonical_float64_hex(final)
            ),
            "paper_measurement_cost": None,
        }
        transaction.stage_json("candidate-result.json", record)
        runtime.ansatz = target
        runtime.energy_hartree = float(selected["energy_hartree"])
        runtime.gradient = target_gradient
        runtime.inverse_hessian = np.asarray(
            selected["final_inverse_hessian"], dtype=np.float64
        )
        runtime.statevector = native_state
        runtime.work = WorkCounters(
            energy_evaluations=(
                2
                + int(primary["optimizer"]["function_evaluations"])
                + (
                    0
                    if fallback is None
                    else int(
                        fallback["optimizer"][
                            "function_evaluations"
                        ]
                    )
                )
                + 2
            ),
            gradient_vector_evaluations=(
                1
                + int(
                    primary["optimizer"][
                        "gradient_vector_evaluations"
                    ]
                )
                + (
                    0
                    if fallback is None
                    else int(
                        fallback["optimizer"][
                            "gradient_vector_evaluations"
                        ]
                    )
                )
                + 1
            ),
            optimizer_iterations=(
                int(primary["optimizer"]["iterations"])
                + (
                    0
                    if fallback is None
                    else int(fallback["optimizer"]["iterations"])
                )
            ),
            statevector_kernels=6 + 4 * int(fallback is not None),
            screening_rounds=1,
            compression_attempts=1,
        )
        runtime.metadata["resource_structure_digest"] = (
            observed_after.structure_digest
        )
        runtime.metadata["classification"] = record["classification"]
        if exploratory.accepted:
            transaction.commit(exploratory)
        else:
            transaction.rollback(
                ";".join(exploratory.rejection_reasons)
            )
        record["transaction_status"] = (
            "committed-isolated-exploratory"
            if exploratory.accepted
            else "rolled-back"
        )
        record["rollback_exact"] = (
            True
            if exploratory.accepted
            else runtime.snapshot().snapshot_digest
            == transaction.snapshot.snapshot_digest
        )
        return record


def build_report(
    execution_freeze: Mapping[str, Any],
    fault_audit: Mapping[str, Any],
    *,
    s6_path: Path = DEFAULT_S6,
    s7_path: Path = DEFAULT_S7,
    s8_1_path: Path = DEFAULT_S8_1,
    model_path: Path = DEFAULT_MODEL,
) -> dict[str, Any]:
    s6 = json.loads(s6_path.read_text(encoding="utf-8"))
    s7 = json.loads(s7_path.read_text(encoding="utf-8"))
    s8_1 = json.loads(s8_1_path.read_text(encoding="utf-8"))
    legacy = json.loads(model_path.read_text(encoding="utf-8"))
    algorithm, pool = _algorithm(CASE)
    source = _structure(s6["target"])
    if s7["source_state_digest"] != s6["target_state_digest"]:
        raise S9CertificationError("S6 and S7 source digests disagree")
    pulled_back = build_pulled_back_model(
        pool, s6, _legacy_primary(legacy)
    )
    source_state = _state_vector(
        algorithm, source.coefficients, source.indices
    )
    source_state_repeat = _state_vector(
        algorithm, source.coefficients, source.indices
    )
    source_energy = float(
        algorithm.evaluate_energy(
            list(source.coefficients), list(source.indices)
        )
    )
    source_energy_repeat = float(
        np.real(
            np.vdot(
                source_state_repeat,
                algorithm.hamiltonian @ source_state_repeat,
            )
        )
    )
    source_gradient = np.asarray(
        algorithm.estimate_gradients(
            list(source.coefficients),
            list(source.indices),
            method="an",
        ),
        dtype=np.float64,
    )
    if (
        abs(source_energy - source_energy_repeat)
        > ENERGY_AGREEMENT_TOLERANCE
        or abs(np.vdot(source_state, source_state_repeat)) ** 2
        < 1.0 - STATE_FIDELITY_TOLERANCE
    ):
        raise S9CertificationError(
            "independent S6 source reconstruction failed"
        )
    candidates = {
        item["candidate_id"]: item for item in s7["candidates"]
    }
    predictions = {
        item["candidate_id"]: float(item["predicted_loss_hartree"])
        for item in s8_1["assessments"]
    }
    results = []
    for ordinal, candidate_id in enumerate(
        execution_freeze["candidate_order"], start=1
    ):
        results.append(
            evaluate_candidate(
                algorithm=algorithm,
                pool=pool,
                source=source,
                source_energy=source_energy,
                source_state=source_state,
                source_gradient=source_gradient,
                pulled_back=pulled_back,
                candidate=candidates[candidate_id],
                predicted_loss_hartree=predictions[candidate_id],
                ordinal=ordinal,
            )
        )
    accepted = [
        item for item in results
        if item["classification"]
        == "EXPLORATORY_NATIVE_RANK2_FEASIBILITY_ACCEPTED"
    ]
    report = {
        "schema_version": "1.0.0",
        "artifact_kind": "v6-s9-native-rank2-top2-certification",
        "runner_version": RUNNER_VERSION,
        "development_only": True,
        "execution_freeze": dict(execution_freeze),
        "fault_audit": dict(fault_audit),
        "source": {
            "state_digest": s6["target_state_digest"],
            "energy_hartree": source_energy,
            "independent_energy_hartree": source_energy_repeat,
            "gradient_infinity": float(
                np.max(np.abs(source_gradient))
            ),
            "parameter_count": len(source.indices),
            "resource_recount": s7["source_recount"],
        },
        "candidate_results": results,
        "summary": {
            "attempted": len(results),
            "exploratory_feasibility_accepted": len(accepted),
            "circuit_primary_accepted": sum(
                item["endpoint_decisions"]["circuit_primary"][
                    "accepted"
                ]
                for item in results
            ),
            "classification": (
                "NATIVE_RANK2_FEASIBLE_WITH_RESOURCE_TRADEOFF"
                if accepted
                else "NATIVE_RANK2_NOT_CERTIFIED"
            ),
            "primary_parent_after_s9": "unchanged-s6-parent",
            "s10_sequential_continuation_authorized": False,
            "next_decision": (
                "native synthesis redesign/resource-only census"
                if accepted
                else "stop current SPARSE_UCRY_RANK2 family"
            ),
        },
        "claim_boundary": (
            "V6-S9 development-only feasibility and predictor diagnostic. "
            "Even an accepted attempt is isolated from primary lineage, "
            "regresses CNOT and CNOT depth under the frozen S7 synthesis, "
            "and is not a V6 primary performance, matched-work, "
            "molecule-general, or paper Measurement Cost result."
        ),
        "paper_measurement_cost": None,
    }
    report["report_digest"] = sha256_hex(report)
    return report


def main() -> None:
    try:
        freeze = build_execution_freeze()
        fault_audit = run_fault_audit()
        report = build_report(freeze, fault_audit)
        atomic_write_new_json(DEFAULT_OUTPUT, report)
    except (
        ImportError,
        KeyError,
        OSError,
        TypeError,
        ValueError,
        S9CertificationError,
    ) as error:
        print(f"V6-S9 certification failed: {error}", file=sys.stderr)
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

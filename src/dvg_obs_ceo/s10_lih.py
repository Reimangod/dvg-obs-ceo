"""Execute the preregistered S10 paired LiH first-accuracy comparison."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import random
import subprocess
import sys
import time
from typing import Any, Mapping, Sequence

from jsonschema import Draft202012Validator
import numpy as np

from .baseline import ROOT, _environment, _load_upstream, _nested_sum, verify_upstream
from .block_ir import block_to_dict, candidate_to_dict, enumerate_candidates, recover_dvg_blocks
from .calibration import (
    embed_block_transformation,
    least_squares_native_coordinates,
    obs_warm_start,
)
from .hessian import HessianCaptureSession, capture_to_dict
from .identity import canonical_json_bytes
from .resources import (
    AnsatzStructure,
    apply_candidate_structure,
    evaluate_full_circuit_resources,
    paper_era_backend,
    resources_to_dict,
)
from .s8_probe import _optimize_target, _state_vector
from .selector import CandidateScore, SelectorConfig, select_candidate
from .telemetry import WorkCounters
from .transaction import (
    AcceptanceCriteria,
    AcceptanceEvidence,
    CompressionRuntime,
    CompressionTransaction,
    OptimizerOutcome,
    RuntimeSnapshot,
    evaluate_acceptance,
)


PROTOCOL_ID = "dvg-obs-s10-lih-paired-protocol-v1.2"
PROTOCOL_TAG = "dvg-obs-s10-lih-primary-protocol-v1.2"
RUNNER_VERSION = "s10-lih-paired-runner-v1.2"
SELECTOR_DIGEST = "09823d0d82b3029ff7f25eeb2d5e22a6208e4029cdcf6ba28365339cf0a62216"
CHEMICAL_ACCURACY_HARTREE = 0.0015936
EXPECTED_ENERGY_HARTREE = -7.797909682469515
EXPECTED_FCI_HARTREE = -7.7988431595024075
EXPECTED_INDICES = (970, 588, 946, 612, 1160, 952, 602, 1154, 940, 618, 1182, 14, 10, 4, 9)
EXPECTED_COUNTS = (2, 5, 8, 11, 15)
SUMMARY_SCHEMA = ROOT / "schemas" / "s10-comparison-summary-v1.schema.json"
REQUIRED_THREAD_ENVIRONMENT = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
}


class S10Error(RuntimeError):
    """Raised when the preregistered LiH comparison cannot be trusted."""


def _sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _git(*arguments: str) -> str:
    return subprocess.check_output(["git", "-C", str(ROOT), *arguments], text=True).strip()


def verify_execution_freeze() -> dict[str, str]:
    """Require execution at the clean commit carrying the preregistered tag."""
    head = _git("rev-parse", "HEAD")
    try:
        tagged = _git("rev-parse", f"{PROTOCOL_TAG}^{{}}")
    except subprocess.CalledProcessError as error:
        raise S10Error(f"missing execution protocol tag: {PROTOCOL_TAG}") from error
    dirty = _git("status", "--porcelain")
    if head != tagged or dirty:
        raise S10Error(
            f"S10 execution must use the clean tagged commit: head={head}, tag={tagged}, dirty={bool(dirty)}"
        )
    config = SelectorConfig()
    if config.digest != SELECTOR_DIGEST:
        raise S10Error("runtime selector digest differs from the frozen S9 selector")
    observed_threads = {
        name: os.environ.get(name) for name in REQUIRED_THREAD_ENVIRONMENT
    }
    if observed_threads != REQUIRED_THREAD_ENVIRONMENT:
        raise S10Error(
            "S10 requires canonical single-thread BLAS environment before process start: "
            + repr(observed_threads)
        )
    return {
        "head": head,
        "protocol_tag": PROTOCOL_TAG,
        "selector_digest": config.digest,
        **REQUIRED_THREAD_ENVIRONMENT,
    }


def _write_exclusive(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    payload = json.dumps(value, indent=2, sort_keys=True, allow_nan=False).encode("utf-8") + b"\n"
    try:
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise S10Error("artifact write made no progress")
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


def _algorithm() -> tuple[Any, Any, float]:
    LinAlgAdapt, DVG_CEO, creators, chemical_accuracy = _load_upstream()
    if float(chemical_accuracy) != CHEMICAL_ACCURACY_HARTREE:
        raise S10Error("pinned upstream chemical-accuracy constant changed")
    _, create_lih = creators
    molecule = create_lih(3.0)
    pool = DVG_CEO(molecule)
    algorithm = LinAlgAdapt(
        pool=pool,
        molecule=molecule,
        verbose=False,
        max_adapt_iter=50,
        max_opt_iter=10000,
        full_opt=True,
        threshold=1e-6,
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
    return algorithm, pool, float(chemical_accuracy)


def _build_checkpoint() -> tuple[Any, Any, AnsatzStructure, dict[str, Any], np.ndarray]:
    started = time.perf_counter()
    random.seed(0)
    np.random.seed(0)
    algorithm, pool, chemical_accuracy = _algorithm()
    adapt_module = importlib.import_module("adaptvqe.algorithms.adapt_vqe")
    algorithm.initialize()
    trajectory: list[dict[str, Any]] = []
    counts: list[int] = []
    with HessianCaptureSession(adapt_module) as capture:
        while algorithm.data.iteration_counter < algorithm.max_adapt_iter:
            previous = int(algorithm.data.iteration_counter)
            finished = bool(algorithm.run_iteration())
            iteration = int(algorithm.data.iteration_counter)
            if iteration == previous:
                raise S10Error("LiH ADAPT iteration made no progress before registered checkpoint")
            error = abs(float(algorithm.energy) - float(algorithm.exact_energy))
            counts.append(len(algorithm.indices))
            trajectory.append({
                "adapt_iteration": iteration,
                "energy_hartree": float(algorithm.energy),
                "absolute_error_hartree": error,
                "parameter_count": len(algorithm.coefficients),
                "finished": finished,
            })
            if error < chemical_accuracy:
                break
            if finished:
                raise S10Error("LiH converged before reaching registered chemical accuracy")
    if not capture.records:
        raise S10Error("LiH checkpoint captured no optimizer Hessian record")
    structure = AnsatzStructure.create(algorithm.indices, algorithm.coefficients, counts)
    if tuple(structure.indices) != EXPECTED_INDICES or tuple(counts) != EXPECTED_COUNTS:
        raise S10Error("LiH first-accuracy ansatz differs from the registered baseline")
    if abs(float(algorithm.energy) - EXPECTED_ENERGY_HARTREE) > 1e-10:
        raise S10Error("LiH first-accuracy energy differs from the registered baseline")
    if abs(float(algorithm.exact_energy) - EXPECTED_FCI_HARTREE) > 1e-10:
        raise S10Error("LiH FCI evaluation oracle differs from the registered problem")
    inverse_hessian = np.asarray(algorithm.inv_hessian, dtype=np.float64)
    gradient = np.asarray(algorithm.gradients, dtype=np.float64)
    last_capture = capture.records[-1]
    if inverse_hessian.shape != (15, 15) or gradient.shape != (15,):
        raise S10Error("LiH checkpoint optimizer state has an invalid dimension")
    if not np.array_equal(inverse_hessian, last_capture.final_inverse_hessian):
        raise S10Error("captured and live recycled inverse Hessians differ")
    independent_energy = float(algorithm.evaluate_energy(list(structure.coefficients), list(structure.indices)))
    if abs(independent_energy - float(algorithm.energy)) > 1e-10:
        raise S10Error("independent LiH checkpoint energy mismatch")
    state = _state_vector(algorithm, structure.coefficients, structure.indices)
    backend = paper_era_backend()
    physical = evaluate_full_circuit_resources(pool, structure, backend)
    structural = evaluate_full_circuit_resources(
        pool, structure, backend, coefficient_policy="deterministic-structural"
    )
    if physical.snapshot != structural.snapshot:
        raise S10Error("baseline physical and structural resource snapshots differ")
    if (physical.snapshot.cnot_count, physical.snapshot.cnot_depth, physical.snapshot.parameter_count) != (107, 30, 15):
        raise S10Error("LiH resource checkpoint differs from registered 107/30/15 baseline")
    checkpoint = {
        "runner_version": RUNNER_VERSION,
        "adapt_iteration": trajectory[-1]["adapt_iteration"],
        "trajectory": trajectory,
        "ansatz_indices": list(structure.indices),
        "ansatz_coefficients": list(structure.coefficients),
        "iteration_counts": list(structure.cumulative_parameter_counts),
        "energy_hartree": float(algorithm.energy),
        "independent_energy_hartree": independent_energy,
        "parameter_count": len(structure.indices),
        "gradient": gradient.tolist(),
        "recycled_inverse_hessian": inverse_hessian.tolist(),
        "hessian_capture": capture_to_dict(last_capture),
        "resources": resources_to_dict(physical),
        "statevector_sha256": hashlib.sha256(np.asarray(state, dtype=">c16").tobytes()).hexdigest(),
        "work": {
            "baseline_optimizer_energy_evaluations": _nested_sum(algorithm.data.evolution.nfevs),
            "baseline_gradient_component_equivalent": _nested_sum(algorithm.data.evolution.ngevs),
            "independent_checkpoint_energy_evaluations": 1,
            "explicit_checkpoint_statevector_kernels": 1,
            "wall_time_seconds": time.perf_counter() - started,
            "paper_measurement_cost": None,
        },
    }
    checkpoint["checkpoint_digest"] = _sha256(checkpoint)
    return algorithm, pool, structure, checkpoint, state


def _runtime(
    structure: AnsatzStructure,
    checkpoint: Mapping[str, Any],
    state: np.ndarray,
) -> CompressionRuntime:
    snapshot = checkpoint["resources"]["snapshot"]
    return CompressionRuntime.create(
        ansatz=structure,
        energy_hartree=float(checkpoint["energy_hartree"]),
        gradient=checkpoint["gradient"],
        inverse_hessian=checkpoint["recycled_inverse_hessian"],
        statevector=state,
        work=WorkCounters(
            energy_evaluations=int(checkpoint["work"]["baseline_optimizer_energy_evaluations"]) + 1,
            gradient_component_evaluations=int(checkpoint["work"]["baseline_gradient_component_equivalent"]),
            statevector_kernels=1,
        ),
        adapt_iteration=int(checkpoint["adapt_iteration"]),
        metadata={
            "run_id": "s10-lih-3a-first-accuracy",
            "resource_structure_digest": snapshot["structure_digest"],
            "budget_reference_energy_hartree": float(checkpoint["energy_hartree"]),
            "selector_digest": SELECTOR_DIGEST,
        },
    )


def _prepare_candidates(
    algorithm: Any,
    pool: Any,
    source: AnsatzStructure,
    checkpoint: Mapping[str, Any],
) -> tuple[list[CandidateScore], dict[str, dict[str, Any]], list[dict[str, Any]]]:
    backend = paper_era_backend()
    before = evaluate_full_circuit_resources(
        pool, source, backend, coefficient_policy="deterministic-structural"
    )
    blocks = recover_dvg_blocks(
        pool, source.indices, source.coefficients, source.cumulative_parameter_counts
    )
    block_by_id = {block.block_id: block for block in blocks}
    representatives: dict[str, Any] = {}
    catalog: list[dict[str, Any]] = []
    for candidate in enumerate_candidates(pool, blocks):
        representatives.setdefault(candidate.equivalence_class_id, candidate)
        catalog.append(candidate_to_dict(candidate))
    scores: list[CandidateScore] = []
    prepared: dict[str, dict[str, Any]] = {}
    theta = np.asarray(source.coefficients, dtype=np.float64)
    gradient = np.asarray(checkpoint["gradient"], dtype=np.float64)
    inverse = np.asarray(checkpoint["recycled_inverse_hessian"], dtype=np.float64)
    hessian_usable = bool(checkpoint["hessian_capture"]["quality"]["numerically_usable"])
    for candidate in representatives.values():
        block = block_by_id[candidate.source_block_id]
        embedded = embed_block_transformation(len(source.indices), block, candidate)
        coordinates, target_inverse, prediction = obs_warm_start(
            theta, gradient, inverse, embedded.transformation
        )
        local = coordinates[embedded.local_target_slice]
        target = apply_candidate_structure(pool, source, candidate, local)
        after = evaluate_full_circuit_resources(
            pool, target, backend, coefficient_policy="deterministic-structural"
        )
        score = CandidateScore(
            candidate.candidate_id,
            candidate.equivalence_class_id,
            candidate.kind,
            candidate.target_family,
            float(prediction.predicted_change_from_current),
            float(checkpoint["energy_hartree"]),
            float(checkpoint["energy_hartree"]),
            before.snapshot,
            after.snapshot,
            hessian_usable,
            True,
            True,
        )
        scores.append(score)
        prepared[candidate.candidate_id] = {
            "candidate": candidate,
            "block": block,
            "embedded": embedded,
            "projection_on": coordinates,
            "projection_off": least_squares_native_coordinates(theta, embedded.transformation),
            "target_inverse_hessian": target_inverse,
            "predicted_change_hartree": float(prediction.predicted_change_from_current),
            "structural_resources": after,
        }
    return scores, prepared, catalog


def _optimizer_outcome(path: Mapping[str, Any]) -> OptimizerOutcome:
    optimizer = path["optimizer"]
    return OptimizerOutcome(
        bool(optimizer["success"]), str(optimizer["status"]), str(optimizer["message"]), True
    )


def _work_for_paths(base: WorkCounters, paths: Sequence[Mapping[str, Any]], dimensions: Sequence[int]) -> WorkCounters:
    nfev = sum(int(path["optimizer"]["function_evaluations"]) + 1 for path in paths)
    njev = sum(int(path["optimizer"]["gradient_vector_evaluations"]) + (1 if dimension else 0) for path, dimension in zip(paths, dimensions))
    components = sum(
        (int(path["optimizer"]["gradient_vector_evaluations"]) + (1 if dimension else 0)) * dimension
        for path, dimension in zip(paths, dimensions)
    )
    return WorkCounters(
        energy_evaluations=base.energy_evaluations + nfev,
        gradient_vector_evaluations=base.gradient_vector_evaluations + njev,
        gradient_component_evaluations=base.gradient_component_evaluations + components,
        optimizer_iterations=base.optimizer_iterations + sum(int(path["optimizer"]["iterations"]) for path in paths),
        statevector_kernels=base.statevector_kernels + 1 + 2 * len(paths),
        screening_rounds=base.screening_rounds,
        compression_attempts=base.compression_attempts + 1,
    )


def _execute_selected(
    algorithm: Any,
    pool: Any,
    source: AnsatzStructure,
    checkpoint: Mapping[str, Any],
    source_state: np.ndarray,
    runtime: CompressionRuntime,
    prepared: Mapping[str, Any],
    transaction_root: Path,
    candidate_id: str,
) -> dict[str, Any]:
    item = prepared[candidate_id]
    candidate = item["candidate"]
    embedded = item["embedded"]
    backend = paper_era_backend()
    with CompressionTransaction(
        runtime, transaction_root, transaction_id="s10-primary-round-1"
    ) as transaction:
        paths: list[dict[str, Any]] = []
        primary_structure = apply_candidate_structure(
            pool, source, candidate, item["projection_on"][embedded.local_target_slice]
        )
        primary = _optimize_target(
            algorithm,
            primary_structure.indices,
            item["projection_on"],
            item["target_inverse_hessian"],
            source_state,
        )
        paths.append(primary)
        fallback: dict[str, Any] | None = None
        selected_path = primary
        initial_kind = "projection_on"
        if not bool(primary["optimizer"]["success"]):
            fallback_structure = apply_candidate_structure(
                pool, source, candidate, item["projection_off"][embedded.local_target_slice]
            )
            fallback = _optimize_target(
                algorithm,
                fallback_structure.indices,
                item["projection_off"],
                item["target_inverse_hessian"],
                source_state,
            )
            paths.append(fallback)
            selected_path = fallback
            initial_kind = "projection_off_fallback"
        coordinates = np.asarray(selected_path["coordinates"], dtype=np.float64)
        local = coordinates[embedded.local_target_slice]
        final_structure = apply_candidate_structure(pool, source, candidate, local)
        final_structure = AnsatzStructure.create(
            final_structure.indices, coordinates, final_structure.cumulative_parameter_counts
        )
        physical = evaluate_full_circuit_resources(pool, final_structure, backend)
        structural = evaluate_full_circuit_resources(
            pool, final_structure, backend, coefficient_policy="deterministic-structural"
        )
        source_theta = embedded.transformation.offset + embedded.transformation.jacobian @ coordinates
        residual = (
            float(np.max(np.abs(embedded.transformation.constraint_matrix @ source_theta - embedded.transformation.constraint_rhs)))
            if embedded.transformation.constraint_matrix.shape[0]
            else 0.0
        )
        final_state = _state_vector(algorithm, coordinates, final_structure.indices)
        runtime.ansatz = final_structure
        runtime.energy_hartree = float(selected_path["energy_hartree"])
        runtime.gradient = np.asarray(selected_path["gradient"], dtype=np.float64)
        runtime.inverse_hessian = np.asarray(selected_path["final_inverse_hessian"], dtype=np.float64)
        runtime.statevector = final_state
        runtime.work = _work_for_paths(runtime.work, paths, [len(path["coordinates"]) for path in paths])
        runtime.metadata["resource_structure_digest"] = physical.snapshot.structure_digest
        runtime.metadata["candidate_id"] = candidate_id
        primary_outcome = _optimizer_outcome(primary)
        fallback_outcome = None if fallback is None else _optimizer_outcome(fallback)
        evidence = AcceptanceEvidence(
            source_energy_hartree=float(checkpoint["energy_hartree"]),
            budget_reference_energy_hartree=float(checkpoint["energy_hartree"]),
            candidate_energy_hartree=float(selected_path["energy_hartree"]),
            independent_energy_hartree=float(selected_path["independent_energy_hartree"]),
            independent_state_fidelity=float(selected_path["independent_state_recomputation_fidelity"]),
            constraint_residual=residual,
            kkt_residual=float(selected_path["gradient_infinity"]),
            before_resources=item["score"].before_resources,
            after_resources=physical.snapshot,
            full_resource_recount_succeeded=physical.snapshot == structural.snapshot,
            transformation_semantics_validated=True,
            primary_optimizer=primary_outcome,
            fallback_optimizer=fallback_outcome,
        )
        decision = evaluate_acceptance(evidence, AcceptanceCriteria())
        record = {
            "candidate": candidate_to_dict(candidate),
            "source_block": block_to_dict(item["block"]),
            "selected_optimizer_path": initial_kind,
            "primary": primary,
            "fallback": fallback,
            "constraint_residual_infinity": residual,
            "physical_resources": resources_to_dict(physical),
            "structural_resources": resources_to_dict(structural),
            "acceptance": asdict(decision),
            "work_after_attempt": asdict(runtime.work),
            "paper_measurement_cost": None,
        }
        transaction.stage_json("trial.json", record)
        if decision.accepted:
            location = transaction.commit(decision)
            status = "accepted"
        else:
            location = transaction.rollback(";".join(decision.rejection_reasons))
            status = "rolled-back"
    record["transaction_status"] = status
    record["transaction_path"] = str(location.relative_to(transaction_root.parent))
    return record


def validate_summary(summary: Mapping[str, Any]) -> None:
    schema = json.loads(SUMMARY_SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    errors = sorted(Draft202012Validator(schema).iter_errors(dict(summary)), key=lambda error: list(error.path))
    if errors:
        raise S10Error("S10 summary schema failed: " + "; ".join(error.message for error in errors))
    clone = summary["clone_audit"]
    digests = (
        clone["source_snapshot_digest"],
        clone["no_pruning_snapshot_digest"],
        clone["v2_snapshot_digest"],
    )
    if any(
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
        for value in digests
    ) or len(set(digests)) != 1:
        raise S10Error("S10 paired clone digest audit failed")
    if summary["selector_digest"] != SELECTOR_DIGEST:
        raise S10Error("S10 summary selector digest is not frozen S9")
    if summary["offline_evaluation"].get("used_by_runtime_selector_or_acceptance") is not False:
        raise S10Error("S10 FCI leakage guard failed")
    selection = summary["selection"]
    result = summary["dvg_obs_ceo"]
    if result["status"] == "no-selection":
        if selection["chosen_candidate_id"] is not None or result["accepted"]:
            raise S10Error("S10 no-selection semantics are inconsistent")
        if result["energy_hartree"] != summary["no_pruning"]["energy_hartree"]:
            raise S10Error("S10 no-selection branch changed the energy")
    elif selection["chosen_candidate_id"] is None:
        raise S10Error("S10 trial result lacks a selected candidate")


def run(bundle: Path) -> dict[str, Any]:
    freeze = verify_execution_freeze()
    provenance = verify_upstream()
    if bundle.exists():
        raise FileExistsError(f"refusing to overwrite S10 bundle: {bundle}")
    staging = bundle.with_name(f".{bundle.name}.staging")
    if staging.exists():
        raise FileExistsError(f"orphan S10 staging requires manual audit: {staging}")
    staging.mkdir(parents=True)
    _fsync_directory(staging.parent)
    algorithm, pool, source, checkpoint, source_state = _build_checkpoint()
    _write_exclusive(staging / "checkpoint.json", checkpoint)
    runtime = _runtime(source, checkpoint, source_state)
    source_snapshot = runtime.snapshot()
    no_pruning_clone = RuntimeSnapshot.from_dict(source_snapshot.to_dict())
    v2_clone = RuntimeSnapshot.from_dict(source_snapshot.to_dict())
    clone_exact = source_snapshot.snapshot_digest == no_pruning_clone.snapshot_digest == v2_clone.snapshot_digest
    if not clone_exact:
        raise S10Error("paired branches are not exact checkpoint clones")
    screening_started = time.perf_counter()
    scores, prepared, catalog = _prepare_candidates(algorithm, pool, source, checkpoint)
    screening_wall_time = time.perf_counter() - screening_started
    runtime.work = WorkCounters(
        **{
            **asdict(runtime.work),
            "screening_rounds": runtime.work.screening_rounds + 1,
        }
    )
    for score in scores:
        prepared[score.candidate_id]["score"] = score
    decision = select_candidate(scores)
    _write_exclusive(staging / "candidate-catalog.json", catalog)
    _write_exclusive(staging / "selector-decision.json", asdict(decision))
    chosen = decision.chosen_candidate_id
    trial = None
    if chosen is not None:
        trial = _execute_selected(
            algorithm, pool, source, checkpoint, source_state, runtime,
            prepared, staging / "transactions", chosen,
        )
        _write_exclusive(staging / "selected-trial.json", trial)
    accepted = bool(trial is not None and trial["transaction_status"] == "accepted")
    status = "no-selection" if chosen is None else trial["transaction_status"]
    final_resources = (
        checkpoint["resources"] if not accepted else trial["physical_resources"]
    )
    no_pruning = {
        "snapshot_digest": no_pruning_clone.snapshot_digest,
        "energy_hartree": float(checkpoint["energy_hartree"]),
        "resources": checkpoint["resources"],
    }
    v2_energy = float(runtime.energy_hartree)
    fci = EXPECTED_FCI_HARTREE
    summary = {
        "schema_version": "1.0.0",
        "artifact_kind": "s10-lih-first-accuracy-paired-comparison",
        "run_id": "s10-lih-3a-first-accuracy-primary-v1",
        "protocol_id": PROTOCOL_ID,
        "execution_freeze": freeze,
        "upstream": provenance,
        "environment": _environment(),
        "selector_digest": SELECTOR_DIGEST,
        "checkpoint": {
            "checkpoint_digest": checkpoint["checkpoint_digest"],
            "adapt_iteration": checkpoint["adapt_iteration"],
            "energy_hartree": checkpoint["energy_hartree"],
            "parameter_count": checkpoint["parameter_count"],
            "resources": checkpoint["resources"],
        },
        "clone_audit": {
            "exact": clone_exact,
            "source_snapshot_digest": source_snapshot.snapshot_digest,
            "no_pruning_snapshot_digest": no_pruning_clone.snapshot_digest,
            "v2_snapshot_digest": v2_clone.snapshot_digest,
        },
        "selection": {
            "candidate_count": len(scores),
            "eligible_count": sum(assessment.eligible for assessment in decision.assessments),
            "chosen_candidate_id": chosen,
            "decision": asdict(decision),
        },
        "no_pruning": no_pruning,
        "dvg_obs_ceo": {
            "status": status,
            "accepted": accepted,
            "energy_hartree": v2_energy,
            "resources": final_resources,
            "trial": trial,
        },
        "work": {
            "checkpoint": checkpoint["work"],
            "final_runtime_counters": asdict(runtime.work),
            "screened_candidates": len(scores),
            "screening_wall_time_seconds": screening_wall_time,
            "optimized_candidates": 0 if chosen is None else 1,
            "fallback_attempts": int(bool(trial and trial["fallback"] is not None)),
            "paper_measurement_cost": None,
        },
        "offline_evaluation": {
            "fci_energy_hartree": fci,
            "no_pruning_absolute_error_hartree": abs(float(checkpoint["energy_hartree"]) - fci),
            "v2_absolute_error_hartree": abs(v2_energy - fci),
            "chemical_accuracy_hartree": CHEMICAL_ACCURACY_HARTREE,
            "no_pruning_within_chemical_accuracy": abs(float(checkpoint["energy_hartree"]) - fci) < CHEMICAL_ACCURACY_HARTREE,
            "v2_within_chemical_accuracy": abs(v2_energy - fci) < CHEMICAL_ACCURACY_HARTREE,
            "used_by_runtime_selector_or_acceptance": False,
            "used_to_define_shared_first_accuracy_checkpoint": True,
        },
        "paper_measurement_cost": None,
        "claim_boundary": [
            "LiH is non-blind because its baseline was observed before this protocol.",
            "FCI defines the shared checkpoint and offline error, but is absent from pruning selector and acceptance inputs.",
            "The primary comparison optimizes at most one frozen-selector candidate.",
            "No-selection and rollback are valid outcomes and do not trigger retuning.",
            "Work counters are not paper-equivalent measurement cost.",
        ],
    }
    validate_summary(summary)
    _write_exclusive(staging / "summary.json", summary)
    _fsync_directory(staging)
    os.replace(staging, bundle)
    _fsync_directory(bundle.parent)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    arguments = parser.parse_args()
    sys.argv[:] = [sys.argv[0]]
    summary = run(arguments.bundle)
    print(json.dumps({
        "bundle": str(arguments.bundle),
        "status": summary["dvg_obs_ceo"]["status"],
        "chosen": summary["selection"]["chosen_candidate_id"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()

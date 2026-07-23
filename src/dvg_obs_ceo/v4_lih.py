"""Execute frozen V4 Global OBS on the stored LiH 3 Angstrom checkpoint."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
import random
import subprocess
import time
from typing import Any, Mapping, Sequence

import numpy as np

from .baseline import ROOT, _environment, verify_upstream
from .block_ir import candidate_to_dict, enumerate_candidates, recover_dvg_blocks
from .calibration import least_squares_native_coordinates
from .composition import compose_registered_candidates
from .global_selector import GlobalResourceCandidate, select_global_candidates
from .identity import canonical_json_bytes
from .joint_prediction import (
    JointQualityPolicy,
    evaluate_joint_quality,
    joint_obs_prediction,
    secant_pairs_from_capture,
)
from .resources import AnsatzStructure, evaluate_full_circuit_resources, paper_era_backend, resources_to_dict
from .s8_probe import OPTIMIZER_G_TOL, OPTIMIZER_MAX_ITERATIONS, _optimize_target, _state_vector
from .s10_lih import _algorithm as _lih_algorithm
from .search import SearchCandidate, SearchConfig, SearchEvaluation, deterministic_search
from .stationarity import GradientAgreementPolicy, audit_gradient_paths
from .telemetry import WorkCounters
from .transaction import (
    AcceptanceCriteria,
    AcceptanceEvidence,
    CompressionRuntime,
    CompressionTransaction,
    OptimizerOutcome,
    evaluate_acceptance,
)
from .v3_protocol import _write_exclusive


PROTOCOL_TAG = "dvg-obs-v4-s7-lih-v1.2"
CONFIG_PATH = ROOT / "manifests" / "v4-s6-frozen-config-v1.json"
CHECKPOINT_PATH = ROOT / "artifacts" / "s10" / "lih-3a-first-accuracy-primary-v1-2" / "checkpoint.json"
EXPECTED_CHECKPOINT_SHA256 = "1ef38be983595fdb094f2a47287e6047193351e0eff4a7c589630ef023ad98eb"
REQUIRED_THREADS = {"OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}


class V4LiHError(RuntimeError):
    """Raised when the frozen LiH development experiment cannot be trusted."""


def _git(*arguments: str) -> str:
    return subprocess.check_output(["git", "-C", str(ROOT), *arguments], text=True).strip()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_value(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def verify_execution_freeze() -> tuple[dict[str, Any], dict[str, Any]]:
    head = _git("rev-parse", "HEAD")
    tagged = _git("rev-parse", f"{PROTOCOL_TAG}^{{}}")
    dirty = _git("status", "--porcelain")
    threads = {name: os.environ.get(name) for name in REQUIRED_THREADS}
    manifest = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    digest = _sha256_value(manifest["configuration"])
    if (
        head != tagged or dirty or threads != REQUIRED_THREADS
        or digest != manifest["configuration_digest"]
        or _sha256_file(CHECKPOINT_PATH) != EXPECTED_CHECKPOINT_SHA256
    ):
        raise V4LiHError(
            f"V4-S7 freeze failed: head={head}, tag={tagged}, dirty={bool(dirty)}, "
            f"threads={threads}, config={digest}, checkpoint={_sha256_file(CHECKPOINT_PATH)}"
        )
    return {
        "head": head, "protocol_tag": PROTOCOL_TAG, "threads": threads,
        "configuration_digest": digest, "checkpoint_sha256": EXPECTED_CHECKPOINT_SHA256,
    }, manifest


def _source_runtime(
    source: AnsatzStructure,
    checkpoint: Mapping[str, Any],
    source_state: np.ndarray,
    configuration_digest: str,
    *,
    run_id: str = "v4-lih-3a-stored-first-accuracy",
) -> CompressionRuntime:
    snapshot = checkpoint["resources"]["snapshot"]
    work = checkpoint["work"]
    return CompressionRuntime.create(
        ansatz=source,
        energy_hartree=checkpoint["energy_hartree"],
        gradient=checkpoint["gradient"],
        inverse_hessian=checkpoint["recycled_inverse_hessian"],
        statevector=source_state,
        work=WorkCounters(
            energy_evaluations=int(work["baseline_optimizer_energy_evaluations"]) + 1,
            gradient_component_evaluations=int(work["baseline_gradient_component_equivalent"]),
            statevector_kernels=1,
        ),
        adapt_iteration=int(checkpoint["adapt_iteration"]),
        metadata={
            "run_id": run_id,
            "resource_structure_digest": snapshot["structure_digest"],
            "budget_reference_energy_hartree": float(checkpoint["energy_hartree"]),
            "configuration_digest": configuration_digest,
        },
    )


def _gradient(algorithm: Any, coordinates: np.ndarray, indices: Sequence[int]) -> np.ndarray:
    if not len(indices):
        return np.zeros(0, dtype=np.float64)
    return np.asarray(algorithm.estimate_gradients(list(coordinates), list(indices), method="an"), dtype=np.float64)


def _energy(algorithm: Any, coordinates: np.ndarray, indices: Sequence[int]) -> float:
    return float(algorithm.evaluate_energy(list(coordinates), list(indices)))


def _optimizer_outcome(path: Mapping[str, Any]) -> OptimizerOutcome:
    optimizer = path["optimizer"]
    return OptimizerOutcome(bool(optimizer["success"]), str(optimizer["status"]), str(optimizer["message"]), True)


def _strict_json_quality(quality: Mapping[str, Any], *, held_out_required: bool) -> dict[str, Any]:
    result = dict(quality)
    result["policy"] = dict(quality["policy"])
    if not held_out_required:
        result["policy"]["maximum_held_out_projected_residual"] = None
    # Fail here, close to the boundary, instead of after expensive transactions.
    json.dumps(result, allow_nan=False)
    return result


def _attempt_work(
    base: WorkCounters,
    paths: Sequence[Mapping[str, Any]],
    target_dimension: int,
    source_dimension: int,
) -> WorkCounters:
    optimizer_energy = sum(int(path["optimizer"]["function_evaluations"]) + 1 for path in paths)
    optimizer_gradients = sum(
        int(path["optimizer"]["gradient_vector_evaluations"]) + (1 if target_dimension else 0)
        for path in paths
    )
    return WorkCounters(
        energy_evaluations=base.energy_evaluations + optimizer_energy + 2,
        gradient_vector_evaluations=base.gradient_vector_evaluations + optimizer_gradients + 2,
        gradient_component_evaluations=(
            base.gradient_component_evaluations
            + optimizer_gradients * target_dimension + target_dimension + source_dimension
        ),
        optimizer_iterations=base.optimizer_iterations + sum(int(path["optimizer"]["iterations"]) for path in paths),
        statevector_kernels=base.statevector_kernels + 2 * len(paths) + 3,
        screening_rounds=base.screening_rounds + 1,
        compression_attempts=base.compression_attempts + 1,
    )


def _execute_attempt(
    *,
    attempt_number: int,
    algorithm: Any,
    pool: Any,
    source: AnsatzStructure,
    checkpoint: Mapping[str, Any],
    source_state: np.ndarray,
    source_resources: Any,
    plan: Any,
    prediction: Mapping[str, Any],
    transaction_root: Path,
    configuration_digest: str,
    run_id: str = "v4-lih-3a-stored-first-accuracy",
    transaction_prefix: str = "v4-lih-attempt",
    cumulative_energy_budget_hartree: float = 1e-4,
) -> dict[str, Any]:
    runtime = _source_runtime(
        source, checkpoint, source_state, configuration_digest, run_id=run_id
    )
    before_digest = runtime.snapshot().snapshot_digest
    initial = np.asarray(prediction["target_native_coordinates"], dtype=np.float64)
    initial_inverse = np.asarray(prediction["target_inverse_hessian"], dtype=np.float64)
    target_indices = plan.target_indices
    fallback_initial = least_squares_native_coordinates(
        np.asarray(source.coefficients, dtype=np.float64), plan.transformation
    )
    transaction_id = f"{transaction_prefix}-{attempt_number:02d}-{plan.state.constraint_semantic_id[-12:]}"
    with CompressionTransaction(runtime, transaction_root, transaction_id=transaction_id) as transaction:
        primary = _optimize_target(algorithm, target_indices, initial, initial_inverse, source_state)
        fallback = None
        selected = primary
        selected_path = "joint-target-native-obs"
        if not primary["optimizer"]["success"]:
            fallback = _optimize_target(
                algorithm, target_indices, fallback_initial, initial_inverse, source_state
            )
            selected = fallback
            selected_path = "least-squares-native-fallback"
        coordinates = np.asarray(selected["coordinates"], dtype=np.float64)
        target = AnsatzStructure.create(target_indices, coordinates, plan.target_iteration_counts)
        physical = evaluate_full_circuit_resources(pool, target, paper_era_backend())
        structural = evaluate_full_circuit_resources(
            pool, target, paper_era_backend(), coefficient_policy="deterministic-structural"
        )
        certificate = audit_gradient_paths(
            coordinates,
            plan.transformation,
            lambda value: _gradient(algorithm, value, target_indices),
            lambda value: _gradient(algorithm, value, source.indices),
            target_state=lambda value: _state_vector(algorithm, value, target_indices),
            source_state=lambda value: _state_vector(algorithm, value, source.indices),
            target_energy=lambda value: _energy(algorithm, value, target_indices),
            source_energy=lambda value: _energy(algorithm, value, source.indices),
            policy=GradientAgreementPolicy(),
        )
        mapped = plan.transformation.offset + plan.transformation.jacobian @ coordinates
        residual = float(np.max(np.abs(plan.transformation.constraint_matrix @ mapped - plan.transformation.constraint_rhs)))
        final_state = _state_vector(algorithm, coordinates, target_indices)
        runtime.ansatz = target
        runtime.energy_hartree = float(selected["energy_hartree"])
        runtime.gradient = np.asarray(selected["gradient"], dtype=np.float64)
        runtime.inverse_hessian = np.asarray(selected["final_inverse_hessian"], dtype=np.float64)
        runtime.statevector = final_state
        runtime.work = _attempt_work(
            runtime.work,
            [primary] if fallback is None else [primary, fallback],
            len(target_indices),
            len(source.indices),
        )
        runtime.metadata["resource_structure_digest"] = physical.snapshot.structure_digest
        runtime.metadata["constraint_semantic_id"] = plan.state.constraint_semantic_id
        criteria = AcceptanceCriteria(
            cumulative_energy_budget_hartree=cumulative_energy_budget_hartree,
            guard_logical_block_count=False,
        )
        semantics_valid = bool(
            certificate["passed"]
            and certificate["source_target_state_fidelity"] >= criteria.minimum_state_fidelity
            and certificate["source_target_energy_difference_hartree"] <= criteria.independent_energy_tolerance_hartree
        )
        evidence = AcceptanceEvidence(
            source_energy_hartree=float(checkpoint["energy_hartree"]),
            budget_reference_energy_hartree=float(checkpoint["energy_hartree"]),
            candidate_energy_hartree=float(selected["energy_hartree"]),
            independent_energy_hartree=float(selected["independent_energy_hartree"]),
            independent_state_fidelity=float(selected["independent_state_recomputation_fidelity"]),
            constraint_residual=residual,
            kkt_residual=float(selected["gradient_infinity"]),
            before_resources=source_resources.snapshot,
            after_resources=physical.snapshot,
            full_resource_recount_succeeded=physical.snapshot == structural.snapshot,
            transformation_semantics_validated=semantics_valid,
            primary_optimizer=_optimizer_outcome(primary),
            fallback_optimizer=None if fallback is None else _optimizer_outcome(fallback),
        )
        decision = evaluate_acceptance(evidence, criteria)
        record = {
            "attempt_number": attempt_number,
            "candidate_ids": list(plan.candidate_ids),
            "constraint_semantic_id": plan.state.constraint_semantic_id,
            "constraint_numerical_id": plan.state.constraint_numerical_id,
            "before_snapshot_digest": before_digest,
            "selected_optimizer_path": selected_path,
            "primary": primary,
            "fallback": fallback,
            "two_path_certificate": certificate,
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
    record["after_rollback_snapshot_digest"] = runtime.snapshot().snapshot_digest
    record["rollback_exact"] = status == "accepted" or runtime.snapshot().snapshot_digest == before_digest
    return record


def run(bundle: Path) -> dict[str, Any]:
    freeze, manifest = verify_execution_freeze()
    if bundle.exists():
        raise FileExistsError(f"refusing to overwrite V4 LiH bundle: {bundle}")
    staging = bundle.with_name(f".{bundle.name}.staging")
    if staging.exists():
        raise FileExistsError(f"orphan V4 LiH staging requires audit: {staging}")
    staging.mkdir(parents=True)
    _fsync_directory(staging.parent)
    random.seed(0)
    np.random.seed(0)
    checkpoint = json.loads(CHECKPOINT_PATH.read_text(encoding="utf-8"))
    stored_digest = checkpoint.pop("checkpoint_digest")
    if _sha256_value(checkpoint) != stored_digest:
        raise V4LiHError("stored checkpoint internal digest mismatch")
    checkpoint["checkpoint_digest"] = stored_digest
    algorithm, pool, _ = _lih_algorithm()
    algorithm.initialize()
    source = AnsatzStructure.create(
        checkpoint["ansatz_indices"], checkpoint["ansatz_coefficients"], checkpoint["iteration_counts"]
    )
    source_state = _state_vector(algorithm, source.coefficients, source.indices)
    state_digest = hashlib.sha256(np.asarray(source_state, dtype=">c16").tobytes()).hexdigest()
    independent_source_energy = _energy(algorithm, np.asarray(source.coefficients), source.indices)
    if state_digest != checkpoint["statevector_sha256"] or abs(independent_source_energy - checkpoint["energy_hartree"]) > 1e-10:
        raise V4LiHError("stored checkpoint independent reconstruction failed")
    backend = paper_era_backend()
    source_resources = evaluate_full_circuit_resources(pool, source, backend)
    if asdict(source_resources.snapshot) != checkpoint["resources"]["snapshot"]:
        raise V4LiHError("stored checkpoint resource reconstruction failed")
    blocks = recover_dvg_blocks(pool, source.indices, source.coefficients, source.cumulative_parameter_counts)
    representatives: dict[str, Any] = {}
    for candidate in enumerate_candidates(pool, blocks):
        representatives.setdefault(candidate.equivalence_class_id, candidate)
    by_id = {candidate.candidate_id: candidate for candidate in representatives.values()}
    search_candidates = tuple(SearchCandidate(candidate.candidate_id, candidate.source_block_id) for candidate in by_id.values())
    internal = secant_pairs_from_capture(checkpoint["hessian_capture"]["secant_pairs"], required_source="internal-bfgs")
    prediction_cache: dict[tuple[str, ...], tuple[Any, dict[str, Any], dict[str, Any]]] = {}
    quality_record = manifest["configuration"]["quality_policy"]
    quality_policy = JointQualityPolicy(
        maximum_constraint_schur_condition_number=quality_record["maximum_constraint_schur_condition_number"],
        maximum_target_hessian_condition_number=quality_record["maximum_target_hessian_condition_number"],
        minimum_constraint_direction_coverage=quality_record["minimum_constraint_direction_coverage"],
        maximum_internal_projected_residual=quality_record["maximum_internal_projected_residual"],
        maximum_held_out_projected_residual=math.inf,
        require_held_out_evidence=quality_record["require_held_out_evidence"],
    )

    def predict(candidate_ids: tuple[str, ...]) -> tuple[Any, dict[str, Any], dict[str, Any]]:
        key = tuple(sorted(candidate_ids))
        if key not in prediction_cache:
            plan = compose_registered_candidates(source, blocks, tuple(by_id[value] for value in key))
            prediction = joint_obs_prediction(
                checkpoint["ansatz_coefficients"], checkpoint["gradient"],
                checkpoint["recycled_inverse_hessian"], plan.transformation,
                internal_pairs=internal, held_out_pairs=(),
            )
            quality = _strict_json_quality(
                evaluate_joint_quality(prediction, quality_policy),
                held_out_required=quality_policy.require_held_out_evidence,
            )
            prediction_cache[key] = (plan, prediction, quality)
        return prediction_cache[key]

    def evaluator(candidate_ids: tuple[str, ...]) -> SearchEvaluation:
        try:
            plan, prediction, _ = predict(candidate_ids)
        except Exception as error:
            return SearchEvaluation("candidate-numerical-failure", None, None, None, reason=repr(error))
        return SearchEvaluation(
            "valid", plan.state.constraint_semantic_id, plan.state.constraint_numerical_id,
            float(prediction["predicted_change_from_current_hartree"]),
        )

    config = manifest["configuration"]
    if (
        config["optimizer"]["maximum_iterations_per_path"] != OPTIMIZER_MAX_ITERATIONS
        or config["optimizer"]["gradient_tolerance"] != OPTIMIZER_G_TOL
    ):
        raise V4LiHError("runtime optimizer constants differ from the frozen configuration")
    search_budget = config["search_budgets"]
    search = deterministic_search(
        search_candidates, evaluator,
        SearchConfig(
            config["screening_budget_hartree"], search_budget["maximum_expanded_nodes"],
            search_budget["maximum_completed_states"], search_budget["maximum_quadratic_solves"],
        ),
    )
    eligible_records = [record for record in search["records"] if record["eligible"]]
    resource_candidates: list[GlobalResourceCandidate] = []
    plan_by_semantic: dict[str, tuple[Any, dict[str, Any], dict[str, Any]]] = {}
    resource_failures: list[dict[str, Any]] = []
    for record in eligible_records[: search_budget["maximum_full_resource_recounts"]]:
        candidate_ids = tuple(record["candidate_ids"])
        plan, prediction, quality = predict(candidate_ids)
        if not quality["passed"]:
            continue
        try:
            target = AnsatzStructure.create(plan.target_indices, [1.0] * len(plan.target_indices), plan.target_iteration_counts)
            resources = evaluate_full_circuit_resources(pool, target, backend, coefficient_policy="deterministic-structural")
        except Exception as error:
            resource_failures.append({"candidate_ids": list(candidate_ids), "error": repr(error)})
            continue
        resource_candidates.append(GlobalResourceCandidate(
            candidate_ids, plan.state.constraint_semantic_id, plan.state.constraint_numerical_id,
            float(prediction["predicted_change_from_current_hartree"]), resources.snapshot,
        ))
        plan_by_semantic[plan.state.constraint_semantic_id] = (plan, prediction, quality)
    if len(eligible_records) > search_budget["maximum_full_resource_recounts"]:
        raise V4LiHError("full-resource recount deterministic budget exceeded")
    selection = select_global_candidates(
        resource_candidates, source_resources.snapshot,
        screening_budget_hartree=config["screening_budget_hartree"],
        top_k_per_endpoint=config["exact_vqe_budget"]["top_k_per_endpoint"],
        maximum_unique_attempts=config["exact_vqe_budget"]["maximum_unique_exact_attempts"],
    )
    attempts: list[dict[str, Any]] = []
    for number, semantic_id in enumerate(selection["unique_attempt_semantic_ids"], 1):
        plan, prediction, quality = plan_by_semantic[semantic_id]
        attempt = _execute_attempt(
            attempt_number=number, algorithm=algorithm, pool=pool, source=source,
            checkpoint=checkpoint, source_state=source_state, source_resources=source_resources,
            plan=plan, prediction=prediction, transaction_root=staging / "transactions",
            configuration_digest=manifest["configuration_digest"],
        )
        attempt["quality"] = quality
        attempt["prediction"] = prediction
        attempts.append(attempt)
    attempt_by_semantic = {item["constraint_semantic_id"]: item for item in attempts}

    def winner(endpoint: str) -> str | None:
        return next((semantic_id for semantic_id in selection[endpoint] if attempt_by_semantic[semantic_id]["transaction_status"] == "accepted"), None)

    summary = {
        "schema_version": "1.0.0",
        "artifact_kind": "v4-s7-lih-development",
        "execution_freeze": freeze,
        "upstream": verify_upstream(),
        "environment": _environment(),
        "checkpoint": {
            "path": str(CHECKPOINT_PATH.relative_to(ROOT)), "checkpoint_digest": stored_digest,
            "energy_hartree": checkpoint["energy_hartree"], "resources": checkpoint["resources"],
            "independent_reconstruction_energy_hartree": independent_source_energy,
            "statevector_sha256": state_digest,
        },
        "catalog": {
            "block_count": len(blocks), "candidate_count": len(search_candidates),
            "candidates": [candidate_to_dict(value) for value in sorted(by_id.values(), key=lambda item: item.candidate_id)],
        },
        "search": search,
        "quality_passed_resource_candidate_count": len(resource_candidates),
        "resource_failures": resource_failures,
        "selection": selection,
        "attempts": attempts,
        "endpoint_winners": {
            "circuit_primary": winner("circuit_primary"),
            "parameter_primary": winner("parameter_primary"),
        },
        "work": {
            "new_ceo_star_adapt_iterations": 0, "new_ordinary_adapt_iterations": 0,
            "quadratic_solves": search["counts"]["quadratic_solves"],
            "full_resource_recounts": len(resource_candidates) + 1,
            "exact_vqe_attempts": len(attempts),
            "paper_measurement_cost": None,
        },
        "claim_boundary": [
            "LiH is observed development data, not confirmatory validation.",
            "The stored CEO* checkpoint is reconstructed but no CEO* or ordinary ADAPT growth iteration is run.",
            "Actual and FCI energies are absent from search and ranking; actual energy is pass/fail only.",
            "A budget-truncated search yields best-found candidates, not a global winner.",
            "Paper Measurement Cost is unavailable.",
        ],
    }
    _write_exclusive(staging / "summary.json", summary)
    _fsync_directory(staging)
    os.replace(staging, bundle)
    _fsync_directory(bundle.parent)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    arguments = parser.parse_args()
    result = run(arguments.bundle)
    print(json.dumps({
        "bundle": str(arguments.bundle), "search_status": result["search"]["status"],
        "catalog": result["catalog"]["candidate_count"],
        "eligible": result["selection"]["eligible_count"],
        "attempts": len(result["attempts"]), "winners": result["endpoint_winners"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()

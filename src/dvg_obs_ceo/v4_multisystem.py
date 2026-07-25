"""Apply frozen V4 Global OBS to registered multisystem CEO-star checkpoints."""

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
from typing import Any

import numpy as np

from .baseline import ROOT, _environment, verify_upstream
from .block_ir import candidate_to_dict, enumerate_candidates, recover_dvg_blocks
from .composition import GlobalCompatibilityError, compose_registered_candidates
from .constraint_state import ConstraintStateError
from .global_selector import GlobalResourceCandidate, select_global_candidates
from .identity import canonical_json_bytes
from .joint_prediction import (
    JointQualityPolicy,
    evaluate_joint_quality,
    joint_obs_prediction,
    secant_pairs_from_capture,
)
from .multisystem_checkpoint import _algorithm
from .resources import AnsatzStructure, evaluate_full_circuit_resources, paper_era_backend, resources_to_dict
from .s8_probe import OPTIMIZER_G_TOL, OPTIMIZER_MAX_ITERATIONS, _state_vector
from .search import SearchCandidate, SearchConfig, SearchEvaluation, deterministic_search
from .transaction import AcceptanceCriteria
from .v3_protocol import _write_exclusive
from .v4_lih import _energy, _execute_attempt, _strict_json_quality


PROTOCOL_TAG = "dvg-obs-v4-multisystem-protocol-v1.1"
MANIFEST_PATH = ROOT / "manifests" / "v4-multisystem-protocol-v1.1.json"
CONFIG_PATH = ROOT / "manifests" / "v4-s6-frozen-config-v1.json"
REQUIRED_THREADS = {"OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}


class V4MultiSystemError(RuntimeError):
    """Raised when a multisystem V4 run cannot be trusted."""


def _git(*arguments: str) -> str:
    return subprocess.check_output(["git", "-C", str(ROOT), *arguments], text=True).strip()


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def protocol() -> dict[str, Any]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def registered_cases() -> dict[str, dict[str, Any]]:
    return {item["case_id"]: item for item in protocol()["cases"]}


def canonical_bundle(case_id: str) -> Path:
    cases = registered_cases()
    if case_id not in cases:
        raise V4MultiSystemError(f"unregistered V4 case: {case_id}")
    return ROOT / protocol()["output_root"] / case_id


def _allowed_result_prefixes() -> tuple[str, ...]:
    root = protocol()["output_root"].rstrip("/") + "/"
    return (root,)


def verify_execution_freeze(case_id: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    cases = registered_cases()
    if case_id not in cases:
        raise V4MultiSystemError(f"unregistered V4 case: {case_id}")
    case = cases[case_id]
    manifest = protocol()
    config_manifest = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    head = _git("rev-parse", "HEAD")
    tag = _git("rev-parse", f"{PROTOCOL_TAG}^{{}}")
    ancestor = subprocess.run(
        ["git", "-C", str(ROOT), "merge-base", "--is-ancestor", tag, head], check=False
    ).returncode == 0
    changed_since_protocol = [
        value for value in _git("diff", "--name-only", tag, head).splitlines() if value
    ]
    disallowed_changes = [
        value for value in changed_since_protocol
        if not value.startswith(_allowed_result_prefixes())
    ]
    tracked_dirty = _git("status", "--porcelain", "--untracked-files=no")
    untracked = [value for value in _git("ls-files", "--others", "--exclude-standard").splitlines() if value]
    unexpected_untracked = [
        value for value in untracked if not value.startswith(_allowed_result_prefixes())
    ]
    threads = {name: os.environ.get(name) for name in REQUIRED_THREADS}
    checkpoint_path = ROOT / case["checkpoint_path"]
    configuration_digest = _digest(config_manifest["configuration"])
    if (
        not ancestor or disallowed_changes or tracked_dirty or unexpected_untracked
        or threads != REQUIRED_THREADS
        or configuration_digest != manifest["configuration_digest"]
        or configuration_digest != config_manifest["configuration_digest"]
        or _sha256(checkpoint_path) != case["checkpoint_sha256"]
    ):
        raise V4MultiSystemError(
            "V4 multisystem freeze failed: "
            f"ancestor={ancestor}, disallowed_changes={disallowed_changes}, "
            f"tracked_dirty={bool(tracked_dirty)}, unexpected_untracked={unexpected_untracked}, "
            f"threads={threads}, configuration_digest={configuration_digest}, "
            f"checkpoint_sha256={_sha256(checkpoint_path)}"
        )
    return {
        "head": head,
        "protocol_commit": tag,
        "protocol_tag": PROTOCOL_TAG,
        "threads": threads,
        "configuration_digest": configuration_digest,
        "checkpoint_sha256": case["checkpoint_sha256"],
    }, case, config_manifest


def _acceptance_configuration_matches(config: dict[str, Any]) -> bool:
    frozen = config["acceptance"]
    runtime = AcceptanceCriteria(guard_logical_block_count=False)
    return bool(
        frozen["cumulative_energy_budget_hartree"] == runtime.cumulative_energy_budget_hartree
        and frozen["independent_energy_tolerance_hartree"] == runtime.independent_energy_tolerance_hartree
        and frozen["minimum_independent_state_recomputation_fidelity"] == runtime.minimum_state_fidelity
        and frozen["maximum_constraint_residual"] == runtime.maximum_constraint_residual
        and frozen["maximum_stationarity_residual"] == runtime.maximum_kkt_residual
        and frozen["componentwise_nonworse_resources"]
        and frozen["at_least_one_strict_resource_improvement"]
    )


def run(case_id: str) -> dict[str, Any]:
    freeze, case_record, config_manifest = verify_execution_freeze(case_id)
    bundle = canonical_bundle(case_id)
    if bundle.exists():
        raise FileExistsError(f"refusing to overwrite V4 multisystem bundle: {bundle}")
    staging = bundle.with_name(f".{bundle.name}.staging")
    if staging.exists():
        raise FileExistsError(f"orphan V4 staging requires audit: {staging}")
    staging.mkdir(parents=True)
    _fsync_directory(staging.parent)
    random.seed(0)
    np.random.seed(0)

    checkpoint_path = ROOT / case_record["checkpoint_path"]
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    stored_digest = checkpoint.pop("checkpoint_digest")
    if _digest(checkpoint) != stored_digest:
        raise V4MultiSystemError("stored checkpoint internal digest mismatch")
    checkpoint["checkpoint_digest"] = stored_digest
    if checkpoint["case"]["case_id"] != case_id:
        raise V4MultiSystemError("checkpoint case identity mismatch")

    algorithm, pool = _algorithm(checkpoint["case"])
    algorithm.initialize()
    source = AnsatzStructure.create(
        checkpoint["ansatz_indices"], checkpoint["ansatz_coefficients"], checkpoint["iteration_counts"]
    )
    source_state = _state_vector(algorithm, source.coefficients, source.indices)
    state_digest = hashlib.sha256(np.asarray(source_state, dtype=">c16").tobytes()).hexdigest()
    independent_source_energy = _energy(algorithm, np.asarray(source.coefficients), source.indices)
    if (
        state_digest != checkpoint["statevector_sha256"]
        or abs(independent_source_energy - checkpoint["energy_hartree"]) > 1e-10
    ):
        raise V4MultiSystemError("stored checkpoint independent reconstruction failed")
    backend = paper_era_backend()
    source_resources = evaluate_full_circuit_resources(pool, source, backend)
    if asdict(source_resources.snapshot) != checkpoint["resources"]["snapshot"]:
        raise V4MultiSystemError("stored checkpoint resource reconstruction failed")

    blocks = recover_dvg_blocks(pool, source.indices, source.coefficients, source.cumulative_parameter_counts)
    representatives: dict[str, Any] = {}
    for candidate in enumerate_candidates(pool, blocks):
        representatives.setdefault(candidate.equivalence_class_id, candidate)
    by_id = {candidate.candidate_id: candidate for candidate in representatives.values()}
    search_candidates = tuple(
        SearchCandidate(candidate.candidate_id, candidate.source_block_id)
        for candidate in by_id.values()
    )
    internal = secant_pairs_from_capture(
        checkpoint["hessian_capture"]["secant_pairs"], required_source="internal-bfgs"
    )
    prediction_cache: dict[tuple[str, ...], tuple[Any, dict[str, Any], dict[str, Any]]] = {}
    config = config_manifest["configuration"]
    quality_record = config["quality_policy"]
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
        except (ConstraintStateError, GlobalCompatibilityError) as error:
            return SearchEvaluation(
                "semantic-composition-failure", None, None, None, reason=repr(error)
            )
        except Exception as error:
            return SearchEvaluation("candidate-numerical-failure", None, None, None, reason=repr(error))
        return SearchEvaluation(
            "valid", plan.state.constraint_semantic_id, plan.state.constraint_numerical_id,
            float(prediction["predicted_change_from_current_hartree"]),
        )

    if (
        config["optimizer"]["maximum_iterations_per_path"] != OPTIMIZER_MAX_ITERATIONS
        or config["optimizer"]["gradient_tolerance"] != OPTIMIZER_G_TOL
        or not _acceptance_configuration_matches(config)
    ):
        raise V4MultiSystemError("runtime optimizer or acceptance constants differ from frozen configuration")
    search_budget = config["search_budgets"]
    search = deterministic_search(
        search_candidates,
        evaluator,
        SearchConfig(
            config["screening_budget_hartree"],
            search_budget["maximum_expanded_nodes"],
            search_budget["maximum_completed_states"],
            search_budget["maximum_quadratic_solves"],
        ),
    )
    eligible_records = [record for record in search["records"] if record["eligible"]]
    resource_candidates: list[GlobalResourceCandidate] = []
    plan_by_semantic: dict[str, tuple[Any, dict[str, Any], dict[str, Any]]] = {}
    resource_failures: list[dict[str, Any]] = []
    quality_rejections: list[dict[str, Any]] = []
    for record in eligible_records[: search_budget["maximum_full_resource_recounts"]]:
        candidate_ids = tuple(record["candidate_ids"])
        plan, prediction, quality = predict(candidate_ids)
        if not quality["passed"]:
            quality_rejections.append({
                "candidate_ids": list(candidate_ids),
                "constraint_semantic_id": plan.state.constraint_semantic_id,
                "failed_checks": sorted(
                    name for name, passed in quality["checks"].items() if not passed
                ),
                "quality": quality,
            })
            continue
        try:
            target = AnsatzStructure.create(
                plan.target_indices, [1.0] * len(plan.target_indices), plan.target_iteration_counts
            )
            resources = evaluate_full_circuit_resources(
                pool, target, backend, coefficient_policy="deterministic-structural"
            )
        except Exception as error:
            resource_failures.append({"candidate_ids": list(candidate_ids), "error": repr(error)})
            continue
        resource_candidates.append(GlobalResourceCandidate(
            candidate_ids,
            plan.state.constraint_semantic_id,
            plan.state.constraint_numerical_id,
            float(prediction["predicted_change_from_current_hartree"]),
            resources.snapshot,
        ))
        plan_by_semantic[plan.state.constraint_semantic_id] = (plan, prediction, quality)
    if len(eligible_records) > search_budget["maximum_full_resource_recounts"]:
        raise V4MultiSystemError("full-resource recount deterministic budget exceeded")
    selection = select_global_candidates(
        resource_candidates,
        source_resources.snapshot,
        screening_budget_hartree=config["screening_budget_hartree"],
        top_k_per_endpoint=config["exact_vqe_budget"]["top_k_per_endpoint"],
        maximum_unique_attempts=config["exact_vqe_budget"]["maximum_unique_exact_attempts"],
    )
    attempts: list[dict[str, Any]] = []
    # Runtime acceptance is deployable and FCI-free. Exact/FCI energy may be
    # consumed only by a separate reporting audit after the run is frozen.
    chemical_accuracy_margin = None
    effective_acceptance_budget = float(
        config["acceptance"]["cumulative_energy_budget_hartree"]
    )
    safe_case_id = case_id.replace(".", "p")
    for number, semantic_id in enumerate(selection["unique_attempt_semantic_ids"], 1):
        plan, prediction, quality = plan_by_semantic[semantic_id]
        attempt = _execute_attempt(
            attempt_number=number,
            algorithm=algorithm,
            pool=pool,
            source=source,
            checkpoint=checkpoint,
            source_state=source_state,
            source_resources=source_resources,
            plan=plan,
            prediction=prediction,
            transaction_root=staging / "transactions",
            configuration_digest=config_manifest["configuration_digest"],
            run_id=f"v4-multisystem-{case_id}-stored-first-accuracy",
            transaction_prefix=f"v4-{safe_case_id}-attempt",
            cumulative_energy_budget_hartree=effective_acceptance_budget,
        )
        attempt["quality"] = quality
        attempt["prediction"] = prediction
        attempts.append(attempt)
    attempt_by_semantic = {item["constraint_semantic_id"]: item for item in attempts}

    def winner(endpoint: str) -> str | None:
        return next(
            (
                semantic_id for semantic_id in selection[endpoint]
                if attempt_by_semantic[semantic_id]["transaction_status"] == "accepted"
            ),
            None,
        )

    summary = {
        "schema_version": "1.0.0",
        "artifact_kind": "v4-global-obs-multisystem-result",
        "case_id": case_id,
        "case": checkpoint["case"],
        "execution_freeze": freeze,
        "upstream": verify_upstream(),
        "environment": _environment(),
        "checkpoint": {
            "path": case_record["checkpoint_path"],
            "checkpoint_digest": stored_digest,
            "energy_hartree": checkpoint["energy_hartree"],
            "exact_energy_hartree": checkpoint["exact_energy_hartree"],
            "chemical_accuracy_hartree": checkpoint["chemical_accuracy_hartree"],
            "resources": checkpoint["resources"],
            "independent_reconstruction_energy_hartree": independent_source_energy,
            "statevector_sha256": state_digest,
        },
        "catalog": {
            "block_count": len(blocks),
            "candidate_count": len(search_candidates),
            "candidates": [
                candidate_to_dict(value)
                for value in sorted(by_id.values(), key=lambda item: item.candidate_id)
            ],
        },
        "search": search,
        "quality_passed_resource_candidate_count": len(resource_candidates),
        "quality_rejections": quality_rejections,
        "resource_failures": resource_failures,
        "selection": selection,
        "attempts": attempts,
        "endpoint_winners": {
            "circuit_primary": winner("circuit_primary"),
            "parameter_primary": winner("parameter_primary"),
        },
        "work": {
            "new_ceo_star_adapt_iterations": 0,
            "new_ordinary_adapt_iterations": 0,
            "quadratic_solves": search["counts"]["quadratic_solves"],
            "full_resource_recounts": len(resource_candidates) + 1,
            "exact_vqe_attempts": len(attempts),
            "paper_measurement_cost": None,
        },
        "accuracy_guard": {
            "rule": "frozen source-relative algorithmic energy budget",
            "chemical_accuracy_margin_hartree": chemical_accuracy_margin,
            "effective_acceptance_budget_hartree": effective_acceptance_budget,
            "used_for_screening_or_ranking": False,
            "fci_or_exact_energy_used_at_runtime": False,
            "chemical_accuracy_audit": "offline-only",
        },
        "claim_boundary": protocol()["claim_boundary"],
    }
    summary["summary_digest"] = _digest(summary)
    _write_exclusive(staging / "summary.json", summary)
    _fsync_directory(staging)
    os.replace(staging, bundle)
    _fsync_directory(bundle.parent)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("case_id", choices=sorted(registered_cases()))
    arguments = parser.parse_args()
    result = run(arguments.case_id)
    print(json.dumps({
        "case": arguments.case_id,
        "search_status": result["search"]["status"],
        "catalog": result["catalog"]["candidate_count"],
        "eligible": result["selection"]["eligible_count"],
        "attempts": len(result["attempts"]),
        "winners": result["endpoint_winners"],
        "summary_digest": result["summary_digest"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()

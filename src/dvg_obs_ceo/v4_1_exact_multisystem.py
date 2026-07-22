"""Execute only the preregistered V4.1-S5 multisystem sentinel queues.

The search is deliberately absent from this module.  Exact energy is exposed
only after the energy-blind S5 queue has been loaded, replayed, and validated.
"""

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
from typing import Any, Mapping

import numpy as np

from .baseline import ROOT, _environment, verify_upstream
from .block_ir import enumerate_candidates, recover_dvg_blocks
from .composition import compose_registered_candidates
from .identity import canonical_json_bytes
from .joint_prediction import (
    JointQualityPolicy,
    evaluate_joint_quality,
    joint_obs_prediction,
    secant_pairs_from_capture,
)
from .multisystem_checkpoint import _algorithm
from .resources import AnsatzStructure, evaluate_full_circuit_resources, paper_era_backend
from .s8_probe import OPTIMIZER_G_TOL, OPTIMIZER_MAX_ITERATIONS, _state_vector
from .transaction import AcceptanceCriteria
from .v3_protocol import _write_exclusive
from .v4_lih import _energy, _execute_attempt
from .v4_1_bundle import CaseRunLease, audit_case_state, validate_complete_bundle
from .v4_1_multisystem import replay_selection_from_resource_evidence
from .v4_1_protocol import DEFAULT_MANIFEST, audit_manifest


EXACT_CODE_TAG = "dvg-obs-v4.1-s7-s9-exact-code-v1.1"
S5_RESULT_TAG = "dvg-obs-v4.1-s5-sentinel-freeze-v1"
S5_ROOT = ROOT / "artifacts/v4.1/s5-sentinels-rerun-v5"
OUTPUT_ROOT = ROOT / "artifacts/v4.1/multisystem"
CONFIG_PATH = ROOT / "manifests/v4-s6-frozen-config-v1.json"
REQUIRED_THREADS = {"OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
SCIENTIFIC_PATHS = ("src/", "tests/", "manifests/", "vendor/", "pyproject.toml", "uv.lock")


class V41ExactError(RuntimeError):
    """Raised when exact multisystem execution cannot be trusted."""


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(*arguments: str) -> str:
    return subprocess.check_output(["git", "-C", str(ROOT), *arguments], text=True).strip()


def _tag_commit(tag: str) -> str:
    return _git("rev-parse", f"{tag}^{{}}")


def _is_ancestor(commit: str, head: str) -> bool:
    return subprocess.run(
        ["git", "-C", str(ROOT), "merge-base", "--is-ancestor", commit, head],
        check=False,
    ).returncode == 0


def _read_summary(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    stored = value.pop("summary_digest")
    if _digest(value) != stored:
        raise V41ExactError(f"summary digest mismatch: {path}")
    value["summary_digest"] = stored
    return value


def _case_record(case_id: str, manifest: Mapping[str, Any]) -> dict[str, Any]:
    try:
        return next(dict(item) for item in manifest["cases"] if item["case_id"] == case_id)
    except StopIteration as error:
        raise V41ExactError(f"unregistered V4.1 case: {case_id}") from error


def verify_execution_freeze(case_id: str) -> dict[str, Any]:
    """Fail closed unless code/config and the preregistered S5 bundle are frozen."""

    s0 = audit_manifest(DEFAULT_MANIFEST)
    manifest = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    case = _case_record(case_id, manifest)
    head = _git("rev-parse", "HEAD")
    code_commit = _tag_commit(EXACT_CODE_TAG)
    s5_commit = _tag_commit(S5_RESULT_TAG)
    changed = [name for name in _git("diff", "--name-only", code_commit, head).splitlines() if name]
    scientific_changes = [
        name for name in changed
        if name in SCIENTIFIC_PATHS or any(name.startswith(prefix) for prefix in SCIENTIFIC_PATHS if prefix.endswith("/"))
    ]
    dirty = _git("status", "--porcelain")
    threads = {name: os.environ.get(name) for name in REQUIRED_THREADS}
    state = audit_case_state(OUTPUT_ROOT, case_id)
    s5_bundle = S5_ROOT / case_id
    s5_manifest = validate_complete_bundle(s5_bundle)
    s5_summary = _read_summary(s5_bundle / "summary.json")
    checks = {
        "exact_code_tag_ancestor": _is_ancestor(code_commit, head),
        "s5_result_tag_ancestor": _is_ancestor(s5_commit, head),
        "scientific_tree_unchanged": not scientific_changes,
        "clean_worktree": not dirty,
        "canonical_case_absent": state["canonical_status"] == "absent",
        "no_lock_or_staging": state["lock_status"] == "absent" and not state["staging"] and not state["ambiguous"],
        "canonical_threads": threads == REQUIRED_THREADS,
        "checkpoint_file": _sha256(ROOT / case["checkpoint_path"]) == case["checkpoint_sha256"],
        "s5_case": s5_summary["case_id"] == case_id,
        "s5_checkpoint": s5_summary["checkpoint_sha256"] == case["checkpoint_sha256"],
        "s5_energy_blind": (
            s5_summary["actual_candidate_energy_evaluations"] == 0
            and s5_summary["exact_or_fci_energy_used"] is False
        ),
        "s5_selection_replay": replay_selection_from_resource_evidence(s5_summary) == s5_summary["selection"],
        "s5_queue_limit": 0 < len(s5_summary["sentinels"]) <= 4,
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise V41ExactError("execution freeze failed: " + ", ".join(failed))
    return {
        "head": head,
        "exact_code_tag": EXACT_CODE_TAG,
        "exact_code_commit": code_commit,
        "s5_result_tag": S5_RESULT_TAG,
        "s5_result_commit": s5_commit,
        "changed_since_exact_code_tag": changed,
        "threads": threads,
        "checks": checks,
        "s0_manifest_sha256": s0["manifest_sha256"],
        "s5_bundle_digest": s5_manifest["bundle_digest"],
        "s5_summary_digest": s5_summary["summary_digest"],
    }


def _quality_policy(config: Mapping[str, Any]) -> JointQualityPolicy:
    record = config["quality_policy"]
    return JointQualityPolicy(
        maximum_constraint_schur_condition_number=record["maximum_constraint_schur_condition_number"],
        maximum_target_hessian_condition_number=record["maximum_target_hessian_condition_number"],
        minimum_constraint_direction_coverage=record["minimum_constraint_direction_coverage"],
        maximum_internal_projected_residual=record["maximum_internal_projected_residual"],
        maximum_held_out_projected_residual=1e12,
        require_held_out_evidence=False,
        target_hessian_condition_is_scientific_gate=False,
        maximum_equilibrated_target_hessian_condition_number=1e12,
        maximum_target_hessian_relative_solve_residual=1e-10,
        maximum_target_hessian_relative_backward_error=1e-10,
    )


def _acceptance_constants_match(config: Mapping[str, Any]) -> bool:
    frozen = config["acceptance"]
    runtime = AcceptanceCriteria(guard_logical_block_count=False)
    return bool(
        frozen["cumulative_energy_budget_hartree"] == runtime.cumulative_energy_budget_hartree
        and frozen["independent_energy_tolerance_hartree"] == runtime.independent_energy_tolerance_hartree
        and frozen["minimum_independent_state_recomputation_fidelity"] == runtime.minimum_state_fidelity
        and frozen["maximum_constraint_residual"] == runtime.maximum_constraint_residual
        and frozen["maximum_stationarity_residual"] == runtime.maximum_kkt_residual
        and frozen["componentwise_nonworse_resources"] is True
        and frozen["at_least_one_strict_resource_improvement"] is True
    )


def execute_case(case_id: str) -> dict[str, Any]:
    """Execute every and only frozen S5 sentinel, independently from one source."""

    freeze = verify_execution_freeze(case_id)
    manifest = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    case = _case_record(case_id, manifest)
    s5 = _read_summary(S5_ROOT / case_id / "summary.json")
    checkpoint_path = ROOT / case["checkpoint_path"]
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    stored_checkpoint_digest = checkpoint.pop("checkpoint_digest")
    if _digest(checkpoint) != stored_checkpoint_digest:
        raise V41ExactError("checkpoint internal digest mismatch")
    checkpoint["checkpoint_digest"] = stored_checkpoint_digest
    config_manifest = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    config = config_manifest["configuration"]
    if (
        config["optimizer"]["maximum_iterations_per_path"] != OPTIMIZER_MAX_ITERATIONS
        or config["optimizer"]["gradient_tolerance"] != OPTIMIZER_G_TOL
        or not _acceptance_constants_match(config)
    ):
        raise V41ExactError("runtime optimizer or acceptance constants drifted")

    random.seed(0)
    np.random.seed(0)
    algorithm, pool = _algorithm(checkpoint["case"])
    algorithm.initialize()
    source = AnsatzStructure.create(
        checkpoint["ansatz_indices"], checkpoint["ansatz_coefficients"], checkpoint["iteration_counts"]
    )
    source_state = _state_vector(algorithm, source.coefficients, source.indices)
    source_state_digest = hashlib.sha256(np.asarray(source_state, dtype=">c16").tobytes()).hexdigest()
    source_energy = _energy(algorithm, np.asarray(source.coefficients), source.indices)
    source_resources = evaluate_full_circuit_resources(pool, source, paper_era_backend())
    if (
        source_state_digest != checkpoint["statevector_sha256"]
        or abs(source_energy - checkpoint["energy_hartree"]) > 1e-10
        or asdict(source_resources.snapshot) != checkpoint["resources"]["snapshot"]
        or asdict(source_resources.snapshot) != s5["source_resources"]
    ):
        raise V41ExactError("independent source reconstruction failed")

    blocks = recover_dvg_blocks(pool, source.indices, source.coefficients, source.cumulative_parameter_counts)
    representatives: dict[str, Any] = {}
    for candidate in enumerate_candidates(pool, blocks):
        representatives.setdefault(candidate.equivalence_class_id, candidate)
    by_id = {candidate.candidate_id: candidate for candidate in representatives.values()}
    if sorted(by_id) != sorted(item["candidate_id"] for item in s5["catalog"]["candidates"]):
        raise V41ExactError("candidate catalog drifted from S5")
    internal = secant_pairs_from_capture(
        checkpoint["hessian_capture"]["secant_pairs"], required_source="internal-bfgs"
    )
    quality_policy = _quality_policy(config)
    queue = s5["sentinels"]
    if [item["constraint_semantic_id"] for item in queue] != s5["selection"]["unique_attempt_semantic_ids"]:
        raise V41ExactError("S5 sentinel queue/order mismatch")

    chemical_margin = (
        float(checkpoint["exact_energy_hartree"])
        + float(checkpoint["chemical_accuracy_hartree"])
        - float(checkpoint["energy_hartree"])
    )
    if not math.isfinite(chemical_margin) or chemical_margin <= 0:
        raise V41ExactError("source is not strictly inside chemical accuracy")
    effective_budget = min(
        float(config["acceptance"]["cumulative_energy_budget_hartree"]),
        float(np.nextafter(chemical_margin, -math.inf)),
    )

    started = time.perf_counter()
    attempts: list[dict[str, Any]] = []
    with CaseRunLease(
        OUTPUT_ROOT, case_id, freeze["s0_manifest_sha256"], case["checkpoint_sha256"]
    ) as lease:
        for number, frozen in enumerate(queue, 1):
            candidate_ids = tuple(frozen["candidate_ids"])
            try:
                candidates = tuple(by_id[value] for value in candidate_ids)
            except KeyError as error:
                raise V41ExactError(f"frozen candidate missing from catalog: {error}") from error
            plan = compose_registered_candidates(source, blocks, candidates)
            prediction = joint_obs_prediction(
                checkpoint["ansatz_coefficients"], checkpoint["gradient"],
                checkpoint["recycled_inverse_hessian"], plan.transformation,
                internal_pairs=internal, held_out_pairs=(),
            )
            quality = evaluate_joint_quality(prediction, quality_policy)
            replay_checks = {
                "semantic_id": plan.state.constraint_semantic_id == frozen["constraint_semantic_id"],
                "numerical_id": plan.state.constraint_numerical_id == frozen["constraint_numerical_id"],
                "target_indices": list(plan.target_indices) == frozen["target_indices"],
                "target_iteration_counts": list(plan.target_iteration_counts) == frozen["target_iteration_counts"],
                "prediction": _digest(prediction) == _digest(frozen["prediction"]),
                "quality": _digest(quality) == _digest(frozen["quality"]),
                "quality_passed": quality["passed"] is True,
            }
            if not all(replay_checks.values()):
                raise V41ExactError(
                    "frozen sentinel replay drift: "
                    + ", ".join(name for name, passed in replay_checks.items() if not passed)
                )
            attempt_started = time.perf_counter()
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
                transaction_root=lease.staging / "transactions",
                configuration_digest=config_manifest["configuration_digest"],
                run_id=f"v4.1-{case_id}-frozen-sentinel-exact",
                transaction_prefix=f"v4.1-{case_id.replace('.', 'p')}-attempt",
                cumulative_energy_budget_hartree=effective_budget,
            )
            attempt["frozen_sentinel"] = frozen
            attempt["prediction"] = prediction
            attempt["quality"] = quality
            attempt["sentinel_replay_checks"] = replay_checks
            attempt["wall_time_seconds"] = time.perf_counter() - attempt_started
            if attempt["transaction_status"] == "rolled-back" and not attempt["rollback_exact"]:
                raise V41ExactError("rejected attempt did not restore exact source snapshot")
            attempts.append(attempt)

        attempt_by_semantic = {item["constraint_semantic_id"]: item for item in attempts}

        def winner(endpoint: str) -> str | None:
            return next(
                (
                    semantic_id for semantic_id in s5["selection"][endpoint]
                    if semantic_id in attempt_by_semantic
                    and attempt_by_semantic[semantic_id]["transaction_status"] == "accepted"
                ),
                None,
            )

        elapsed = time.perf_counter() - started
        final: dict[str, Any] = {
            "schema_version": "1.0.0",
            "artifact_kind": "v4.1-frozen-sentinel-exact-result",
            "case_id": case_id,
            "case": checkpoint["case"],
            "protocol_id": manifest["protocol_id"],
            "execution_freeze": freeze,
            "upstream": verify_upstream(),
            "environment": _environment(),
            "checkpoint": {
                "path": case["checkpoint_path"],
                "file_sha256": case["checkpoint_sha256"],
                "checkpoint_digest": stored_checkpoint_digest,
                "energy_hartree": checkpoint["energy_hartree"],
                "exact_energy_hartree": checkpoint["exact_energy_hartree"],
                "chemical_accuracy_hartree": checkpoint["chemical_accuracy_hartree"],
                "resources": checkpoint["resources"],
                "independent_reconstruction_energy_hartree": source_energy,
                "statevector_sha256": source_state_digest,
            },
            "s5_frozen_selection": {
                "bundle_digest": freeze["s5_bundle_digest"],
                "summary_digest": freeze["s5_summary_digest"],
                "selection": s5["selection"],
                "search_status": s5["search"]["status"],
                "search_counts": s5["search"]["counts"],
                "quality_passed_resource_candidate_count": s5["quality_passed_resource_candidate_count"],
                "actual_candidate_energy_evaluations": s5["actual_candidate_energy_evaluations"],
                "exact_or_fci_energy_used": s5["exact_or_fci_energy_used"],
            },
            "attempts": attempts,
            "endpoint_winners": {name: winner(name) for name in (
                "cnot_primary", "cnot_depth_primary", "total_depth_primary", "parameter_primary"
            )},
            "accuracy_guard": {
                "reference": "original-ceo-star-checkpoint",
                "chemical_accuracy_margin_hartree": chemical_margin,
                "effective_cumulative_budget_hartree": effective_budget,
                "used_for_screening_or_ranking": False,
            },
            "work": {
                "new_ceo_star_adapt_iterations": 0,
                "new_ordinary_adapt_iterations": 0,
                "screening_quadratic_solves": s5["search"]["counts"]["quadratic_solves"],
                "full_quality_predictions_screening": s5["screening_work"]["full_quality_predictions"],
                "full_resource_recounts_screening": s5["quality_passed_resource_candidate_count"] + 1,
                "source_energy_recomputations_exact_stage": 1,
                "source_statevector_recomputations_exact_stage": 1,
                "source_full_resource_recounts_exact_stage": 1,
                "exact_vqe_attempts": len(attempts),
                "accepted_attempts": sum(item["transaction_status"] == "accepted" for item in attempts),
                "rolled_back_attempts": sum(item["transaction_status"] == "rolled-back" for item in attempts),
                "attempt_work": [item["work_after_attempt"] for item in attempts],
                "wall_time_seconds": elapsed,
                "paper_measurement_cost": None,
            },
            "search_completeness": s5["search"]["status"],
            "claim_boundary": (
                "Observed development-case frozen-sentinel evaluation; budget-truncated search, "
                "no global-optimum, unseen-generalization, hardware-noise, shot-cost, or paper Measurement Cost claim."
            ),
        }
        final["summary_digest"] = _digest(final)
        _write_exclusive(lease.staging / "summary.json", final)
        lease.finalize()
        canonical = lease.promote()
    return {**final, "canonical_bundle": str(canonical)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("case_id", choices=("h6-1.5", "h6-3.0", "beh2-3.0"))
    args = parser.parse_args()
    result = execute_case(args.case_id)
    print(json.dumps({
        "case_id": result["case_id"],
        "attempts": len(result["attempts"]),
        "accepted": result["work"]["accepted_attempts"],
        "endpoint_winners": result["endpoint_winners"],
        "summary_digest": result["summary_digest"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()

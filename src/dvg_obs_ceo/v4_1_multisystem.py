"""V4.1 corrected multisystem screening and preregistered sentinel selection."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from .baseline import ROOT
from .block_ir import candidate_to_dict, enumerate_candidates, recover_dvg_blocks
from .composition import GlobalCompatibilityError, compose_registered_candidates
from .constraint_state import ConstraintStateError
from .global_selector import GlobalResourceCandidate, select_global_candidates
from .identity import canonical_json_bytes
from .joint_prediction import (
    JointQualityPolicy,
    JointScreeningContext,
    evaluate_joint_quality,
    joint_obs_prediction,
    secant_pairs_from_capture,
)
from .multisystem_checkpoint import _algorithm
from .resources import AnsatzStructure, evaluate_full_circuit_resources, paper_era_backend
from .search import SearchCandidate, SearchConfig, SearchEvaluation, deterministic_search
from .v4_1_protocol import DEFAULT_MANIFEST, audit_manifest
from .v4_1_bundle import CaseRunLease
from .v3_protocol import _write_exclusive


ENDPOINT_ORDERS = {
    "cnot_primary": ("cnot_count", "cnot_depth", "total_depth", "parameter_count"),
    "cnot_depth_primary": ("cnot_depth", "cnot_count", "total_depth", "parameter_count"),
    "total_depth_primary": ("total_depth", "cnot_count", "cnot_depth", "parameter_count"),
    "parameter_primary": ("parameter_count", "cnot_count", "cnot_depth", "total_depth"),
}


class V41MultiSystemError(RuntimeError):
    """Raised when corrected screening cannot be trusted."""


SCREENING_CODE_TAG = "dvg-obs-v4.1-s5-screening-code-v1.4"
DEFAULT_SCREENING_ROOT = ROOT / "artifacts/v4.1/s5-sentinels-rerun-v4"
REQUIRED_THREADS = {"OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _rank(candidate: GlobalResourceCandidate, order: Sequence[str]) -> tuple[Any, ...]:
    return tuple(getattr(candidate.resources, field) for field in order) + (
        candidate.predicted_loss_hartree,
        candidate.constraint_semantic_id,
    )


def select_v4_1_sentinels(
    candidates: Sequence[GlobalResourceCandidate],
    source: Any,
    *,
    screening_budget_hartree: float,
    top_k_per_endpoint: int = 2,
    maximum_unique_attempts: int = 4,
) -> dict[str, Any]:
    base = select_global_candidates(
        candidates,
        source,
        screening_budget_hartree=screening_budget_hartree,
        top_k_per_endpoint=top_k_per_endpoint,
        maximum_unique_attempts=maximum_unique_attempts,
    )
    by_semantic = {candidate.constraint_semantic_id: candidate for candidate in candidates}
    pareto = [by_semantic[value] for value in base["pareto_semantic_ids"]]
    endpoints = {
        name: sorted(pareto, key=lambda candidate, order=order: _rank(candidate, order))[
            :top_k_per_endpoint
        ]
        for name, order in ENDPOINT_ORDERS.items()
    }
    selected: list[GlobalResourceCandidate] = []
    seen: set[str] = set()
    for rank in range(top_k_per_endpoint):
        for name in ENDPOINT_ORDERS:
            ranked = endpoints[name]
            if rank >= len(ranked):
                continue
            candidate = ranked[rank]
            digest = candidate.resources.structure_digest
            if digest not in seen and len(selected) < maximum_unique_attempts:
                seen.add(digest)
                selected.append(candidate)
    payload = {
        **base,
        "version": "v4.1-four-endpoint-sentinel-selector-v1",
        "endpoint_orders": {name: list(order) for name, order in ENDPOINT_ORDERS.items()},
        **{
            name: [candidate.constraint_semantic_id for candidate in values]
            for name, values in endpoints.items()
        },
        "unique_attempt_semantic_ids": [
            candidate.constraint_semantic_id for candidate in selected
        ],
    }
    payload.pop("selection_digest", None)
    payload["selection_digest"] = _digest(payload)
    return payload


def replay_selected_sentinel_evidence(
    selection: Mapping[str, Any],
    evidence: Mapping[str, Mapping[str, Any]],
    predictor: Any,
) -> list[dict[str, Any]]:
    """Materialize full diagnostics only for the frozen unique sentinel queue."""

    sentinels: list[dict[str, Any]] = []
    for semantic_id in selection["unique_attempt_semantic_ids"]:
        stored = dict(evidence[semantic_id])
        candidate_ids = tuple(stored["candidate_ids"])
        plan, prediction, quality = predictor(candidate_ids)
        if (
            plan.state.constraint_semantic_id != semantic_id
            or plan.state.constraint_numerical_id != stored["constraint_numerical_id"]
            or not quality["passed"]
        ):
            raise V41MultiSystemError(
                "selected sentinel full-prediction replay drift"
            )
        sentinels.append({**stored, "prediction": prediction, "quality": quality})
    return sentinels


def screen_case(case_id: str, manifest_path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    s0 = audit_manifest(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    registered = {case["case_id"]: case for case in manifest["cases"]}
    if case_id not in registered:
        raise V41MultiSystemError(f"unregistered V4.1 case: {case_id}")
    case_record = registered[case_id]
    checkpoint = json.loads((ROOT / case_record["checkpoint_path"]).read_text(encoding="utf-8"))
    stored_digest = checkpoint.pop("checkpoint_digest")
    if _digest(checkpoint) != stored_digest:
        raise V41MultiSystemError("checkpoint internal digest mismatch")
    checkpoint["checkpoint_digest"] = stored_digest
    algorithm, pool = _algorithm(checkpoint["case"])
    algorithm.initialize()
    source = AnsatzStructure.create(
        checkpoint["ansatz_indices"], checkpoint["ansatz_coefficients"], checkpoint["iteration_counts"]
    )
    backend = paper_era_backend()
    source_resources = evaluate_full_circuit_resources(pool, source, backend)
    if asdict(source_resources.snapshot) != checkpoint["resources"]["snapshot"]:
        raise V41MultiSystemError("source full-resource recount drift")
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
    config_manifest = json.loads(
        (ROOT / "manifests/v4-s6-frozen-config-v1.json").read_text(encoding="utf-8")
    )
    config = config_manifest["configuration"]
    record = config["quality_policy"]
    quality_policy = JointQualityPolicy(
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
    screening_context = JointScreeningContext.create(
        checkpoint["ansatz_coefficients"], checkpoint["gradient"],
        checkpoint["recycled_inverse_hessian"],
    )

    def predict(candidate_ids: tuple[str, ...]) -> tuple[Any, dict[str, Any], dict[str, Any]]:
        key = tuple(sorted(candidate_ids))
        plan = compose_registered_candidates(source, blocks, tuple(by_id[value] for value in key))
        prediction = joint_obs_prediction(
            checkpoint["ansatz_coefficients"], checkpoint["gradient"],
            checkpoint["recycled_inverse_hessian"], plan.transformation,
            internal_pairs=internal, held_out_pairs=(),
        )
        quality = evaluate_joint_quality(prediction, quality_policy)
        return plan, prediction, quality

    def evaluator(candidate_ids: tuple[str, ...]) -> SearchEvaluation:
        try:
            key = tuple(sorted(candidate_ids))
            plan = compose_registered_candidates(
                source, blocks, tuple(by_id[value] for value in key)
            )
            predicted_change = screening_context.predicted_change(plan.transformation)
        except (ConstraintStateError, GlobalCompatibilityError) as error:
            return SearchEvaluation("semantic-composition-failure", None, None, None, reason=repr(error))
        except Exception as error:
            return SearchEvaluation("candidate-numerical-failure", None, None, None, reason=repr(error))
        return SearchEvaluation(
            "valid", plan.state.constraint_semantic_id, plan.state.constraint_numerical_id,
            float(predicted_change),
        )

    budgets = config["search_budgets"]
    search = deterministic_search(
        search_candidates,
        evaluator,
        SearchConfig(
            config["screening_budget_hartree"], budgets["maximum_expanded_nodes"],
            budgets["maximum_completed_states"], budgets["maximum_quadratic_solves"],
        ),
    )
    eligible_records = [item for item in search["records"] if item["eligible"]]
    resources: list[GlobalResourceCandidate] = []
    evidence: dict[str, dict[str, Any]] = {}
    quality_rejections: list[dict[str, Any]] = []
    resource_failures: list[dict[str, Any]] = []
    for item in eligible_records[: budgets["maximum_full_resource_recounts"]]:
        candidate_ids = tuple(item["candidate_ids"])
        plan, prediction, quality = predict(candidate_ids)
        if not quality["passed"]:
            quality_rejections.append({
                "candidate_ids": list(candidate_ids),
                "constraint_semantic_id": plan.state.constraint_semantic_id,
                "failed_checks": sorted(name for name, passed in quality["checks"].items() if not passed),
            })
            continue
        try:
            target = AnsatzStructure.create(
                plan.target_indices, [1.0] * len(plan.target_indices), plan.target_iteration_counts
            )
            recount = evaluate_full_circuit_resources(
                pool, target, backend, coefficient_policy="deterministic-structural"
            )
        except Exception as error:
            resource_failures.append({"candidate_ids": list(candidate_ids), "error": repr(error)})
            continue
        candidate = GlobalResourceCandidate(
            candidate_ids, plan.state.constraint_semantic_id, plan.state.constraint_numerical_id,
            float(prediction["predicted_change_from_current_hartree"]), recount.snapshot,
        )
        resources.append(candidate)
        evidence[plan.state.constraint_semantic_id] = {
            "candidate_ids": list(candidate_ids),
            "constraint_semantic_id": plan.state.constraint_semantic_id,
            "constraint_numerical_id": plan.state.constraint_numerical_id,
            "resources": asdict(recount.snapshot),
            "target_indices": list(plan.target_indices),
            "target_iteration_counts": list(plan.target_iteration_counts),
        }
    if len(eligible_records) > budgets["maximum_full_resource_recounts"]:
        raise V41MultiSystemError("full-resource recount budget exceeded")
    selection = select_v4_1_sentinels(
        resources, source_resources.snapshot,
        screening_budget_hartree=config["screening_budget_hartree"],
        top_k_per_endpoint=config["exact_vqe_budget"]["top_k_per_endpoint"],
        maximum_unique_attempts=4,
    )
    sentinels = replay_selected_sentinel_evidence(selection, evidence, predict)
    result: dict[str, Any] = {
        "schema_version": "1.0.0",
        "artifact_kind": "v4.1-s5-case-sentinel-screening",
        "case_id": case_id,
        "protocol_id": manifest["protocol_id"],
        "s0_manifest_sha256": s0["manifest_sha256"],
        "checkpoint_sha256": case_record["checkpoint_sha256"],
        "catalog": {
            "block_count": len(blocks), "candidate_count": len(by_id),
            "candidates": [candidate_to_dict(value) for value in sorted(by_id.values(), key=lambda x: x.candidate_id)],
        },
        "source_resources": asdict(source_resources.snapshot),
        "search": search,
        "screening_work": {
            "fixed_source_hessian_factorizations": 1,
            "constraint_space_solves": search["counts"]["quadratic_solves"],
            "full_quality_predictions": len(eligible_records) + len(sentinels),
            "retained_full_prediction_records": len(sentinels),
            "algorithm": "memory-bounded-fixed-source-constrained-newton-v1",
        },
        "quality_passed_resource_candidate_count": len(resources),
        "quality_rejections": quality_rejections,
        "resource_failures": resource_failures,
        "selection": selection,
        "sentinels": sentinels,
        "actual_candidate_energy_evaluations": 0,
        "exact_or_fci_energy_used": False,
        "paper_measurement_cost": None,
        "claim_boundary": "Observed development screening; no exact candidate VQE or actual/FCI-energy ranking.",
    }
    result["summary_digest"] = _digest(result)
    return result


def verify_screening_freeze() -> dict[str, Any]:
    import subprocess

    head = subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip()
    tag = subprocess.check_output(
        ["git", "-C", str(ROOT), "rev-parse", f"{SCREENING_CODE_TAG}^{{}}"], text=True
    ).strip()
    dirty = subprocess.check_output(
        ["git", "-C", str(ROOT), "status", "--porcelain"], text=True
    ).strip()
    threads = {name: os.environ.get(name) for name in REQUIRED_THREADS}
    if head != tag or dirty or threads != REQUIRED_THREADS:
        raise V41MultiSystemError(
            f"S5 freeze failed: head={head}, tag={tag}, dirty={bool(dirty)}, threads={threads}"
        )
    return {"head": head, "tag": SCREENING_CODE_TAG, "threads": threads}


def screen_and_store(
    case_id: str,
    *,
    output_root: Path = DEFAULT_SCREENING_ROOT,
    manifest_path: Path = DEFAULT_MANIFEST,
) -> dict[str, Any]:
    s0 = audit_manifest(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    case_record = next(case for case in manifest["cases"] if case["case_id"] == case_id)
    with CaseRunLease(
        output_root,
        case_id,
        s0["manifest_sha256"],
        case_record["checkpoint_sha256"],
    ) as lease:
        result = screen_case(case_id, manifest_path)
        _write_exclusive(lease.staging / "summary.json", result)
        lease.finalize()
        canonical = lease.promote()
    return {"case_id": case_id, "path": str(canonical), "summary_digest": result["summary_digest"]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("case_id", choices=("all", "h6-1.5", "h6-3.0", "beh2-3.0"))
    parser.add_argument("--output-root", type=Path, default=DEFAULT_SCREENING_ROOT)
    arguments = parser.parse_args()
    freeze = verify_screening_freeze()
    cases = ("h6-1.5", "h6-3.0", "beh2-3.0") if arguments.case_id == "all" else (arguments.case_id,)
    results = [screen_and_store(case, output_root=arguments.output_root) for case in cases]
    print(json.dumps({"freeze": freeze, "results": results}, sort_keys=True))


if __name__ == "__main__":
    main()

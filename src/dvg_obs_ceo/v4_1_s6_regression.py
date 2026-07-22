"""V4.1-S6 H2/H4 semantic regression and LiH exact transaction rehearsal."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
from typing import Any

import numpy as np

from .baseline import ROOT
from .block_ir import enumerate_candidates, recover_dvg_blocks
from .composition import compose_registered_candidates
from .constraint_state import exact_atomic_constraint
from .identity import canonical_json_bytes
from .joint_prediction import (
    JointQualityPolicy,
    evaluate_joint_quality,
    joint_obs_prediction,
    secant_pairs_from_capture,
)
from .resources import AnsatzStructure, evaluate_full_circuit_resources, paper_era_backend
from .s8_probe import _algorithm as _fixture_algorithm, _state_vector
from .s10_lih import _algorithm as _lih_algorithm
from .v3_gradient_audit import _load_and_verify
from .v3_protocol import _write_exclusive
from .v4_1_bundle import CaseRunLease
from .v4_1_protocol import DEFAULT_MANIFEST, audit_manifest
from .v4_1_scale_audit import LIH_CHECKPOINT, LIH_V4_SUMMARY, _matches_stored
from .v4_lih import _energy, _execute_attempt


PROTOCOL_TAG = "dvg-obs-v4.1-s6-regression-code-v1"
S5_TAG = "dvg-obs-v4.1-s5-sentinel-freeze-v1"
OUTPUT_ROOT = ROOT / "artifacts/v4.1/s6-regression"
V4_COMPOSITION = ROOT / "artifacts/v4/s2-global-composition-audit-v1-1.json"
V4_CONSTRAINT = ROOT / "artifacts/v4/s1-constraint-state-audit-v1-2.json"
V4_RESOURCE = ROOT / "artifacts/v4/s5-full-resource-pareto-audit-v1.json"
REQUIRED_THREADS = {"OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}


class V41S6RegressionError(RuntimeError):
    """Raised when a low-cost regression or exact LiH rehearsal drifts."""


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _git(*arguments: str) -> str:
    return subprocess.check_output(["git", "-C", str(ROOT), *arguments], text=True).strip()


def verify_freeze() -> dict[str, Any]:
    head = _git("rev-parse", "HEAD")
    tagged = _git("rev-parse", f"{PROTOCOL_TAG}^{{}}")
    dirty = _git("status", "--porcelain")
    threads = {name: os.environ.get(name) for name in REQUIRED_THREADS}
    ancestor = subprocess.run(
        ["git", "-C", str(ROOT), "merge-base", "--is-ancestor", S5_TAG, "HEAD"],
        check=False,
    ).returncode == 0
    if head != tagged or dirty or threads != REQUIRED_THREADS or not ancestor:
        raise V41S6RegressionError(
            f"S6 freeze failed: head={head}, tag={tagged}, dirty={bool(dirty)}, "
            f"threads={threads}, s5_ancestor={ancestor}"
        )
    return {"head": head, "tag": PROTOCOL_TAG, "s5_tag_ancestor": ancestor, "threads": threads}


def h2_h4_regression() -> dict[str, Any]:
    _, _, checkpoints = _load_and_verify(
        ROOT / "manifests/v3-s1-gradient-audit-v1.json"
    )
    old_composition = json.loads(V4_COMPOSITION.read_text(encoding="utf-8"))
    old_constraints = json.loads(V4_CONSTRAINT.read_text(encoding="utf-8"))
    old_resources = {
        case["case_id"]: case["source_resources"]
        for case in json.loads(V4_RESOURCE.read_text(encoding="utf-8"))["cases"]
    }
    current: dict[str, Any] = {}
    old_to_current: dict[str, dict[str, Any]] = {}
    total_single_replays = 0
    for case_id in sorted(checkpoints):
        checkpoint = checkpoints[case_id]
        _, pool = _fixture_algorithm(case_id)
        source = AnsatzStructure.create(
            checkpoint["ansatz_indices"], checkpoint["ansatz_coefficients"],
            checkpoint["iteration_counts"],
        )
        blocks = recover_dvg_blocks(
            pool, source.indices, source.coefficients, source.cumulative_parameter_counts
        )
        representatives: dict[str, Any] = {}
        for candidate in enumerate_candidates(pool, blocks):
            representatives.setdefault(candidate.equivalence_class_id, candidate)
        by_id = {candidate.candidate_id: candidate for candidate in representatives.values()}
        old_records = [
            record for record in old_constraints["records"]
            if record["case_id"] == case_id
        ]
        mapping: dict[str, Any] = {}
        for record in old_records:
            primitive = record["semantic_primitive"]
            matches = [
                candidate for candidate in by_id.values()
                if candidate.source_block_id == primitive["source_block_id"]
                and list(candidate.source_pool_indices) == primitive["source_pool_indices"]
                and candidate.target_family == primitive["target_family"]
                and list(candidate.target_pool_indices) == primitive["target_pool_indices"]
                and list(candidate.removed_source_slots) == primitive["removed_source_slots"]
            ]
            if len(matches) != 1:
                raise V41S6RegressionError(
                    f"old H2/H4 primitive does not map uniquely: {record['candidate_id']}"
                )
            exact = exact_atomic_constraint(matches[0])
            if [list(row) for row in exact.system.augmented_rref] != primitive[
                "exact_augmented_rref"
            ]:
                raise V41S6RegressionError("H2/H4 exact atomic relation drift")
            mapping[record["candidate_id"]] = matches[0]
        if {candidate.candidate_id for candidate in mapping.values()} != set(by_id):
            raise V41S6RegressionError(f"H2/H4 candidate mapping coverage drift: {case_id}")
        old_to_current[case_id] = mapping
        single_ids = []
        for candidate in sorted(by_id.values(), key=lambda value: value.candidate_id):
            first = compose_registered_candidates(source, blocks, (candidate,))
            second = compose_registered_candidates(source, blocks, (candidate,))
            if (
                first.state.constraint_semantic_id != second.state.constraint_semantic_id
                or first.state.constraint_numerical_id != second.state.constraint_numerical_id
                or first.target_indices != second.target_indices
            ):
                raise V41S6RegressionError(f"single-candidate replay drift: {case_id}")
            single_ids.append(first.state.constraint_semantic_id)
        total_single_replays += len(single_ids)
        source_resources = evaluate_full_circuit_resources(
            pool, source, paper_era_backend(), coefficient_policy="deterministic-structural"
        ).snapshot
        if asdict(source_resources) != old_resources[case_id]:
            raise V41S6RegressionError(f"H2/H4 resource drift: {case_id}")
        current[case_id] = {
            "candidate_count": len(by_id),
            "old_candidate_ids_mapped": len(mapping),
            "candidate_ids_changed_by_semantic_version": sum(
                old_id != candidate.candidate_id
                for old_id, candidate in mapping.items()
            ),
            "unique_single_semantic_ids": len(set(single_ids)),
            "source_resources": asdict(source_resources),
        }
    h4_case = "h4-1.5-first-chemical-accuracy"
    checkpoint = checkpoints[h4_case]
    _, h4_pool = _fixture_algorithm(h4_case)
    h4_source = AnsatzStructure.create(
        checkpoint["ansatz_indices"], checkpoint["ansatz_coefficients"],
        checkpoint["iteration_counts"],
    )
    h4_blocks = recover_dvg_blocks(
        h4_pool, h4_source.indices, h4_source.coefficients,
        h4_source.cumulative_parameter_counts,
    )
    replayed_batches = 0
    for record in old_composition["records"]:
        try:
            batch = tuple(old_to_current[h4_case][value] for value in record["candidate_ids"])
        except KeyError as error:
            raise V41S6RegressionError("H4 candidate identity drift") from error
        plan = compose_registered_candidates(h4_source, h4_blocks, batch)
        if (
            len(plan.target_indices) != record["target_dimension"]
        ):
            raise V41S6RegressionError("H4 stored joint target dimension drift")
        replayed_batches += 1
    if total_single_replays != 17 or replayed_batches != 420:
        raise V41S6RegressionError("H2/H4 fixture coverage drift")
    return {
        "cases": current,
        "single_candidate_replays": total_single_replays,
        "stored_joint_batch_replays": replayed_batches,
        "physical_semantics_comparison": (
            "exact atomic RREF and mapped joint target dimensions; semantic IDs are "
            "intentionally versioned and are not asserted equal"
        ),
        "paper_measurement_cost": None,
        "passed": True,
    }


def _quality_policy() -> JointQualityPolicy:
    record = json.loads(
        (ROOT / "manifests/v4-s6-frozen-config-v1.json").read_text(encoding="utf-8")
    )["configuration"]["quality_policy"]
    return JointQualityPolicy(
        maximum_constraint_schur_condition_number=record[
            "maximum_constraint_schur_condition_number"
        ],
        maximum_target_hessian_condition_number=record[
            "maximum_target_hessian_condition_number"
        ],
        minimum_constraint_direction_coverage=record[
            "minimum_constraint_direction_coverage"
        ],
        maximum_internal_projected_residual=record[
            "maximum_internal_projected_residual"
        ],
        maximum_held_out_projected_residual=1e12,
        require_held_out_evidence=False,
        target_hessian_condition_is_scientific_gate=False,
        maximum_equilibrated_target_hessian_condition_number=1e12,
        maximum_target_hessian_relative_solve_residual=1e-10,
        maximum_target_hessian_relative_backward_error=1e-10,
    )


def run(output_root: Path = OUTPUT_ROOT) -> dict[str, Any]:
    freeze = verify_freeze()
    s0 = audit_manifest(DEFAULT_MANIFEST)
    h2_h4 = h2_h4_regression()
    checkpoint = json.loads(LIH_CHECKPOINT.read_text(encoding="utf-8"))
    stored_checkpoint_digest = checkpoint.pop("checkpoint_digest")
    if _digest(checkpoint) != stored_checkpoint_digest:
        raise V41S6RegressionError("LiH checkpoint internal digest mismatch")
    checkpoint["checkpoint_digest"] = stored_checkpoint_digest
    old_summary = json.loads(LIH_V4_SUMMARY.read_text(encoding="utf-8"))
    old_accepted = next(
        attempt for attempt in old_summary["attempts"]
        if attempt["transaction_status"] == "accepted"
    )
    algorithm, pool, _ = _lih_algorithm()
    algorithm.initialize()
    source = AnsatzStructure.create(
        checkpoint["ansatz_indices"], checkpoint["ansatz_coefficients"],
        checkpoint["iteration_counts"],
    )
    source_state = _state_vector(algorithm, source.coefficients, source.indices)
    source_energy = _energy(algorithm, np.asarray(source.coefficients), source.indices)
    source_resources = evaluate_full_circuit_resources(pool, source, paper_era_backend())
    if (
        abs(source_energy - checkpoint["energy_hartree"]) > 1e-10
        or asdict(source_resources.snapshot) != checkpoint["resources"]["snapshot"]
    ):
        raise V41S6RegressionError("LiH source reconstruction drift")
    blocks = recover_dvg_blocks(
        pool, source.indices, source.coefficients, source.cumulative_parameter_counts
    )
    representatives: dict[str, Any] = {}
    for candidate in enumerate_candidates(pool, blocks):
        representatives.setdefault(candidate.equivalence_class_id, candidate)
    current = tuple(representatives.values())
    stored_catalog = {
        item["candidate_id"]: item for item in old_summary["catalog"]["candidates"]
    }
    mapped = []
    mapping = []
    for old_id in old_accepted["candidate_ids"]:
        matches = [candidate for candidate in current if _matches_stored(candidate, stored_catalog[old_id])]
        if len(matches) != 1:
            raise V41S6RegressionError("LiH accepted candidate mapping is not unique")
        mapped.append(matches[0])
        mapping.append({"v4_candidate_id": old_id, "v4_1_candidate_id": matches[0].candidate_id})
    plan = compose_registered_candidates(source, blocks, tuple(mapped))
    internal = secant_pairs_from_capture(
        checkpoint["hessian_capture"]["secant_pairs"], required_source="internal-bfgs"
    )
    prediction = joint_obs_prediction(
        checkpoint["ansatz_coefficients"], checkpoint["gradient"],
        checkpoint["recycled_inverse_hessian"], plan.transformation,
        internal_pairs=internal, held_out_pairs=(),
    )
    quality = evaluate_joint_quality(prediction, _quality_policy())
    prediction_delta = (
        prediction["predicted_change_from_current_hartree"]
        - old_accepted["prediction"]["predicted_change_from_current_hartree"]
    )
    if not quality["passed"] or abs(prediction_delta) > 1e-10:
        raise V41S6RegressionError("LiH prediction or scale-aware quality drift")
    checkpoint_sha256 = hashlib.sha256(LIH_CHECKPOINT.read_bytes()).hexdigest()
    random.seed(0)
    np.random.seed(0)
    with CaseRunLease(
        output_root, "lih-3.0", s0["manifest_sha256"], checkpoint_sha256
    ) as lease:
        rejection = _execute_attempt(
            attempt_number=1, algorithm=algorithm, pool=pool, source=source,
            checkpoint=checkpoint, source_state=source_state,
            source_resources=source_resources, plan=plan, prediction=prediction,
            transaction_root=lease.staging / "transactions",
            configuration_digest=freeze["head"],
            run_id="v4.1-s6-lih-regression-rejection",
            transaction_prefix="v4.1-s6-reject",
            cumulative_energy_budget_hartree=0.0,
        )
        acceptance = _execute_attempt(
            attempt_number=2, algorithm=algorithm, pool=pool, source=source,
            checkpoint=checkpoint, source_state=source_state,
            source_resources=source_resources, plan=plan, prediction=prediction,
            transaction_root=lease.staging / "transactions",
            configuration_digest=freeze["head"],
            run_id="v4.1-s6-lih-regression-acceptance",
            transaction_prefix="v4.1-s6-accept",
            cumulative_energy_budget_hartree=1e-4,
        )
        if rejection["transaction_status"] != "rolled-back" or not rejection["rollback_exact"]:
            raise V41S6RegressionError("deterministic LiH rejection did not roll back exactly")
        if acceptance["transaction_status"] != "accepted":
            raise V41S6RegressionError("LiH accepted regression candidate was lost")
        current_path = acceptance["fallback"] or acceptance["primary"]
        old_path = old_accepted["fallback"] or old_accepted["primary"]
        resource_equal = (
            acceptance["physical_resources"]["snapshot"]
            == old_accepted["physical_resources"]["snapshot"]
        )
        final_energy_delta = current_path["energy_hartree"] - old_path["energy_hartree"]
        if abs(final_energy_delta) > 1e-10 or not resource_equal:
            raise V41S6RegressionError("LiH exact result or resource regression drift")
        result: dict[str, Any] = {
            "schema_version": "1.0.0",
            "artifact_kind": "v4.1-s6-regression-and-transaction-rehearsal",
            "execution_freeze": freeze,
            "s0_manifest_sha256": s0["manifest_sha256"],
            "h2_h4": h2_h4,
            "lih": {
                "checkpoint_sha256": checkpoint_sha256,
                "candidate_mapping": mapping,
                "constraint_semantic_id": plan.state.constraint_semantic_id,
                "constraint_numerical_id": plan.state.constraint_numerical_id,
                "prediction": prediction,
                "quality": quality,
                "v4_prediction_delta_hartree": prediction_delta,
                "v4_final_energy_delta_hartree": final_energy_delta,
                "v4_resource_snapshot_equal": resource_equal,
                "source_energy_hartree": source_energy,
                "source_resources": asdict(source_resources.snapshot),
                "deterministic_rejection": rejection,
                "accepted_replay": acceptance,
            },
            "actual_candidate_energy_evaluations": 2,
            "paper_measurement_cost": None,
            "passed": True,
            "claim_boundary": "H2/H4 regression and observed LiH transaction rehearsal only; no new search, ranking, generalization, or paper Measurement Cost claim.",
        }
        result["summary_digest"] = _digest(result)
        _write_exclusive(lease.staging / "summary.json", result)
        lease.finalize()
        canonical = lease.promote()
    return {"path": str(canonical), "summary_digest": result["summary_digest"], "passed": True}


def main() -> None:
    print(json.dumps(run(), sort_keys=True))


if __name__ == "__main__":
    main()

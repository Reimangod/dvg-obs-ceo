"""Independent per-case audit for frozen-sentinel V4.1 exact results."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from .baseline import ROOT
from .block_ir import enumerate_candidates, recover_dvg_blocks
from .composition import compose_registered_candidates
from .identity import canonical_json_bytes
from .multisystem_checkpoint import _algorithm
from .resources import (
    AnsatzStructure,
    evaluate_full_circuit_resources,
    paper_era_backend,
    resources_to_dict,
)
from .s8_probe import _state_vector
from .transaction import RuntimeSnapshot
from .v3_protocol import _write_exclusive
from .v4_lih import _energy, _gradient
from .v4_1_bundle import audit_case_state, validate_complete_bundle
from .v4_1_exact_multisystem import OUTPUT_ROOT, S5_ROOT, _read_summary
from .v4_1_multisystem import replay_selection_from_resource_evidence
from .v4_1_protocol import DEFAULT_MANIFEST, audit_manifest


class V41ExactAuditError(RuntimeError):
    """Raised when independently reconstructed exact evidence is inconsistent."""


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _contains_key(value: Any, forbidden: str) -> bool:
    if isinstance(value, dict):
        return any(key == forbidden or _contains_key(item, forbidden) for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_key(item, forbidden) for item in value)
    return False


def _resource_snapshots_equal(physical: dict[str, Any], structural: dict[str, Any]) -> bool:
    """Compare counted resources while retaining distinct policy provenance."""

    return physical["snapshot"] == structural["snapshot"]


def _same_unique_candidate_set(left: list[str], right: list[str]) -> bool:
    """Candidate composition is order-independent but duplicate candidates are invalid."""

    return (
        len(left) == len(set(left))
        and len(right) == len(set(right))
        and sorted(left) == sorted(right)
    )


def audit_case(case_id: str, artifact_path: Path | None = None) -> dict[str, Any]:
    s0 = audit_manifest(DEFAULT_MANIFEST)
    manifest = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    case = next(item for item in manifest["cases"] if item["case_id"] == case_id)
    bundle = OUTPUT_ROOT / case_id
    bundle_manifest = validate_complete_bundle(bundle)
    summary = _read_summary(bundle / "summary.json")
    s5_bundle_manifest = validate_complete_bundle(S5_ROOT / case_id)
    s5 = _read_summary(S5_ROOT / case_id / "summary.json")
    checkpoint = json.loads((ROOT / case["checkpoint_path"]).read_text(encoding="utf-8"))
    stored_checkpoint_digest = checkpoint.pop("checkpoint_digest")
    checkpoint_digest_ok = _digest(checkpoint) == stored_checkpoint_digest
    checkpoint["checkpoint_digest"] = stored_checkpoint_digest

    algorithm, pool = _algorithm(checkpoint["case"])
    algorithm.initialize()
    source = AnsatzStructure.create(
        checkpoint["ansatz_indices"], checkpoint["ansatz_coefficients"], checkpoint["iteration_counts"]
    )
    source_state = _state_vector(algorithm, source.coefficients, source.indices)
    source_state_digest = hashlib.sha256(np.asarray(source_state, dtype=">c16").tobytes()).hexdigest()
    source_energy = _energy(algorithm, np.asarray(source.coefficients), source.indices)
    source_resources = evaluate_full_circuit_resources(pool, source, paper_era_backend())
    blocks = recover_dvg_blocks(pool, source.indices, source.coefficients, source.cumulative_parameter_counts)
    representatives: dict[str, Any] = {}
    for candidate in enumerate_candidates(pool, blocks):
        representatives.setdefault(candidate.equivalence_class_id, candidate)
    by_id = {candidate.candidate_id: candidate for candidate in representatives.values()}

    attempts = summary["attempts"]
    attempt_checks: list[dict[str, Any]] = []
    transaction_hashes: dict[str, str] = {}
    for attempt, frozen in zip(attempts, s5["sentinels"]):
        plan = compose_registered_candidates(
            source, blocks, tuple(by_id[value] for value in frozen["candidate_ids"])
        )
        selected = attempt["fallback"] if attempt["fallback"] is not None else attempt["primary"]
        coordinates = np.asarray(selected["coordinates"], dtype=np.float64)
        target = AnsatzStructure.create(plan.target_indices, coordinates, plan.target_iteration_counts)
        energy = _energy(algorithm, coordinates, plan.target_indices)
        gradient = _gradient(algorithm, coordinates, plan.target_indices)
        state = _state_vector(algorithm, coordinates, plan.target_indices)
        resources = evaluate_full_circuit_resources(pool, target, paper_era_backend())
        transaction = bundle / attempt["transaction_path"]
        terminal_name = "commit.json" if attempt["transaction_status"] == "accepted" else "rollback.json"
        required = ("attempt.json", "snapshot.json", "trial.json", terminal_name)
        layout = transaction.is_dir() and all((transaction / name).is_file() for name in required)
        snapshot_valid = False
        terminal_valid = False
        if layout:
            snapshot_value = json.loads((transaction / "snapshot.json").read_text(encoding="utf-8"))
            snapshot = RuntimeSnapshot.from_dict(snapshot_value)
            terminal = json.loads((transaction / terminal_name).read_text(encoding="utf-8"))
            snapshot_valid = snapshot.snapshot_digest == attempt["before_snapshot_digest"]
            if attempt["transaction_status"] == "accepted":
                terminal_valid = (
                    terminal["before_snapshot_digest"] == snapshot.snapshot_digest
                    and terminal["acceptance"] == attempt["acceptance"]
                )
            else:
                terminal_valid = (
                    terminal["before_snapshot_digest"] == snapshot.snapshot_digest
                    and terminal["restored_snapshot_digest"] == snapshot.snapshot_digest
                    and attempt["after_rollback_snapshot_digest"] == snapshot.snapshot_digest
                    and attempt["rollback_exact"] is True
                )
            for name in required:
                path = transaction / name
                transaction_hashes[str(path.relative_to(bundle))] = _sha256(path)
        checks = {
            "queue_identity": (
                _same_unique_candidate_set(attempt["candidate_ids"], frozen["candidate_ids"])
                and attempt["constraint_semantic_id"] == frozen["constraint_semantic_id"]
                and attempt["constraint_numerical_id"] == frozen["constraint_numerical_id"]
            ),
            "plan_replay": (
                plan.state.constraint_semantic_id == attempt["constraint_semantic_id"]
                and plan.state.constraint_numerical_id == attempt["constraint_numerical_id"]
            ),
            "sentinel_replay": all(attempt["sentinel_replay_checks"].values()),
            "energy_recomputed": abs(energy - float(selected["energy_hartree"])) <= 1e-10,
            "independent_energy_recomputed": abs(energy - float(selected["independent_energy_hartree"])) <= 1e-10,
            "gradient_recomputed": abs(float(np.max(np.abs(gradient))) - float(selected["gradient_infinity"])) <= 1e-8,
            "state_normalized": abs(float(np.vdot(state, state).real) - 1.0) <= 1e-10,
            "resources_recomputed": resources_to_dict(resources) == attempt["physical_resources"],
            # The two records intentionally name different coefficient policies.
            # Acceptance is bound to the synthesized resource snapshot itself.
            "physical_structural_snapshot_equal": _resource_snapshots_equal(
                attempt["physical_resources"], attempt["structural_resources"]
            ),
            "quality_passed": attempt["quality"]["passed"] is True,
            "two_path_certificate": attempt["two_path_certificate"]["passed"] is True,
            "transaction_layout": layout,
            "snapshot_valid": snapshot_valid,
            "terminal_record_valid": terminal_valid,
            "acceptance_status": (
                attempt["acceptance"]["accepted"]
                == (attempt["transaction_status"] == "accepted")
            ),
            "accepted_all_checks": (
                attempt["transaction_status"] != "accepted"
                or all(attempt["acceptance"]["checks"].values())
            ),
            "rejection_has_reason": (
                attempt["transaction_status"] != "rolled-back"
                or bool(attempt["acceptance"]["rejection_reasons"])
            ),
        }
        attempt_checks.append({
            "constraint_semantic_id": attempt["constraint_semantic_id"],
            "status": attempt["transaction_status"],
            "checks": checks,
            "failed_checks": [name for name, passed in checks.items() if not passed],
            "independent_energy_hartree": energy,
            "independent_gradient_infinity": float(np.max(np.abs(gradient))),
            "independent_resources": asdict(resources.snapshot),
        })

    by_semantic = {item["constraint_semantic_id"]: item for item in attempts}

    def expected_winner(endpoint: str) -> str | None:
        return next((
            semantic_id for semantic_id in s5["selection"][endpoint]
            if semantic_id in by_semantic and by_semantic[semantic_id]["transaction_status"] == "accepted"
        ), None)

    state = audit_case_state(OUTPUT_ROOT, case_id)
    endpoint_names = ("cnot_primary", "cnot_depth_primary", "total_depth_primary", "parameter_primary")
    accepted = [item for item in attempts if item["transaction_status"] == "accepted"]
    checks = {
        "s0_manifest": summary["execution_freeze"]["s0_manifest_sha256"] == s0["manifest_sha256"],
        "checkpoint_internal_digest": checkpoint_digest_ok,
        "checkpoint_file_sha256": _sha256(ROOT / case["checkpoint_path"]) == case["checkpoint_sha256"],
        "bundle_complete": bundle_manifest["case_id"] == case_id,
        "canonical_state": (
            state["canonical_status"] == "complete"
            and state["canonical_bundle_digest"] == bundle_manifest["bundle_digest"]
            and state["lock_status"] == "absent" and not state["staging"] and not state["ambiguous"]
        ),
        "source_energy": abs(source_energy - checkpoint["energy_hartree"]) <= 1e-10,
        "source_state": source_state_digest == checkpoint["statevector_sha256"],
        "source_resources": asdict(source_resources.snapshot) == checkpoint["resources"]["snapshot"],
        "s5_bundle": summary["s5_frozen_selection"]["bundle_digest"] == s5_bundle_manifest["bundle_digest"],
        "s5_summary": summary["s5_frozen_selection"]["summary_digest"] == s5["summary_digest"],
        "s5_selection_replay": replay_selection_from_resource_evidence(s5) == s5["selection"],
        "energy_blind_selection": (
            not _contains_key(s5["selection"], "actual_energy_hartree")
            and not _contains_key(s5["search"], "actual_energy_hartree")
            and s5["actual_candidate_energy_evaluations"] == 0
            and s5["exact_or_fci_energy_used"] is False
        ),
        "queue_complete_and_ordered": (
            len(attempts) == len(s5["sentinels"])
            and [item["constraint_semantic_id"] for item in attempts]
            == s5["selection"]["unique_attempt_semantic_ids"]
        ),
        "attempt_audits": all(not item["failed_checks"] for item in attempt_checks),
        "endpoint_winners": all(
            summary["endpoint_winners"][endpoint] == expected_winner(endpoint)
            for endpoint in endpoint_names
        ),
        "cumulative_energy_budget": all(
            (item["fallback"] or item["primary"])["energy_hartree"] - checkpoint["energy_hartree"]
            <= summary["accuracy_guard"]["effective_cumulative_budget_hartree"] + 1e-12
            for item in accepted
        ),
        "chemical_accuracy_retained": all(
            (item["fallback"] or item["primary"])["energy_hartree"]
            < checkpoint["exact_energy_hartree"] + checkpoint["chemical_accuracy_hartree"]
            for item in accepted
        ),
        "measurement_cost_unclaimed": summary["work"]["paper_measurement_cost"] is None,
        "search_status_preserved": summary["search_completeness"] == s5["search"]["status"],
        "no_ansatz_growth": (
            summary["work"]["new_ceo_star_adapt_iterations"] == 0
            and summary["work"]["new_ordinary_adapt_iterations"] == 0
        ),
    }
    failed = [name for name, passed in checks.items() if not passed]
    result: dict[str, Any] = {
        "schema_version": "1.0.0",
        "artifact_kind": "v4.1-frozen-sentinel-independent-case-audit",
        "case_id": case_id,
        "passed": not failed,
        "checks": checks,
        "failed_checks": failed,
        "attempt_audits": attempt_checks,
        "summary_sha256": _sha256(bundle / "summary.json"),
        "summary_digest": summary["summary_digest"],
        "bundle_digest": bundle_manifest["bundle_digest"],
        "transaction_sha256": transaction_hashes,
        "claim_boundary": "Independent observed-case audit; no global-optimum or generalization claim.",
    }
    result["artifact_digest"] = _digest(result)
    if artifact_path is not None:
        _write_exclusive(artifact_path, result)
    if failed:
        raise V41ExactAuditError("independent exact audit failed: " + ", ".join(failed))
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("case_id", choices=("h6-1.5", "h6-3.0", "beh2-3.0"))
    parser.add_argument("--artifact-path", type=Path)
    args = parser.parse_args()
    result = audit_case(args.case_id, args.artifact_path)
    print(json.dumps({"case_id": args.case_id, "passed": result["passed"]}, sort_keys=True))


if __name__ == "__main__":
    main()

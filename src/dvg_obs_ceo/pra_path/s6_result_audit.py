"""Independent invariant audit for the frozen PRA S6 result."""

from __future__ import annotations

import json
import math
from pathlib import Path
import subprocess
from typing import Any

from dvg_obs_ceo.artifact_io import atomic_write_new_json
from dvg_obs_ceo.baseline import ROOT
from dvg_obs_ceo.identity import sha256_hex

from .s6_development_evaluation import FREEZE_OUTPUT, RESULT_OUTPUT


OUTPUT = ROOT / "artifacts/pra_path/s6/result-audit-v1.json"


class S6ResultAuditError(RuntimeError):
    """Raised when S6 result and freeze do not reconcile."""


def _git(*arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _verified_json(path: Path, digest_field: str) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    content = dict(payload)
    digest = content.pop(digest_field, None)
    if digest != sha256_hex(content):
        raise S6ResultAuditError(f"digest mismatch: {path}")
    return payload


def build_audit() -> dict[str, Any]:
    freeze = _verified_json(FREEZE_OUTPUT, "freeze_digest")
    result = _verified_json(RESULT_OUTPUT, "report_digest")
    queue_ids = [item["queue_id"] for item in freeze["queue"]]
    attempted_ids = [item["queue_item"]["queue_id"] for item in result["attempts"]]
    queue_exactly_once = (
        len(queue_ids) == len(set(queue_ids))
        and len(attempted_ids) == len(set(attempted_ids))
        and set(queue_ids) == set(attempted_ids)
    )
    acceptance_integrity = []
    numeric_integrity = []
    transaction_integrity = []
    for attempt in result["attempts"]:
        accepted = bool(attempt["acceptance"]["accepted"])
        checks = attempt["acceptance"]["checks"]
        classification_expected = (
            "PRIMARY_NATIVE_RANK2_ACCEPTED"
            if accepted
            else "PRIMARY_NATIVE_RANK2_REJECTED"
        )
        acceptance_integrity.append(
            attempt["classification"] == classification_expected
            and accepted == all(checks.values())
            and (
                not attempt["acceptance"]["rejection_reasons"]
                if accepted
                else bool(attempt["acceptance"]["rejection_reasons"])
            )
        )
        certification = attempt["certification"]
        scalar_values = [
            certification[key]
            for key in (
                "candidate_energy_hartree",
                "semantic_energy_hartree",
                "native_energy_hartree",
                "source_relative_loss_hartree",
                "candidate_full_source_coordinate_gradient_infinity",
                "candidate_target_coordinate_gradient_infinity",
                "candidate_orthonormal_tangent_gradient_infinity",
                "normal_component_l2",
                "constraint_residual",
                "semantic_native_state_fidelity",
            )
        ]
        numeric_integrity.append(all(math.isfinite(value) for value in scalar_values))
        transaction = attempt["transaction"]
        transaction_integrity.append(
            transaction["source_immutable"]
            and transaction["source_snapshot_before"]
            == transaction["source_snapshot_after"]
            and transaction["committed_to_primary_lineage"] is False
            and transaction["rollback_complete"] is True
        )
    summaries = {item["case_id"]: item for item in result["case_summaries"]}
    h5_attempts = [
        item for item in result["attempts"]
        if item["queue_item"]["case_id"] == "h5-1.5"
    ]
    h5_failure_signature = {
        "attempt_count": len(h5_attempts),
        "all_rejected": all(not item["acceptance"]["accepted"] for item in h5_attempts),
        "all_hit_optimizer_iteration_cap": all(
            item["optimizer"]["iterations"] == freeze["protocol"]["maximum_iterations"]
            and item["optimizer"]["message"]
            == "Maximum number of iterations has been exceeded."
            for item in h5_attempts
        ),
        "all_fail_orthonormal_tangent_stationarity": all(
            not item["acceptance"]["checks"]["kkt"] for item in h5_attempts
        ),
        "all_pass_energy_budget": all(
            item["acceptance"]["checks"]["cumulative_energy_budget"]
            for item in h5_attempts
        ),
        "all_pass_semantic_native_evidence": all(
            item["acceptance"]["checks"]["independent_energy_agreement"]
            and item["acceptance"]["checks"]["independent_state_fidelity"]
            and item["acceptance"]["checks"]["constraint"]
            and item["acceptance"]["checks"]["transformation_semantics"]
            for item in h5_attempts
        ),
        "all_pass_resource_policy": all(
            item["acceptance"]["checks"]["pareto_nonworse"]
            and item["acceptance"]["checks"]["resource_improved"]
            for item in h5_attempts
        ),
    }
    checks = {
        "queue_attempted_exactly_once": queue_exactly_once,
        "all_acceptance_records_self_consistent": all(acceptance_integrity),
        "all_numeric_evidence_finite": all(numeric_integrity),
        "all_attempts_preserve_source_and_rollback": all(transaction_integrity),
        "summary_attempt_count": result["summary"]["attempted"] == len(queue_ids),
        "summary_acceptance_count": result["summary"]["accepted"]
        == sum(item["acceptance"]["accepted"] for item in result["attempts"]),
        "two_h4_conditions_positive": all(
            summaries[case]["new_energy_resource_nondominated_point"]
            for case in ("h4-1.0", "h4-2.0")
        ),
        "h5_not_certified": summaries["h5-1.5"][
            "new_energy_resource_nondominated_point"
        ] is False,
        "h5_failure_signature_complete": all(h5_failure_signature.values()),
        "s7_not_authorized": result["authorization"]["s7"] is False,
        "prospective_not_authorized": result["authorization"][
            "prospective_execution"
        ] is False,
    }
    if not all(checks.values()):
        raise S6ResultAuditError(
            f"S6 invariant audit failed: "
            f"{[name for name, passed in checks.items() if not passed]}"
        )
    audit: dict[str, Any] = {
        "schema": "dvg-obs-ceo.pra-path.s6-result-audit.v1",
        "decision": "S6_RESULT_VALID_NO_GO_PERFORMANCE_ROUTE",
        "inputs": {
            "queue_freeze_digest": freeze["freeze_digest"],
            "result_report_digest": result["report_digest"],
        },
        "checks": checks,
        "case_summaries": result["case_summaries"],
        "h5_failure_signature": h5_failure_signature,
        "failure_interpretation": {
            "classification": "OPTIMIZER_CAP_AND_STATIONARITY_NOT_CERTIFIED",
            "engineering_corruption_detected": False,
            "energy_or_resource_failure": False,
            "threshold_relaxation_authorized": False,
            "post_outcome_optimizer_change_authorized": False,
            "statement": (
                "The frozen H5 candidates are energy- and resource-feasible "
                "but are not certified because the fixed optimizer reaches "
                "200 iterations before the coordinate-invariant tangent "
                "stationarity threshold. This is a valid negative result, not "
                "evidence of a corrupt artifact."
            ),
        },
        "authorization": {
            "s7": False,
            "s8": False,
            "s9": False,
            "s10_closure_gate": True,
            "s11_negative_result_release": True,
        },
        "execution": {"git_commit": _git("rev-parse", "HEAD")},
        "claim_boundary": (
            "Audits the frozen S6 result only. It does not rescue H5, alter "
            "the protocol, or establish matched-work or prospective evidence."
        ),
    }
    audit["audit_digest"] = sha256_hex(audit)
    return audit


def main() -> None:
    if OUTPUT.exists():
        raise S6ResultAuditError("refusing to overwrite S6 result audit")
    if _git("status", "--porcelain"):
        raise S6ResultAuditError("S6 result audit requires a clean worktree")
    atomic_write_new_json(OUTPUT, build_audit())


if __name__ == "__main__":
    main()

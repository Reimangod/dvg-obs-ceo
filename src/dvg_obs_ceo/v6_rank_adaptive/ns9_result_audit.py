"""Independent audit of the frozen V6-NS9 sequential pilot."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from typing import Any

from dvg_obs_ceo.artifact_io import atomic_write_new_json
from dvg_obs_ceo.baseline import ROOT
from dvg_obs_ceo.identity import sha256_hex

from .ns9_sequential_pilot import (
    FREEZE_OUTPUT,
    RESULT_OUTPUT,
    RUNNER_VERSION,
    WORK_CAP,
)


AUDIT_OUTPUT = ROOT / "artifacts/v6/ns9/result-audit-v1.json"
AUDIT_VERSION = "v6-ns9-independent-result-audit-v1"


class NS9ResultAuditError(RuntimeError):
    """Raised when the NS9 result is inconsistent."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit_result(result_path: Path = RESULT_OUTPUT) -> dict[str, Any]:
    report = json.loads(result_path.read_text(encoding="utf-8"))
    freeze = json.loads(FREEZE_OUTPUT.read_text(encoding="utf-8"))
    content = dict(report)
    digest = content.pop("report_digest")
    freeze_content = dict(freeze)
    freeze_digest = freeze_content.pop("freeze_digest")
    attempts = report["attempts"]
    accepted = [
        item for item in attempts if item["acceptance"]["accepted"]
    ]
    rejected = [
        item for item in attempts if not item["acceptance"]["accepted"]
    ]
    checks = {
        "report_digest": digest == sha256_hex(content),
        "freeze_digest": freeze_digest == sha256_hex(freeze_content),
        "freeze_sha256": (
            report["freeze"]["sha256"] == _sha256(FREEZE_OUTPUT)
        ),
        "runner_version": report["runner_version"] == RUNNER_VERSION,
        "queue_order_preserved": (
            [item["queue_item"] for item in attempts] == freeze["queue"]
        ),
        "exactly_four_attempts": len(attempts) == 4,
        "three_accept_one_reject": (
            len(accepted) == 3 and len(rejected) == 1
        ),
        "acceptance_conjunction": all(
            item["acceptance"]["accepted"]
            == all(item["acceptance"]["checks"].values())
            for item in attempts
        ),
        "accepted_stationary_and_inside_budget": all(
            item["certification"]["target_gradient_infinity"] <= 1e-8
            and item["certification"]["source_relative_loss_hartree"]
            <= 1e-4
            and item["optimizer"]["success"] is True
            for item in accepted
        ),
        "single_rejection_is_kkt_and_optimizer": (
            rejected[0]["acceptance"]["rejection_reasons"]
            == ["kkt", "optimizer_path_reviewed"]
            and rejected[0]["certification"]["target_gradient_infinity"]
            > 1e-8
        ),
        "semantic_native_equivalence": all(
            item["certification"]["semantic_native_state_fidelity"]
            >= 1.0 - 1e-10
            and max(
                record["absolute_error"]
                for record in item["certification"][
                    "finite_difference_spot_checks"
                ].values()
            )
            <= 1e-6
            for item in attempts
        ),
        "source_state_preserved_for_accepted": all(
            item["certification"]["source_candidate_state_fidelity"]
            >= 1.0 - 1e-12
            for item in accepted
        ),
        "full_resource_gain": all(
            item["resources"]["delta"]["cnot_count"] == -4
            and item["resources"]["delta"]["cnot_depth"] == -2
            and item["resources"]["delta"]["total_depth"] == -8
            and item["resources"]["delta"]["parameter_count"] == -2
            and item["resources"]["independent_repeat_equal"] is True
            for item in attempts
        ),
        "work_caps_reconcile": (
            report["work"]["cap"] == WORK_CAP
            and all(report["work"]["checks"].values())
            and all(
                report["work"]["observed"][name] <= maximum
                for name, maximum in WORK_CAP.items()
            )
        ),
        "frontier_gate_reconciles": (
            len(report["frontier_checks"]) == len(accepted)
            and all(
                item["adds_legacy_nondominated_point"]
                and not item["dominated_by_legacy"]
                for item in report["frontier_checks"]
            )
            and report["summary"]["scientific_frontier_gate"]
            == "PASS_NEW_LEGACY_NONDOMINATED_POINT"
        ),
        "h6_ablation_authorized_but_pra_not_claimed": (
            report["summary"]["h6_optimizer_ablation_authorized"] is True
            and report["summary"]["pra_performance_claim_established"]
            is False
            and report["paper_measurement_cost"] is None
        ),
        "roots_immutable": all(
            item["functional_roots_immutable"] is True for item in attempts
        ),
    }
    audit = {
        "schema_version": "1.0.0",
        "artifact_kind": "v6-ns9-independent-result-audit",
        "audit_version": AUDIT_VERSION,
        "result_path": str(result_path.relative_to(ROOT)),
        "result_sha256": _sha256(result_path),
        "checks": checks,
        "passed": all(checks.values()),
        "claim_boundary": (
            "Independent queue, arithmetic, certificate, resource, work-cap, "
            "and frontier reconciliation; quantum kernels are not rerun."
        ),
    }
    audit["audit_digest"] = sha256_hex(audit)
    if not audit["passed"]:
        raise NS9ResultAuditError(
            "failed checks: "
            + ", ".join(
                name for name, value in checks.items() if not value
            )
        )
    return audit


def main() -> None:
    try:
        audit = audit_result()
        atomic_write_new_json(AUDIT_OUTPUT, audit)
    except (
        KeyError,
        OSError,
        TypeError,
        ValueError,
        NS9ResultAuditError,
    ) as error:
        print(f"V6-NS9 result audit failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    print(json.dumps(audit, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

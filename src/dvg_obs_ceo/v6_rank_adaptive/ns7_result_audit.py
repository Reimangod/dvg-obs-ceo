"""Independent structural and arithmetic audit of the V6-NS7 result."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any

from dvg_obs_ceo.artifact_io import atomic_write_new_json
from dvg_obs_ceo.baseline import ROOT
from dvg_obs_ceo.identity import sha256_hex

from .ns7_energy_certification import (
    DEFAULT_OUTPUT,
    ENERGY_AGREEMENT_TOLERANCE,
    ENERGY_BUDGET_HARTREE,
    RUNNER_VERSION,
    STATE_FIDELITY_TOLERANCE,
    STATIONARITY_TOLERANCE,
)


AUDIT_VERSION = "v6-ns7-result-audit-v1"
DEFAULT_AUDIT_OUTPUT = ROOT / "artifacts/v6/ns7/result-audit-v1.json"


class NS7ResultAuditError(RuntimeError):
    """Raised when an NS7 result is internally inconsistent."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _resource_gate(delta: dict[str, int]) -> bool:
    cnot = int(delta["cnot_count"])
    cnot_depth = int(delta["cnot_depth"])
    total_depth = int(delta["total_depth"])
    parameters = int(delta["parameter_count"])
    return (
        (cnot < 0 and cnot_depth <= 0)
        or (cnot <= 0 and cnot_depth < 0)
        or (
            cnot <= 0
            and cnot_depth <= 0
            and total_depth < 0
            and parameters < 0
        )
    )


def audit_result(result_path: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    report = json.loads(result_path.read_text(encoding="utf-8"))
    content = dict(report)
    observed_digest = content.pop("report_digest")
    attempts = report["attempts"]
    queue = report["execution_freeze"]["queue"]
    summary = report["summary"]
    accepted = [
        item for item in attempts if item["acceptance"]["accepted"]
    ]

    checks: dict[str, bool] = {
        "report_digest": observed_digest == sha256_hex(content),
        "runner_version": report.get("runner_version") == RUNNER_VERSION,
        "development_only": report.get("development_only") is True,
        "worktree_was_clean": (
            report["execution_freeze"]["worktree_clean"] is True
            and "--dirty"
            not in report["execution_freeze"]["git_describe"]
        ),
        "queue_order_preserved": [
            item["queue_item"] for item in attempts
        ]
        == queue,
        "queue_count_preserved": (
            len(attempts)
            == len(queue)
            == report["execution_freeze"]["queue_count"]
            == summary["attempted"]
        ),
        "outcome_blind_queue": (
            report["execution_freeze"][
                "candidate_outcomes_may_change_queue"
            ]
            is False
        ),
        "source_lineage_immutable": all(
            item["functional_attempt_source_immutable"] is True
            and item["primary_lineage_mutated"] is False
            and item["source"]["snapshot_digest_before"]
            == item["source"]["snapshot_digest_after"]
            for item in attempts
        ),
        "summary_counts_reconcile": (
            summary["accepted"] == len(accepted)
            and summary["rejected"] == len(attempts) - len(accepted)
            and summary["accepted_attempt_ids"]
            == [item["attempt_id"] for item in accepted]
        ),
        "classification_reconciles": all(
            item["classification"]
            == (
                "PRIMARY_NATIVE_RANK2_ACCEPTED"
                if item["acceptance"]["accepted"]
                else "PRIMARY_NATIVE_RANK2_REJECTED"
            )
            for item in attempts
        ),
        "acceptance_is_conjunction": all(
            item["acceptance"]["accepted"]
            == all(item["acceptance"]["checks"].values())
            for item in attempts
        ),
        "energy_arithmetic": all(
            math.isclose(
                item["certification"]["actual_loss_hartree"],
                item["certification"][
                    "independent_native_energy_hartree"
                ]
                - item["source"]["energy_hartree"],
                rel_tol=0.0,
                abs_tol=1e-15,
            )
            for item in attempts
        ),
        "independent_energy_agreement": all(
            abs(
                item["certification"]["candidate_energy_hartree"]
                - item["certification"][
                    "independent_native_energy_hartree"
                ]
            )
            <= ENERGY_AGREEMENT_TOLERANCE
            for item in attempts
        ),
        "semantic_native_fidelity": all(
            item["certification"]["semantic_native_state_fidelity"]
            >= 1.0 - STATE_FIDELITY_TOLERANCE
            for item in attempts
        ),
        "finite_difference_spot_checks": all(
            max(
                check["absolute_error"]
                for check in item["certification"][
                    "finite_difference_spot_checks"
                ].values()
            )
            <= 1e-6
            for item in attempts
        ),
        "resource_recounts_match_ns5": all(
            all(item["resources"]["recount_checks"].values())
            and all(
                item["resources"]["observed"][field]
                == item["resources"]["expected_ns5"][field]
                for field in (
                    "cnot_count",
                    "cnot_depth",
                    "total_depth",
                    "parameter_count",
                    "logical_block_count",
                    "counter_version",
                )
            )
            for item in attempts
        ),
        "hard_resource_gate": all(
            _resource_gate(item["resources"]["delta"])
            for item in attempts
        ),
        "accepted_energy_and_stationarity": all(
            item["certification"]["actual_loss_hartree"]
            <= ENERGY_BUDGET_HARTREE
            and item["certification"]["target_gradient_infinity"]
            <= STATIONARITY_TOLERANCE
            and item["optimizer"]["success"] is True
            for item in accepted
        ),
        "rejections_are_not_resource_or_semantic_failures": all(
            item["acceptance"]["rejection_reasons"]
            == ["kkt", "optimizer_path_reviewed"]
            for item in attempts
            if not item["acceptance"]["accepted"]
        ),
        "accepted_contexts_reconcile": summary[
            "contexts_with_acceptance"
        ]
        == sorted(
            {
                item["queue_item"]["context_id"]
                for item in accepted
            }
        ),
        "no_validation_or_pra_claim": (
            summary["validation_context_attempted"] is False
            and summary["pra_performance_claim_established"] is False
            and report["paper_measurement_cost"] is None
        ),
    }
    for name, value in report["execution_freeze"]["inputs"].items():
        path = ROOT / value["path"]
        checks[f"input_hash_{name}"] = (
            path.is_file() and _sha256(path) == value["sha256"]
        )

    audit = {
        "schema_version": "1.0.0",
        "artifact_kind": "v6-ns7-independent-result-audit",
        "audit_version": AUDIT_VERSION,
        "result_path": str(result_path.relative_to(ROOT)),
        "result_sha256": _sha256(result_path),
        "checks": checks,
        "passed": all(checks.values()),
        "outcome_summary": {
            "attempted": len(attempts),
            "accepted": len(accepted),
            "accepted_contexts": summary["contexts_with_acceptance"],
            "maximum_finite_difference_error": max(
                check["absolute_error"]
                for item in attempts
                for check in item["certification"][
                    "finite_difference_spot_checks"
                ].values()
            ),
            "maximum_native_energy_disagreement": max(
                abs(
                    item["certification"]["candidate_energy_hartree"]
                    - item["certification"][
                        "independent_native_energy_hartree"
                    ]
                )
                for item in attempts
            ),
        },
        "claim_boundary": (
            "Independent structural, arithmetic, queue, resource, and "
            "certificate audit of the frozen NS7 report. It does not rerun "
            "quantum kernels and does not establish cross-molecule or PRA "
            "performance."
        ),
    }
    audit["audit_digest"] = sha256_hex(audit)
    if not audit["passed"]:
        failed = [name for name, passed in checks.items() if not passed]
        raise NS7ResultAuditError(
            f"V6-NS7 result audit failed: {failed}"
        )
    return audit


def main() -> None:
    try:
        audit = audit_result()
        atomic_write_new_json(DEFAULT_AUDIT_OUTPUT, audit)
    except (
        KeyError,
        OSError,
        TypeError,
        ValueError,
        NS7ResultAuditError,
    ) as error:
        print(f"V6-NS7 result audit failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    print(json.dumps(audit, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

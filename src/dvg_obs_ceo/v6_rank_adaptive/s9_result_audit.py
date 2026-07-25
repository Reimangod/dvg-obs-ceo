"""Independent structural audit of the committed V6-S9 result bundle."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any, Mapping

from dvg_obs_ceo.artifact_io import atomic_write_new_json
from dvg_obs_ceo.baseline import ROOT
from dvg_obs_ceo.identity import sha256_hex

from .s9_certification import DEFAULT_OUTPUT, RUNNER_VERSION


AUDIT_VERSION = "v6-s9-result-audit-v1"
DEFAULT_AUDIT_OUTPUT = ROOT / "artifacts/v6/s9/result-audit-v1.json"


class S9ResultAuditError(RuntimeError):
    """Raised when the S9 result or rollback evidence is inconsistent."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit_result(
    result_path: Path = DEFAULT_OUTPUT,
) -> dict[str, Any]:
    report = json.loads(result_path.read_text(encoding="utf-8"))
    content = dict(report)
    observed_digest = content.pop("report_digest")
    checks: dict[str, bool] = {
        "report_digest": observed_digest == sha256_hex(content),
        "runner_version": report.get("runner_version") == RUNNER_VERSION,
        "development_only": report.get("development_only") is True,
        "fault_audit_passed": report.get("fault_audit", {}).get(
            "all_passed"
        )
        is True,
        "primary_lineage_frozen": (
            report["summary"]["primary_parent_after_s9"]
            == "unchanged-s6-parent"
            and report["summary"][
                "s10_sequential_continuation_authorized"
            ]
            is False
        ),
    }
    for name, value in report["execution_freeze"]["inputs"].items():
        path = ROOT / value["path"]
        checks[f"input_hash_{name}"] = (
            path.is_file() and _sha256(path) == value["sha256"]
        )
    queue = report["execution_freeze"]["candidate_order"]
    results = report["candidate_results"]
    checks["queue_order_preserved"] = [
        item["candidate_id"] for item in results
    ] == queue
    checks["top2_only"] = len(results) == len(queue) == 2
    checks["no_primary_acceptance"] = (
        report["summary"]["circuit_primary_accepted"] == 0
        and all(
            not item["endpoint_decisions"]["circuit_primary"][
                "accepted"
            ]
            for item in results
        )
    )
    checks["classification_reconciles"] = (
        report["summary"]["classification"]
        == "NATIVE_RANK2_NOT_CERTIFIED"
        and report["summary"]["exploratory_feasibility_accepted"] == 0
        and all(
            item["classification"] == "NATIVE_RANK2_NOT_CERTIFIED"
            for item in results
        )
    )
    checks["only_stationarity_failed_exploratory"] = all(
        item["endpoint_decisions"]["exploratory_depth_parameter"][
            "rejection_reasons"
        ]
        == ["kkt"]
        for item in results
    )
    checks["independent_certificates_passed"] = all(
        item["certification"]["semantic_native_state_fidelity"]
        >= 1.0 - 1e-10
        and item["certification"]["two_path_gradient_residual_infinity"]
        <= 1e-8
        and abs(
            item["certification"]["optimizer_energy_hartree"]
            - item["certification"]["independent_native_energy_hartree"]
        )
        <= 1e-10
        and item["resource_recount"]["incident"] is False
        and all(item["resource_recount"]["checks"].values())
        for item in results
    )
    checks["prediction_arithmetic"] = all(
        math.isclose(
            item["prediction"]["signed_error_actual_minus_predicted_hartree"],
            item["prediction"]["actual_postoptimization_loss_hartree"]
            - item["prediction"]["predicted_loss_hartree"],
            rel_tol=0.0,
            abs_tol=1e-18,
        )
        and math.isclose(
            item["prediction"]["absolute_error_hartree"],
            abs(
                item["prediction"][
                    "signed_error_actual_minus_predicted_hartree"
                ]
            ),
            rel_tol=0.0,
            abs_tol=1e-18,
        )
        for item in results
    )
    rollback_checks = []
    for item in results:
        transaction_id = item["transaction_id"]
        failed = (
            result_path.parent
            / "transactions"
            / "failed"
            / transaction_id
        )
        rollback = json.loads(
            (failed / "rollback.json").read_text(encoding="utf-8")
        )
        snapshot = json.loads(
            (failed / "snapshot.json").read_text(encoding="utf-8")
        )
        rollback_checks.append(
            item["transaction_status"] == "rolled-back"
            and item["rollback_exact"] is True
            and rollback["before_snapshot_digest"]
            == rollback["restored_snapshot_digest"]
            == snapshot["snapshot_digest"]
            and not (
                result_path.parent
                / "transactions"
                / "committed"
                / transaction_id
            ).exists()
        )
    checks["all_candidate_rollbacks_exact"] = all(rollback_checks)
    audit = {
        "schema_version": "1.0.0",
        "artifact_kind": "v6-s9-independent-result-audit",
        "audit_version": AUDIT_VERSION,
        "result_path": str(result_path.relative_to(ROOT)),
        "result_sha256": _sha256(result_path),
        "checks": checks,
        "passed": all(checks.values()),
        "claim_boundary": (
            "Structural, arithmetic, input-hash, and transaction-lifecycle "
            "audit of the S9 result. Quantum kernels are checked through the "
            "independent certificates stored by S9, not recomputed here."
        ),
    }
    audit["audit_digest"] = sha256_hex(audit)
    if not audit["passed"]:
        failed = [name for name, passed in checks.items() if not passed]
        raise S9ResultAuditError(
            f"V6-S9 result audit failed: {failed}"
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
        S9ResultAuditError,
    ) as error:
        print(f"V6-S9 result audit failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    print(json.dumps(audit, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

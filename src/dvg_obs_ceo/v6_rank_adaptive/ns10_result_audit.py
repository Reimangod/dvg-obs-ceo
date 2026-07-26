"""Independent audit of the V6-NS10 H6 optimizer ablation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from typing import Any

from dvg_obs_ceo.artifact_io import atomic_write_new_json
from dvg_obs_ceo.baseline import ROOT
from dvg_obs_ceo.identity import sha256_hex

from .ns10_h6_optimizer_ablation import (
    FREEZE_OUTPUT,
    RESULT_OUTPUT,
    RUNNER_VERSION,
    WORK_CAP,
)


AUDIT_OUTPUT = ROOT / "artifacts/v6/ns10/result-audit-v1.json"
AUDIT_VERSION = "v6-ns10-independent-result-audit-v1"


class NS10ResultAuditError(RuntimeError):
    """Raised when the NS10 report is inconsistent."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit_result(result_path: Path = RESULT_OUTPUT) -> dict[str, Any]:
    report = json.loads(result_path.read_text(encoding="utf-8"))
    freeze = json.loads(FREEZE_OUTPUT.read_text(encoding="utf-8"))
    content = dict(report)
    digest = content.pop("report_digest")
    freeze_content = dict(freeze)
    freeze_digest = freeze_content.pop("freeze_digest")
    results = report["results"]
    candidates = [
        item for item in results if item["kind"] == "rank2-trust-region"
    ]
    controls = [
        item for item in results
        if item["kind"] == "same-structure-trust-region-control"
    ]
    checks = {
        "report_digest": digest == sha256_hex(content),
        "freeze_digest": freeze_digest == sha256_hex(freeze_content),
        "freeze_sha256": (
            report["freeze"]["sha256"] == _sha256(FREEZE_OUTPUT)
        ),
        "runner_version": report["runner_version"] == RUNNER_VERSION,
        "queue_order_preserved": (
            [item["queue_item"] for item in results] == freeze["queue"]
        ),
        "four_candidates_two_controls": (
            len(candidates) == 4 and len(controls) == 2
        ),
        "no_candidate_certified": all(
            item["certified"] is False for item in candidates
        ),
        "candidate_failures_are_stationarity_and_optimizer": all(
            item["checks"]["energy_budget"] is True
            and item["checks"]["constraint"] is True
            and item["checks"]["semantic_native_energy"] is True
            and item["checks"]["semantic_native_state"] is True
            and item["checks"]["finite_difference"] is True
            and item["checks"]["resource_match_ns7"] is True
            and item["checks"]["stationarity"] is False
            and item["checks"]["optimizer_success"] is False
            for item in candidates
        ),
        "both_controls_already_stationary_and_certified": all(
            item["certified"] is True
            and item["initial"]["gradient_infinity"] <= 1e-8
            and item["final"]["gradient_infinity"] <= 1e-8
            and item["optimizer"]["success"] is True
            for item in controls
        ),
        "independent_fd_checks": all(
            max(
                record["absolute_error"]
                for record in (
                    item["certification"]["finite_difference"].values()
                    if item["kind"] == "rank2-trust-region"
                    else item["final"]["finite_difference"].values()
                )
            )
            <= 1e-6
            for item in results
        ),
        "work_caps_reconcile": (
            report["work"]["cap"] == WORK_CAP
            and all(report["work"]["checks"].values())
            and all(
                report["work"]["observed"][name] <= maximum
                for name, maximum in WORK_CAP.items()
            )
        ),
        "summary_reconciles": (
            report["summary"]["candidate_certified"] == 0
            and report["summary"]["control_certified"] == 2
            and report["summary"]["decision"]
            == "NO_TRUST_REGION_RECOVERY_WITHIN_FROZEN_CAP"
            and report["summary"]["optimizer_sensitive_contexts"] == []
        ),
        "ns7_and_pra_claims_unchanged": (
            report["summary"]["ns7_decisions_modified"] is False
            and report["summary"]["pra_performance_claim_established"]
            is False
            and report["paper_measurement_cost"] is None
        ),
    }
    audit = {
        "schema_version": "1.0.0",
        "artifact_kind": "v6-ns10-independent-result-audit",
        "audit_version": AUDIT_VERSION,
        "result_path": str(result_path.relative_to(ROOT)),
        "result_sha256": _sha256(result_path),
        "checks": checks,
        "passed": all(checks.values()),
        "interpretation": (
            "Both unconstrained sources are already stationary under the "
            "same trust-region implementation, while all four constrained "
            "rank-two runs hit the frozen iteration cap above the stationarity "
            "threshold. This implicates the fixed constrained landscapes or "
            "families within this protocol; it does not prove that no "
            "stationary point exists."
        ),
        "claim_boundary": (
            "Independent queue, certificate, finite-difference, work, and "
            "summary reconciliation; quantum kernels are not rerun."
        ),
    }
    audit["audit_digest"] = sha256_hex(audit)
    if not audit["passed"]:
        raise NS10ResultAuditError(
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
        NS10ResultAuditError,
    ) as error:
        print(f"V6-NS10 result audit failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    print(json.dumps(audit, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

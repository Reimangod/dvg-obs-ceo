"""Independent structural audit of the V6-NS8 follow-up result."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from typing import Any

from dvg_obs_ceo.artifact_io import atomic_write_new_json
from dvg_obs_ceo.baseline import ROOT
from dvg_obs_ceo.identity import sha256_hex

from .ns8_followup_audit import (
    AUDIT_VERSION as RUNNER_VERSION,
    DEFAULT_OUTPUT,
)


DEFAULT_AUDIT_OUTPUT = ROOT / "artifacts/v6/ns8/result-audit-v1.json"
RESULT_AUDIT_VERSION = "v6-ns8-independent-result-audit-v1"


class NS8ResultAuditError(RuntimeError):
    """Raised when the NS8 report is inconsistent."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit_result(result_path: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    report = json.loads(result_path.read_text(encoding="utf-8"))
    content = dict(report)
    digest = content.pop("report_digest")
    mechanism = report["mechanism_audit"]
    candidates = mechanism["candidates"]
    frontier = report["frontier_audit"]
    v6_points = [
        point for point in frontier["points"]
        if point["method"] == "V6 NS7 native rank-2"
    ]
    v5_round1 = next(
        point for point in frontier["points"]
        if point["method"] == "V5 round-1 intermediate"
    )
    checks = {
        "report_digest": digest == sha256_hex(content),
        "runner_version": report["audit_version"] == RUNNER_VERSION,
        "development_only": report["development_only"] is True,
        "input_hashes": all(
            (ROOT / value["path"]).is_file()
            and _sha256(ROOT / value["path"]) == value["sha256"]
            for value in report["inputs"].values()
        ),
        "two_accepted_candidates_audited": len(candidates) == 2,
        "source_candidate_fidelity": all(
            item["source_candidate_state_fidelity"] >= 1.0 - 1e-12
            for item in candidates
        ),
        "candidate_candidate_fidelity": (
            mechanism["candidate_candidate_state_fidelity"]
            >= 1.0 - 1e-12
        ),
        "symmetry_preserved": all(
            abs(item["symmetries"]["particle_number"]["expectation"] - 4.0)
            <= 1e-12
            and abs(item["symmetries"]["spin_z"]["expectation"]) <= 1e-12
            and abs(
                item["symmetries"]["spin_squared"]["expectation"]
            )
            <= 1e-12
            and max(
                observable["variance"]
                for observable in item["symmetries"].values()
            )
            <= 1e-12
            for item in candidates
        ),
        "full_fd_includes_analytic_maximum": all(
            all(
                record["analytic_maximum_component_index"]
                == item["gradient"]["maximum_component_index"]
                for record in item["gradient"][
                    "finite_difference"
                ].values()
            )
            for item in candidates
        ),
        "all_fd_stationarity_checks_inside_threshold": all(
            max(
                record["gradient_infinity"]
                for record in item["gradient"][
                    "finite_difference"
                ].values()
            )
            <= 1e-8
            for item in candidates
        ),
        "ns7_decisions_not_modified": (
            mechanism["acceptance_decisions_modified"] is False
        ),
        "same_source_checks": all(
            frontier["same_source_checks"].values()
        ),
        "v6_frontier_addition_is_false": (
            frontier[
                "ns7_adds_same_source_energy_resource_pareto_point"
            ]
            is False
            and all(not point["pareto_nondominated"] for point in v6_points)
        ),
        "v5_round1_dominates_both_v6_points": all(
            v5_round1["point_id"] in point["dominated_by"]
            for point in v6_points
        ),
        "matched_work_superiority_not_claimed": (
            frontier["matched_work_superiority_established"] is False
            and frontier["paper_measurement_cost"] is None
        ),
    }
    audit = {
        "schema_version": "1.0.0",
        "artifact_kind": "v6-ns8-independent-result-audit",
        "audit_version": RESULT_AUDIT_VERSION,
        "result_path": str(result_path.relative_to(ROOT)),
        "result_sha256": _sha256(result_path),
        "checks": checks,
        "passed": all(checks.values()),
        "claim_boundary": (
            "Independent arithmetic, identity, symmetry, full-gradient, and "
            "frontier reconciliation. Quantum kernels are not rerun here."
        ),
    }
    audit["audit_digest"] = sha256_hex(audit)
    if not audit["passed"]:
        raise NS8ResultAuditError(
            "failed checks: "
            + ", ".join(
                name for name, value in checks.items() if not value
            )
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
        NS8ResultAuditError,
    ) as error:
        print(f"V6-NS8 result audit failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    print(json.dumps(audit, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

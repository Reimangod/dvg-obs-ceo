"""Independent audit of the retained V3-S2 failed calibration."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import subprocess
from typing import Any

import numpy as np

from .baseline import ROOT
from .v3_polishing_calibration import DEFAULT_MANIFEST, _sha256


DEFAULT_RESULT = ROOT / "artifacts" / "v3" / "s2-polishing-calibration-v1-2.json"
EXPECTED_FAILED = "candidate-v1:d23aa90310d38b46684404e6b5d8c53f0297d5b46b7441cdd2908c7ed224d799"


class V3PolishingResultAuditError(RuntimeError):
    """Raised when the retained S2 evidence is inconsistent."""


def _git(*arguments: str) -> str:
    return subprocess.check_output(["git", "-C", str(ROOT), *arguments], text=True).strip()


def audit_result(
    result_path: Path = DEFAULT_RESULT,
    manifest_path: Path = DEFAULT_MANIFEST,
) -> dict[str, Any]:
    artifact = json.loads(result_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    s1_path = ROOT / manifest["inputs"]["s1_manifest"]["path"]
    s1_manifest = json.loads(s1_path.read_text(encoding="utf-8"))
    rows_path = ROOT / s1_manifest["input"]["candidate_rows"]["path"]
    rows = [json.loads(line) for line in rows_path.read_text(encoding="utf-8").splitlines() if line]
    initial_by_id = {
        row["candidate"]["candidate_id"]: row["paths"]["projection_on"]["coordinates"]
        for row in rows
    }
    records = artifact["records"]
    failed = [record["candidate_id"] for record in records if not record["passed"]]
    passed_records = [record for record in records if record["passed"]]
    origins = Counter(record["result"]["termination_origin"] for record in records)
    checks: dict[str, bool] = {
        "protocol": artifact["protocol_id"] == manifest["protocol_id"],
        "manifest_sha256": artifact["manifest_sha256"] == _sha256(manifest_path),
        "calibration_failed": artifact["passed"] is False,
        "record_count": len(records) == manifest["scope"]["candidate_count"] == 17,
        "candidate_ids_unique": len({record["candidate_id"] for record in records}) == 17,
        "record_checks_reconcile": all(
            record["passed"] == all(record["checks"].values()) for record in records
        ),
        "sixteen_passed": len(passed_records) == 16,
        "one_expected_failure": failed == artifact["failed_candidate_ids"] == [EXPECTED_FAILED],
        "preflight_scope": origins == Counter(
            {"zero-dimensional-exact": 1, "preflight-certificate": 15, "fail-closed": 1}
        ),
        "failure_injection": artifact["failure_injection"]["passed"] is True,
        "baseline_not_reexecuted": artifact["total_polishing_work_first_replay"][
            "ordinary_gsd_adapt_iterations"
        ]
        == 0
        and artifact["total_polishing_work_first_replay"]["ceo_star_adapt_iterations"] == 0,
        "paper_measurement_cost_unclaimed": artifact["total_polishing_work_first_replay"][
            "paper_measurement_cost"
        ]
        is None,
    }
    failed_record = next(record for record in records if record["candidate_id"] == EXPECTED_FAILED)
    failed_result = failed_record["result"]
    checks["budget_failure"] = bool(
        failed_result["failure_reason"] == "EvaluationBudgetExceeded"
        and failed_result["work"]["gradient_vector_evaluations"]
        == manifest["solver"]["maximum_gradient_vector_evaluations"]
        and failed_result["work"]["hessian_vector_products"]
        == manifest["solver"]["maximum_hessian_vector_products"]
    )
    checks["failed_coordinates_rolled_back"] = bool(
        np.array_equal(
            np.asarray(failed_result["coordinates"]),
            np.asarray(initial_by_id[EXPECTED_FAILED]),
        )
    )
    checks["threshold_not_relaxed"] = (
        manifest["solver"]["certification_infinity_threshold"] == 1e-8
    )
    execution = artifact["execution_freeze"]
    checks["execution_tag"] = _git(
        "rev-parse", f"{execution['protocol_tag']}^{{}}"
    ) == execution["head"]
    failed_checks = [name for name, passed in checks.items() if not passed]
    result = {
        "schema_version": "1.0.0",
        "artifact_kind": "v3-s2-independent-failed-result-audit",
        "result_sha256": _sha256(result_path),
        "passed": not failed_checks,
        "checks": checks,
        "failed_checks": failed_checks,
        "scientific_outcome": "calibration-unsuccessful-lih-not-authorized",
    }
    if failed_checks:
        raise V3PolishingResultAuditError(
            "S2 result audit failed: " + ", ".join(failed_checks)
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result-file", type=Path, default=DEFAULT_RESULT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    arguments = parser.parse_args()
    print(json.dumps(audit_result(arguments.result_file, arguments.manifest), sort_keys=True))


if __name__ == "__main__":
    main()

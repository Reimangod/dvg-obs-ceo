"""Read-only reproduction and classification of the observed V4 scale failures."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any

from .baseline import ROOT
from .identity import canonical_json_bytes
from .v3_protocol import _write_exclusive
from .v4_1_protocol import DEFAULT_MANIFEST, V41ProtocolError, audit_manifest


EXPECTED_SEMANTIC_REASON = (
    "ConstraintStateError('registered OVP tie must map two sources to one target')"
)
KNOWN_QUALITY_CHECKS = {
    "constraint_schur_condition",
    "target_hessian_condition",
    "constraint_direction_coverage",
    "internal_projected_residual",
    "held_out_projected_residual",
}


class V41FailureReproductionError(RuntimeError):
    """Raised when stored V4 failure evidence cannot be explained exactly."""


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _source_location() -> dict[str, Any]:
    path = "src/dvg_obs_ceo/constraint_state.py"
    historical = subprocess.check_output(
        [
            "git",
            "-C",
            str(ROOT),
            "show",
            f"488ec8b87079fd7ca63f1b3825cda3d6aecfa9f0:{path}",
        ],
        text=True,
    ).splitlines()
    offset = next(
        index for index, line in enumerate(historical) if "registered OVP tie must map" in line
    )
    return {
        "path": path,
        "line": offset + 1,
        "function": "exact_atomic_constraint",
        "commit": "488ec8b87079fd7ca63f1b3825cda3d6aecfa9f0",
    }


def classify_semantic_reason(reason: str | None) -> str:
    if reason == EXPECTED_SEMANTIC_REASON:
        return "hard-coded-two-source-ovp-primitive"
    return "unknown"


def reproduce(manifest_path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    try:
        s0 = audit_manifest(manifest_path)
    except V41ProtocolError as error:
        raise V41FailureReproductionError(str(error)) from error
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    case_results: list[dict[str, Any]] = []
    unknown: list[dict[str, Any]] = []

    for case_record in manifest["cases"]:
        case_id = case_record["case_id"]
        summary_path = ROOT / case_record["v4_summary_path"]
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        catalog = {item["candidate_id"]: item for item in summary["catalog"]["candidates"]}
        records = summary["search"]["records"]
        semantic_records = [
            record
            for record in records
            if record["evaluation"]["status"] == "semantic-composition-failure"
        ]
        implicated: Counter[str] = Counter()
        registered_large_ovp_ids: set[str] = set()
        for item in catalog.values():
            source_dimension = len(item["source_slots"])
            target_dimension = len(item["target_slots"])
            if (
                item["kind"] in {"mvp-to-ovp-sum", "mvp-to-ovp-diff"}
                and source_dimension > 2
                and target_dimension == 1
            ):
                registered_large_ovp_ids.add(item["candidate_id"])

        failure_with_registered_large_ovp = 0
        for record in semantic_records:
            classification = classify_semantic_reason(record["evaluation"].get("reason"))
            implicated[classification] += 1
            candidate_ids = set(record["candidate_ids"])
            if candidate_ids & registered_large_ovp_ids:
                failure_with_registered_large_ovp += 1
            if classification == "unknown":
                unknown.append(
                    {
                        "case_id": case_id,
                        "kind": "semantic",
                        "reason": record["evaluation"].get("reason"),
                    }
                )

        quality_histogram: Counter[str] = Counter()
        for rejection in summary["quality_rejections"]:
            for failed_check in rejection["failed_checks"]:
                quality_histogram[failed_check] += 1
                if failed_check not in KNOWN_QUALITY_CHECKS:
                    unknown.append(
                        {"case_id": case_id, "kind": "quality", "reason": failed_check}
                    )

        status_histogram = Counter(record["evaluation"]["status"] for record in records)
        counts = summary["search"]["counts"]
        checks = {
            "case_identity": summary["case_id"] == case_id,
            "catalog_count": len(catalog) == summary["catalog"]["candidate_count"],
            "completed_record_count": len(records) == counts["completed"],
            "semantic_count": len(semantic_records)
            == counts["semantic_composition_failures"],
            "valid_count": status_histogram["valid"]
            == counts["completed"] - counts["semantic_composition_failures"],
            "eligible_count": len(summary["search"]["eligible_semantic_ids"])
            == len(summary["quality_rejections"]),
            "zero_quality_pass": summary["quality_passed_resource_candidate_count"] == 0,
            "zero_exact_attempts": len(summary["attempts"]) == 0,
            "budget_truncated": summary["search"]["status"] == "budget-truncated"
            and summary["search"]["truncated_reason"] == "maximum-completed-states",
            "large_ovp_catalog_presence": bool(registered_large_ovp_ids)
            if case_id.startswith("h6")
            else not registered_large_ovp_ids,
            "large_ovp_explains_semantic_failures": (
                failure_with_registered_large_ovp == len(semantic_records)
                if semantic_records
                else True
            ),
        }
        failures = [name for name, passed in checks.items() if not passed]
        if failures:
            raise V41FailureReproductionError(
                f"{case_id} stored V4 evidence mismatch: {', '.join(failures)}"
            )
        case_results.append(
            {
                "case_id": case_id,
                "v4_summary_sha256": case_record["v4_summary_sha256"],
                "v4_summary_digest": case_record["v4_summary_digest"],
                "catalog": {
                    "block_count": summary["catalog"]["block_count"],
                    "candidate_count": len(catalog),
                    "registered_source_dimension_gt2_to_ovp_count": len(
                        registered_large_ovp_ids
                    ),
                },
                "search": {
                    "status": summary["search"]["status"],
                    "truncated_reason": summary["search"]["truncated_reason"],
                    "counts": counts,
                    "record_status_histogram": dict(sorted(status_histogram.items())),
                    "surrogate_eligible_count": len(
                        summary["search"]["eligible_semantic_ids"]
                    ),
                },
                "semantic_failure": {
                    "count": len(semantic_records),
                    "classification_histogram": dict(sorted(implicated.items())),
                    "with_registered_source_dimension_gt2_to_ovp": failure_with_registered_large_ovp,
                    "source_location": _source_location(),
                    "candidate_families": ["mvp-to-ovp-sum", "mvp-to-ovp-diff"]
                    if semantic_records
                    else [],
                },
                "quality_failure": {
                    "rejected_candidate_count": len(summary["quality_rejections"]),
                    "failed_check_histogram": dict(sorted(quality_histogram.items())),
                    "quality_passed_resource_candidate_count": summary[
                        "quality_passed_resource_candidate_count"
                    ],
                },
                "exact_attempt_count": len(summary["attempts"]),
                "checks": checks,
            }
        )

    if unknown:
        raise V41FailureReproductionError(f"unclassified V4 failures: {unknown[:5]}")
    result: dict[str, Any] = {
        "schema_version": "1.0.0",
        "artifact_kind": "v4.1-s1-failure-reproduction",
        "protocol_id": manifest["protocol_id"],
        "s0_manifest_sha256": s0["manifest_sha256"],
        "read_only": True,
        "cases": case_results,
        "unknown_failure_count": 0,
        "passed": True,
        "claim_boundary": (
            "Reproduction from immutable V4 summaries only; no search, quality decision, "
            "resource selection, or exact VQE was rerun."
        ),
    }
    result["artifact_digest"] = _digest(result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--artifact-path", type=Path)
    arguments = parser.parse_args()
    result = reproduce(arguments.manifest)
    if arguments.artifact_path is not None:
        _write_exclusive(arguments.artifact_path, result)
    print(
        json.dumps(
            {
                "passed": result["passed"],
                "cases": len(result["cases"]),
                "unknown_failure_count": result["unknown_failure_count"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()

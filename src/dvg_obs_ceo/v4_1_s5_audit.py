"""Independent audit of the final V4.1-S5 energy-blind sentinel bundles."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .baseline import ROOT
from .identity import canonical_json_bytes
from .v3_protocol import _write_exclusive
from .v4_1_bundle import audit_case_state, validate_complete_bundle
from .v4_1_multisystem import replay_selection_from_resource_evidence
from .v4_1_protocol import DEFAULT_MANIFEST, audit_manifest


FINAL_ROOT = ROOT / "artifacts/v4.1/s5-sentinels-rerun-v5"
SUPERSEDED_ROOT = ROOT / "artifacts/v4.1/s5-sentinels-rerun-v4"
CASES = ("h6-1.5", "h6-3.0", "beh2-3.0")


class V41S5AuditError(RuntimeError):
    """Raised when final S5 screening evidence cannot be independently replayed."""


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _summary(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    stored = value.pop("summary_digest")
    if _digest(value) != stored:
        raise V41S5AuditError(f"summary digest mismatch: {path}")
    value["summary_digest"] = stored
    return value


def _strict_resource_improvement(
    source: Mapping[str, Any], target: Mapping[str, Any]
) -> bool:
    fields = ("parameter_count", "cnot_count", "cnot_depth", "total_depth")
    deltas = [int(target[field]) - int(source[field]) for field in fields]
    return all(delta <= 0 for delta in deltas) and any(delta < 0 for delta in deltas)


def _v14_common_fields_equal(old: Mapping[str, Any], new: Mapping[str, Any]) -> bool:
    top_level = (
        "search", "source_resources", "quality_passed_resource_candidate_count",
        "resource_failures", "selection", "actual_candidate_energy_evaluations",
        "exact_or_fci_energy_used", "paper_measurement_cost",
    )
    if any(old[field] != new[field] for field in top_level):
        return False
    if len(old["sentinels"]) != len(new["sentinels"]):
        return False
    for previous, current in zip(old["sentinels"], new["sentinels"]):
        if any(current.get(field) != value for field, value in previous.items()):
            return False
    if len(old["quality_rejections"]) != len(new["quality_rejections"]):
        return False
    projection = ("candidate_ids", "constraint_semantic_id", "failed_checks")
    return all(
        all(previous[field] == current[field] for field in projection)
        for previous, current in zip(
            old["quality_rejections"], new["quality_rejections"]
        )
    )


def run(
    final_root: Path = FINAL_ROOT,
    superseded_root: Path = SUPERSEDED_ROOT,
    manifest_path: Path = DEFAULT_MANIFEST,
) -> dict[str, Any]:
    manifest_audit = audit_manifest(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    case_manifest = {case["case_id"]: case for case in manifest["cases"]}
    cases: dict[str, Any] = {}
    failed: list[str] = []
    for case_id in CASES:
        bundle = final_root / case_id
        bundle_audit = validate_complete_bundle(bundle)
        summary = _summary(bundle / "summary.json")
        state = audit_case_state(final_root, case_id)
        replay = replay_selection_from_resource_evidence(summary)
        sentinels = summary["sentinels"]
        search_counts = summary["search"]["counts"]
        eligible_count = sum(
            bool(record["eligible"]) for record in summary["search"]["records"]
        )
        checks = {
            "case_id": summary["case_id"] == case_id,
            "protocol": (
                summary["protocol_id"] == manifest["protocol_id"]
                and summary["s0_manifest_sha256"] == manifest_audit["manifest_sha256"]
            ),
            "checkpoint": summary["checkpoint_sha256"]
            == case_manifest[case_id]["checkpoint_sha256"],
            "canonical_bundle": (
                state["canonical_status"] == "complete"
                and state["canonical_bundle_digest"] == bundle_audit["bundle_digest"]
            ),
            "no_runtime_residue": (
                state["lock_status"] == "absent"
                and not state["staging"]
                and not state["ambiguous"]
            ),
            "no_actual_or_fci_energy": (
                summary["actual_candidate_energy_evaluations"] == 0
                and summary["exact_or_fci_energy_used"] is False
            ),
            "measurement_cost_unclaimed": summary["paper_measurement_cost"] is None,
            "known_failure_counts_zero": (
                search_counts["candidate_numerical_failures"] == 0
                and search_counts["semantic_composition_failures"] == 0
                and not summary["resource_failures"]
            ),
            "resource_evidence_complete": (
                len(summary["resource_candidate_evidence"])
                == summary["quality_passed_resource_candidate_count"]
            ),
            "selection_replay": replay == summary["selection"],
            "sentinel_queue": (
                0 < len(sentinels) <= 4
                and [item["constraint_semantic_id"] for item in sentinels]
                == summary["selection"]["unique_attempt_semantic_ids"]
                and len({item["resources"]["structure_digest"] for item in sentinels})
                == len(sentinels)
            ),
            "sentinel_quality_and_resources": all(
                item["quality"]["passed"]
                and item["predicted_loss_hartree"]
                == item["prediction"]["predicted_change_from_current_hartree"]
                and item["predicted_loss_hartree"]
                <= summary["selection"]["screening_budget_hartree"]
                and _strict_resource_improvement(
                    summary["source_resources"], item["resources"]
                )
                for item in sentinels
            ),
            "work_telemetry": (
                summary["screening_work"]["constraint_space_solves"]
                == search_counts["quadratic_solves"]
                and summary["screening_work"]["full_quality_predictions"]
                == eligible_count + len(sentinels)
                and summary["screening_work"]["retained_full_prediction_records"]
                == len(sentinels)
            ),
            "v1_4_common_science_reproduced": _v14_common_fields_equal(
                _summary(superseded_root / case_id / "summary.json"), summary
            ),
        }
        case_failed = [name for name, passed in checks.items() if not passed]
        failed.extend(f"{case_id}:{name}" for name in case_failed)
        source = summary["source_resources"]
        cases[case_id] = {
            "summary_digest": summary["summary_digest"],
            "bundle_digest": bundle_audit["bundle_digest"],
            "checks": checks,
            "failed_checks": case_failed,
            "search_status": summary["search"]["status"],
            "search_counts": search_counts,
            "energy_eligible_count": eligible_count,
            "quality_passed_resource_candidate_count": summary[
                "quality_passed_resource_candidate_count"
            ],
            "sentinel_count": len(sentinels),
            "sentinel_reductions": [
                {
                    "constraint_semantic_id": item["constraint_semantic_id"],
                    "cnot": source["cnot_count"] - item["resources"]["cnot_count"],
                    "cnot_depth": source["cnot_depth"] - item["resources"]["cnot_depth"],
                    "total_depth": source["total_depth"] - item["resources"]["total_depth"],
                    "parameters": source["parameter_count"] - item["resources"]["parameter_count"],
                }
                for item in sentinels
            ],
        }
    result: dict[str, Any] = {
        "schema_version": "1.0.0",
        "artifact_kind": "v4.1-s5-independent-sentinel-freeze-audit",
        "protocol_id": manifest["protocol_id"],
        "s0_manifest_sha256": manifest_audit["manifest_sha256"],
        "cases": cases,
        "failed_checks": failed,
        "passed": not failed,
        "actual_candidate_energy_evaluations": 0,
        "paper_measurement_cost": None,
        "claim_boundary": "Energy-blind, budget-truncated sentinel screening only; no exact VQE performance, global optimum, or generalization claim.",
    }
    result["artifact_digest"] = _digest(result)
    if failed:
        raise V41S5AuditError("S5 independent audit failed: " + ", ".join(failed))
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-path", type=Path)
    arguments = parser.parse_args()
    result = run()
    if arguments.artifact_path is not None:
        _write_exclusive(arguments.artifact_path, result)
    print(json.dumps({"passed": result["passed"], "cases": len(result["cases"])}, sort_keys=True))


if __name__ == "__main__":
    main()

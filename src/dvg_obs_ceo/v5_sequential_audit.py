"""V5-S3 width-one and V4.1 round-one replay audit."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .baseline import ROOT
from .v3_protocol import _write_exclusive
from .v4_1_multisystem import replay_selection_from_resource_evidence
from .v4_1_s6_regression import h2_h4_regression


V41_SUMMARIES = {
    case_id: ROOT / "artifacts" / "v4.1" / "s5-sentinels-rerun-v5" / case_id / "summary.json"
    for case_id in ("h6-1.5", "h6-3.0", "beh2-3.0")
}


def _contains_forbidden_screening_key(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            "actual" in str(key).lower()
            or "fci" in str(key).lower()
            or _contains_forbidden_screening_key(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_screening_key(item) for item in value)
    return False


def run_audit() -> dict[str, Any]:
    small_system_replay = h2_h4_regression()
    replay: dict[str, Any] = {}
    for case_id, path in V41_SUMMARIES.items():
        summary = json.loads(path.read_text(encoding="utf-8"))
        selection = replay_selection_from_resource_evidence(summary)
        replay[case_id] = {
            "selection_digest": selection["selection_digest"],
            "first_exact_semantic_id": selection["unique_attempt_semantic_ids"][0],
            "queue_length": len(selection["unique_attempt_semantic_ids"]),
            "matches_stored": selection == summary["selection"],
        }

    comparison = json.loads((ROOT / "artifacts/v4.1/s10-release-v1/comparison.json").read_text(encoding="utf-8"))
    lih_rows = [row for row in comparison["rows"] if row["case_id"] == "lih-3.0"]
    lih_v4 = next(row for row in lih_rows if row["method"] == "V4")
    lih_v41 = next(row for row in lih_rows if row["method"] == "V4.1-regression")
    lih_fields = ("final_energy_hartree", "final_resources", "energy_increase_hartree")
    checks = {
        "h2_h4_exhaustive_fixture_replay": (
            small_system_replay["passed"]
            and small_system_replay["single_candidate_replays"] == 17
            and small_system_replay["stored_joint_batch_replays"] == 420
        ),
        "all_v4_1_round_one_queues_replay": all(value["matches_stored"] for value in replay.values()),
        "all_v4_1_queues_nonempty": all(value["queue_length"] > 0 for value in replay.values()),
        "lih_v4_1_round_one_regression_matches_v4": all(lih_v4[field] == lih_v41[field] for field in lih_fields),
        "stored_selection_has_no_actual_or_fci_field": all(
            not _contains_forbidden_screening_key(
                json.loads(path.read_text(encoding="utf-8"))["selection"]
            )
            for path in V41_SUMMARIES.values()
        ),
    }
    result = {
        "schema_version": "1.0.0",
        "artifact_kind": "v5-s3-width1-independent-audit",
        "passed": all(checks.values()),
        "checks": checks,
        "h2_h4_exhaustive_fixture_replay": small_system_replay,
        "v4_1_round_one_replay": replay,
        "claim_boundary": "Stored V4.1 round-one selector replay and synthetic sequential-kernel evidence; no new molecular VQE execution or V5 performance claim.",
    }
    if not result["passed"]:
        raise RuntimeError("V5-S3 independent audit failed")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-path", type=Path)
    arguments = parser.parse_args()
    result = run_audit()
    if arguments.artifact_path is not None:
        _write_exclusive(arguments.artifact_path, result)
    print(json.dumps({"passed": result["passed"], "checks": len(result["checks"])}, sort_keys=True))


if __name__ == "__main__":
    main()

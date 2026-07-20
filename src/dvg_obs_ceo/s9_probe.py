"""Freeze and replay the S9 selector on pre-LiH calibration artifacts."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
from typing import Any

from .selector import CandidateScore, SelectorConfig, select_candidate
from .telemetry import ResourceSnapshot


ROOT = Path(__file__).resolve().parents[2]


def _scores(bundle: Path) -> tuple[dict[str, list[CandidateScore]], dict[str, dict[str, Any]]]:
    summary = json.loads((bundle / "summary.json").read_text(encoding="utf-8"))
    checkpoint_by_case = {item["case_id"]: item for item in summary["checkpoints"]}
    rows = [
        json.loads(line)
        for line in (bundle / "all-candidates.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    scores: dict[str, list[CandidateScore]] = {}
    row_by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        if "error" in row:
            continue
        case = row["case_id"]
        path = row["paths"]["projection_on"]
        after_value = path["resources"]["snapshot"]
        delta = path["resource_delta"]
        before = ResourceSnapshot(
            *(
                int(after_value[field] - delta[field])
                for field in (
                    "cnot_count", "cnot_depth", "total_depth",
                    "parameter_count", "logical_block_count",
                )
            ),
            after_value["counter_version"],
            "0" * 64,
        )
        after = ResourceSnapshot(
            after_value["cnot_count"],
            after_value["cnot_depth"],
            after_value["total_depth"],
            after_value["parameter_count"],
            after_value["logical_block_count"],
            after_value["counter_version"],
            after_value["structure_digest"],
        )
        source_energy = float(checkpoint_by_case[case]["energy_hartree"])
        candidate = CandidateScore(
            candidate_id=row["candidate"]["candidate_id"],
            equivalence_class_id=row["candidate"]["equivalence_class_id"],
            kind=row["candidate"]["kind"],
            target_family=row["candidate"]["target_family"],
            predicted_change_from_source_hartree=float(
                row["predictors"]["general_constraint_obs"]
            ),
            source_energy_hartree=source_energy,
            budget_reference_energy_hartree=source_energy,
            before_resources=before,
            after_resources=after,
            hessian_quality_usable=bool(
                checkpoint_by_case[case]["hessian_quality_usable"]
            ),
            full_resource_recount_succeeded=bool(
                path["resource_recount_consistent"]
            ),
            transformation_semantics_validated=True,
        )
        scores.setdefault(case, []).append(candidate)
        row_by_id[candidate.candidate_id] = row
    return scores, row_by_id


def run_probe(path: Path) -> dict[str, Any]:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite S9 freeze artifact: {path}")
    config = SelectorConfig()
    bundles = (
        ROOT / "artifacts" / "s8" / "calibration-bundle",
        ROOT / "artifacts" / "s8-1" / "later-checkpoint-calibration-bundle",
    )
    replay: list[dict[str, Any]] = []
    for bundle in bundles:
        scores, row_by_id = _scores(bundle)
        for case, candidates in scores.items():
            decision = select_candidate(candidates, config)
            selected_row = (
                None if decision.chosen_candidate_id is None
                else row_by_id[decision.chosen_candidate_id]
            )
            replay.append(
                {
                    "bundle": str(bundle),
                    "case_id": case,
                    "candidate_count": len(candidates),
                    "chosen_candidate_id": decision.chosen_candidate_id,
                    "eligible_count": sum(item.eligible for item in decision.assessments),
                    "decision": asdict(decision),
                    "offline_actual_safe_for_replay_audit_only": (
                        None if selected_row is None else bool(selected_row["safe"])
                    ),
                    "offline_actual_change_hartree_for_replay_audit_only": (
                        None if selected_row is None
                        else float(selected_row["actual_change_hartree"])
                    ),
                }
            )
    expected = {
        "h2-1.5-iteration-1": None,
        "h4-1.5-first-chemical-accuracy": None,
        "h4-1.5-iteration-12-or-convergence": (
            "candidate-v1:1334771f370cda2d7a4a8da467c52657b8b453fde4271dbcaa4c81fe48435128"
        ),
    }
    observed = {item["case_id"]: item["chosen_candidate_id"] for item in replay}
    if observed != expected:
        raise RuntimeError(f"frozen selector replay changed: {observed}")
    terminal = next(
        item for item in replay
        if item["case_id"] == "h4-1.5-iteration-12-or-convergence"
    )
    if terminal["offline_actual_safe_for_replay_audit_only"] is not True:
        raise RuntimeError("selector replay chose an actually unsafe development candidate")
    artifact = {
        "schema_version": "1.0.0",
        "artifact_kind": "s9-pre-lih-selector-freeze-replay",
        "selector_config": config.to_dict(),
        "selector_digest": config.digest,
        "replay": replay,
        "selector_freeze_gate": {
            "primary_first_accuracy_no_candidate_is_allowed": True,
            "terminal_positive_selected_without_actual_outcome_input": True,
            "terminal_selected_candidate_offline_safe": True,
            "general_obs_calibration_false_safe_count": 0,
            "fci_runtime_field_present": False,
        },
        "claim_boundary": [
            "Replay actual outcomes are audit labels and were not selector inputs.",
            "S9 freezes behavior before any new-method LiH execution.",
            "A no-selection LiH result is valid and must not trigger threshold changes.",
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(artifact, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    return artifact


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", type=Path, required=True)
    arguments = parser.parse_args()
    result = run_probe(arguments.artifact)
    print(json.dumps({
        "artifact": str(arguments.artifact),
        "selector_digest": result["selector_digest"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()

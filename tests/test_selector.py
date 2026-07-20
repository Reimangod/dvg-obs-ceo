import json
from pathlib import Path

import pytest

from dvg_obs_ceo.selector import (
    CandidateScore,
    SelectorConfig,
    SelectorError,
    select_candidate,
)
from dvg_obs_ceo.telemetry import ResourceSnapshot


ROOT = Path(__file__).resolve().parents[1]


def resource(cnot, cnot_depth, total_depth, parameters, blocks, digest):
    return ResourceSnapshot(cnot, cnot_depth, total_depth, parameters, blocks, "selector-test", digest * 64)


def candidate(identifier, predicted, before, after, *, source=-1.0, reference=-1.0, usable=True):
    return CandidateScore(
        identifier,
        "equivalence:" + identifier,
        "block-deletion",
        "empty",
        predicted,
        source,
        reference,
        before,
        after,
        usable,
        True,
        True,
    )


def test_selector_uses_cumulative_budget_and_lexicographic_resources() -> None:
    before = resource(30, 10, 50, 5, 4, "a")
    candidates = [
        candidate("smaller-loss", 1e-5, before, resource(25, 10, 45, 4, 4, "b")),
        candidate("more-cnots", 8e-5, before, resource(20, 10, 40, 4, 4, "c")),
        candidate("reset-trap", 6e-5, before, resource(15, 9, 35, 3, 3, "d"), source=-0.99995),
    ]
    decision = select_candidate(candidates)
    assert decision.chosen_candidate_id == "more-cnots"
    trap = next(item for item in decision.assessments if item.candidate_id == "reset-trap")
    assert not trap.eligible
    assert "predicted-cumulative-energy-budget" in trap.rejection_reasons


def test_selector_fails_closed_on_quality_semantics_resources_and_duplicates() -> None:
    before = resource(20, 10, 30, 2, 2, "a")
    values = [
        candidate("bad-hessian", 0.0, before, resource(10, 8, 20, 1, 1, "b"), usable=False),
        CandidateScore(
            "bad-semantics", "eq-semantics", "delete", "empty", 0.0, -1.0, -1.0,
            before, resource(10, 8, 20, 1, 1, "c"), True, True, False,
        ),
        candidate("regression", 0.0, before, resource(10, 11, 20, 1, 1, "d")),
    ]
    decision = select_candidate(values)
    assert decision.chosen_candidate_id is None
    with pytest.raises(SelectorError, match="equivalence"):
        duplicate = candidate("other", 0.0, before, resource(10, 8, 20, 1, 1, "e"))
        duplicate = CandidateScore(
            duplicate.candidate_id, values[0].equivalence_class_id, duplicate.kind,
            duplicate.target_family, duplicate.predicted_change_from_source_hartree,
            duplicate.source_energy_hartree, duplicate.budget_reference_energy_hartree,
            duplicate.before_resources, duplicate.after_resources, True, True, True,
        )
        select_candidate([values[0], duplicate])


def _bundle_candidates(bundle: Path):
    summary = json.loads((bundle / "summary.json").read_text())
    checkpoint = summary["checkpoints"][0]
    if len(summary["checkpoints"]) > 1:
        checkpoint_by_case = {item["case_id"]: item for item in summary["checkpoints"]}
    else:
        checkpoint_by_case = {checkpoint["case_id"]: checkpoint}
    quality_by_case = {item["case_id"]: item["hessian_quality_usable"] for item in summary["checkpoints"]}
    rows = [json.loads(line) for line in (bundle / "all-candidates.jsonl").read_text().splitlines()]
    result = {}
    for row in rows:
        if "error" in row:
            continue
        case = row["case_id"]
        path = row["paths"]["projection_on"]
        after_value = path["resources"]["snapshot"]
        delta = path["resource_delta"]
        before_value = {
            field: after_value[field] - delta[field]
            for field in ("cnot_count", "cnot_depth", "total_depth", "parameter_count", "logical_block_count")
        }
        before = ResourceSnapshot(
            **before_value,
            counter_version=after_value["counter_version"],
            structure_digest="a" * 64,
        )
        after = ResourceSnapshot(
            after_value["cnot_count"], after_value["cnot_depth"], after_value["total_depth"],
            after_value["parameter_count"], after_value["logical_block_count"],
            after_value["counter_version"], after_value["structure_digest"],
        )
        source_energy = checkpoint_by_case[case]["energy_hartree"]
        result.setdefault(case, []).append(CandidateScore(
            row["candidate"]["candidate_id"],
            row["candidate"]["equivalence_class_id"],
            row["candidate"]["kind"],
            row["candidate"]["target_family"],
            row["predictors"]["general_constraint_obs"],
            source_energy,
            source_energy,
            before,
            after,
            quality_by_case[case],
            path["resource_recount_consistent"],
            True,
        ))
    return result


def test_frozen_selector_replays_s8_without_looking_at_actual_outcomes() -> None:
    primary = _bundle_candidates(ROOT / "artifacts" / "s8" / "calibration-bundle")
    assert select_candidate(primary["h2-1.5-iteration-1"]).chosen_candidate_id is None
    assert select_candidate(primary["h4-1.5-first-chemical-accuracy"]).chosen_candidate_id is None
    terminal = _bundle_candidates(ROOT / "artifacts" / "s8-1" / "later-checkpoint-calibration-bundle")
    decision = select_candidate(terminal["h4-1.5-iteration-12-or-convergence"])
    assert decision.chosen_candidate_id == "candidate-v1:1334771f370cda2d7a4a8da467c52657b8b453fde4271dbcaa4c81fe48435128"


def test_config_digest_is_stable_and_has_no_fci_field() -> None:
    first = SelectorConfig()
    second = SelectorConfig()
    assert first.digest == second.digest
    assert "fci" not in json.dumps(first.to_dict()).lower()
    assert "fci" not in CandidateScore.__dataclass_fields__

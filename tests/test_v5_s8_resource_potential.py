from copy import deepcopy
import json
from pathlib import Path

import pytest

from dvg_obs_ceo.v5_s8_resource_potential import (
    V5S8ResourcePotentialError,
    _row_by_candidate,
    build_h4_resource_potential,
)


ROOT = Path(__file__).resolve().parents[1]


def _inputs():
    oracle = json.loads((ROOT / "artifacts/v5/s8/h4-hvp-sentinels-damped.json").read_text())
    rows = _row_by_candidate(
        ROOT / "artifacts/s8-1/later-checkpoint-calibration-bundle/rows",
        "h4-1.5-iteration-12-or-convergence-",
    )
    return oracle, rows


def test_queue_is_independent_of_posthoc_outcomes():
    oracle, rows = _inputs()
    first = build_h4_resource_potential(
        oracle_artifact=oracle, rows=rows, screening_budget_hartree=1e-4
    )
    perturbed = deepcopy(oracle)
    for record in perturbed["oracle_records"]:
        record["posthoc_actual_change_hartree"] = 999.0
        record["posthoc_complete_safe"] = False
    second = build_h4_resource_potential(
        oracle_artifact=perturbed, rows=rows, screening_budget_hartree=1e-4
    )
    assert first["prereveal_digest"] == second["prereveal_digest"]
    assert first["posthoc_selected_outcomes"] != second["posthoc_selected_outcomes"]


def test_resource_counts_and_claim_boundaries_are_explicit():
    oracle, rows = _inputs()
    result = build_h4_resource_potential(
        oracle_artifact=oracle, rows=rows, screening_budget_hartree=1e-4
    )
    assert result["summary"]["input_candidate_count"] == 62
    assert result["summary"]["solved_candidate_count"] == 60
    assert result["paper_measurement_cost"] is None
    assert result["prereveal"]["source_resources"]["parameter_count"] == 24
    assert result["prereveal"]["source_resources"]["logical_block_count"] == 14
    assert result["prereveal"]["source_resources"]["cnot_count"] == 158
    assert result["summary"]["selected_attempt_count"] <= 4
    assert all(
        any(value < 0 for value in item["resource_delta"].values())
        and all(value <= 0 for value in item["resource_delta"].values())
        for item in result["posthoc_selected_outcomes"]
    )


def test_missing_row_fails_closed():
    oracle, rows = _inputs()
    solved_id = next(
        record["candidate_id"] for record in oracle["oracle_records"]
        if record["status"] == "solved"
    )
    rows.pop(solved_id)
    with pytest.raises(V5S8ResourcePotentialError, match="missing candidate rows"):
        build_h4_resource_potential(
            oracle_artifact=oracle, rows=rows, screening_budget_hartree=1e-4
        )

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from dvg_obs_ceo.identity import canonical_json_bytes
from dvg_obs_ceo.v4_1_exact_multisystem import (
    V41ExactError,
    _acceptance_constants_match,
    _digest,
    _read_summary,
)


def test_read_summary_rejects_tampering(tmp_path: Path) -> None:
    value = {"case_id": "h6-1.5", "attempts": []}
    path = tmp_path / "summary.json"
    path.write_bytes(canonical_json_bytes({**value, "summary_digest": _digest(value)}) + b"\n")
    assert _read_summary(path)["case_id"] == "h6-1.5"
    tampered = json.loads(path.read_text())
    tampered["case_id"] = "h6-3.0"
    path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(V41ExactError, match="digest mismatch"):
        _read_summary(path)


def test_acceptance_runtime_constants_are_bound() -> None:
    config = {
        "acceptance": {
            "cumulative_energy_budget_hartree": 1e-4,
            "independent_energy_tolerance_hartree": 1e-10,
            "minimum_independent_state_recomputation_fidelity": 1.0 - 1e-10,
            "maximum_constraint_residual": 1e-10,
            "maximum_stationarity_residual": 1e-8,
            "componentwise_nonworse_resources": True,
            "at_least_one_strict_resource_improvement": True,
        }
    }
    assert _acceptance_constants_match(config)
    config["acceptance"]["cumulative_energy_budget_hartree"] = 2e-4
    assert not _acceptance_constants_match(config)


def test_exact_runner_has_no_search_or_selector_call() -> None:
    source = Path(__file__).parents[1] / "src/dvg_obs_ceo/v4_1_exact_multisystem.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    calls = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "deterministic_search" not in calls
    assert "select_v4_1_sentinels" not in calls


def test_exact_runner_binds_four_registered_cases_only() -> None:
    source = Path(__file__).parents[1] / "src/dvg_obs_ceo/v4_1_exact_multisystem.py"
    text = source.read_text(encoding="utf-8")
    assert 'choices=("h6-1.5", "h6-3.0", "beh2-3.0")' in text
    assert "maximum_unique_attempts" not in text

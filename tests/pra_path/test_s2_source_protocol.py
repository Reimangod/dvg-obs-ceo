from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_s2_source_roles_are_distinct_and_fail_closed() -> None:
    value = json.loads(
        (
            ROOT / "artifacts/pra_path/s2/source-protocol-v1.json"
        ).read_text()
    )
    roles = value["source_roles"]
    assert roles["historical_paper_endpoint_source"][
        "may_be_used_for_new_causal_performance_claim"
    ] is False
    assert roles["stationarity_normalized_source"][
        "parameter_gradient_infinity_max"
    ] == 1e-8
    assert value["runtime_firewall"] == {
        "candidate_outcomes_may_change_source": False,
        "chemical_accuracy_used_for_source_stopping": False,
        "fci_or_reference_energy_used_for_source_stopping": False,
    }
    assert value["authorization"] == {
        "new_performance_execution": False,
        "s3": True,
    }


def test_existing_h6_sources_need_no_reoptimization() -> None:
    value = json.loads(
        (
            ROOT / "artifacts/pra_path/s2/source-protocol-v1.json"
        ).read_text()
    )
    for source in value["existing_source_classification"].values():
        assert source["stationarity_normalized_source"] is True
        assert source["reoptimization_required"] is False
        assert source["parameter_gradient_infinity"] <= 1e-8

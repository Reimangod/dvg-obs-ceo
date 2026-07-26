from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_v6_1_protocol_is_strict_and_non_circular() -> None:
    payload = json.loads(
        (ROOT / "artifacts/v6_1/t0/protocol-v1.json").read_text()
    )
    assert payload["status"] == "frozen_before_outcome_computation"
    assert payload["metric"]["compensation_projection"] == "real-linear"
    assert payload["gate"]["threshold_tuning_after_outcomes"] is False
    assert payload["conditional_stages"][
        "t3_t4_authorized_only_if_t2_go"
    ] is True
    assert "prospective" in payload["claim_boundary"]

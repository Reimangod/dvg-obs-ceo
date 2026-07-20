import json

import pytest
from jsonschema import ValidationError

from dvg_obs_ceo.s11_gsd import (
    PAPER_REFERENCE,
    PROTOCOL_ID,
    REQUIRED_THREADS,
    validate_summary,
)


def test_s11_gsd_protocol_matches_paper_reference_and_claim_boundary() -> None:
    protocol = json.load(open("manifests/s11-gsd-lih-protocol-v1.json", encoding="utf-8"))
    assert protocol["protocol_id"] == PROTOCOL_ID
    assert protocol["algorithm"]["pool"] == "GSD"
    assert protocol["algorithm"]["tetris"] is False
    assert protocol["algorithm"]["hessian_recycling"] is False
    assert protocol["paper_first_accuracy_reference"] == PAPER_REFERENCE
    assert protocol["numerical_environment"] == REQUIRED_THREADS
    assert any("not recomputed" in item for item in protocol["claim_boundary"])


def test_s11_schema_rejects_non_success_and_missing_trajectory() -> None:
    with pytest.raises(ValidationError):
        validate_summary({
            "schema_version": "1.0.0",
            "artifact_kind": "s11-direct-pinned-gsd-adapt-lih",
            "protocol_id": PROTOCOL_ID,
            "trajectory": [],
            "reached_chemical_accuracy": False,
        })

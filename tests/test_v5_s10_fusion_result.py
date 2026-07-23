import hashlib
import json
from pathlib import Path

from dvg_obs_ceo.identity import canonical_json_bytes


ROOT = Path(__file__).resolve().parents[1]
RESULT = ROOT / "artifacts/v5/s10/exact-fusion-gate-v1.json"


def test_s10_result_is_bound_to_frozen_inputs_and_passes_only_h6_1p5():
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    content = dict(result)
    observed_digest = content.pop("result_digest")
    assert hashlib.sha256(canonical_json_bytes(content)).hexdigest() == observed_digest
    manifest = json.loads(
        (ROOT / result["manifest_path"]).read_text(encoding="utf-8")
    )
    assert hashlib.sha256(
        (ROOT / result["manifest_path"]).read_bytes()
    ).hexdigest() == result["manifest_sha256"]
    for case, registered in zip(result["cases"], manifest["inputs"]):
        assert case["case_id"] == registered["case_id"]
        assert hashlib.sha256(
            (ROOT / registered["checkpoint_path"]).read_bytes()
        ).hexdigest() == registered["checkpoint_sha256"]
    counts = {
        case["case_id"]: (case["candidate_count"], case["certified_count"])
        for case in result["cases"]
    }
    assert counts == {
        "lih-3.0": (0, 0),
        "h6-1.5": (2, 2),
        "h6-3.0": (0, 0),
        "beh2-3.0": (0, 0),
    }
    assert result["certified_candidate_count"] == 2
    assert result["adoption_gate_passed"] is True
    assert result["authorized_next_stage"] == "V5.1-S11"
    assert result["paper_measurement_cost"] is None


def test_every_certified_fusion_reduces_physical_circuit_without_energy_loss():
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    records = [
        record for case in result["cases"] for record in case["candidates"]
    ]
    assert len(records) == 2
    for record in records:
        assert record["certified"] is True
        assert all(record["checks"].values())
        assert record["operator_audit"]["generator_identity_residual"] == 0.0
        assert record["operator_audit"]["maximum_commutator_residual"] == 0.0
        assert record["absolute_energy_drift_hartree"] <= 1e-10
        assert record["source_resources"]["cnot_count"] == 879
        assert record["target_resources"]["cnot_count"] == 870
        assert record["source_resources"]["parameter_count"] == 137
        assert record["target_resources"]["parameter_count"] == 136


import hashlib
import json
from pathlib import Path

from dvg_obs_ceo.identity import canonical_json_bytes


ROOT = Path(__file__).resolve().parents[1]
RESULT = ROOT / "artifacts/v5/s11/h6-1.5-exact-fusion-v1.json"


def test_s11_result_digest_inputs_and_acceptance_are_fixed():
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    content = dict(result)
    digest = content.pop("result_digest")
    assert hashlib.sha256(canonical_json_bytes(content)).hexdigest() == digest
    assert hashlib.sha256(
        (ROOT / result["manifest_path"]).read_bytes()
    ).hexdigest() == result["manifest_sha256"]
    assert result["passed"] is True
    assert all(result["checks"].values())
    assert result["state_fidelity"] >= 0.9999999999
    assert result["absolute_energy_drift_hartree"] <= 1e-10
    assert result["work"]["optimizer_starts"] == 0
    assert result["work"]["optimizer_iterations"] == 0
    assert result["work"]["paper_measurement_cost"] is None


def test_s11_joint_fusion_strictly_improves_v4_1_resources_losslessly():
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    source = result["source"]["resources"]
    target = result["target"]["resources"]
    assert (source["cnot_count"], target["cnot_count"]) == (858, 840)
    assert (source["parameter_count"], target["parameter_count"]) == (131, 129)
    assert (source["total_depth"], target["total_depth"]) == (1546, 1520)
    assert (source["cnot_depth"], target["cnot_depth"]) == (300, 300)
    assert (source["logical_block_count"], target["logical_block_count"]) == (78, 76)
    assert abs(
        result["target"]["energy_hartree"] - result["source"]["energy_hartree"]
    ) <= 1e-10


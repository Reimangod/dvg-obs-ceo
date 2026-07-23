import hashlib
import json
from pathlib import Path

from dvg_obs_ceo.identity import canonical_json_bytes


ROOT = Path(__file__).resolve().parents[1]
RESULT = ROOT / "artifacts/v5/s11/h6-1.5-s9-fusion-integration-v1.json"


def test_s11b_result_is_auditable_and_explicitly_outcome_informed():
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    content = dict(result)
    digest = content.pop("result_digest")
    assert hashlib.sha256(canonical_json_bytes(content)).hexdigest() == digest
    assert hashlib.sha256(
        (ROOT / result["manifest_path"]).read_bytes()
    ).hexdigest() == result["manifest_sha256"]
    assert result["classification"] == "outcome-informed-exploratory-integration"
    assert result["passed"] is True
    assert all(result["checks"].values())
    assert result["absolute_energy_drift_hartree"] == 0.0
    assert result["state_fidelity"] >= 0.9999999999
    assert result["work"]["optimizer_starts"] == 0
    assert result["work"]["paper_measurement_cost"] is None


def test_s11b_exact_fusion_improves_every_s9_resource_without_energy_loss():
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    source = result["source"]["resources"]
    target = result["target"]["resources"]
    assert (source["cnot_count"], target["cnot_count"]) == (858, 840)
    assert (source["parameter_count"], target["parameter_count"]) == (132, 130)
    assert (source["total_depth"], target["total_depth"]) == (1549, 1523)
    assert (source["cnot_depth"], target["cnot_depth"]) == (301, 301)
    assert (source["logical_block_count"], target["logical_block_count"]) == (78, 76)
    assert result["target"]["energy_hartree"] == result["source"]["energy_hartree"]


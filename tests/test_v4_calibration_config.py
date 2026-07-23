import hashlib
import json
from pathlib import Path

from dvg_obs_ceo.identity import canonical_json_bytes


ROOT = Path(__file__).resolve().parents[1]


def test_v4_s6_configuration_digest_and_fail_closed_rules() -> None:
    manifest = json.loads((ROOT / "manifests/v4-s6-frozen-config-v1.json").read_text())
    digest = hashlib.sha256(canonical_json_bytes(manifest["configuration"])).hexdigest()
    assert digest == manifest["configuration_digest"]
    assert all(manifest["stop_rules"].values())
    assert manifest["calibration_interpretation"]["positive_class_metrics_available"] is False
    assert manifest["calibration_interpretation"]["held_out_joint_secants_available"] is False


def test_v4_s6_exact_attempt_and_accuracy_guards_are_unchanged() -> None:
    configuration = json.loads(
        (ROOT / "manifests/v4-s6-frozen-config-v1.json").read_text()
    )["configuration"]
    assert configuration["exact_vqe_budget"] == {
        "top_k_per_endpoint": 2,
        "maximum_unique_exact_attempts": 4,
    }
    assert configuration["acceptance"]["cumulative_energy_budget_hartree"] == 1e-4
    assert configuration["acceptance"]["maximum_stationarity_residual"] == 1e-8

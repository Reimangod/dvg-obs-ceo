import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_cp_integration_freeze_binds_successful_calibration_probe():
    manifest = json.loads(
        (ROOT / "manifests/v5-s8-lih-cp-integration-v1.json").read_text()
    )
    evidence = manifest["calibration_evidence"]
    assert hashlib.sha256((ROOT / evidence["probe_path"]).read_bytes()).hexdigest() == evidence["probe_sha256"]
    assert hashlib.sha256((ROOT / evidence["audit_path"]).read_bytes()).hexdigest() == evidence["audit_sha256"]
    assert manifest["algorithm"]["fresh_execution"] is True
    assert manifest["algorithm"]["probe_coordinates_reused"] is False
    assert manifest["algorithm"]["threshold_relaxation"] is False
    assert manifest["algorithm"]["full_ablation_F"] is False

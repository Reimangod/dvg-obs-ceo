import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_s8_freeze_binds_all_evidence_and_protocol():
    manifest = json.loads(
        (ROOT / "manifests/v5-s8-calibration-freeze-v1.json").read_text(
            encoding="utf-8"
        )
    )
    assert all(
        hashlib.sha256((ROOT / item["path"]).read_bytes()).hexdigest()
        == item["sha256"]
        for item in manifest["evidence"]
    )
    protocol = manifest["frozen_s9_protocol"]
    assert protocol["width"] == 2
    assert protocol["maximum_rounds"] == 3
    assert protocol["maximum_exact_attempts"] == 6
    assert protocol["threshold_relaxation"] is False
    assert protocol["complete_terminal_catalog_accounting"] is True
    assert protocol["paper_measurement_cost"] is None
    decision = manifest["calibration_decision"]
    assert decision["width4_adopted"] is False
    assert decision["width8_executed"] is False
    assert manifest["s9_entry_gate"]["performance_superiority_established"] is False

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_lih_transfer_manifest_binds_unopened_checkpoint_and_small_system_choice():
    manifest = json.loads(
        (ROOT / "manifests/v5-s8-lih-width1-transfer-v1.json").read_text()
    )
    checkpoint = ROOT / manifest["input_checkpoint"]["path"]
    assert hashlib.sha256(checkpoint.read_bytes()).hexdigest() == manifest["input_checkpoint"]["sha256"]
    assert manifest["algorithm"]["ablation"] == "C"
    assert manifest["algorithm"]["maximum_exact_vqe_attempts"] == 2
    assert manifest["algorithm"]["fresh_hessian_or_hvp"] is False


def test_small_system_decision_does_not_claim_confirmation():
    decision = json.loads(
        (ROOT / "manifests/v5-s8-small-system-decision-v1.json").read_text()
    )
    assert decision["status"] == "frozen-before-lih-transfer"
    assert decision["lih_transfer_choice"]["threshold_changes"] is False
    assert any("not confirmatory" in line for line in decision["anti_overfitting_boundary"])

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_polishing_probe_freeze_binds_audited_trigger():
    manifest = json.loads(
        (ROOT / "manifests/v5-s8-lih-conditional-polishing-probe-v1.json").read_text()
    )
    trigger = manifest["trigger_evidence"]
    assert hashlib.sha256((ROOT / trigger["result_path"]).read_bytes()).hexdigest() == trigger["result_sha256"]
    assert hashlib.sha256((ROOT / trigger["audit_path"]).read_bytes()).hexdigest() == trigger["audit_sha256"]
    assert manifest["algorithm"]["candidate_reselection"] is False
    assert manifest["algorithm"]["threshold_relaxation"] is False
    assert "not-full-ablation-F" in manifest["algorithm"]["role"]

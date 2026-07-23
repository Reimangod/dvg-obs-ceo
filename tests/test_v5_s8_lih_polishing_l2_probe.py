import hashlib
import json
from pathlib import Path

from dvg_obs_ceo.polishing import TrustNCGConfig


ROOT = Path(__file__).resolve().parents[1]


def test_l2_alignment_is_not_an_infinity_gate_relaxation():
    config = TrustNCGConfig(gradient_l2_tolerance=1e-8)
    assert config.gradient_l2_tolerance == config.certification_infinity_threshold
    config.validate()


def test_l2_alignment_manifest_binds_negative_parent_probe():
    manifest = json.loads(
        (ROOT / "manifests/v5-s8-lih-polishing-l2-alignment-probe-v1.json").read_text()
    )
    parent = manifest["parent_probe"]
    assert hashlib.sha256((ROOT / parent["result_path"]).read_bytes()).hexdigest() == parent["result_sha256"]
    assert hashlib.sha256((ROOT / parent["audit_path"]).read_bytes()).hexdigest() == parent["audit_sha256"]
    assert manifest["single_change"]["after"] == manifest["unchanged"]["scientific_gradient_infinity_gate"]

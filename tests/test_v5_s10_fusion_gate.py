import json
from pathlib import Path

from dvg_obs_ceo.v5_s10_fusion_gate import MANIFEST


ROOT = Path(__file__).resolve().parents[1]


def test_s10_manifest_separates_v5_1_and_forbids_unsafe_shortcuts():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["extension_version"] == "V5.1"
    assert manifest["candidate_family"]["generic_qiskit_compilation"] is False
    assert manifest["candidate_family"]["floating_coefficient_inference"] is False
    assert manifest["candidate_family"]["requires_operator_commutator_audit"] is True
    assert len(manifest["inputs"]) == 4
    assert manifest["paper_measurement_cost"] is None
    assert "coefficient-only deletion claims" in manifest["forbidden"]


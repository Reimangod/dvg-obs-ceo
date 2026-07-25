import hashlib
import inspect
import json
from pathlib import Path

from dvg_obs_ceo.v5_s8_h4_width1 import _measurement_id, _state_id


ROOT = Path(__file__).resolve().parents[1]


def test_execution_manifest_binds_inputs_and_rejected_work_policy():
    manifest = json.loads(
        (ROOT / "manifests/v5-s8-h4-width1-recycled-v1.json").read_text()
    )
    for field in ("parent_protocol", "input_checkpoint"):
        path = ROOT / manifest[field]["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == manifest[field]["sha256"]
    assert manifest["algorithm"]["count_rejected_work"] is True
    assert manifest["algorithm"]["fresh_hessian_or_hvp"] is False
    assert manifest["paper_measurement_cost"] is None


def test_pilot_amendment_forbids_scientific_changes():
    amendment = json.loads(
        (ROOT / "manifests/v5-s8-h4-width1-recycled-amendment-v1.json").read_text()
    )
    assert amendment["rerun_required"] is True
    assert "change candidate ranking" in amendment["changes_forbidden"]
    assert "use pilot outcomes in screening" in amendment["changes_forbidden"]


def test_state_and_measurement_identity_separate_processing_context():
    state = "state-v1:" + "a" * 64
    problem = "problem-v1:" + "b" * 64
    measurement = _measurement_id(state, problem)
    assert state.startswith("state-v1:")
    assert measurement.startswith("measurement-v1:")
    assert state != measurement


def test_production_state_id_delegates_to_canonical_three_layer_identity():
    source = inspect.getsource(_state_id)
    assert "state_preparation_spec" in source
    assert "tobytes" not in source
    assert "versioned_id" not in source

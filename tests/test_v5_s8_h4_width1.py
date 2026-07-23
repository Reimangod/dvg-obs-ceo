import hashlib
import json
from pathlib import Path

import numpy as np

from dvg_obs_ceo.resources import AnsatzStructure
from dvg_obs_ceo.telemetry import WorkCounters
from dvg_obs_ceo.transaction import CompressionRuntime
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


def test_state_and_measurement_identity_separate_processing_context():
    runtime = CompressionRuntime.create(
        ansatz=AnsatzStructure.create([1], [0.25], [1]),
        energy_hartree=-1.0,
        gradient=[0.0],
        inverse_hessian=np.eye(1),
        statevector=[1.0, 0.0],
        work=WorkCounters(),
        adapt_iteration=1,
        metadata={
            "resource_structure_digest": "a" * 64,
            "budget_reference_energy_hartree": -1.0,
        },
    )
    state = _state_id(runtime)
    problem = "problem-v1:" + "b" * 64
    measurement = _measurement_id(state, problem)
    assert state.startswith("state-v1:")
    assert measurement.startswith("measurement-v1:")
    assert state != measurement


def test_state_identity_changes_with_canonical_coefficient_bytes():
    runtime = CompressionRuntime.create(
        ansatz=AnsatzStructure.create([1], [0.25], [1]),
        energy_hartree=-1.0,
        gradient=[0.0],
        inverse_hessian=np.eye(1),
        statevector=[1.0, 0.0],
        work=WorkCounters(),
        adapt_iteration=1,
        metadata={
            "resource_structure_digest": "a" * 64,
            "budget_reference_energy_hartree": -1.0,
        },
    )
    first = _state_id(runtime)
    runtime.ansatz = AnsatzStructure.create([1], [0.5], [1])
    assert _state_id(runtime) != first

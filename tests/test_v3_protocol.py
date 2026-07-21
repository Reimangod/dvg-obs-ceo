import json
from pathlib import Path

import pytest

from dvg_obs_ceo.v3_protocol import (
    DEFAULT_MANIFEST,
    V3ProtocolError,
    audit_inputs,
)


def test_registered_v3_inputs_and_scope_are_immutable() -> None:
    result = audit_inputs()
    assert result["passed"]
    assert not result["failed_checks"]
    assert len(result["checks"]) >= 30


def test_v3_manifest_rejects_candidate_reselection(tmp_path: Path) -> None:
    manifest = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    manifest["immutable_candidate"]["candidate_id"] = "candidate-v1:" + "0" * 64
    path = tmp_path / "tampered.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(V3ProtocolError, match="candidate_identity:candidate_id"):
        audit_inputs(path)


def test_v3_manifest_rejects_threshold_relaxation(tmp_path: Path) -> None:
    manifest = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    manifest["acceptance"]["maximum_stationarity_residual"] = 3e-8
    path = tmp_path / "tampered.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(V3ProtocolError, match="criteria_unchanged"):
        audit_inputs(path)


def test_v3_manifest_rejects_repository_escape(tmp_path: Path) -> None:
    manifest = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    manifest["source_files"]["plan"]["path"] = "../outside.json"
    path = tmp_path / "tampered.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(V3ProtocolError, match="escapes repository"):
        audit_inputs(path)

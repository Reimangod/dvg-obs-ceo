import json
from pathlib import Path

import pytest

from dvg_obs_ceo.v4_1_protocol import DEFAULT_MANIFEST, V41ProtocolError, audit_manifest


def test_v4_1_parent_evidence_and_protocol_are_frozen() -> None:
    result = audit_manifest()
    assert result["passed"]
    assert len(result["checks"]) >= 20


def test_v4_1_rejects_checkpoint_drift(tmp_path: Path) -> None:
    manifest = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    manifest["cases"][0]["checkpoint_sha256"] = "0" * 64
    path = tmp_path / "tampered.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(V41ProtocolError, match="checkpoint_sha256:h6-1.5"):
        audit_manifest(path)


def test_v4_1_rejects_postselection_expansion(tmp_path: Path) -> None:
    manifest = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    manifest["frozen_scientific_invariants"]["maximum_unique_exact_attempts_per_case"] = 40
    path = tmp_path / "tampered.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(V41ProtocolError, match="scientific_guards"):
        audit_manifest(path)


def test_v4_1_rejects_non_atomic_execution_policy(tmp_path: Path) -> None:
    manifest = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    manifest["execution_safety"]["atomic_promotion"] = False
    path = tmp_path / "tampered.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(V41ProtocolError, match="execution_fail_closed"):
        audit_manifest(path)

import json
from pathlib import Path

import pytest

from dvg_obs_ceo.v4_protocol import DEFAULT_MANIFEST, V4ProtocolError, audit_manifest


def test_v4_protocol_and_sources_are_frozen() -> None:
    result = audit_manifest()
    assert result["passed"]
    assert len(result["checks"]) >= 20


def test_v4_protocol_rejects_more_postselected_attempts(tmp_path: Path) -> None:
    manifest = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    manifest["exact_vqe_budget"]["maximum_unique_exact_attempts"] = 20
    path = tmp_path / "tampered.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(V4ProtocolError, match="bounded_exact_attempts"):
        audit_manifest(path)


def test_v4_protocol_rejects_resource_regression(tmp_path: Path) -> None:
    manifest = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    manifest["co_primary_endpoints"]["componentwise_nonworse_guards"].remove("cnot_depth")
    path = tmp_path / "tampered.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(V4ProtocolError, match="hard_guards"):
        audit_manifest(path)

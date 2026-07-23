import json
from pathlib import Path

import pytest

from dvg_obs_ceo.v3_gradient_result_audit import (
    DEFAULT_RESULT,
    V3GradientResultAuditError,
    audit_result,
)


def test_committed_s1_result_reconciles() -> None:
    result = audit_result()
    assert result["passed"]
    assert not result["failed_checks"]


def test_s1_result_auditor_rejects_changed_component(tmp_path: Path) -> None:
    artifact = json.loads(DEFAULT_RESULT.read_text(encoding="utf-8"))
    certificate = artifact["results"][1]["certificate"]
    certificate["componentwise_difference"][0] = 1.0
    path = tmp_path / "tampered.json"
    path.write_text(json.dumps(artifact), encoding="utf-8")
    with pytest.raises(V3GradientResultAuditError, match="entry_recomputation"):
        audit_result(path)

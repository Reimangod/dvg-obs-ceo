import json
from pathlib import Path

import pytest

from dvg_obs_ceo.v3_polishing_result_audit import (
    DEFAULT_RESULT,
    V3PolishingResultAuditError,
    audit_result,
)


def test_s2_failed_result_is_complete_and_consistent() -> None:
    result = audit_result()
    assert result["passed"]
    assert result["scientific_outcome"] == "calibration-unsuccessful-lih-not-authorized"


def test_s2_auditor_rejects_relabelled_success(tmp_path: Path) -> None:
    artifact = json.loads(DEFAULT_RESULT.read_text(encoding="utf-8"))
    artifact["passed"] = True
    path = tmp_path / "tampered.json"
    path.write_text(json.dumps(artifact), encoding="utf-8")
    with pytest.raises(V3PolishingResultAuditError, match="calibration_failed"):
        audit_result(path)

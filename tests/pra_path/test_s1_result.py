from __future__ import annotations

import json
from pathlib import Path

from dvg_obs_ceo.pra_path.s1_gradient_identity_audit import audit_report


ROOT = Path(__file__).resolve().parents[2]


def test_s1_result_corrects_names_without_changing_decisions() -> None:
    result = json.loads(
        (
            ROOT
            / "artifacts/pra_path/s1/gradient-identity-audit-v1.json"
        ).read_text()
    )
    audit_report(result)
    assert result["decision"] == "GO_S2_FIELD_NAMING_CORRECTION"
    assert result["authorization"]["s2"] is True
    assert result["interpretation"]["historical_ns7_decisions_changed"] is False
    assert all(item["identity_established"] for item in result["contexts"])

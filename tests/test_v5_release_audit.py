import json

from dvg_obs_ceo.v5_release_audit import ROOT, audit


def test_v5_release_evidence_chain_passes_independent_static_audit():
    result = audit()
    assert result["passed"] is True
    assert all(result["checks"].values())
    assert result["paper_measurement_cost"] is None
    stored = json.loads(
        (ROOT / "artifacts/v5/release/audit-v1.json").read_text(encoding="utf-8")
    )
    assert stored == result

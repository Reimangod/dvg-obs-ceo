from dvg_obs_ceo.v4_release_audit import audit_evidence


def test_frozen_v4_evidence_passes_release_checks() -> None:
    checks, details = audit_evidence()
    assert all(checks.values()), checks
    assert details["tracked_raw_paths"] == []
    assert len(details["required_tag_commits"]) == 7

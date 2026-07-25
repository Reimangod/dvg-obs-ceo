from dvg_obs_ceo.v6_rank_adaptive.s9_result_audit import audit_result


def test_committed_s9_result_and_rollbacks_are_consistent():
    audit = audit_result()
    assert audit["passed"]
    assert all(audit["checks"].values())

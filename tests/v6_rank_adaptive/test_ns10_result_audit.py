from dvg_obs_ceo.v6_rank_adaptive.ns10_result_audit import audit_result


def test_ns10_result_passes_independent_audit():
    audit = audit_result()
    assert audit["passed"]
    assert all(audit["checks"].values())

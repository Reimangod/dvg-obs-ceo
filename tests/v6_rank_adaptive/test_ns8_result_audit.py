from dvg_obs_ceo.v6_rank_adaptive.ns8_result_audit import audit_result


def test_ns8_result_passes_independent_audit():
    audit = audit_result()
    assert audit["passed"]
    assert all(audit["checks"].values())

from dvg_obs_ceo.v6_rank_adaptive.ns7_result_audit import audit_result


def test_ns7_result_is_internally_consistent():
    audit = audit_result()
    assert audit["passed"]
    assert all(audit["checks"].values())


def test_resource_audit_does_not_require_equal_parameterized_qasm_digest():
    """NS5 and NS7 use different angles but must have equal gate resources."""
    audit = audit_result()
    assert audit["checks"]["resource_recounts_match_ns5"]

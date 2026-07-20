from dvg_obs_ceo.s11_compare import audit_sources


def test_s11_source_artifacts_pass_independent_comparison_audit() -> None:
    gsd, s10, audit = audit_sources()
    assert audit["passed"] is True
    assert all(audit["checks"].values())
    assert gsd["paper_resource_parity"] == {
        "cnot_count": True,
        "cnot_depth": True,
        "measurement_cost": None,
    }
    assert s10["dvg_obs_ceo"]["accepted"] is False

from dvg_obs_ceo.v6_rank_adaptive.s9_fault_audit import (
    SCENARIOS,
    run_fault_audit,
)


def test_s9_fault_audit_restores_every_registered_stage():
    report = run_fault_audit()
    assert report["all_passed"]
    assert {item["scenario"] for item in report["scenarios"]} == set(
        SCENARIOS
    )
    assert all(item["rollback_exact"] for item in report["scenarios"])
    assert all(
        item["committed_artifact_absent"]
        for item in report["scenarios"]
    )

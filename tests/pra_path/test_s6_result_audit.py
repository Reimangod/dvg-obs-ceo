from __future__ import annotations

from dvg_obs_ceo.pra_path.s6_result_audit import build_audit


def test_s6_result_reconciles_and_preserves_no_go() -> None:
    audit = build_audit()
    assert audit["decision"] == "S6_RESULT_VALID_NO_GO_PERFORMANCE_ROUTE"
    assert all(audit["checks"].values())
    assert audit["authorization"]["s7"] is False
    assert audit["authorization"]["s10_closure_gate"] is True


def test_h5_failure_is_not_energy_or_resource_failure() -> None:
    audit = build_audit()
    signature = audit["h5_failure_signature"]
    assert signature["all_pass_energy_budget"]
    assert signature["all_pass_semantic_native_evidence"]
    assert signature["all_pass_resource_policy"]
    assert signature["all_fail_orthonormal_tangent_stationarity"]

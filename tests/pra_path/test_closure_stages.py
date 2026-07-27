from __future__ import annotations

from dvg_obs_ceo.pra_path.closure_stages import build_s7


def test_s7_fails_closed_after_s6_no_go() -> None:
    report = build_s7()
    assert report["status"] == "NOT_AUTHORIZED"
    assert report["matched_work_executed"] is False
    assert report["causal_ablation_executed"] is False
    assert report["authorization"]["s8"] is False

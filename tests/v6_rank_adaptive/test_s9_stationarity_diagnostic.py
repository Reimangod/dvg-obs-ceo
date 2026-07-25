import json

from dvg_obs_ceo.identity import sha256_hex
from dvg_obs_ceo.v6_rank_adaptive.s9_stationarity_diagnostic import (
    DEFAULT_OUTPUT,
    build_report,
)


def test_s9_d_is_read_only_and_does_not_reassess_acceptance():
    report = build_report()
    assert report["work"]["optimizer_runs"] == 0
    assert report["work"]["energy_evaluations"] == 0
    assert report["work"]["gradient_evaluations"] == 0
    assert report["work"]["hvp_evaluations"] == 0
    assert all(
        item["no_new_quantum_or_optimizer_work"]
        and not item["acceptance_reassessed"]
        for item in report["candidate_diagnostics"]
    )


def test_committed_s9_d_digest_and_claim_boundary():
    report = json.loads(DEFAULT_OUTPUT.read_text(encoding="utf-8"))
    digest = report.pop("report_digest")
    assert digest == sha256_hex(report)
    assert len(report["candidate_diagnostics"]) == 2
    assert all(
        item["stationarity"]["gradient_infinity"]
        > item["stationarity"]["fixed_threshold"]
        and item["surrogate_curvature"]["not_exact_physical_hessian"]
        for item in report["candidate_diagnostics"]
    )

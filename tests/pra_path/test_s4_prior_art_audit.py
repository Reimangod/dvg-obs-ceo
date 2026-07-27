from __future__ import annotations

from dvg_obs_ceo.pra_path.s4_prior_art_audit import (
    FEATURES,
    audit_report,
    build_report,
    primary_sources,
)


def test_publication_status_and_identifiers_are_explicit() -> None:
    sources = primary_sources()
    statuses = {source["publication_status"] for source in sources}
    assert {"peer reviewed", "preprint"}.issubset(statuses)
    for source in sources:
        assert source["identifier"]
        assert source["url"].startswith("https://")
        assert set(source["features"]) == set(FEATURES)


def test_direct_prior_art_is_not_claimed_as_new() -> None:
    report = build_report()
    overlap = " ".join(report["direct_overlap"]).lower()
    assert "ceo" in overlap
    assert "pruning" in overlap
    assert "qfi" in overlap
    assert "excitation synthesis" in overlap


def test_bounded_audit_does_not_claim_world_exhaustiveness() -> None:
    report = build_report()
    assert report["audit_scope"]["exhaustive_world_literature_claim"] is False
    assert report["exact_protocol_matches_in_bounded_audit"] == []
    assert report["authorization"]["s5"] is True
    assert report["authorization"]["performance_execution"] is False
    audit_report(report)

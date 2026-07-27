from __future__ import annotations

from dvg_obs_ceo.pra_path.s5_applicability_census import (
    DEVELOPMENT_CASES,
    PROSPECTIVE_ORDER,
)


def test_development_and_prospective_molecules_do_not_overlap() -> None:
    development = {case["molecule"] for case in DEVELOPMENT_CASES}
    prospective = {case["molecule"] for case in PROSPECTIVE_ORDER}
    assert development.isdisjoint(prospective)


def test_low_cost_then_cross_system_order_is_frozen() -> None:
    roles = [case["role"] for case in DEVELOPMENT_CASES]
    assert roles[:2] == ["development-low-cost-reproducibility"] * 2
    assert roles[-1] == "development-cross-system"
    assert [case["case_id"] for case in DEVELOPMENT_CASES] == [
        "h4-1.0",
        "h4-2.0",
        "h5-1.5",
    ]


def test_prospective_rule_requires_two_geometries() -> None:
    assert PROSPECTIVE_ORDER
    for item in PROSPECTIVE_ORDER:
        assert len(item["geometries_angstrom"]) == 2
        assert len(set(item["geometries_angstrom"])) == 2

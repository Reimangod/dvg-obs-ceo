from __future__ import annotations

from dvg_obs_ceo.v4_1_exact_audit import (
    _contains_key,
    _resource_snapshots_equal,
    _same_unique_candidate_set,
)


def test_energy_leak_detection_is_recursive() -> None:
    assert _contains_key({"nested": [{"actual_energy_hartree": -1.0}]}, "actual_energy_hartree")
    assert not _contains_key({"predicted_loss_hartree": 1e-5}, "actual_energy_hartree")


def test_resource_audit_compares_snapshot_not_policy_provenance() -> None:
    physical = {"coefficient_policy": "physical", "snapshot": {"cnot_count": 8}}
    structural = {"coefficient_policy": "deterministic-structural", "snapshot": {"cnot_count": 8}}
    assert physical != structural
    assert _resource_snapshots_equal(physical, structural)
    structural["snapshot"]["cnot_count"] = 7
    assert not _resource_snapshots_equal(physical, structural)


def test_candidate_composition_identity_is_order_independent_but_duplicate_safe() -> None:
    assert _same_unique_candidate_set(["b", "a"], ["a", "b"])
    assert not _same_unique_candidate_set(["a", "a"], ["a", "a"])
    assert not _same_unique_candidate_set(["a"], ["b"])

from __future__ import annotations

from dvg_obs_ceo.v4_1_exact_audit import _contains_key, _resource_snapshots_equal


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

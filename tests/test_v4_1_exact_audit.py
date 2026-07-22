from __future__ import annotations

from dvg_obs_ceo.v4_1_exact_audit import _contains_key


def test_energy_leak_detection_is_recursive() -> None:
    assert _contains_key({"nested": [{"actual_energy_hartree": -1.0}]}, "actual_energy_hartree")
    assert not _contains_key({"predicted_loss_hartree": 1e-5}, "actual_energy_hartree")

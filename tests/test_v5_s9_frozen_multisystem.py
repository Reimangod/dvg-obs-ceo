import hashlib
import json
from pathlib import Path

import pytest

from dvg_obs_ceo.v5_s8_lih_multitrajectory import (
    V5S8LiHMultiTrajectoryError,
    _effective_energy_budget,
)


ROOT = Path(__file__).resolve().parents[1]


def test_s9_manifest_binds_checkpoints_and_carry_forward():
    manifest = json.loads(
        (ROOT / "manifests/v5-s9-frozen-development-v1.json").read_text(
            encoding="utf-8"
        )
    )
    s8 = manifest["s8_freeze"]
    assert hashlib.sha256(
        (ROOT / s8["manifest_path"]).read_bytes()
    ).hexdigest() == s8["manifest_sha256"]
    for case in manifest["cases"]:
        assert hashlib.sha256(
            (ROOT / case["checkpoint_path"]).read_bytes()
        ).hexdigest() == case["checkpoint_sha256"]
    carry = manifest["lih_handling"]
    assert hashlib.sha256(
        (ROOT / carry["carry_forward_path"]).read_bytes()
    ).hexdigest() == carry["carry_forward_sha256"]
    assert hashlib.sha256(
        (ROOT / carry["carry_forward_audit_path"]).read_bytes()
    ).hexdigest() == carry["carry_forward_audit_sha256"]
    protocol = manifest["protocol"]
    assert protocol["maximum_exact_attempts"] == 6
    assert protocol["threshold_relaxation"] is False
    assert protocol["complete_terminal_catalog_accounting"] is True


def test_historical_manifest_records_oracle_assisted_budget_rule():
    manifest = json.loads(
        (ROOT / "manifests/v5-s9-frozen-development-v1.json").read_text(
            encoding="utf-8"
        )
    )
    rule = manifest["protocol"]["effective_energy_budget_rule"]
    assert rule == (
        "min(algorithmic budget, nextafter(chemical-accuracy margin, -infinity))"
    )


def test_deployable_budget_is_invariant_to_fci_poisoning():
    checkpoint = {
        "energy_hartree": -2.0,
        "exact_energy_hartree": -2.1,
        "chemical_accuracy_hartree": 0.0015936,
    }
    poisoned = {
        **checkpoint,
        "exact_energy_hartree": 1.0e12,
        "chemical_accuracy_hartree": 9.0e11,
    }
    assert _effective_energy_budget(
        checkpoint, enforce_chemical_accuracy=False
    ) == (1e-4, None)
    assert _effective_energy_budget(
        poisoned, enforce_chemical_accuracy=False
    ) == (1e-4, None)


def test_runtime_chemical_accuracy_enforcement_fails_closed():
    with pytest.raises(V5S8LiHMultiTrajectoryError, match="offline"):
        _effective_energy_budget({}, enforce_chemical_accuracy=True)

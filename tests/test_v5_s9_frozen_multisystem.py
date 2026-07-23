import hashlib
import json
from pathlib import Path

import numpy as np

from dvg_obs_ceo.v5_s8_lih_multitrajectory import _effective_energy_budget


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


def test_chemical_accuracy_guard_is_common_and_fail_closed():
    manifest = json.loads(
        (ROOT / "manifests/v5-s9-frozen-development-v1.json").read_text(
            encoding="utf-8"
        )
    )
    rule = manifest["protocol"]["effective_energy_budget_rule"]
    assert rule == (
        "min(algorithmic budget, nextafter(chemical-accuracy margin, -infinity))"
    )
    cases = {
        item["case_id"]: json.loads(
            (ROOT / item["checkpoint_path"]).read_text(encoding="utf-8")
        )
        for item in manifest["cases"]
    }
    h6_15_budget, h6_15_margin = _effective_energy_budget(
        cases["h6-1.5"], enforce_chemical_accuracy=True
    )
    h6_30_budget, h6_30_margin = _effective_energy_budget(
        cases["h6-3.0"], enforce_chemical_accuracy=True
    )
    assert h6_15_budget == 1e-4
    assert h6_15_margin > 1e-4
    assert h6_30_margin < 1e-4
    assert h6_30_budget == float(np.nextafter(h6_30_margin, -np.inf))

import json
from pathlib import Path

import pytest

from dvg_obs_ceo.v3_polishing_calibration import (
    DEFAULT_MANIFEST,
    V3PolishingCalibrationError,
    _load_manifest,
)


def test_s2_manifest_matches_runtime_and_local_scipy_sources() -> None:
    manifest, config = _load_manifest(DEFAULT_MANIFEST)
    assert manifest["scope"]["solver_family_count"] == 1
    assert manifest["scope"]["lih_evaluations"] == 0
    assert config.fallback_policy == "none-fail-closed"


def test_s2_manifest_rejects_lih_specific_retuning(tmp_path: Path) -> None:
    manifest = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    manifest["solver"]["gradient_l2_tolerance"] = 3e-8
    path = tmp_path / "retuned.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(V3PolishingCalibrationError, match="configuration differs"):
        _load_manifest(path)

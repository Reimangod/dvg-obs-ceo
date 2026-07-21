import json
from pathlib import Path

import pytest

from dvg_obs_ceo.v3_gradient_audit import (
    DEFAULT_MANIFEST,
    V3GradientAuditError,
    _load_and_verify,
)


def test_s1_manifest_and_inputs_are_frozen() -> None:
    manifest, rows, checkpoints = _load_and_verify(DEFAULT_MANIFEST)
    assert manifest["evaluation"]["checkpoint_gradient_reuse"] is False
    assert manifest["evaluation"]["ordinary_gsd_adapt_iterations"] == 0
    assert len(rows) == 17
    assert set(checkpoints) == {
        "h2-1.5-iteration-1",
        "h4-1.5-first-chemical-accuracy",
    }


def test_s1_rejects_tolerance_change(tmp_path: Path) -> None:
    manifest = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    manifest["agreement_policy"]["absolute_tolerance"] = 1e-8
    path = tmp_path / "modified.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(V3GradientAuditError, match="policy was modified"):
        _load_and_verify(path)

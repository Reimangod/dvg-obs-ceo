from pathlib import Path

import pytest

from dvg_obs_ceo.s10_audit import S10AuditError, audit


REAL_BUNDLE = Path("artifacts/s10/lih-3a-first-accuracy-primary-v1-2")


@pytest.mark.skipif(not REAL_BUNDLE.exists(), reason="S10 molecular artifact is not installed")
def test_real_s10_bundle_passes_independent_audit() -> None:
    result = audit(REAL_BUNDLE)
    assert result["passed"]
    assert all(result["checks"].values())
    assert result["interpretation"]["scientific_outcome"].endswith("fully-rolled-back")


def test_missing_s10_bundle_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(S10AuditError, match="required JSON"):
        audit(tmp_path / "missing")

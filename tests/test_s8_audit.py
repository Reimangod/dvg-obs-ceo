from pathlib import Path

from dvg_obs_ceo.s8_audit import validate_bundle


ROOT = Path(__file__).resolve().parents[1]


def test_registered_s8_bundle_is_internally_consistent() -> None:
    bundle = ROOT / "artifacts" / "s8" / "calibration-bundle"
    if not bundle.exists():
        return
    audit = validate_bundle(bundle)
    assert audit["passed"]
    assert audit["executed_candidates"] == 17


def test_registered_s8_extension_keeps_checkpoint_failures_separate() -> None:
    bundle = ROOT / "artifacts" / "s8-1" / "later-checkpoint-calibration-bundle"
    if not bundle.exists():
        return
    audit = validate_bundle(bundle)
    assert audit["passed"]
    assert audit["executed_candidates"] == 62

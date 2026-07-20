from pathlib import Path

from dvg_obs_ceo.s8_audit import compare_recomputed_metrics, validate_bundle


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


def test_metric_audit_accepts_only_small_float_roundoff() -> None:
    recorded = [{"method": "obs", "count": 17, "score": 0.5}]
    observed = [{"method": "obs", "count": 17, "score": 0.5 + 1e-15}]
    comparison = compare_recomputed_metrics(observed, recorded)
    assert comparison["passed"]
    assert comparison["max_absolute_difference"] > 0.0


def test_metric_audit_rejects_scientifically_meaningful_float_change() -> None:
    recorded = [{"method": "obs", "count": 17, "score": 0.5}]
    observed = [{"method": "obs", "count": 17, "score": 0.500001}]
    comparison = compare_recomputed_metrics(observed, recorded)
    assert not comparison["passed"]
    assert comparison["mismatch_paths"] == ["metrics[0].score"]


def test_metric_audit_keeps_discrete_fields_exact() -> None:
    recorded = [{"method": "obs", "count": 17, "score": 0.5}]
    observed = [{"method": "obs", "count": 18, "score": 0.5}]
    comparison = compare_recomputed_metrics(observed, recorded)
    assert not comparison["passed"]
    assert comparison["mismatch_paths"] == ["metrics[0].count"]

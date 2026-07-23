import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_s9_summary_binds_all_audited_inputs_and_keeps_strict_gate():
    summary = json.loads(
        (ROOT / "artifacts/v5/s9/summary-v1.json").read_text(encoding="utf-8")
    )
    for item in summary["inputs"]:
        assert hashlib.sha256(
            (ROOT / item["result_path"]).read_bytes()
        ).hexdigest() == item["result_sha256"]
        assert hashlib.sha256(
            (ROOT / item["audit_path"]).read_bytes()
        ).hexdigest() == item["audit_sha256"]
    successes = [
        item["case_id"] for item in summary["cases"]
        if item["strict_primary_success"]
    ]
    assert successes == ["h6-3.0"]
    assert summary["performance_gates"]["primary_success_case_count"] == 1
    assert summary["performance_gates"]["strong_development_success_passed"] is False
    assert summary["performance_gates"]["global_v5_superiority_established"] is False
    assert summary["paper_measurement_cost"] is None

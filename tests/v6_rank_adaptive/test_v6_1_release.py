from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_v6_1_negative_release_matches_result_and_gate() -> None:
    result_path = ROOT / "artifacts/v6_1/t2/mechanism-audit-v1.json"
    manifest = json.loads(
        (ROOT / "artifacts/v6_1/release/negative-result-manifest-v1.json")
        .read_text()
    )
    result = json.loads(result_path.read_text())
    assert result["decision"] == manifest["decision"]
    assert result["authorization"] == {
        "t3_t4": False,
        "t5_t6_performance": False,
    }
    assert set(manifest["not_authorized_stages"]) == {"T3", "T4", "T5", "T6_performance"}
    assert hashlib.sha256(result_path.read_bytes()).hexdigest() == manifest[
        "input_and_result_sha256"
    ]["artifacts/v6_1/t2/mechanism-audit-v1.json"]
    assert all(value is False for value in manifest["integrity"].values())

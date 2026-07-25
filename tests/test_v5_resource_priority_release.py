import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AMENDMENT = ROOT / "artifacts/v5/release/resource-priority-amendment-v1.json"
STRICT_RELEASE = ROOT / "artifacts/v5/release/summary-v1.json"
ERRATA = ROOT / "artifacts/v5/release/correctness-errata-v1.json"


def test_resource_priority_amendment_binds_inputs_and_preserves_strict_labels():
    amendment = json.loads(AMENDMENT.read_text(encoding="utf-8"))
    for item in amendment["inputs"]:
        assert hashlib.sha256(
            (ROOT / item["path"]).read_bytes()
        ).hexdigest() == item["sha256"]
    rule = amendment["selection_rule"]
    assert rule["maximum_cumulative_energy_increase_hartree"] == 1e-4
    assert rule["strict_chemical_accuracy_required"] is True
    assert rule["does_not_reclassify_original_strict_success_tests"] is True
    assert amendment["scientific_results_modified"] is False


def test_every_selected_point_stays_inside_guard_and_expected_resources_match():
    amendment = json.loads(AMENDMENT.read_text(encoding="utf-8"))
    points = {item["case_id"]: item for item in amendment["selected_points"]}
    assert all(item["energy_increase_hartree"] <= 1e-4 for item in points.values())
    assert (points["h6-3.0"]["cnot_count"], points["h6-3.0"]["parameter_count"]) == (741, 138)
    assert (points["beh2-3.0"]["cnot_count"], points["beh2-3.0"]["parameter_count"]) == (221, 31)
    assert points["beh2-3.0"]["energy_increase_hartree"] > 9.8e-5


def test_resource_priority_policy_cannot_be_confused_with_strict_release():
    amendment = json.loads(AMENDMENT.read_text(encoding="utf-8"))
    strict = json.loads(STRICT_RELEASE.read_text(encoding="utf-8"))
    errata = json.loads(ERRATA.read_text(encoding="utf-8"))
    assert amendment["classification"] == "post-outcome-user-authorized-selection-policy"
    assert amendment["supersedes_release_choice_only"] is True
    assert strict["artifact_kind"] == "v5-v5.1-audited-development-release-summary"
    assert any(
        correction["id"] == "release-policy-nonidentity"
        for correction in errata["corrections"]
    )

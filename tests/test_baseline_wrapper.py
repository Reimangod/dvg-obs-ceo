import json
from pathlib import Path

import pytest

from dvg_obs_ceo.baseline import BaselineError, verify_upstream
from dvg_obs_ceo.parity import compare


ROOT = Path(__file__).resolve().parents[1]


def test_upstream_provenance_is_exact() -> None:
    provenance = verify_upstream()
    assert provenance["commit"] == "a3f89d03e6a03c89767d3cf8ee7657a57653dda0"
    assert provenance["git_tree"] == "794d847f5c1be1590d93da81b905a915dfa17d13"


def test_parity_accepts_registered_reference() -> None:
    manifest = json.loads(
        (ROOT / "manifests" / "baseline-lih-3a-v1.json").read_text()
    )
    reference = dict(manifest["expected_reference"])
    reference["first_chemical_accuracy_iteration"] = reference.pop("adapt_iteration")
    report = compare(reference, manifest)
    assert report["passed"]


def test_parity_rejects_single_resource_difference() -> None:
    manifest = json.loads(
        (ROOT / "manifests" / "baseline-lih-3a-v1.json").read_text()
    )
    reference = dict(manifest["expected_reference"])
    reference["first_chemical_accuracy_iteration"] = reference.pop("adapt_iteration")
    reference["cnot_count"] += 1
    report = compare(reference, manifest)
    assert not report["passed"]
    assert not report["checks"]["cnot_count"]["passed"]


def test_unknown_case_fails_before_mutation(tmp_path: Path) -> None:
    from dvg_obs_ceo.baseline import run_case

    with pytest.raises(BaselineError):
        run_case("unknown", tmp_path / "result.json")
    assert not (tmp_path / "result.json").exists()

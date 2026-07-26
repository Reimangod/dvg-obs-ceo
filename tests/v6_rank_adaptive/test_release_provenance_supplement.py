from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_release_provenance_supplement_is_finite_and_claim_safe() -> None:
    path = ROOT / "artifacts/v6/release/provenance-supplement-v1.json"
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["schema"] == "dvg-obs-ceo.v6.release-provenance-supplement.v1"
    assert payload["github_ci"]["conclusion"] == "success"
    assert payload["github_ci"]["test_count"] == 471
    assert payload["corrected_defect"]["scientific_outcome_impact"] == "none"
    assert payload["claim_boundary"]["changed"] is False
    assert payload["claim_boundary"]["pra_superiority_established"] is False
    assert len(payload["original_completion_tag"]["peeled_commit"]) == 40
    assert len(payload["submodule_commits"]["vendor/ceo-adapt-vqe"]) == 40

from __future__ import annotations

import json
from pathlib import Path

from dvg_obs_ceo.pra_path.s3_registry_audit import audit_report


ROOT = Path(__file__).resolve().parents[2]


def test_s3_result_is_complete_only_within_declared_finite_scope() -> None:
    result = json.loads(
        (
            ROOT / "artifacts/pra_path/s3/normal-registry-audit-v1.json"
        ).read_text()
    )
    audit_report(result)
    assert result["decision"] == "GO_S4_FINITE_REGISTRY_COMPLETE"
    assert result["scope"]["slot_permutation_equivalence"] is False
    assert result["scope"]["all_rank_two_subspaces_in_scope"] is False
    assert result["authorization"]["performance_execution"] is False

from __future__ import annotations

import json
from pathlib import Path

from dvg_obs_ceo.pra_path.s0_evidence_ledger import audit_ledger


ROOT = Path(__file__).resolve().parents[2]


def test_committed_s0_result_authorizes_only_identity_audit() -> None:
    value = json.loads(
        (ROOT / "artifacts/pra_path/s0/evidence-ledger-v1.json").read_text()
    )
    audit_ledger(value)
    assert value["status"] == "immutable-parent-reconciled"
    assert value["evidence_roles"]["prospective_selection_status"] == "NOT_SELECTED"

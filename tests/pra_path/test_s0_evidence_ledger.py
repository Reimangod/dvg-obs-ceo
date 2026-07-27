from __future__ import annotations

import pytest

from dvg_obs_ceo.pra_path.s0_evidence_ledger import (
    S0EvidenceLedgerError,
    audit_ledger,
    build_ledger,
)


def test_s0_ledger_reconciles_parent_without_new_claims() -> None:
    value = build_ledger()
    audit_ledger(value)
    assert value["status"] == "immutable-parent-reconciled"
    assert value["evidence_roles"]["prospective"] == []
    assert not any(value["claim_boundary"].values())


def test_s0_audit_rejects_relabelled_prospective_data() -> None:
    value = build_ledger()
    value["evidence_roles"]["prospective"] = ["H4 1.5 A"]
    with pytest.raises(S0EvidenceLedgerError, match="ledger digest"):
        audit_ledger(value)

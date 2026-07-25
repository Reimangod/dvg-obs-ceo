import json

import pytest

from dvg_obs_ceo import v5_release_audit
from dvg_obs_ceo.v5_release_audit import ROOT, audit


def test_v5_release_evidence_chain_passes_independent_static_audit():
    result = audit()
    assert result["passed"] is True
    assert all(result["checks"].values())
    assert result["paper_measurement_cost"] is None
    stored = json.loads(
        (ROOT / "artifacts/v5/release/audit-v1.json").read_text(encoding="utf-8")
    )
    assert stored["summary_sha256"] == result["summary_sha256"]
    for name, passed in stored["checks"].items():
        assert result["checks"][name] == passed
    assert result["errata_sha256"]


def test_v5_release_audit_cli_emits_machine_readable_result(capsys):
    v5_release_audit.main()
    emitted = json.loads(capsys.readouterr().out)
    assert emitted["passed"] is True


def test_v5_release_audit_cli_fails_visibly(monkeypatch, capsys):
    def fail():
        raise v5_release_audit.V5ReleaseAuditError("injected")

    monkeypatch.setattr(v5_release_audit, "audit", fail)
    with pytest.raises(SystemExit) as error:
        v5_release_audit.main()
    assert error.value.code == 1
    assert "injected" in capsys.readouterr().err

"""Build the immutable parent and prior-observation ledger for PRA S0."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any

from dvg_obs_ceo.artifact_io import atomic_write_new_json
from dvg_obs_ceo.baseline import ROOT
from dvg_obs_ceo.identity import sha256_hex


OUTPUT = ROOT / "artifacts/pra_path/s0/evidence-ledger-v1.json"
PARENT_TAG = "v6.1-t2-negative-result-complete-v1"
PARENT_COMMIT = "406ccbf49691aec638d78951959cdc6eeb7f472f"
VENDOR_COMMIT = "a3f89d03e6a03c89767d3cf8ee7657a57653dda0"

INPUTS = (
    "docs/PRA_CRITICAL_PATH_PLAN.md",
    "artifacts/v6/ns7/energy-certification-v1.json",
    "artifacts/v6/ns9/sequential-pilot-v1.json",
    "artifacts/v6/ns10/h6-optimizer-ablation-v1.json",
    "artifacts/v6/release/ns8-ns10-manifest-v1.json",
    "artifacts/v6/release/provenance-supplement-v1.json",
    "artifacts/v6_1/t0/protocol-v1.json",
    "artifacts/v6_1/t2/mechanism-audit-v1.json",
    "artifacts/v6_1/release/negative-result-manifest-v1.json",
)


class S0EvidenceLedgerError(RuntimeError):
    """Raised when immutable parent evidence cannot be reconciled."""


def _git(*arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _file_record(relative: str) -> dict[str, Any]:
    path = ROOT / relative
    if not path.is_file():
        raise S0EvidenceLedgerError(f"missing required parent input: {relative}")
    return {
        "path": relative,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "bytes": path.stat().st_size,
    }


def build_ledger() -> dict[str, Any]:
    peeled = _git("rev-parse", f"{PARENT_TAG}^{{}}")
    if peeled != PARENT_COMMIT:
        raise S0EvidenceLedgerError("parent tag does not resolve to frozen commit")
    submodule = _git("rev-parse", "HEAD:vendor/ceo-adapt-vqe")
    if submodule != VENDOR_COMMIT:
        raise S0EvidenceLedgerError("vendored CEO* commit changed")
    inputs = [_file_record(value) for value in INPUTS]
    ledger: dict[str, Any] = {
        "schema": "dvg-obs-ceo.pra-path.s0-evidence-ledger.v1",
        "status": "immutable-parent-reconciled",
        "parent": {
            "tag": PARENT_TAG,
            "peeled_commit": peeled,
            "vendor_ceo_adapt_vqe_commit": submodule,
        },
        "inputs": inputs,
        "evidence_roles": {
            "development": [
                "H2 prior calibration contexts",
                "H4 all previously executed geometries/checkpoints",
                "LiH 3.0 A",
                "H6 1.5 A",
                "H6 3.0 A",
                "BeH2 3.0 A",
            ],
            "prospective": [],
            "prospective_selection_status": "NOT_SELECTED",
        },
        "prior_visible_outcomes": [
            {
                "context": "H4 1.5 A late checkpoint",
                "outcome": "two sequential native rank demotions certified",
                "role": "development",
            },
            {
                "context": "H6 1.5 A and 3.0 A",
                "outcome": (
                    "tested registered rank-two families not certified under "
                    "the frozen NS7/NS10 protocols"
                ),
                "role": "development",
            },
            {
                "context": "BeH2 3.0 A",
                "outcome": "no eligible frozen rank-three MVP block",
                "role": "development",
            },
            {
                "context": "V6.1 tangent/QFI diagnostic",
                "outcome": "NO_GO_MECHANISM_NOT_SEPARATED",
                "role": "development",
            },
        ],
        "claim_boundary": {
            "matched_work_superiority_established": False,
            "cross_molecule_robustness_established": False,
            "prospective_validation_established": False,
            "pra_performance_claim_established": False,
        },
        "immutability": {
            "historical_artifacts_rewritten": False,
            "historical_outcomes_relabelled_prospective": False,
            "force_push_authorized": False,
        },
    }
    ledger["ledger_digest"] = sha256_hex(ledger)
    return ledger


def audit_ledger(value: dict[str, Any]) -> None:
    content = dict(value)
    digest = content.pop("ledger_digest", None)
    if digest != sha256_hex(content):
        raise S0EvidenceLedgerError("ledger digest mismatch")
    for record in value["inputs"]:
        if _file_record(record["path"]) != record:
            raise S0EvidenceLedgerError(
                f"input changed after ledger build: {record['path']}"
            )
    if any(value["claim_boundary"].values()):
        raise S0EvidenceLedgerError("S0 may not create a performance claim")
    if value["evidence_roles"]["prospective"]:
        raise S0EvidenceLedgerError("S0 may not select prospective cases")
    json.dumps(value, allow_nan=False)


def main() -> None:
    if OUTPUT.exists():
        raise S0EvidenceLedgerError("refusing to overwrite S0 evidence ledger")
    if _git("status", "--porcelain"):
        raise S0EvidenceLedgerError("S0 execution requires a clean worktree")
    value = build_ledger()
    audit_ledger(value)
    atomic_write_new_json(OUTPUT, value)


if __name__ == "__main__":
    main()

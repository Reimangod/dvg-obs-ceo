"""Immutable V6-NS0 closure manifest for the stopped S9 protocol."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

from dvg_obs_ceo.artifact_io import atomic_write_new_json
from dvg_obs_ceo.baseline import ROOT
from dvg_obs_ceo.identity import sha256_hex

from .s8_1_protocol_freeze import DEFAULT_OUTPUT as DEFAULT_S8_1
from .s9_certification import DEFAULT_OUTPUT as DEFAULT_S9
from .s9_result_audit import DEFAULT_AUDIT_OUTPUT
from .s9_stationarity_diagnostic import DEFAULT_OUTPUT as DEFAULT_S9_D


DEFAULT_OUTPUT = ROOT / "artifacts/v6/ns0/s9-closure-manifest-v1.json"
CLOSURE_VERSION = "v6-ns0-s9-immutable-closure-v1"
S9_COMMIT = "21654bfb1ca62fc1668dfd79defe15592c350922"
S9_TAG = "v6-s9-native-rank2-not-certified-v1"


class NS0ClosureError(RuntimeError):
    """Raised when immutable S9 evidence cannot be closed safely."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(*arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def build_manifest() -> dict[str, Any]:
    tag_commit = _git("rev-parse", f"{S9_TAG}^{{commit}}")
    if tag_commit != S9_COMMIT:
        raise NS0ClosureError("S9 annotated tag does not resolve to S9 commit")
    s8_1 = json.loads(DEFAULT_S8_1.read_text(encoding="utf-8"))
    s9 = json.loads(DEFAULT_S9.read_text(encoding="utf-8"))
    audit = json.loads(DEFAULT_AUDIT_OUTPUT.read_text(encoding="utf-8"))
    s9_d = json.loads(DEFAULT_S9_D.read_text(encoding="utf-8"))
    if (
        s9["summary"]["classification"]
        != "NATIVE_RANK2_NOT_CERTIFIED"
        or s9["summary"]["primary_parent_after_s9"]
        != "unchanged-s6-parent"
        or s9["summary"]["s10_sequential_continuation_authorized"]
        is not False
        or audit["passed"] is not True
    ):
        raise NS0ClosureError("S9 status is not safely closed")
    inputs = {
        name: {
            "path": str(path.relative_to(ROOT)),
            "sha256": _sha256(path),
            "semantic_digest": semantic_digest,
        }
        for name, path, semantic_digest in (
            (
                "v6_s8_1",
                DEFAULT_S8_1,
                s8_1["freeze_digest"],
            ),
            ("v6_s9", DEFAULT_S9, s9["report_digest"]),
            (
                "v6_s9_result_audit",
                DEFAULT_AUDIT_OUTPUT,
                audit["audit_digest"],
            ),
            (
                "v6_s9_d",
                DEFAULT_S9_D,
                s9_d["report_digest"],
            ),
        )
    }
    manifest = {
        "schema_version": "1.0.0",
        "artifact_kind": "v6-ns0-s9-immutable-closure",
        "closure_version": CLOSURE_VERSION,
        "s9_commit": S9_COMMIT,
        "s9_tag": S9_TAG,
        "tag_resolved_commit": tag_commit,
        "inputs": inputs,
        "closed_state": {
            "protocol_family": "SPARSE_UCRY_RANK2 optimization protocol",
            "status": "STOPPED_NOT_CERTIFIED",
            "s8_1_candidate_queue_mutable": False,
            "s9_outcomes_mutable": False,
            "s6_primary_parent_mutable_by_ns": False,
            "s10_authorized": False,
            "stationarity_threshold_mutable": False,
            "optimizer_cap_mutable": False,
            "third_candidate_addition_allowed": False,
        },
        "new_namespace_contract": {
            "protocol": "V6-NS",
            "purpose": "primary-resource native circuit synthesis",
            "reuses": [
                "abstract exact generator relations",
                "familywise semantic evidence",
                "frozen paper-era resource counter",
            ],
            "does_not_reuse_as_acceptance": [
                "S9 optimizer outcomes",
                "S9 exploratory endpoint",
                "historical S8 Top-1 selection",
            ],
            "energy_evaluation_forbidden_until": (
                "a separately frozen NS6 primary-resource-eligible queue"
            ),
        },
        "paper_measurement_cost": None,
    }
    manifest["closure_digest"] = sha256_hex(manifest)
    return manifest


def main() -> None:
    try:
        manifest = build_manifest()
        atomic_write_new_json(DEFAULT_OUTPUT, manifest)
    except (
        KeyError,
        OSError,
        subprocess.CalledProcessError,
        TypeError,
        ValueError,
        NS0ClosureError,
    ) as error:
        print(f"V6-NS0 closure failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

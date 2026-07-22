"""V4.1-S4 deterministic fault-injection audit for bundle lifecycle."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
from typing import Any

from .identity import canonical_json_bytes
from .v3_protocol import _write_exclusive
from .v4_1_bundle import (
    BundleLifecycleError,
    CaseAlreadyLocked,
    CaseRunLease,
    ExistingBundleError,
    audit_case_state,
    validate_complete_bundle,
)
from .v4_1_protocol import DEFAULT_MANIFEST, audit_manifest


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _payload(staging: Path, label: str) -> None:
    (staging / "summary.json").write_text(
        json.dumps({"label": label}, sort_keys=True), encoding="utf-8"
    )


def run(manifest_path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    s0 = audit_manifest(manifest_path)
    protocol_digest = s0["manifest_sha256"]
    checkpoint_digest = "c" * 64
    checks: dict[str, bool] = {}
    with tempfile.TemporaryDirectory(prefix="v4.1-s4-audit-") as directory:
        root = Path(directory)
        first = CaseRunLease(
            root,
            "h6-1.5",
            protocol_digest,
            checkpoint_digest,
            run_uuid="00000000-0000-4000-8000-000000000001",
        ).acquire()
        second = CaseRunLease(
            root,
            "h6-1.5",
            protocol_digest,
            checkpoint_digest,
            run_uuid="00000000-0000-4000-8000-000000000002",
        )
        try:
            second.acquire()
        except CaseAlreadyLocked:
            checks["second_writer_refused"] = True
        else:
            checks["second_writer_refused"] = False
        _payload(first.staging, "crash-before-finalize")
        orphan = first.staging
        first.close()
        state = audit_case_state(root, "h6-1.5")
        checks["orphan_retained_and_classified"] = bool(
            orphan.is_dir()
            and state["lock_status"] == "absent"
            and state["staging"][0]["status"] == "incomplete"
        )

        promote = CaseRunLease(
            root,
            "beh2-3.0",
            protocol_digest,
            checkpoint_digest,
            run_uuid="00000000-0000-4000-8000-000000000003",
        ).acquire()
        _payload(promote.staging, "canonical")
        expected = promote.finalize()["bundle_digest"]
        canonical = promote.promote()
        checks["atomic_promotion_valid"] = (
            validate_complete_bundle(canonical)["bundle_digest"] == expected
        )
        try:
            CaseRunLease(root, "beh2-3.0", protocol_digest, checkpoint_digest).acquire()
        except ExistingBundleError:
            checks["existing_canonical_refused"] = True
        else:
            checks["existing_canonical_refused"] = False

        duplicate = root / ".staging" / "beh2-3.0" / "00000000-0000-4000-8000-000000000004"
        duplicate.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(canonical, duplicate)
        duplicate_state = audit_case_state(root, "beh2-3.0")
        checks["complete_duplicate_classified"] = any(
            item["status"] == "complete-duplicate" for item in duplicate_state["staging"]
        )

        tamper = CaseRunLease(
            root,
            "h6-3.0",
            protocol_digest,
            checkpoint_digest,
            run_uuid="00000000-0000-4000-8000-000000000005",
        ).acquire()
        _payload(tamper.staging, "before")
        tamper.finalize()
        _payload(tamper.staging, "after")
        try:
            tamper.promote()
        except BundleLifecycleError:
            checks["post_finalize_tamper_refused"] = True
        else:
            checks["post_finalize_tamper_refused"] = False
        tamper.close()
        checks["tampered_staging_retained"] = tamper.staging.is_dir()

    failures = [name for name, passed in checks.items() if not passed]
    result: dict[str, Any] = {
        "schema_version": "1.0.0",
        "artifact_kind": "v4.1-s4-bundle-fault-injection-audit",
        "protocol_id": "dvg-obs-v4.1-scale-transfer-protocol-v1",
        "s0_manifest_sha256": protocol_digest,
        "checks": checks,
        "failed_checks": failures,
        "passed": not failures,
        "temporary_fault_injection_only": True,
        "production_artifacts_modified": False,
        "claim_boundary": "Filesystem lifecycle fault injection only; no scientific computation or VQE execution.",
    }
    result["artifact_digest"] = _digest(result)
    if failures:
        raise BundleLifecycleError("S4 fault-injection checks failed: " + ", ".join(failures))
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--artifact-path", type=Path)
    arguments = parser.parse_args()
    result = run(arguments.manifest)
    if arguments.artifact_path is not None:
        _write_exclusive(arguments.artifact_path, result)
    print(json.dumps({"passed": result["passed"], "checks": len(result["checks"])}, sort_keys=True))


if __name__ == "__main__":
    main()

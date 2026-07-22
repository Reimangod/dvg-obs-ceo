import json
from pathlib import Path

import pytest

from dvg_obs_ceo.v4_1_bundle import (
    BundleLifecycleError,
    CaseAlreadyLocked,
    CaseRunLease,
    ExistingBundleError,
    audit_case_state,
    validate_complete_bundle,
)


DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


def _write_payload(staging: Path, value: str = "evidence") -> None:
    (staging / "summary.json").write_text(json.dumps({"value": value}), encoding="utf-8")


def test_case_lock_refuses_second_writer_and_retains_first_staging(tmp_path: Path) -> None:
    first = CaseRunLease(tmp_path, "h6-1.5", DIGEST_A, DIGEST_B).acquire()
    second = CaseRunLease(tmp_path, "h6-1.5", DIGEST_A, DIGEST_B)
    with pytest.raises(CaseAlreadyLocked):
        second.acquire()
    first.close()
    audit = audit_case_state(tmp_path, "h6-1.5")
    assert audit["lock_status"] == "absent"
    assert audit["staging"][0]["status"] == "incomplete"
    assert audit["ambiguous"]


def test_finalize_and_atomic_promotion_produce_valid_canonical_bundle(tmp_path: Path) -> None:
    lease = CaseRunLease(tmp_path, "beh2-3.0", DIGEST_A, DIGEST_B).acquire()
    _write_payload(lease.staging)
    manifest = lease.finalize()
    promoted = lease.promote()
    assert validate_complete_bundle(promoted)["bundle_digest"] == manifest["bundle_digest"]
    audit = audit_case_state(tmp_path, "beh2-3.0")
    assert audit["canonical_status"] == "complete"
    assert audit["lock_status"] == "absent"
    assert not audit["ambiguous"]
    assert not audit["safe_to_start"]
    with pytest.raises(ExistingBundleError):
        CaseRunLease(tmp_path, "beh2-3.0", DIGEST_A, DIGEST_B).acquire()


def test_completion_manifest_detects_post_finalize_tampering(tmp_path: Path) -> None:
    lease = CaseRunLease(tmp_path, "h6-3.0", DIGEST_A, DIGEST_B).acquire()
    _write_payload(lease.staging)
    lease.finalize()
    _write_payload(lease.staging, "tampered")
    with pytest.raises(BundleLifecycleError, match="file_inventory"):
        validate_complete_bundle(lease.staging)
    with pytest.raises(BundleLifecycleError):
        lease.promote()
    lease.close()
    assert audit_case_state(tmp_path, "h6-3.0")["staging"][0]["status"] == "incomplete"


def test_exception_releases_lock_but_never_deletes_orphan_staging(tmp_path: Path) -> None:
    staging = None
    with pytest.raises(RuntimeError, match="simulated crash"):
        with CaseRunLease(tmp_path, "lih-3.0", DIGEST_A, DIGEST_B) as lease:
            staging = lease.staging
            _write_payload(staging)
            raise RuntimeError("simulated crash")
    assert staging is not None and staging.is_dir()
    audit = audit_case_state(tmp_path, "lih-3.0")
    assert audit["lock_status"] == "absent"
    assert audit["staging"][0]["status"] == "incomplete"


def test_invalid_case_identity_and_empty_finalize_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(BundleLifecycleError, match="invalid case"):
        CaseRunLease(tmp_path, "../escape", DIGEST_A, DIGEST_B)
    lease = CaseRunLease(tmp_path, "safe-case", DIGEST_A, DIGEST_B).acquire()
    with pytest.raises(BundleLifecycleError, match="empty"):
        lease.finalize()
    lease.close()

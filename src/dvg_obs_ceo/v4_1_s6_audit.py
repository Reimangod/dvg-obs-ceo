"""Independent audit of V4.1-S6 regression and LiH transaction evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any

from .baseline import ROOT
from .identity import canonical_json_bytes
from .transaction import RuntimeSnapshot
from .v3_protocol import _write_exclusive
from .v4_1_bundle import audit_case_state, validate_complete_bundle
from .v4_1_scale_audit import LIH_V4_SUMMARY


BUNDLE = ROOT / "artifacts/v4.1/s6-regression/lih-3.0"
RESULT_TAG = "dvg-obs-v4.1-s6-regression-result-v1"
REQUIRED_THREADS = {"OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}


class V41S6AuditError(RuntimeError):
    """Raised when S6 evidence is incomplete or inconsistent."""


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _git(*arguments: str) -> str:
    return subprocess.check_output(["git", "-C", str(ROOT), *arguments], text=True).strip()


def verify_freeze() -> dict[str, Any]:
    head = _git("rev-parse", "HEAD")
    tag = _git("rev-parse", f"{RESULT_TAG}^{{}}")
    dirty = _git("status", "--porcelain")
    threads = {name: os.environ.get(name) for name in REQUIRED_THREADS}
    if head != tag or dirty or threads != REQUIRED_THREADS:
        raise V41S6AuditError(
            f"S6 audit freeze failed: head={head}, tag={tag}, dirty={bool(dirty)}, threads={threads}"
        )
    return {"head": head, "tag": RESULT_TAG, "threads": threads}


def run(
    artifact_path: Path,
    bundle: Path = BUNDLE,
) -> dict[str, Any]:
    freeze = verify_freeze()
    complete = validate_complete_bundle(bundle)
    summary = json.loads((bundle / "summary.json").read_text(encoding="utf-8"))
    stored_digest = summary.pop("summary_digest")
    digest_ok = _digest(summary) == stored_digest
    summary["summary_digest"] = stored_digest
    state = audit_case_state(bundle.parent, bundle.name)
    rejection = summary["lih"]["deterministic_rejection"]
    acceptance = summary["lih"]["accepted_replay"]
    rejected_path = bundle / rejection["transaction_path"]
    accepted_path = bundle / acceptance["transaction_path"]
    rejected_snapshot_value = json.loads(
        (rejected_path / "snapshot.json").read_text(encoding="utf-8")
    )
    rejected_snapshot = RuntimeSnapshot.from_dict(rejected_snapshot_value)
    rollback = json.loads((rejected_path / "rollback.json").read_text(encoding="utf-8"))
    commit = json.loads((accepted_path / "commit.json").read_text(encoding="utf-8"))
    old_summary = json.loads(LIH_V4_SUMMARY.read_text(encoding="utf-8"))
    old_accepted = next(
        item for item in old_summary["attempts"]
        if item["transaction_status"] == "accepted"
    )
    old_path = old_accepted["fallback"] or old_accepted["primary"]
    new_path = acceptance["fallback"] or acceptance["primary"]
    checks = {
        "summary_digest": digest_ok,
        "canonical_bundle": (
            state["canonical_status"] == "complete"
            and state["canonical_bundle_digest"] == complete["bundle_digest"]
        ),
        "no_runtime_residue": (
            state["lock_status"] == "absent"
            and not state["staging"]
            and not state["ambiguous"]
        ),
        "h2_h4_passed": (
            summary["h2_h4"]["passed"]
            and summary["h2_h4"]["single_candidate_replays"] == 17
            and summary["h2_h4"]["stored_joint_batch_replays"] == 420
            and summary["h2_h4"]["cases"]["h2-1.5-iteration-1"]
            ["source_resources"]["cnot_count"] == 9
            and summary["h2_h4"]["cases"]["h4-1.5-first-chemical-accuracy"]
            ["source_resources"]["cnot_count"] == 80
        ),
        "lih_prediction_unchanged": (
            abs(summary["lih"]["v4_prediction_delta_hartree"]) <= 1e-10
            and summary["lih"]["quality"]["passed"]
        ),
        "deterministic_rejection": (
            rejection["transaction_status"] == "rolled-back"
            and not rejection["acceptance"]["accepted"]
            and "cumulative_energy_budget" in rejection["acceptance"]["rejection_reasons"]
        ),
        "rollback_snapshot_round_trip": (
            rejected_snapshot.snapshot_digest == rejection["before_snapshot_digest"]
            and rollback["before_snapshot_digest"] == rejected_snapshot.snapshot_digest
            and rollback["restored_snapshot_digest"] == rejected_snapshot.snapshot_digest
            and rejection["after_rollback_snapshot_digest"] == rejected_snapshot.snapshot_digest
            and rejection["rollback_exact"]
        ),
        "rollback_payload_covers_all_mutable_state": set(rejected_snapshot_value) == {
            "version", "snapshot_digest", "ansatz", "energy_float64",
            "gradient_float64", "inverse_hessian_float64",
            "statevector_real_float64", "statevector_imag_float64", "work",
            "adapt_iteration", "metadata", "python_rng_state", "numpy_rng_state",
        },
        "accepted_transaction": (
            acceptance["transaction_status"] == "accepted"
            and acceptance["acceptance"]["accepted"]
            and all(acceptance["acceptance"]["checks"].values())
            and commit["acceptance"]["accepted"]
            and commit["before_snapshot_digest"] == acceptance["before_snapshot_digest"]
        ),
        "v4_final_energy_reproduced": (
            abs(new_path["energy_hartree"] - old_path["energy_hartree"]) <= 1e-10
            and abs(summary["lih"]["v4_final_energy_delta_hartree"]) <= 1e-10
        ),
        "v4_resources_reproduced": (
            summary["lih"]["v4_resource_snapshot_equal"]
            and acceptance["physical_resources"]["snapshot"]
            == old_accepted["physical_resources"]["snapshot"]
        ),
        "independent_semantics": (
            acceptance["two_path_certificate"]["passed"]
            and acceptance["two_path_certificate"]["source_target_state_fidelity"]
            >= 1.0 - 1e-10
            and acceptance["two_path_certificate"]
            ["source_target_energy_difference_hartree"] <= 1e-10
        ),
        "measurement_cost_unclaimed": summary["paper_measurement_cost"] is None,
    }
    failed = [name for name, passed in checks.items() if not passed]
    result: dict[str, Any] = {
        "schema_version": "1.0.0",
        "artifact_kind": "v4.1-s6-independent-regression-audit",
        "audit_freeze": freeze,
        "bundle_digest": complete["bundle_digest"],
        "summary_digest": stored_digest,
        "checks": checks,
        "failed_checks": failed,
        "passed": not failed,
        "result": {
            "source_energy_hartree": summary["lih"]["source_energy_hartree"],
            "accepted_energy_hartree": new_path["energy_hartree"],
            "accepted_resources": acceptance["physical_resources"]["snapshot"],
            "rejection_reasons": rejection["acceptance"]["rejection_reasons"],
            "rollback_snapshot_digest": rejected_snapshot.snapshot_digest,
        },
        "paper_measurement_cost": None,
        "claim_boundary": "Independent S6 regression and transaction-integrity audit; LiH remains observed development evidence.",
    }
    result["artifact_digest"] = _digest(result)
    if failed:
        raise V41S6AuditError("S6 independent audit failed: " + ", ".join(failed))
    _write_exclusive(artifact_path, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-path", type=Path, required=True)
    arguments = parser.parse_args()
    result = run(arguments.artifact_path)
    print(json.dumps({"passed": result["passed"], "result": result["result"]}, sort_keys=True))


if __name__ == "__main__":
    main()

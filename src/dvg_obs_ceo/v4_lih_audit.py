"""Independent artifact audit for the V4-S7 LiH development result."""

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
from .v3_protocol import _write_exclusive


DEFAULT_BUNDLE = ROOT / "artifacts" / "v4" / "s7-lih-development-v1-2"
AUDIT_TAG = "dvg-obs-v4-s7-lih-audit-v1"
REQUIRED_THREADS = {"OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}


class V4LiHAuditError(RuntimeError):
    """Raised when the stored V4 LiH result is internally inconsistent."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _verify_audit_freeze() -> dict[str, Any]:
    head = subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip()
    tag = subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", f"{AUDIT_TAG}^{{}}"], text=True).strip()
    dirty = subprocess.check_output(["git", "-C", str(ROOT), "status", "--porcelain"], text=True).strip()
    threads = {name: os.environ.get(name) for name in REQUIRED_THREADS}
    if head != tag or dirty or threads != REQUIRED_THREADS:
        raise V4LiHAuditError("independent audit requires clean tagged code and canonical threads")
    return {"head": head, "audit_tag": AUDIT_TAG, "threads": threads}


def _contains_key(value: Any, forbidden: str) -> bool:
    if isinstance(value, dict):
        return any(key == forbidden or _contains_key(item, forbidden) for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_key(item, forbidden) for item in value)
    return False


def run(bundle: Path, artifact_path: Path) -> dict[str, Any]:
    audit_freeze = _verify_audit_freeze()
    summary_path = bundle / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    selection = summary["selection"]
    selection_without_digest = dict(selection)
    recorded_selection_digest = selection_without_digest.pop("selection_digest")
    observed_selection_digest = hashlib.sha256(
        canonical_json_bytes(selection_without_digest)
    ).hexdigest()
    attempts = summary["attempts"]
    attempt_by_id = {item["constraint_semantic_id"]: item for item in attempts}

    def expected_winner(endpoint: str) -> str | None:
        return next(
            (
                identifier for identifier in selection[endpoint]
                if attempt_by_id[identifier]["transaction_status"] == "accepted"
            ),
            None,
        )

    accepted = [item for item in attempts if item["transaction_status"] == "accepted"]
    rejected = [item for item in attempts if item["transaction_status"] == "rolled-back"]
    source = summary["checkpoint"]["resources"]["snapshot"]
    winner_id = summary["endpoint_winners"]["circuit_primary"]
    winner = None if winner_id is None else attempt_by_id[winner_id]
    winner_path = None if winner is None else (winner["fallback"] or winner["primary"])
    transaction_files: dict[str, str] = {}
    transaction_layout_ok = True
    for item in attempts:
        directory = bundle / item["transaction_path"]
        required = {"attempt.json", "snapshot.json", "trial.json"}
        required.add("commit.json" if item["transaction_status"] == "accepted" else "rollback.json")
        transaction_layout_ok &= directory.is_dir() and all((directory / name).is_file() for name in required)
        for name in sorted(required):
            path = directory / name
            if path.is_file():
                transaction_files[str(path.relative_to(bundle))] = _sha256(path)
    checks = {
        "strict_json_summary": summary_path.is_file(),
        "execution_tag_v1_2": summary["execution_freeze"]["protocol_tag"] == "dvg-obs-v4-s7-lih-v1.2",
        "stored_checkpoint_hash": summary["execution_freeze"]["checkpoint_sha256"] == "1ef38be983595fdb094f2a47287e6047193351e0eff4a7c589630ef023ad98eb",
        "source_checkpoint_reconstructed": bool(
            summary["checkpoint"]["energy_hartree"] == -7.797909682469515
            and source["parameter_count"] == 15 and source["cnot_count"] == 107
            and source["cnot_depth"] == 30 and source["total_depth"] == 171
        ),
        "no_new_ansatz_growth": summary["work"]["new_ceo_star_adapt_iterations"] == 0 and summary["work"]["new_ordinary_adapt_iterations"] == 0,
        "search_surrogate_complete": summary["search"]["status"] == "surrogate-complete" and summary["search"]["truncated_reason"] is None,
        "no_search_numerical_failures": summary["search"]["counts"]["candidate_numerical_failures"] == 0,
        "selection_digest": observed_selection_digest == recorded_selection_digest,
        "attempt_bound": len(attempts) <= 4 and len(attempts) == len(selection["unique_attempt_semantic_ids"]),
        "attempt_order": [item["constraint_semantic_id"] for item in attempts] == selection["unique_attempt_semantic_ids"],
        "transaction_layout": transaction_layout_ok,
        "rollback_exact": all(item["rollback_exact"] for item in rejected),
        "accepted_checks_complete": bool(accepted) and all(
            item["acceptance"]["accepted"] and all(item["acceptance"]["checks"].values())
            for item in accepted
        ),
        "rejected_checks_fail": all(
            not item["acceptance"]["accepted"] and item["acceptance"]["rejection_reasons"]
            for item in rejected
        ),
        "endpoint_winners_replayed": all(
            summary["endpoint_winners"][endpoint] == expected_winner(endpoint)
            for endpoint in ("circuit_primary", "parameter_primary")
        ),
        "actual_energy_absent_from_selector": not _contains_key(summary["search"], "actual_energy_hartree") and not _contains_key(selection, "actual_energy_hartree"),
        "fci_absent_from_selector": not _contains_key(summary["search"], "fci_energy_hartree") and not _contains_key(selection, "fci_energy_hartree"),
        "winner_energy_budget": winner_path is not None and winner_path["energy_hartree"] - summary["checkpoint"]["energy_hartree"] <= 1e-4,
        "winner_independent_energy": winner_path is not None and winner_path["independent_energy_difference_hartree"] <= 1e-10,
        "winner_two_path_semantics": winner is not None and winner["two_path_certificate"]["passed"] and winner["two_path_certificate"]["source_target_state_fidelity"] >= 1.0 - 1e-10 and winner["two_path_certificate"]["source_target_energy_difference_hartree"] <= 1e-10,
        "winner_resources": winner is not None and bool(
            winner["physical_resources"]["snapshot"]["parameter_count"] == 8
            and winner["physical_resources"]["snapshot"]["cnot_count"] == 58
            and winner["physical_resources"]["snapshot"]["cnot_depth"] == 30
            and winner["physical_resources"]["snapshot"]["total_depth"] == 92
        ),
        "strict_quality_payload": all(
            item["quality"]["policy"]["maximum_held_out_projected_residual"] is None
            for item in attempts
        ),
        "no_orphan_staging_in_result": not (bundle / ".staging").exists(),
    }
    failed = [name for name, passed in checks.items() if not passed]
    artifact = {
        "schema_version": "1.0.0",
        "artifact_kind": "v4-s7-lih-independent-audit",
        "audit_freeze": audit_freeze,
        "passed": not failed,
        "checks": checks,
        "failed_checks": failed,
        "summary_sha256": _sha256(summary_path),
        "transaction_sha256": transaction_files,
        "selection_digest": observed_selection_digest,
        "result": {
            "source": {key: source[key] for key in ("parameter_count", "cnot_count", "cnot_depth", "total_depth")},
            "winner": None if winner is None else {
                "constraint_semantic_id": winner_id,
                "energy_hartree": winner_path["energy_hartree"],
                "energy_change_hartree": winner_path["energy_hartree"] - summary["checkpoint"]["energy_hartree"],
                "resources": {key: winner["physical_resources"]["snapshot"][key] for key in ("parameter_count", "cnot_count", "cnot_depth", "total_depth")},
                "kkt_residual": winner_path["gradient_infinity"],
            },
            "accepted_attempts": len(accepted),
            "rolled_back_attempts": len(rejected),
        },
        "claim_boundary": "Independent consistency audit of observed LiH development evidence; not blind validation or a general superiority claim.",
    }
    if failed:
        raise V4LiHAuditError("V4-S7 audit failed: " + ", ".join(failed))
    _write_exclusive(artifact_path, artifact)
    return artifact


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    parser.add_argument("--artifact-path", type=Path, required=True)
    arguments = parser.parse_args()
    result = run(arguments.bundle, arguments.artifact_path)
    print(json.dumps({"passed": result["passed"], "result": result["result"]}, sort_keys=True))


if __name__ == "__main__":
    main()

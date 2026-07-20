"""Independent structural audit for a completed S10 LiH comparison bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .selector import RESOURCE_FIELDS
from .s10_lih import EXPECTED_ENERGY_HARTREE, EXPECTED_INDICES, SELECTOR_DIGEST, validate_summary


class S10AuditError(RuntimeError):
    """Raised when an S10 bundle fails an independent invariant."""


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise S10AuditError(f"cannot read required JSON artifact: {path}") from error
    if not isinstance(value, dict):
        raise S10AuditError(f"artifact is not a JSON object: {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(bundle: Path) -> dict[str, Any]:
    summary = _read(bundle / "summary.json")
    checkpoint = _read(bundle / "checkpoint.json")
    selector = _read(bundle / "selector-decision.json")
    trial = _read(bundle / "selected-trial.json")
    transaction = bundle / "transactions" / "failed" / "s10-primary-round-1"
    rollback = _read(transaction / "rollback.json")
    staged_trial = _read(transaction / "trial.json")
    validate_summary(summary)

    checks: dict[str, bool] = {}
    checks["canonical_indices"] = tuple(checkpoint["ansatz_indices"]) == EXPECTED_INDICES
    checks["canonical_energy"] = abs(checkpoint["energy_hartree"] - EXPECTED_ENERGY_HARTREE) <= 1e-10
    snapshot = checkpoint["resources"]["snapshot"]
    checks["canonical_resources"] = (
        snapshot["cnot_count"], snapshot["cnot_depth"], snapshot["parameter_count"]
    ) == (107, 30, 15)
    checks["selector_frozen"] = selector["selector_digest"] == SELECTOR_DIGEST
    checks["selector_artifact_matches_summary"] = selector == summary["selection"]["decision"]
    eligible = [item for item in selector["assessments"] if item["eligible"]]
    def key(item: Mapping[str, Any]) -> tuple[Any, ...]:
        delta = item["resource_delta"]
        return (
            *(delta[field] for field in RESOURCE_FIELDS),
            item["predicted_cumulative_change_hartree"],
            item["candidate_id"],
        )
    replayed = min(eligible, key=key)["candidate_id"] if eligible else None
    checks["selector_replay"] = replayed == selector["chosen_candidate_id"]
    checks["single_candidate_only"] = summary["work"]["optimized_candidates"] == 1
    checks["trial_artifact_bound"] = staged_trial["acceptance"] == trial["acceptance"]
    checks["rejected_only_by_kkt"] = trial["acceptance"]["rejection_reasons"] == ["kkt"]
    checks["rollback_digest_exact"] = (
        rollback["before_snapshot_digest"] == rollback["restored_snapshot_digest"]
    )
    checks["no_commit_directory"] = not (
        bundle / "transactions" / "committed" / "s10-primary-round-1"
    ).exists()
    checks["summary_reports_rollback"] = (
        summary["dvg_obs_ceo"]["status"] == "rolled-back"
        and summary["dvg_obs_ceo"]["accepted"] is False
        and summary["dvg_obs_ceo"]["energy_hartree"] == summary["no_pruning"]["energy_hartree"]
    )
    checks["fci_not_pruning_input"] = (
        summary["offline_evaluation"]["used_by_runtime_selector_or_acceptance"] is False
    )
    checks["measurement_cost_unclaimed"] = summary["paper_measurement_cost"] is None
    failures = [name for name, passed in checks.items() if not passed]
    if failures:
        raise S10AuditError("S10 audit failed: " + ", ".join(failures))
    files = sorted(path for path in bundle.rglob("*") if path.is_file())
    return {
        "schema_version": "1.0.0",
        "artifact_kind": "s10-lih-independent-bundle-audit",
        "bundle": str(bundle),
        "passed": True,
        "checks": checks,
        "file_sha256": {
            str(path.relative_to(bundle)): _sha256(path) for path in files
        },
        "interpretation": {
            "candidate_resource_delta": {
                field: (
                    trial["physical_resources"]["snapshot"][field]
                    - checkpoint["resources"]["snapshot"][field]
                )
                for field in RESOURCE_FIELDS
            },
            "candidate_energy_change_hartree": (
                trial["fallback"]["independent_energy_hartree"]
                - checkpoint["energy_hartree"]
            ),
            "candidate_kkt_residual": trial["fallback"]["gradient_infinity"],
            "registered_kkt_limit": 1e-8,
            "scientific_outcome": "promising-candidate-rejected-and-fully-rolled-back",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--artifact", type=Path)
    arguments = parser.parse_args()
    result = audit(arguments.bundle)
    if arguments.artifact:
        if arguments.artifact.exists():
            raise FileExistsError(f"refusing to overwrite audit artifact: {arguments.artifact}")
        arguments.artifact.parent.mkdir(parents=True, exist_ok=True)
        arguments.artifact.write_text(
            json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
    print(json.dumps({"passed": result["passed"], "checks": len(result["checks"])}, sort_keys=True))


if __name__ == "__main__":
    main()

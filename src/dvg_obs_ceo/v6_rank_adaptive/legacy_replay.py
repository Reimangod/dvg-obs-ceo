"""Read-only differential replay of V4.1, V5, and V5.1 evidence."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import IntEnum
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping

from dvg_obs_ceo.artifact_io import atomic_write_new_json
from dvg_obs_ceo.baseline import ROOT
from dvg_obs_ceo.identity import canonical_json_bytes, sha256_hex


PARENT_TAG = "stable-v5-correctness-audit-v1"
DEFAULT_OUTPUT = ROOT / "artifacts/v6/s3/differential-replay-v1.json"


class LegacyReplayError(RuntimeError):
    """Raised when historical evidence drifts or is overstated."""


class ReplayStrength(IntEnum):
    ARTIFACT_ONLY = 0
    SEMANTIC_NORMALIZED = 1
    SOURCE_STATE_RECONSTRUCTED = 2
    CANDIDATE_RANKING_REPLAYED = 3
    DECISION_REPLAYED = 4
    FULL_WORK_REPLAYED = 5


@dataclass(frozen=True)
class LegacyArtifactSpec:
    method: str
    case_id: str
    path: str
    adapter: str
    source_checkpoint_path: str | None = None


SPECS = (
    LegacyArtifactSpec(
        "V4.1",
        "lih-3.0",
        "artifacts/v4.1/s6-regression/lih-3.0/summary.json",
        "v4.1-regression",
        "artifacts/s10/lih-3a-first-accuracy-primary-v1-2/checkpoint.json",
    ),
    LegacyArtifactSpec(
        "V4.1",
        "h6-1.5",
        "artifacts/v4.1/multisystem/h6-1.5/summary.json",
        "v4.1",
        "artifacts/full-figures/ceo-star/h6-1.5/checkpoint.json",
    ),
    LegacyArtifactSpec(
        "V4.1",
        "h6-3.0",
        "artifacts/v4.1/multisystem/h6-3.0/summary.json",
        "v4.1",
        "artifacts/full-figures/ceo-star/h6-3.0/checkpoint.json",
    ),
    LegacyArtifactSpec(
        "V4.1",
        "beh2-3.0",
        "artifacts/v4.1/multisystem/beh2-3.0/summary.json",
        "v4.1",
        "artifacts/full-figures/ceo-star/beh2-3.0/checkpoint.json",
    ),
    LegacyArtifactSpec(
        "V5",
        "lih-3.0",
        "artifacts/v5/s8/lih-energy-aware-width2-round3-v1/summary.json",
        "v5",
        "artifacts/s10/lih-3a-first-accuracy-primary-v1-2/checkpoint.json",
    ),
    LegacyArtifactSpec(
        "V5",
        "h6-1.5",
        "artifacts/v5/s9/h6-1.5-v1/summary.json",
        "v5",
        "artifacts/full-figures/ceo-star/h6-1.5/checkpoint.json",
    ),
    LegacyArtifactSpec(
        "V5",
        "h6-3.0",
        "artifacts/v5/s9/h6-3.0-v1/summary.json",
        "v5",
        "artifacts/full-figures/ceo-star/h6-3.0/checkpoint.json",
    ),
    LegacyArtifactSpec(
        "V5",
        "beh2-3.0",
        "artifacts/v5/s9/beh2-3.0-v1/summary.json",
        "v5",
        "artifacts/full-figures/ceo-star/beh2-3.0/checkpoint.json",
    ),
    LegacyArtifactSpec(
        "V5.1",
        "h6-1.5-v4.1-source",
        "artifacts/v5/s11/h6-1.5-exact-fusion-v1.json",
        "v5.1",
    ),
    LegacyArtifactSpec(
        "V5.1",
        "h6-1.5-v5-source",
        "artifacts/v5/s11/h6-1.5-s9-fusion-integration-v1.json",
        "v5.1",
    ),
)


def _digest_without(value: Mapping[str, Any], field: str) -> bool:
    content = dict(value)
    observed = content.pop(field, None)
    return (
        isinstance(observed, str)
        and hashlib.sha256(canonical_json_bytes(content)).hexdigest()
        == observed
    )


def _tagged_bytes(path: str) -> bytes:
    return subprocess.run(
        ("git", "show", f"{PARENT_TAG}:{path}"),
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout


def _parent_bytes_match(path: str) -> bool:
    return hashlib.sha256((ROOT / path).read_bytes()).digest() == hashlib.sha256(
        _tagged_bytes(path)
    ).digest()


def _checkpoint_evidence(path: str | None) -> tuple[dict[str, Any], dict[str, bool]]:
    if path is None:
        return {}, {}
    checkpoint_path = ROOT / path
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    required = (
        "ansatz_indices",
        "ansatz_coefficients",
        "checkpoint_digest",
        "energy_hartree",
        "resources",
        "statevector_sha256",
    )
    checks = {
        "checkpoint_parent_bytes": _parent_bytes_match(path),
        "checkpoint_source_fields": all(
            field in checkpoint for field in required
        ),
        "checkpoint_ansatz_shape": len(checkpoint["ansatz_indices"])
        == len(checkpoint["ansatz_coefficients"]),
    }
    normalized = {
        "path": path,
        "file_sha256": hashlib.sha256(checkpoint_path.read_bytes()).hexdigest(),
        "checkpoint_digest": checkpoint["checkpoint_digest"],
        "statevector_sha256": checkpoint["statevector_sha256"],
        "energy_hartree": checkpoint["energy_hartree"],
        "parameter_count": len(checkpoint["ansatz_indices"]),
        "resources": checkpoint["resources"]["snapshot"],
    }
    return normalized, checks


def _sum_work(items: list[Mapping[str, Any]]) -> dict[str, int]:
    names = set().union(*(item.keys() for item in items)) if items else set()
    return {
        name: sum(int(item.get(name, 0)) for item in items)
        for name in sorted(names)
    }


def _normalize_v41(
    spec: LegacyArtifactSpec,
    value: Mapping[str, Any],
    checkpoint: Mapping[str, Any],
) -> tuple[dict[str, Any], ReplayStrength, dict[str, bool], list[str], list[str]]:
    internal_field = "summary_digest"
    checks = {
        "internal_digest": _digest_without(value, internal_field),
        "measurement_cost_undefined": value.get("paper_measurement_cost") is None,
    }
    if spec.adapter == "v4.1-regression":
        checks["regression_passed"] = value.get("passed") is True
        normalized = {
            "artifact_kind": value["artifact_kind"],
            "case_id": spec.case_id,
            "passed": value["passed"],
            "lih": value["lih"],
            "claim_boundary": value["claim_boundary"],
        }
        unavailable = [
            "V4.1-specific candidate catalog",
            "V4.1-specific exact-attempt trajectory",
            "V4.1-specific work ledger",
            "three-layer scientific identity",
        ]
        derived = [
            "case_id from the registered adapter",
            "V4.1 equivalence from the stored regression checks",
        ]
        return (
            normalized,
            ReplayStrength.SEMANTIC_NORMALIZED,
            checks,
            unavailable,
            derived,
        )

    attempts = value["attempts"]
    selection = value["s5_frozen_selection"]["selection"]
    accepted = [
        attempt["constraint_semantic_id"]
        for attempt in attempts
        if attempt["transaction_status"] == "accepted"
    ]
    endpoint_ids = [
        identifier
        for identifier in value["endpoint_winners"].values()
        if identifier is not None
    ]
    work = value["work"]
    checks.update(
        {
            "case_id": value["case_id"] == spec.case_id,
            "candidate_ranking_present": bool(selection["assessments"]),
            "attempts_have_work": len(work["attempt_work"]) == len(attempts),
            "attempt_count": work["exact_vqe_attempts"] == len(attempts),
            "accepted_count": work["accepted_attempts"] == len(accepted),
            "rollback_count": work["rolled_back_attempts"]
            == len(attempts) - len(accepted),
            "endpoint_is_accepted": all(
                identifier in accepted for identifier in endpoint_ids
            ),
            "transaction_records_complete": all(
                attempt["transaction_status"] in {"accepted", "rolled-back"}
                and isinstance(attempt["rollback_exact"], bool)
                for attempt in attempts
            ),
        }
    )
    normalized = {
        "artifact_kind": value["artifact_kind"],
        "case_id": value["case_id"],
        "source": checkpoint,
        "candidate_ranking": {
            "assessment_count": len(selection["assessments"]),
            "frozen_attempt_count": len(
                selection["unique_attempt_semantic_ids"]
            ),
            "selection_digest": sha256_hex(selection),
        },
        "attempts": [
            {
                "attempt_number": attempt["attempt_number"],
                "candidate_ids": attempt["candidate_ids"],
                "constraint_semantic_id": attempt["constraint_semantic_id"],
                "transaction_status": attempt["transaction_status"],
                "rollback_exact": attempt["rollback_exact"],
                "accepted": attempt["acceptance"]["accepted"],
                "physical_resources": attempt["physical_resources"]["snapshot"],
                "work_after_attempt": attempt["work_after_attempt"],
            }
            for attempt in attempts
        ],
        "endpoint_winners": value["endpoint_winners"],
        "work": work,
        "claim_boundary": value["claim_boundary"],
    }
    unavailable = [
        "canonical V6 generator-definition evidence",
        "ProblemID",
        "MeasurementContextID",
        "complete event timestamps",
    ]
    derived = [
        "normalized candidate-ranking digest",
        "accepted and rollback counts replayed from attempts",
    ]
    return normalized, ReplayStrength.DECISION_REPLAYED, checks, unavailable, derived


def _normalize_v5(
    spec: LegacyArtifactSpec,
    value: Mapping[str, Any],
    checkpoint: Mapping[str, Any],
) -> tuple[dict[str, Any], ReplayStrength, dict[str, bool], list[str], list[str]]:
    result = value["result"]
    branch_records = value["branch_records"]
    exact_sum = _sum_work([record["work"] for record in branch_records])
    catalog_sum = _sum_work(list(result["catalog_work_by_path"].values()))
    aggregate_sum = _sum_work([exact_sum, catalog_sum])
    checks = {
        "internal_digest": _digest_without(value, "result_digest"),
        "nested_result_digest": _digest_without(result, "result_digest"),
        "measurement_cost_undefined": (
            value.get("paper_measurement_cost") is None
            and result.get("paper_measurement_cost") is None
        ),
        "candidate_ranking_present": bool(value["catalog_diagnostics_by_path"]),
        "exact_attempt_count": result["exact_attempts"] == len(branch_records),
        "exact_work_reconciled": exact_sum == result["exact_attempt_work"],
        "catalog_work_reconciled": catalog_sum == result["catalog_work"],
        "aggregate_work_reconciled": aggregate_sum == result["aggregate_work"],
        "accepted_branches_pass": all(
            not record["decision"]["accepted"]
            or all(record["decision"]["checks"].values())
            for record in branch_records
        ),
        "rejected_branches_explain": all(
            record["decision"]["accepted"]
            or bool(record["decision"]["rejection_reasons"])
            for record in branch_records
        ),
        "source_runtime_unchanged": value["source_runtime_unchanged"] is True,
    }
    normalized = {
        "artifact_kind": value["artifact_kind"],
        "case_id": spec.case_id,
        "source": checkpoint,
        "source_energy_hartree": value["source_energy_hartree"],
        "source_resources": value["source_resources"],
        "candidate_catalogs": {
            path_id: {
                "catalog_digest": next(iter(records)),
                "diagnostic_digest": sha256_hex(next(iter(records.values()))),
            }
            for path_id, records in sorted(
                value["catalog_diagnostics_by_path"].items()
            )
        },
        "branch_records": [
            {
                "proposal_id": record["proposal_id"],
                "candidate_id": record["candidate_id"],
                "parent_path_id": record["parent_path_id"],
                "decision": record["decision"],
                "work": record["work"],
            }
            for record in branch_records
        ],
        "trajectory": result["trajectory"],
        "winner_path_id": result["winner_path_id"],
        "winner_state_preparation_id": result[
            "winner_state_preparation_id"
        ],
        "winner_resources": result["winner_resources"],
        "aggregate_work": result["aggregate_work"],
        "stop_reason": result["stop_reason"],
        "claim_boundary": value["claim_boundary"],
    }
    unavailable = [
        "ProblemID",
        "MeasurementContextID",
        "canonical V6 generator-definition evidence",
        "per-operation wall-clock trace",
    ]
    derived = [
        "catalog diagnostic digests",
        "exact, catalog, and aggregate work reconciliation",
        "case_id from the registered LiH adapter when absent historically",
    ]
    return normalized, ReplayStrength.FULL_WORK_REPLAYED, checks, unavailable, derived


def _normalize_v51(
    spec: LegacyArtifactSpec,
    value: Mapping[str, Any],
) -> tuple[dict[str, Any], ReplayStrength, dict[str, bool], list[str], list[str]]:
    checks = {
        "internal_digest": _digest_without(value, "result_digest"),
        "stored_checks_pass": value["passed"] is True
        and all(value["checks"].values()),
        "measurement_cost_undefined": value["work"]["paper_measurement_cost"]
        is None,
        "candidate_ids_present": bool(value["candidate_ids"]),
        "operator_audits_present": len(value["operator_audits"])
        == len(value["candidate_ids"]),
        "zero_optimizer_starts": value["work"]["optimizer_starts"] == 0,
        "physical_cnot_gain": value["target"]["resources"]["cnot_count"]
        < value["source"]["resources"]["cnot_count"],
    }
    normalized = {
        "artifact_kind": value["artifact_kind"],
        "case_id": spec.case_id,
        "candidate_ids": value["candidate_ids"],
        "operator_audits": value["operator_audits"],
        "source": value["source"],
        "target": value["target"],
        "state_fidelity": value["state_fidelity"],
        "absolute_energy_drift_hartree": value[
            "absolute_energy_drift_hartree"
        ],
        "checks": value["checks"],
        "work": value["work"],
        "claim_boundary": value["claim_boundary"],
    }
    unavailable = [
        "complete pre-fusion candidate catalog",
        "complete candidate ranking",
        "ProblemID",
        "MeasurementContextID",
        "canonical V6 familywise proof object",
    ]
    derived = [
        "physical CNOT gain",
        "operator-audit cardinality",
    ]
    return normalized, ReplayStrength.DECISION_REPLAYED, checks, unavailable, derived


def replay_one(spec: LegacyArtifactSpec) -> dict[str, Any]:
    path = ROOT / spec.path
    original = json.loads(path.read_text(encoding="utf-8"))
    checkpoint, checkpoint_checks = _checkpoint_evidence(
        spec.source_checkpoint_path
    )
    if spec.adapter.startswith("v4.1"):
        normalized, strength, checks, unavailable, derived = _normalize_v41(
            spec,
            original,
            checkpoint,
        )
    elif spec.adapter == "v5":
        normalized, strength, checks, unavailable, derived = _normalize_v5(
            spec,
            original,
            checkpoint,
        )
    elif spec.adapter == "v5.1":
        normalized, strength, checks, unavailable, derived = _normalize_v51(
            spec,
            original,
        )
    else:
        raise LegacyReplayError(f"unknown legacy adapter: {spec.adapter}")
    checks = {
        "parent_bytes_unchanged": _parent_bytes_match(spec.path),
        **checkpoint_checks,
        **checks,
    }
    failed = sorted(name for name, passed in checks.items() if not passed)
    if failed:
        raise LegacyReplayError(
            f"{spec.method} {spec.case_id} replay failed: "
            + ", ".join(failed)
        )
    normalized_digest = sha256_hex(normalized)
    return {
        "schema_version": "1.0.0",
        "artifact_kind": "v6-legacy-differential-replay",
        "method": spec.method,
        "case_id": spec.case_id,
        "source_path": spec.path,
        "original_artifact_digest": hashlib.sha256(path.read_bytes()).hexdigest(),
        "normalized_ir_digest": normalized_digest,
        "replay_strength": strength.name,
        "replay_level": int(strength),
        "reconstructible_fields": sorted(normalized),
        "unavailable_fields": unavailable,
        "derived_fields": derived,
        "checks": checks,
        "normalized": normalized,
        "passed": True,
        "paper_measurement_cost": None,
    }


def build_report() -> dict[str, Any]:
    records = [replay_one(spec) for spec in SPECS]
    levels: dict[str, int] = {}
    for strength in ReplayStrength:
        levels[strength.name] = sum(
            record["replay_strength"] == strength.name for record in records
        )
    report = {
        "schema_version": "1.0.0",
        "artifact_kind": "v6-s3-differential-replay-report",
        "parent_tag": PARENT_TAG,
        "historical_artifacts_modified": False,
        "record_count": len(records),
        "replay_level_histogram": levels,
        "records": records,
        "limitations": [
            "Normalized V6 replay digests are intentionally distinct from original byte digests.",
            "Missing historical scientific identities and proof objects are not inferred.",
            "V4.1 LiH is a regression record, not a separate full V4.1 trajectory.",
            "V5.1 records lack a complete pre-fusion catalog and are capped at decision replay.",
            "All cases are development evidence; no prospective validation is created by replay.",
        ],
        "paper_measurement_cost": None,
    }
    report["report_digest"] = sha256_hex(report)
    return report


def main() -> None:
    try:
        report = build_report()
        atomic_write_new_json(DEFAULT_OUTPUT, report)
    except (
        OSError,
        KeyError,
        TypeError,
        ValueError,
        subprocess.SubprocessError,
        LegacyReplayError,
    ) as error:
        print(f"V6 S3 replay failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()

"""Pre-outcome S8.1 endpoint-policy amendment and exploratory Top-2 freeze."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

from dvg_obs_ceo.artifact_io import atomic_write_new_json
from dvg_obs_ceo.baseline import ROOT
from dvg_obs_ceo.identity import sha256_hex


DEFAULT_S7 = ROOT / "artifacts/v6/s7/rank-candidate-catalog-v1.json"
DEFAULT_S8 = ROOT / "artifacts/v6/s8/predictor-candidate-freeze-v1.json"
DEFAULT_OUTPUT = (
    ROOT / "artifacts/v6/s8.1/exploratory-top2-freeze-v1.json"
)
S9_ROOT = ROOT / "artifacts/v6/s9"
PROTOCOL_VERSION = "v6-s8.1-pre-outcome-endpoint-top2-freeze-v1"


class S81ProtocolFreezeError(RuntimeError):
    """Raised when the endpoint amendment is late, ambiguous, or inconsistent."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _resource_delta(candidate: Mapping[str, Any]) -> dict[str, int]:
    resources = candidate["resources"]
    before = resources["before"]
    after = resources["after"]
    return {
        field: int(after[field] - before[field])
        for field in (
            "cnot_count",
            "cnot_depth",
            "total_depth",
            "parameter_count",
            "logical_block_count",
        )
    }


def freeze_top2(
    s7: Mapping[str, Any],
    s8: Mapping[str, Any],
    *,
    input_order: Sequence[str] | None = None,
) -> dict[str, Any]:
    catalog = {
        item["candidate_id"]: item for item in s7["candidates"]
    }
    predictions = {
        item["candidate_id"]: item for item in s8["prediction_records"]
    }
    if set(catalog) != set(predictions) or len(catalog) != 3:
        raise S81ProtocolFreezeError(
            "S7 catalog and S8 predictor inventory disagree"
        )
    order = tuple(input_order or sorted(catalog))
    if set(order) != set(catalog) or len(order) != len(catalog):
        raise S81ProtocolFreezeError(
            "candidate traversal must contain every candidate exactly once"
        )
    assessments = []
    for candidate_id in order:
        delta = _resource_delta(catalog[candidate_id])
        prediction = float(
            predictions[candidate_id]["predicted_loss_hartree"]
        )
        if not math.isfinite(prediction) or prediction < 0.0:
            raise S81ProtocolFreezeError(
                "candidate prediction is invalid"
            )
        circuit_primary = (
            delta["cnot_count"] <= 0
            and delta["cnot_depth"] <= 0
            and (
                delta["cnot_count"] < 0
                or delta["cnot_depth"] < 0
            )
        )
        exploratory = (
            delta["total_depth"] < 0
            and delta["parameter_count"] < 0
        )
        assessments.append(
            {
                "candidate_id": candidate_id,
                "predicted_loss_hartree": prediction,
                "resource_delta_target_minus_s6": delta,
                "circuit_primary_eligible": circuit_primary,
                "circuit_primary_rejection_reasons": (
                    []
                    if circuit_primary
                    else [
                        "cnot-regression"
                        if delta["cnot_count"] > 0
                        else "no-cnot-gain",
                        "cnot-depth-regression"
                        if delta["cnot_depth"] > 0
                        else "no-cnot-depth-gain",
                    ]
                ),
                "exploratory_depth_parameter_eligible": exploratory,
                "exploratory_disclosed_regressions": [
                    field
                    for field in ("cnot_count", "cnot_depth")
                    if delta[field] > 0
                ],
                "quality_stratum": "boundary",
                "empirical_uncertainty_calibrated": False,
            }
        )
    ranked = sorted(
        (
            item
            for item in assessments
            if item["exploratory_depth_parameter_eligible"]
        ),
        key=lambda item: (
            item["predicted_loss_hartree"],
            item["candidate_id"],
        ),
    )
    frozen = [item["candidate_id"] for item in ranked[:2]]
    if len(frozen) != 2:
        raise S81ProtocolFreezeError(
            "exploratory Top-2 queue is incomplete"
        )
    return {
        "assessments": sorted(
            assessments, key=lambda item: item["candidate_id"]
        ),
        "circuit_primary_candidate_ids": sorted(
            item["candidate_id"]
            for item in assessments
            if item["circuit_primary_eligible"]
        ),
        "exploratory_top2_candidate_ids": frozen,
        "excluded_by_top2_cap": [
            item["candidate_id"] for item in ranked[2:]
        ],
    }


def build_report(
    s7_path: Path = DEFAULT_S7,
    s8_path: Path = DEFAULT_S8,
    *,
    require_no_s9_outcome: bool = True,
) -> dict[str, Any]:
    if require_no_s9_outcome and S9_ROOT.exists():
        raise S81ProtocolFreezeError(
            "S8.1 cannot be created after an S9 artifact exists"
        )
    s7 = json.loads(s7_path.read_text(encoding="utf-8"))
    s8 = json.loads(s8_path.read_text(encoding="utf-8"))
    freeze = freeze_top2(s7, s8)
    report = {
        "schema_version": "1.0.0",
        "artifact_kind": "v6-s8.1-pre-outcome-protocol-freeze",
        "protocol_version": PROTOCOL_VERSION,
        "development_only": True,
        "amends_but_does_not_overwrite": (
            "v6-s8-predictor-candidate-freeze"
        ),
        "inputs": {
            "s7": {
                "path": str(s7_path.relative_to(ROOT)),
                "sha256": _sha256(s7_path),
                "report_digest": s7["report_digest"],
            },
            "s8": {
                "path": str(s8_path.relative_to(ROOT)),
                "sha256": _sha256(s8_path),
                "report_digest": s8["report_digest"],
                "original_top1_retained_as_historical_evidence": True,
            },
        },
        "pre_outcome_attestation": {
            "s9_artifact_absent_when_freeze_created": True,
            "actual_candidate_energy_observed": False,
            "fci_or_chemical_accuracy_used": False,
        },
        "endpoint_policy": {
            "circuit_primary": {
                "protected_resources": ["cnot_count", "cnot_depth"],
                "eligibility": (
                    "both nonregress and at least one strictly improves"
                ),
                "current_candidates_are_primary_results": False,
            },
            "exploratory_depth_parameter": {
                "required_strict_gains": [
                    "total_depth",
                    "parameter_count",
                ],
                "allowed_but_disclosed_regressions": [
                    "cnot_count",
                    "cnot_depth",
                ],
                "s9_purpose": (
                    "native rank-2 feasibility and predictor diagnosis only"
                ),
            },
        },
        "selector_policy": {
            "name": "boundary-quality-deterministic-top2-v1",
            "risk_aware_claim": False,
            "top_k": 2,
            "ranking": [
                "predicted_loss_hartree",
                "canonical_candidate_id",
            ],
            "reason": (
                "The first two point predictions differ by only about "
                "5e-7 Ha while empirical uncertainty is uncalibrated."
            ),
            "s9_outcomes_may_change_this_queue": False,
        },
        **freeze,
        "claim_boundary": (
            "The Top-2 queue is an exploratory pre-outcome development "
            "freeze. Even accepted S9 attempts are not circuit-primary CNOT "
            "compression results and cannot establish matched-work or "
            "molecule-general performance."
        ),
        "paper_measurement_cost": None,
    }
    report["freeze_digest"] = sha256_hex(report)
    return report


def main() -> None:
    try:
        report = build_report()
        atomic_write_new_json(DEFAULT_OUTPUT, report)
    except (
        KeyError,
        OSError,
        TypeError,
        ValueError,
        S81ProtocolFreezeError,
    ) as error:
        print(f"V6 S8.1 freeze failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    print(
        json.dumps(
            {
                "circuit_primary_candidate_ids": (
                    report["circuit_primary_candidate_ids"]
                ),
                "exploratory_top2_candidate_ids": (
                    report["exploratory_top2_candidate_ids"]
                ),
                "freeze_digest": report["freeze_digest"],
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()

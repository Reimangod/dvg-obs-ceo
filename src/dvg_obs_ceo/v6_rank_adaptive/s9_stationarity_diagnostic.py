"""Read-only post-S9 stationarity mechanism diagnostic."""

from __future__ import annotations

import json
import math
from pathlib import Path
import sys
from typing import Any, Mapping

import numpy as np

from dvg_obs_ceo.artifact_io import atomic_write_new_json
from dvg_obs_ceo.baseline import ROOT
from dvg_obs_ceo.identity import sha256_hex

from .predictor_freeze import DEFAULT_S6, _structure
from .s9_certification import DEFAULT_OUTPUT as DEFAULT_S9


DEFAULT_OUTPUT = ROOT / "artifacts/v6/s9-d/stationarity-diagnostic-v1.json"
DIAGNOSTIC_VERSION = "v6-s9-d-read-only-stationarity-v1"


class S9StationarityDiagnosticError(RuntimeError):
    """Raised when saved S9 evidence is insufficient or inconsistent."""


def _target_positions(
    candidate: Mapping[str, Any],
) -> tuple[int, ...]:
    omitted = int(
        candidate["source_ansatz_positions"][
            candidate["omitted_source_slot"]
        ]
    )
    return tuple(
        int(position - int(position > omitted))
        for position in candidate["source_ansatz_positions"]
        if position != omitted
    )


def _surrogate_diagnostics(
    inverse_hessian: np.ndarray,
    gradient: np.ndarray,
) -> dict[str, Any]:
    scale = max(1.0, float(np.linalg.norm(inverse_hessian, ord="fro")))
    symmetry = float(
        np.linalg.norm(
            inverse_hessian - inverse_hessian.T, ord="fro"
        )
        / scale
    )
    symmetric = (inverse_hessian + inverse_hessian.T) / 2.0
    eigenvalues, eigenvectors = np.linalg.eigh(symmetric)
    positive = bool(np.all(eigenvalues > 0.0))
    condition = (
        float(eigenvalues[-1] / eigenvalues[0])
        if positive
        else None
    )
    gradient_norm = float(np.linalg.norm(gradient))
    low_curvature_count = min(5, gradient.size)
    # Large eigenvalues of inverse Hessian correspond to low-curvature
    # directions of its implied Hessian, if the SPD surrogate is accepted.
    low_curvature_vectors = eigenvectors[:, -low_curvature_count:]
    low_alignment = (
        float(
            np.linalg.norm(low_curvature_vectors.T @ gradient) ** 2
            / gradient_norm**2
        )
        if gradient_norm > 0.0
        else 0.0
    )
    return {
        "evidence_kind": "optimizer-final-BFGS-inverse-Hessian-surrogate",
        "not_exact_physical_hessian": True,
        "dimension": int(gradient.size),
        "symmetry_relative_residual": symmetry,
        "symmetric_part_positive_definite": positive,
        "minimum_inverse_hessian_eigenvalue": float(eigenvalues[0]),
        "maximum_inverse_hessian_eigenvalue": float(eigenvalues[-1]),
        "condition_number_if_spd": condition,
        "implied_hessian_minimum_eigenvalue_if_spd": (
            float(1.0 / eigenvalues[-1]) if positive else None
        ),
        "implied_hessian_maximum_eigenvalue_if_spd": (
            float(1.0 / eigenvalues[0]) if positive else None
        ),
        "gradient_squared_alignment_with_five_lowest_implied_curvature_directions": (
            low_alignment
        ),
    }


def diagnose_candidate(
    result: Mapping[str, Any],
    candidate: Mapping[str, Any],
    source_indices: tuple[int, ...],
) -> dict[str, Any]:
    selected_name = result["selected_optimizer_path"]
    selected = (
        result["primary_optimizer"]
        if selected_name == "primary"
        else result["fallback_optimizer"]
    )
    gradient = np.asarray(selected["gradient"], dtype=np.float64)
    inverse_hessian = np.asarray(
        selected["final_inverse_hessian"], dtype=np.float64
    )
    omitted = int(
        candidate["source_ansatz_positions"][
            candidate["omitted_source_slot"]
        ]
    )
    target_indices = tuple(
        value
        for position, value in enumerate(source_indices)
        if position != omitted
    )
    if (
        gradient.shape != (len(target_indices),)
        or inverse_hessian.shape
        != (len(target_indices), len(target_indices))
        or not np.all(np.isfinite(gradient))
        or not np.all(np.isfinite(inverse_hessian))
    ):
        raise S9StationarityDiagnosticError(
            "saved optimizer arrays have inconsistent dimensions"
        )
    absolute = np.abs(gradient)
    order = np.argsort(-absolute, kind="stable")
    block_positions = set(_target_positions(candidate))
    top = [
        {
            "rank": rank,
            "target_position": int(position),
            "pool_index": int(target_indices[position]),
            "gradient": float(gradient[position]),
            "absolute_gradient": float(absolute[position]),
            "inside_demoted_block": int(position) in block_positions,
        }
        for rank, position in enumerate(order[:10], start=1)
    ]
    block_max = max(
        (float(absolute[position]) for position in block_positions),
        default=0.0,
    )
    outside_max = max(
        (
            float(value)
            for position, value in enumerate(absolute)
            if position not in block_positions
        ),
        default=0.0,
    )
    return {
        "candidate_id": result["candidate_id"],
        "selected_optimizer_path": selected_name,
        "optimizer": {
            "success": selected["optimizer"]["success"],
            "status": selected["optimizer"]["status"],
            "message": selected["optimizer"]["message"],
            "iterations": selected["optimizer"]["iterations"],
            "function_evaluations": selected["optimizer"][
                "function_evaluations"
            ],
            "gradient_vector_evaluations": selected["optimizer"][
                "gradient_vector_evaluations"
            ],
        },
        "stationarity": {
            "fixed_threshold": 1e-8,
            "gradient_infinity": float(np.max(absolute)),
            "threshold_multiple": float(np.max(absolute) / 1e-8),
            "gradient_l2": float(np.linalg.norm(gradient)),
            "absolute_gradient_quantiles": {
                str(quantile): float(np.quantile(absolute, quantile))
                for quantile in (0.0, 0.25, 0.5, 0.75, 0.9, 0.99, 1.0)
            },
            "components_above_threshold": int(
                np.count_nonzero(absolute > 1e-8)
            ),
            "fraction_components_above_threshold": float(
                np.mean(absolute > 1e-8)
            ),
            "demoted_block_target_positions": sorted(block_positions),
            "demoted_block_max_absolute_gradient": block_max,
            "outside_block_max_absolute_gradient": outside_max,
            "maximum_component_inside_demoted_block": (
                bool(top[0]["inside_demoted_block"]) if top else False
            ),
            "top_components": top,
        },
        "surrogate_curvature": _surrogate_diagnostics(
            inverse_hessian, gradient
        ),
        "unavailable_from_saved_s9_evidence": [
            "per-iteration coordinate and step-norm trajectory",
            "line-search trial points and Wolfe-condition diagnostics",
            "exact Hessian or new Hessian-vector products at final point",
            "proof that another optimizer or parameterization would fail",
        ],
        "no_new_quantum_or_optimizer_work": True,
        "acceptance_reassessed": False,
    }


def build_report(
    s9_path: Path = DEFAULT_S9,
    s6_path: Path = DEFAULT_S6,
) -> dict[str, Any]:
    s9 = json.loads(s9_path.read_text(encoding="utf-8"))
    s6 = json.loads(s6_path.read_text(encoding="utf-8"))
    source = _structure(s6["target"])
    catalog_path = (
        ROOT
        / s9["execution_freeze"]["inputs"]["s7"]["path"]
    )
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    candidates = {
        item["candidate_id"]: item for item in catalog["candidates"]
    }
    diagnostics = [
        diagnose_candidate(
            result,
            candidates[result["candidate_id"]],
            source.indices,
        )
        for result in s9["candidate_results"]
    ]
    report = {
        "schema_version": "1.0.0",
        "artifact_kind": "v6-s9-d-stationarity-mechanism-diagnostic",
        "diagnostic_version": DIAGNOSTIC_VERSION,
        "development_only": True,
        "inputs": {
            "s9_path": str(s9_path.relative_to(ROOT)),
            "s9_report_digest": s9["report_digest"],
            "s6_path": str(s6_path.relative_to(ROOT)),
            "s6_target_state_digest": s6["target_state_digest"],
        },
        "candidate_diagnostics": diagnostics,
        "work": {
            "optimizer_runs": 0,
            "energy_evaluations": 0,
            "gradient_evaluations": 0,
            "hvp_evaluations": 0,
            "statevector_recomputations": 0,
            "circuit_recounts": 0,
            "saved_array_decompositions": len(diagnostics),
            "paper_measurement_cost": None,
        },
        "conclusion_scope": (
            "Read-only diagnosis of saved S9 gradients and optimizer BFGS "
            "surrogates. It cannot distinguish representation insufficiency "
            "from optimizer or parameterization limitations, cannot certify "
            "physical Hessian curvature, and does not alter S9 acceptance."
        ),
        "paper_measurement_cost": None,
    }
    report["report_digest"] = sha256_hex(report)
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
        S9StationarityDiagnosticError,
    ) as error:
        print(f"V6 S9-D diagnostic failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    print(
        json.dumps(
            {
                "report_digest": report["report_digest"],
                "candidate_count": len(
                    report["candidate_diagnostics"]
                ),
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()

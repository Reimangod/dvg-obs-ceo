"""Outcome-aware H4 mechanism and same-source frontier audit for V6-NS8."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import struct
import subprocess
import sys
from typing import Any, Mapping

import numpy as np

from dvg_obs_ceo.artifact_io import atomic_write_new_json
from dvg_obs_ceo.baseline import ROOT
from dvg_obs_ceo.block_ir import recover_dvg_blocks
from dvg_obs_ceo.identity import sha256_hex
from dvg_obs_ceo.s8_probe import _algorithm as h4_algorithm

from .native_synthesis_pipeline import (
    CONTEXTS,
    NS1_OUTPUT,
    _load_context_structure,
)
from .ns7_energy_certification import DEFAULT_OUTPUT as NS7_OUTPUT
from .ns7_energy_certification import affine_embedding


DEFAULT_OUTPUT = ROOT / "artifacts/v6/ns8/h4-followup-audit-v1.json"
V5_H4_OUTPUT = (
    ROOT / "artifacts/v5/s8/h4-width1-recycled-v1-1/summary.json"
)
AUDIT_VERSION = "v6-ns8-h4-mechanism-frontier-audit-v1"
FD_STEPS = (5e-7, 1e-6, 2e-6)
HESSIAN_STEP = 1e-4
ENERGY_EQUIVALENCE = 1e-12
REQUIRED_THREADS = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
}


class NS8AuditError(RuntimeError):
    """Raised when the NS8 audit cannot preserve its evidence boundary."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _decode(values: list[str]) -> np.ndarray:
    return np.asarray(
        [struct.unpack(">d", bytes.fromhex(value))[0] for value in values],
        dtype=np.float64,
    )


def _state(algorithm: Any, coordinates: np.ndarray, indices: list[int]) -> np.ndarray:
    value = np.asarray(
        algorithm.compute_state(list(coordinates), indices).toarray()
    ).ravel()
    return value / np.linalg.norm(value)


def _expectation(state: np.ndarray, operator: Any) -> tuple[float, float]:
    applied = operator @ state
    mean = float(np.real(np.vdot(state, applied)))
    second = float(np.real(np.vdot(applied, applied)))
    return mean, max(0.0, second - mean * mean)


def _symmetries(state: np.ndarray, n_qubits: int) -> dict[str, Any]:
    from openfermion import (
        get_sparse_operator,
        jordan_wigner,
        number_operator,
        s_squared_operator,
        sz_operator,
    )

    fermion_ops = {
        "particle_number": number_operator(n_qubits),
        "spin_z": sz_operator(n_qubits // 2),
        "spin_squared": s_squared_operator(n_qubits // 2),
    }
    result = {}
    for name, operator in fermion_ops.items():
        sparse = get_sparse_operator(
            jordan_wigner(operator), n_qubits=n_qubits
        )
        mean, variance = _expectation(state, sparse)
        result[name] = {"expectation": mean, "variance": variance}
    return result


def _top_determinants(state: np.ndarray, n_qubits: int) -> list[dict[str, Any]]:
    probabilities = np.abs(state) ** 2
    order = sorted(
        range(probabilities.size),
        key=lambda index: (-float(probabilities[index]), index),
    )[:8]
    return [
        {
            "basis_index": int(index),
            "bitstring": format(index, f"0{n_qubits}b"),
            "probability": float(probabilities[index]),
            "amplitude_real": float(state[index].real),
            "amplitude_imag": float(state[index].imag),
        }
        for index in order
    ]


def _dominates(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    left_values = (
        max(0.0, float(left["energy_loss_hartree"]) - ENERGY_EQUIVALENCE),
        int(left["resources"]["cnot_count"]),
        int(left["resources"]["cnot_depth"]),
        int(left["resources"]["total_depth"]),
        int(left["resources"]["parameter_count"]),
    )
    right_values = (
        max(0.0, float(right["energy_loss_hartree"]) - ENERGY_EQUIVALENCE),
        int(right["resources"]["cnot_count"]),
        int(right["resources"]["cnot_depth"]),
        int(right["resources"]["total_depth"]),
        int(right["resources"]["parameter_count"]),
    )
    return all(a <= b for a, b in zip(left_values, right_values)) and any(
        a < b for a, b in zip(left_values, right_values)
    )


def _mechanism_audit(
    ns7: Mapping[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    algorithm, pool = h4_algorithm(
        "h4-1.5-iteration-12-or-convergence"
    )
    context = next(
        item for item in CONTEXTS if item["case_id"] == "h4-1.5-late"
    )
    source = _load_context_structure(context)
    indices = list(source.indices)
    source_coordinates = np.asarray(source.coefficients, dtype=np.float64)
    source_state = _state(algorithm, source_coordinates, indices)
    families = {
        item["family_id"]: item
        for item in json.loads(NS1_OUTPUT.read_text(encoding="utf-8"))[
            "families"
        ]
    }
    blocks = recover_dvg_blocks(
        pool,
        source.indices,
        source.coefficients,
        source.cumulative_parameter_counts,
    )
    accepted = [
        item
        for item in ns7["attempts"]
        if item["classification"] == "PRIMARY_NATIVE_RANK2_ACCEPTED"
    ]
    diagnostics = []
    states = []
    work = {
        "energy_evaluations": 0,
        "gradient_vector_evaluations": 0,
        "statevector_evaluations": 1,
        "observable_expectations": 3,
    }
    for attempt in accepted:
        family = families[attempt["family_id"]]
        block = next(
            item
            for item in blocks
            if item.block_id == attempt["queue_item"]["source_block_id"]
        )
        parameter_map = np.asarray(
            family["parameter_map"], dtype=np.float64
        )
        embedding, _ = affine_embedding(
            len(indices), block.ansatz_positions, parameter_map
        )
        target = _decode(attempt["final_target_coordinates_float64_hex"])
        mapped = embedding @ target
        candidate_state = _state(algorithm, mapped, indices)
        states.append(candidate_state)

        def energy(value: np.ndarray) -> float:
            work["energy_evaluations"] += 1
            return float(
                algorithm.evaluate_energy(
                    list(embedding @ value), indices
                )
            )

        def gradient(value: np.ndarray) -> np.ndarray:
            work["gradient_vector_evaluations"] += 1
            source_gradient = np.asarray(
                algorithm.estimate_gradients(
                    list(embedding @ value), indices, method="an"
                ),
                dtype=np.float64,
            )
            return embedding.T @ source_gradient

        analytic = gradient(target)
        maximum_index = int(np.argmax(np.abs(analytic)))
        finite_difference = {}
        for step in FD_STEPS:
            estimate = np.zeros_like(target)
            for index in range(target.size):
                plus = target.copy()
                minus = target.copy()
                plus[index] += step
                minus[index] -= step
                estimate[index] = (
                    energy(plus) - energy(minus)
                ) / (2.0 * step)
            finite_difference[f"{step:.1e}"] = {
                "gradient_infinity": float(np.max(np.abs(estimate))),
                "maximum_absolute_error": float(
                    np.max(np.abs(estimate - analytic))
                ),
                "analytic_maximum_component_index": maximum_index,
                "analytic_maximum_component": float(
                    analytic[maximum_index]
                ),
                "finite_difference_at_analytic_maximum": float(
                    estimate[maximum_index]
                ),
            }
        hessian = np.zeros((target.size, target.size), dtype=np.float64)
        for index in range(target.size):
            plus = target.copy()
            minus = target.copy()
            plus[index] += HESSIAN_STEP
            minus[index] -= HESSIAN_STEP
            hessian[:, index] = (
                gradient(plus) - gradient(minus)
            ) / (2.0 * HESSIAN_STEP)
        symmetric = 0.5 * (hessian + hessian.T)
        eigenvalues = np.linalg.eigvalsh(symmetric)
        nonzero = np.abs(eigenvalues) > 1e-10
        diagnostics.append(
            {
                "attempt_id": attempt["attempt_id"],
                "family_id": attempt["family_id"],
                "normal": attempt["normal"],
                "source_candidate_state_fidelity": float(
                    abs(np.vdot(source_state, candidate_state)) ** 2
                ),
                "candidate_energy_hartree": energy(target),
                "symmetries": _symmetries(candidate_state, pool.n),
                "leading_determinants": _top_determinants(
                    candidate_state, pool.n
                ),
                "gradient": {
                    "dimension": int(target.size),
                    "analytic_infinity": float(
                        np.max(np.abs(analytic))
                    ),
                    "maximum_component_index": maximum_index,
                    "finite_difference": finite_difference,
                },
                "hessian_diagnostic": {
                    "method": "centered-difference-of-analytic-gradient",
                    "step": HESSIAN_STEP,
                    "symmetry_residual_infinity": float(
                        np.max(np.abs(hessian - hessian.T))
                    ),
                    "minimum_eigenvalue": float(eigenvalues[0]),
                    "maximum_eigenvalue": float(eigenvalues[-1]),
                    "negative_eigenvalue_count": int(
                        np.count_nonzero(eigenvalues < -1e-8)
                    ),
                    "near_zero_eigenvalue_count": int(
                        np.count_nonzero(np.abs(eigenvalues) <= 1e-8)
                    ),
                    "absolute_condition_above_1e-10": (
                        float(
                            np.max(np.abs(eigenvalues[nonzero]))
                            / np.min(np.abs(eigenvalues[nonzero]))
                        )
                        if np.any(nonzero)
                        else None
                    ),
                    "claim_boundary": (
                        "Numerical target-coordinate Hessian diagnostic; "
                        "not an exact physical Hessian proof."
                    ),
                },
            }
        )
        work["statevector_evaluations"] += 1
        work["observable_expectations"] += 3
    return {
        "source": {
            "state_sha256": hashlib.sha256(
                np.asarray(source_state, dtype=">c16").tobytes()
            ).hexdigest(),
            "symmetries": _symmetries(source_state, pool.n),
            "leading_determinants": _top_determinants(source_state, pool.n),
        },
        "candidates": diagnostics,
        "candidate_candidate_state_fidelity": float(
            abs(np.vdot(states[0], states[1])) ** 2
        ),
        "optimizer_trajectory": {
            "status": "UNAVAILABLE",
            "reason": (
                "NS7 did not record iterates; no rerun is presented as "
                "historical optimizer trajectory."
            ),
        },
        "work": work,
        "acceptance_decisions_modified": False,
    }, accepted


def _frontier_audit(
    ns7: Mapping[str, Any],
    accepted: list[dict[str, Any]],
) -> dict[str, Any]:
    legacy = json.loads(V5_H4_OUTPUT.read_text(encoding="utf-8"))
    source_resources = legacy["source_resources"]
    source_energy = float(legacy["source_energy_hartree"])
    ns7_source = accepted[0]["source"]
    same_source_checks = {
        "state_digest": (
            legacy["source_reconstruction"]["statevector_sha256"]
            == ns7_source["state_sha256"]
        ),
        "energy": math.isclose(
            source_energy,
            float(ns7_source["energy_hartree"]),
            rel_tol=0.0,
            abs_tol=1e-12,
        ),
        "resources": all(
            int(source_resources[field])
            == int(
                accepted[0]["resources"]["observed"][field]
                - accepted[0]["resources"]["delta"][field]
            )
            for field in (
                "cnot_count",
                "cnot_depth",
                "total_depth",
                "parameter_count",
                "logical_block_count",
            )
        ),
    }
    if not all(same_source_checks.values()):
        raise NS8AuditError(
            f"same-source comparison failed: {same_source_checks}"
        )
    points = [
        {
            "point_id": "ceo-star-source",
            "method": "CEO* source / same-structure control",
            "energy_loss_hartree": 0.0,
            "resources": {
                key: source_resources[key]
                for key in (
                    "cnot_count",
                    "cnot_depth",
                    "total_depth",
                    "parameter_count",
                    "logical_block_count",
                )
            },
            "work": {
                "energy_evaluations": 0,
                "gradient_vector_evaluations": 0,
                "gradient_component_equivalents": 0,
                "exact_vqe_attempts": 0,
                "full_resource_recounts": 0,
            },
        }
    ]
    for attempt in accepted:
        points.append(
            {
                "point_id": attempt["attempt_id"],
                "method": "V6 NS7 native rank-2",
                "normal": attempt["normal"],
                "energy_loss_hartree": attempt["certification"][
                    "actual_loss_hartree"
                ],
                "resources": {
                    key: attempt["resources"]["observed"][key]
                    for key in (
                        "cnot_count",
                        "cnot_depth",
                        "total_depth",
                        "parameter_count",
                        "logical_block_count",
                    )
                },
                "work": {
                    "energy_evaluations": (
                        attempt["work"]["optimizer_energy_evaluations"]
                        + attempt["work"][
                            "finite_difference_energy_evaluations"
                        ]
                        + attempt["work"][
                            "independent_energy_evaluations"
                        ]
                    ),
                    "gradient_vector_evaluations": attempt["work"][
                        "optimizer_gradient_vector_evaluations"
                    ],
                    "gradient_component_equivalents": (
                        attempt["work"][
                            "optimizer_gradient_vector_evaluations"
                        ]
                        * attempt["acceptance"]["after_parameter_count"]
                    ),
                    "exact_vqe_attempts": 1,
                    "full_resource_recounts": 1,
                },
            }
        )
    for trajectory in legacy["result"]["trajectory"]:
        points.append(
            {
                "point_id": trajectory["candidate_id"],
                "method": (
                    "V5 round-1 intermediate"
                    if trajectory["round_index"] == 1
                    else "V5 two-round endpoint"
                ),
                "energy_loss_hartree": trajectory[
                    "actual_cumulative_energy_increase_hartree"
                ],
                "resources": trajectory["resources"],
                "work": trajectory["work_after_attempt"],
            }
        )
    for point in points:
        point["dominated_by"] = [
            other["point_id"]
            for other in points
            if other is not point and _dominates(other, point)
        ]
        point["pareto_nondominated"] = not point["dominated_by"]
    ns7_points = [
        point for point in points if point["method"].startswith("V6")
    ]
    return {
        "same_source_checks": same_source_checks,
        "energy_equivalence_tolerance_hartree": ENERGY_EQUIVALENCE,
        "points": points,
        "legacy_comparator_availability": {
            "v4.1_exact_late_h4_endpoint": "UNAVAILABLE",
            "v5_round1_and_endpoint": "AVAILABLE_L5",
            "v5.1_exact_fusion_late_h4_endpoint": "UNAVAILABLE",
            "standalone_magnitude_late_h4_endpoint": "UNAVAILABLE",
            "same_structure_reoptimization": (
                "SOURCE_ALREADY_RECONSTRUCTED_AND_STATIONARY; "
                "NO_SEPARATE_MATCHED-WORK RUN"
            ),
        },
        "ns7_adds_same_source_energy_resource_pareto_point": any(
            point["pareto_nondominated"] for point in ns7_points
        ),
        "matched_work_superiority_established": False,
        "matched_work_limitation": (
            "Legacy and V6 work fields are reconstructible but were not "
            "generated under one prospectively shared work envelope; no "
            "matched-work superiority claim is made."
        ),
        "paper_measurement_cost": None,
    }


def build_report() -> dict[str, Any]:
    if DEFAULT_OUTPUT.exists():
        raise NS8AuditError("NS8 output already exists")
    if _git("status", "--porcelain"):
        raise NS8AuditError("NS8 requires a clean committed worktree")
    threads = {name: os.environ.get(name) for name in REQUIRED_THREADS}
    if threads != REQUIRED_THREADS:
        raise NS8AuditError(f"noncanonical thread settings: {threads}")
    ns7 = json.loads(NS7_OUTPUT.read_text(encoding="utf-8"))
    mechanism, accepted = _mechanism_audit(ns7)
    report = {
        "schema_version": "1.0.0",
        "artifact_kind": "v6-ns8-h4-mechanism-frontier-audit",
        "audit_version": AUDIT_VERSION,
        "development_only": True,
        "execution": {
            "git_commit": _git("rev-parse", "HEAD"),
            "git_describe": _git("describe", "--always", "--dirty"),
            "threads": threads,
            "python": sys.version,
            "platform": platform.platform(),
            "dependencies": {
                name: importlib.metadata.version(name)
                for name in ("numpy", "scipy", "openfermion")
            },
        },
        "inputs": {
            "ns7": {
                "path": str(NS7_OUTPUT.relative_to(ROOT)),
                "sha256": _sha256(NS7_OUTPUT),
                "report_digest": ns7["report_digest"],
            },
            "v5_h4": {
                "path": str(V5_H4_OUTPUT.relative_to(ROOT)),
                "sha256": _sha256(V5_H4_OUTPUT),
            },
        },
        "mechanism_audit": mechanism,
        "frontier_audit": _frontier_audit(ns7, accepted),
        "claim_boundary": (
            "Outcome-aware development mechanism and same-source historical "
            "frontier audit. NS7 decisions are immutable; no prospective, "
            "cross-molecule, matched-work superiority, or PRA claim."
        ),
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
        subprocess.CalledProcessError,
        TypeError,
        ValueError,
        NS8AuditError,
    ) as error:
        print(f"V6-NS8 audit failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    print(
        json.dumps(
            {
                "report_digest": report["report_digest"],
                "frontier": {
                    "ns7_adds_point": report["frontier_audit"][
                        "ns7_adds_same_source_energy_resource_pareto_point"
                    ],
                    "nondominated": [
                        item["method"]
                        for item in report["frontier_audit"]["points"]
                        if item["pareto_nondominated"]
                    ],
                },
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()

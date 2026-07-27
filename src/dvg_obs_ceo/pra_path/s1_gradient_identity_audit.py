"""PRA S1 audit of source identity and gradient coordinate semantics."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
from typing import Any, Mapping, Sequence

import numpy as np

from dvg_obs_ceo.artifact_io import atomic_write_new_json
from dvg_obs_ceo.baseline import ROOT
from dvg_obs_ceo.block_ir import recover_dvg_blocks
from dvg_obs_ceo.identity import (
    MeasurementContextSpec,
    ProblemSpec,
    StatePreparationSpec,
    canonical_float64_hex,
    sha256_hex,
)
from dvg_obs_ceo.v6_rank_adaptive.native_synthesis_pipeline import (
    CONTEXTS,
    NS1_OUTPUT,
    _load_context_structure,
)
from dvg_obs_ceo.v6_rank_adaptive.ns7_energy_certification import (
    DEFAULT_OUTPUT as NS7_OUTPUT,
    _algorithm_for,
    affine_embedding,
)
from dvg_obs_ceo.v6_rank_adaptive.ns10_h6_optimizer_ablation import (
    RESULT_OUTPUT as NS10_OUTPUT,
)


OUTPUT = ROOT / "artifacts/pra_path/s1/gradient-identity-audit-v1.json"
S0_OUTPUT = ROOT / "artifacts/pra_path/s0/evidence-ledger-v1.json"
SOURCE_STATIONARITY_TOLERANCE = 1e-8
AGREEMENT_TOLERANCE = 1e-12
FINITE_DIFFERENCE_STEP = 1e-6
REQUIRED_THREADS = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
}


class S1GradientIdentityError(RuntimeError):
    """Raised when S1 cannot establish unambiguous gradient semantics."""


def _git(*arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _decode_float64(values: Sequence[str]) -> np.ndarray:
    return np.asarray(
        [struct.unpack(">d", bytes.fromhex(value))[0] for value in values],
        dtype=np.float64,
    )


def _state_digest(state: np.ndarray) -> str:
    value = np.asarray(state, dtype=np.complex128).ravel()
    value /= np.linalg.norm(value)
    return hashlib.sha256(
        np.asarray(value, dtype=">c16").tobytes()
    ).hexdigest()


def _sparse_digest(matrix: Any) -> str:
    value = matrix.tocsr()
    payload = (
        np.asarray(value.shape, dtype=">i8").tobytes()
        + np.asarray(value.indptr, dtype=">i8").tobytes()
        + np.asarray(value.indices, dtype=">i8").tobytes()
        + np.asarray(value.data, dtype=">c16").tobytes()
    )
    return hashlib.sha256(payload).hexdigest()


def _reference_bits(state: Any, qubits: int) -> tuple[int, ...]:
    array = np.asarray(state.toarray()).ravel()
    nonzero = np.flatnonzero(np.abs(array) > 1e-12)
    if nonzero.size != 1 or not np.isclose(abs(array[nonzero[0]]), 1.0):
        raise S1GradientIdentityError(
            "reference is not one computational-basis state"
        )
    basis_index = int(nonzero[0])
    return tuple((basis_index >> qubit) & 1 for qubit in range(qubits))


def _context(context_id: str) -> Mapping[str, Any]:
    return next(item for item in CONTEXTS if item["case_id"] == context_id)


def _geometry(distance: float) -> tuple[tuple[str, tuple[float, float, float]], ...]:
    return tuple(
        ("H", (0.0, 0.0, float(index * distance))) for index in range(6)
    )


def _identities(
    *,
    context_id: str,
    algorithm: Any,
    pool: Any,
    source: Any,
    blocks: Sequence[Any],
) -> dict[str, Any]:
    generator_payload = [
        {
            "family": block.family,
            "generator_digests": list(block.generator_digests),
            "orientation": block.orientation,
            "normalization": block.normalization,
        }
        for block in blocks
    ]
    state = StatePreparationSpec.create(
        reference_state=_reference_bits(algorithm.ref_state, pool.n),
        generator_definition_digest=sha256_hex(generator_payload),
        ansatz_block_structure=[
            (block.family, block.pool_indices) for block in blocks
        ],
        ansatz_indices=source.indices,
        coefficients=source.coefficients,
        qubit_mapping="jordan-wigner-paper-era",
        qubit_ordering=range(pool.n),
    )
    distance = 1.5 if context_id == "h6-1.5-s6" else 3.0
    hamiltonian_digest = _sparse_digest(algorithm.hamiltonian)
    problem = ProblemSpec(
        hamiltonian_digest=hamiltonian_digest,
        molecule="linear-H6",
        geometry_angstrom=_geometry(distance),
        basis_set="sto-3g",
        active_space=tuple(range(6)),
        frozen_orbitals=(),
        fermion_to_qubit_mapping_convention="jordan-wigner-paper-era",
    )
    measurement = MeasurementContextSpec(
        state_preparation_id=state.state_preparation_id,
        problem_id=problem.problem_id,
        observable_set_digest=hamiltonian_digest,
        measurement_plan_version="exact-statevector-v1",
        grouping_strategy="none-exact",
        estimator_version="paper-era-analytic-v1",
        backend_context_digest=sha256_hex(
            {"backend": "exact-statevector", "noise": False}
        ),
    )
    return {
        "StatePreparationID": state.state_preparation_id,
        "ProblemID": problem.problem_id,
        "MeasurementContextID": measurement.measurement_context_id,
        "state_preparation_payload": state.payload(),
        "problem_payload": problem.payload(),
        "measurement_context_payload": measurement.payload(),
    }


def _finite_difference_checks(
    algorithm: Any,
    indices: Sequence[int],
    embedding: np.ndarray,
    target: np.ndarray,
    analytic: np.ndarray,
) -> dict[str, Any]:
    positions = np.linspace(
        0, target.size - 1, num=min(5, target.size), dtype=int
    )
    result: dict[str, Any] = {}
    for raw in positions:
        index = int(raw)
        plus = target.copy()
        minus = target.copy()
        plus[index] += FINITE_DIFFERENCE_STEP
        minus[index] -= FINITE_DIFFERENCE_STEP
        estimate = (
            algorithm.evaluate_energy(
                list(embedding @ plus), list(indices)
            )
            - algorithm.evaluate_energy(
                list(embedding @ minus), list(indices)
            )
        ) / (2.0 * FINITE_DIFFERENCE_STEP)
        result[str(index)] = {
            "analytic": float(analytic[index]),
            "finite_difference": float(estimate),
            "absolute_error": float(abs(analytic[index] - estimate)),
        }
    return result


def _candidate_audit(
    *,
    attempt: Mapping[str, Any],
    algorithm: Any,
    source: Any,
    blocks: Sequence[Any],
    families: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    block = next(
        item for item in blocks
        if item.block_id == attempt["queue_item"]["source_block_id"]
    )
    family = families[attempt["family_id"]]
    embedding, _ = affine_embedding(
        len(source.indices),
        block.ansatz_positions,
        np.asarray(family["parameter_map"], dtype=np.float64),
    )
    target = _decode_float64(
        attempt["final_target_coordinates_float64_hex"]
    )
    mapped = embedding @ target
    full_gradient = np.asarray(
        algorithm.estimate_gradients(
            list(mapped), list(source.indices), method="an"
        ),
        dtype=np.float64,
    )
    target_gradient = embedding.T @ full_gradient
    tangent_basis, _ = np.linalg.qr(embedding, mode="reduced")
    orthonormal_gradient = tangent_basis.T @ full_gradient
    constraint_normal = np.zeros(len(source.indices), dtype=np.float64)
    constraint_normal[list(block.ansatz_positions)] = np.asarray(
        family["normal"], dtype=np.float64
    )
    multiplier = -float(
        constraint_normal @ full_gradient
        / (constraint_normal @ constraint_normal)
    )
    kkt_vector = full_gradient + multiplier * constraint_normal
    finite_difference = _finite_difference_checks(
        algorithm,
        source.indices,
        embedding,
        target,
        target_gradient,
    )
    stored = attempt["certification"]
    checks = {
        "stored_full_gradient_matches": abs(
            float(np.max(np.abs(full_gradient)))
            - stored["source_gradient_infinity"]
        ) <= AGREEMENT_TOLERANCE,
        "stored_target_gradient_matches": abs(
            float(np.max(np.abs(target_gradient)))
            - stored["target_gradient_infinity"]
        ) <= AGREEMENT_TOLERANCE,
        "finite_difference_agrees": max(
            value["absolute_error"] for value in finite_difference.values()
        ) <= 1e-6,
        "embedding_constraint_holds": abs(
            float(constraint_normal @ mapped)
        ) <= 1e-10,
    }
    return {
        "attempt_id": attempt["attempt_id"],
        "context_id": attempt["queue_item"]["context_id"],
        "family_id": attempt["family_id"],
        "normal": family["normal"],
        "field_semantics": {
            "historical_source_gradient_infinity": (
                "candidate_full_source_coordinate_gradient_infinity"
            ),
            "historical_target_gradient_infinity": (
                "candidate_target_coordinate_gradient_infinity"
            ),
        },
        "gradients": {
            "candidate_full_source_coordinate_gradient_infinity": float(
                np.max(np.abs(full_gradient))
            ),
            "candidate_target_coordinate_gradient_infinity": float(
                np.max(np.abs(target_gradient))
            ),
            "candidate_orthonormal_tangent_gradient_infinity": float(
                np.max(np.abs(orthonormal_gradient))
            ),
            "candidate_normal_kkt_multiplier": multiplier,
            "candidate_kkt_residual_infinity": float(
                np.max(np.abs(kkt_vector))
            ),
        },
        "finite_difference": finite_difference,
        "checks": {name: bool(value) for name, value in checks.items()},
    }


def build_report() -> dict[str, Any]:
    s0 = json.loads(S0_OUTPUT.read_text(encoding="utf-8"))
    if s0["status"] != "immutable-parent-reconciled":
        raise S1GradientIdentityError("S0 did not authorize S1")
    ns7 = json.loads(NS7_OUTPUT.read_text(encoding="utf-8"))
    ns10 = json.loads(NS10_OUTPUT.read_text(encoding="utf-8"))
    families = {
        value["family_id"]: value
        for value in json.loads(NS1_OUTPUT.read_text(encoding="utf-8"))[
            "families"
        ]
    }
    controls = {
        value["queue_item"]["context_id"]: value
        for value in ns10["results"]
        if value["kind"] == "same-structure-trust-region-control"
    }
    contexts: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    for context_id in ("h6-1.5-s6", "h6-3.0"):
        algorithm, pool = _algorithm_for(context_id)
        source = _load_context_structure(_context(context_id))
        blocks = recover_dvg_blocks(
            pool,
            source.indices,
            source.coefficients,
            source.cumulative_parameter_counts,
        )
        source_theta = np.asarray(source.coefficients, dtype=np.float64)
        source_energy = float(
            algorithm.evaluate_energy(list(source_theta), list(source.indices))
        )
        source_gradient = np.asarray(
            algorithm.estimate_gradients(
                list(source_theta), list(source.indices), method="an"
            ),
            dtype=np.float64,
        )
        source_state = np.asarray(
            algorithm.compute_state(
                list(source_theta), list(source.indices)
            ).toarray()
        ).ravel()
        snapshot_digest = sha256_hex(
            {
                "indices": list(source.indices),
                "coefficients": list(
                    canonical_float64_hex(source.coefficients)
                ),
                "counts": list(source.cumulative_parameter_counts),
            }
        )
        prior_attempts = [
            value for value in ns7["attempts"]
            if value["queue_item"]["context_id"] == context_id
        ]
        control = controls[context_id]
        state_digest = _state_digest(source_state)
        checks = {
            "all_ns7_snapshot_digests_match": all(
                value["source"]["snapshot_digest_before"] == snapshot_digest
                and value["source"]["snapshot_digest_after"] == snapshot_digest
                for value in prior_attempts
            ),
            "all_ns7_state_digests_match": all(
                value["source"]["state_sha256"] == state_digest
                for value in prior_attempts
            ),
            "all_ns7_source_energies_match": all(
                abs(value["source"]["energy_hartree"] - source_energy)
                <= AGREEMENT_TOLERANCE
                for value in prior_attempts
            ),
            "ns10_control_initial_energy_matches": abs(
                control["initial"]["energy_hartree"] - source_energy
            ) <= AGREEMENT_TOLERANCE,
            "ns10_control_initial_gradient_matches": abs(
                control["initial"]["gradient_infinity"]
                - float(np.max(np.abs(source_gradient)))
            ) <= AGREEMENT_TOLERANCE,
            "source_checkpoint_stationary": float(
                np.max(np.abs(source_gradient))
            ) <= SOURCE_STATIONARITY_TOLERANCE,
        }
        contexts.append(
            {
                "context_id": context_id,
                "identities": _identities(
                    context_id=context_id,
                    algorithm=algorithm,
                    pool=pool,
                    source=source,
                    blocks=blocks,
                ),
                "source": {
                    "snapshot_digest": snapshot_digest,
                    "state_sha256": state_digest,
                    "energy_hartree": source_energy,
                    "source_checkpoint_parameter_gradient_infinity": float(
                        np.max(np.abs(source_gradient))
                    ),
                    "parameter_count": len(source.indices),
                    "logical_block_count": len(blocks),
                },
                "checks": {
                    name: bool(value) for name, value in checks.items()
                },
                "identity_established": all(checks.values()),
            }
        )
        for attempt in prior_attempts:
            candidates.append(
                _candidate_audit(
                    attempt=attempt,
                    algorithm=algorithm,
                    source=source,
                    blocks=blocks,
                    families=families,
                )
            )
    all_source_checks = all(
        value["identity_established"] for value in contexts
    )
    all_candidate_checks = all(
        all(value["checks"].values()) for value in candidates
    )
    decision = (
        "GO_S2_FIELD_NAMING_CORRECTION"
        if all_source_checks and all_candidate_checks
        else "NO_GO_SOURCE_OR_GRADIENT_MISMATCH"
    )
    report: dict[str, Any] = {
        "schema": "dvg-obs-ceo.pra-path.s1-gradient-identity-audit.v1",
        "decision": decision,
        "contexts": contexts,
        "candidates": candidates,
        "interpretation": {
            "h6_source_nonstationary_claim_supported": False,
            "historical_field_name_ambiguous": True,
            "historical_ns7_decisions_changed": False,
            "correct_h6_statement": (
                "The registered rank-two families were not certified on the "
                "two stationary H6 source checkpoints under the frozen "
                "optimization protocols."
            ),
        },
        "authorization": {
            "s2": decision == "GO_S2_FIELD_NAMING_CORRECTION",
            "source_reoptimization_required_before_s2": False,
        },
        "execution": {
            "git_commit": _git("rev-parse", "HEAD"),
            "threads": {
                name: os.environ.get(name) for name in REQUIRED_THREADS
            },
        },
        "claim_boundary": (
            "Gradient-semantics and source-identity correction only; no new "
            "rank-demotion performance or generalization claim."
        ),
    }
    report["report_digest"] = sha256_hex(report)
    return report


def audit_report(report: Mapping[str, Any]) -> None:
    content = dict(report)
    digest = content.pop("report_digest", None)
    if digest != sha256_hex(content):
        raise S1GradientIdentityError("S1 report digest mismatch")
    if report["interpretation"]["historical_ns7_decisions_changed"]:
        raise S1GradientIdentityError("S1 may not rewrite NS7 decisions")
    if any(
        not all(value["checks"].values())
        for value in report["candidates"]
    ):
        raise S1GradientIdentityError("candidate gradient audit failed")
    json.dumps(report, allow_nan=False)


def main() -> None:
    if OUTPUT.exists():
        raise S1GradientIdentityError("refusing to overwrite S1 audit")
    if _git("status", "--porcelain"):
        raise S1GradientIdentityError("S1 requires a clean committed worktree")
    threads = {name: os.environ.get(name) for name in REQUIRED_THREADS}
    if threads != REQUIRED_THREADS:
        raise S1GradientIdentityError(
            f"S1 requires canonical single-thread settings: {threads}"
        )
    report = build_report()
    audit_report(report)
    atomic_write_new_json(OUTPUT, report)


if __name__ == "__main__":
    main()

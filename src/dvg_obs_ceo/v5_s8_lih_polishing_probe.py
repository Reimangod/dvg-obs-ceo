"""Conditional target-native polishing probe for the audited LiH C rejection."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path

import numpy as np

from .baseline import ROOT
from .block_ir import enumerate_candidates, recover_dvg_blocks
from .composition import compose_registered_candidates
from .identity import canonical_json_bytes
from .resources import AnsatzStructure, evaluate_full_circuit_resources, paper_era_backend
from .s8_probe import _state_vector
from .s10_lih import _algorithm as _lih_algorithm
from .stationarity import GradientAgreementPolicy, audit_gradient_paths
from .transaction import (
    AcceptanceCriteria,
    AcceptanceEvidence,
    OptimizerOutcome,
    evaluate_acceptance,
)
from .v4_lih import _energy, _gradient
from .v5_conditional_polishing import (
    ConditionalPolishingConfig,
    PolishingEligibility,
    polish_target_native_conditionally,
)


RUNNER_VERSION = "v5-s8-lih-conditional-polishing-probe-v1"
CHECKPOINT = ROOT / "artifacts/s10/lih-3a-first-accuracy-primary-v1-2/checkpoint.json"
SOURCE_RESULT = ROOT / "artifacts/v5/s8/lih-width1-transfer-v1/summary.json"
SOURCE_AUDIT = ROOT / "artifacts/v5/s8/lih-width1-transfer-v1-audit.json"
OUTPUT = ROOT / "artifacts/v5/s8/lih-conditional-polishing-probe-v1.json"
REQUIRED_THREADS = {"OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}


class V5S8LiHPolishingProbeError(RuntimeError):
    pass


def _digest(value):
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def run(
    output: Path = OUTPUT,
    *,
    polishing_config: ConditionalPolishingConfig = ConditionalPolishingConfig(),
    runner_version: str = RUNNER_VERSION,
) -> dict:
    if output.exists():
        raise V5S8LiHPolishingProbeError("refusing to overwrite polishing probe")
    threads = {name: os.environ.get(name) for name in REQUIRED_THREADS}
    if threads != REQUIRED_THREADS:
        raise V5S8LiHPolishingProbeError(f"single-thread freeze missing: {threads}")
    source_result = json.loads(SOURCE_RESULT.read_text(encoding="utf-8"))
    source_audit = json.loads(SOURCE_AUDIT.read_text(encoding="utf-8"))
    if (
        source_audit.get("passed") is not True
        or source_audit["failed_acceptance_checks"] != ["kkt"]
        or source_result["result"]["accepted_rounds"] != 0
    ):
        raise V5S8LiHPolishingProbeError("registered polishing trigger is absent")
    checkpoint = json.loads(CHECKPOINT.read_text(encoding="utf-8"))
    observed = checkpoint.pop("checkpoint_digest")
    if _digest(checkpoint) != observed:
        raise V5S8LiHPolishingProbeError("LiH checkpoint digest drift")
    checkpoint["checkpoint_digest"] = observed
    algorithm, pool, _ = _lih_algorithm()
    algorithm.initialize()
    source = AnsatzStructure.create(
        checkpoint["ansatz_indices"], checkpoint["ansatz_coefficients"], checkpoint["iteration_counts"]
    )
    source_state = _state_vector(algorithm, source.coefficients, source.indices)
    source_resources = evaluate_full_circuit_resources(pool, source, paper_era_backend())
    attempt = source_result["exact_attempt_records"][0]
    blocks = recover_dvg_blocks(
        pool, source.indices, source.coefficients, source.cumulative_parameter_counts
    )
    representatives: dict[str, object] = {}
    for candidate in enumerate_candidates(pool, blocks):
        representatives.setdefault(candidate.equivalence_class_id, candidate)
    by_id = {candidate.candidate_id: candidate for candidate in representatives.values()}
    atomic_ids = tuple(attempt["atomic_candidate_ids"])
    if any(candidate_id not in by_id for candidate_id in atomic_ids):
        raise V5S8LiHPolishingProbeError("rejected candidate identity drift")
    plan = compose_registered_candidates(source, blocks, tuple(by_id[value] for value in atomic_ids))
    if (
        plan.state.constraint_semantic_id != attempt["constraint_semantic_id"]
        or plan.state.constraint_numerical_id != attempt["constraint_numerical_id"]
    ):
        raise V5S8LiHPolishingProbeError("rejected constraint identity drift")
    rejected_coordinates = np.asarray(attempt["fallback"]["coordinates"], dtype=np.float64)
    projected_source = plan.transformation.offset + plan.transformation.jacobian @ rejected_coordinates
    polishing = polish_target_native_conditionally(
        plan.transformation,
        projected_source,
        np.asarray(source.coefficients, dtype=np.float64),
        lambda theta: _energy(algorithm, theta, source.indices),
        lambda theta: _gradient(algorithm, theta, source.indices),
        PolishingEligibility(
            semantics_validated=True,
            physical_resource_benefit=True,
            predicted_energy_within_budget=True,
            refinement_required=True,
        ),
        config=polishing_config,
    )
    acceptance = None
    independent = None
    if polishing["success"]:
        coordinates = np.asarray(polishing["target_coordinates"], dtype=np.float64)
        target = AnsatzStructure.create(plan.target_indices, coordinates, plan.target_iteration_counts)
        physical = evaluate_full_circuit_resources(pool, target, paper_era_backend())
        structural = evaluate_full_circuit_resources(
            pool, target, paper_era_backend(), coefficient_policy="deterministic-structural"
        )
        energy = _energy(algorithm, coordinates, plan.target_indices)
        energy_second = _energy(algorithm, coordinates, plan.target_indices)
        gradient = _gradient(algorithm, coordinates, plan.target_indices)
        state_first = _state_vector(algorithm, coordinates, plan.target_indices)
        state_second = _state_vector(algorithm, coordinates, plan.target_indices)
        repeat_fidelity = float(abs(np.vdot(state_first, state_second)) ** 2)
        certificate = audit_gradient_paths(
            coordinates,
            plan.transformation,
            lambda value: _gradient(algorithm, value, plan.target_indices),
            lambda value: _gradient(algorithm, value, source.indices),
            target_state=lambda value: _state_vector(algorithm, value, plan.target_indices),
            source_state=lambda value: _state_vector(algorithm, value, source.indices),
            target_energy=lambda value: _energy(algorithm, value, plan.target_indices),
            source_energy=lambda value: _energy(algorithm, value, source.indices),
            policy=GradientAgreementPolicy(),
        )
        mapped = plan.transformation.offset + plan.transformation.jacobian @ coordinates
        residual_vector = plan.transformation.constraint_matrix @ mapped - plan.transformation.constraint_rhs
        residual = float(np.max(np.abs(residual_vector))) if residual_vector.size else 0.0
        criteria = AcceptanceCriteria(cumulative_energy_budget_hartree=1e-4, guard_logical_block_count=True)
        semantics = bool(
            certificate["passed"]
            and certificate["source_target_state_fidelity"] >= criteria.minimum_state_fidelity
            and certificate["source_target_energy_difference_hartree"] <= criteria.independent_energy_tolerance_hartree
        )
        decision = evaluate_acceptance(AcceptanceEvidence(
            source_energy_hartree=float(checkpoint["energy_hartree"]),
            budget_reference_energy_hartree=float(checkpoint["energy_hartree"]),
            candidate_energy_hartree=energy,
            independent_energy_hartree=energy_second,
            independent_state_fidelity=repeat_fidelity,
            constraint_residual=residual,
            kkt_residual=float(np.max(np.abs(gradient))),
            before_resources=source_resources.snapshot,
            after_resources=physical.snapshot,
            full_resource_recount_succeeded=physical.snapshot == structural.snapshot,
            transformation_semantics_validated=semantics,
            primary_optimizer=OptimizerOutcome(
                bool(polishing["success"]),
                str(polishing["attempts"][0]["result"]["status"]),
                str(polishing["attempts"][0]["result"]["message"]),
                True,
            ),
            fallback_optimizer=None,
        ), criteria)
        acceptance = asdict(decision)
        independent = {
            "energy_hartree": energy,
            "independent_energy_hartree": energy_second,
            "gradient_infinity": float(np.max(np.abs(gradient))),
            "repeat_state_fidelity": repeat_fidelity,
            "constraint_residual_infinity": residual,
            "two_path_certificate": certificate,
            "physical_resources": asdict(physical.snapshot),
            "structural_resources": asdict(structural.snapshot),
        }
    payload = {
        "schema_version": "1.0.0",
        "artifact_kind": "v5-s8-lih-conditional-polishing-probe",
        "runner_version": runner_version,
        "trigger": {
            "source_result_digest": source_result["result_digest"],
            "source_audit_digest": source_audit["audit_digest"],
            "failed_gate": "kkt",
            "candidate_ids": list(atomic_ids),
            "constraint_semantic_id": plan.state.constraint_semantic_id,
        },
        "polishing": polishing,
        "independent_acceptance_evidence": independent,
        "acceptance": acceptance,
        "incremental_work": polishing["work"],
        "original_c_work": source_result["result"]["terminal_work"],
        "claim_boundary": [
            "Causal rescue probe only; not a committed sequential V5 result or full ablation F.",
            "Candidate and thresholds are inherited unchanged from the audited C rejection.",
            "All incremental finite-difference HVP work is reported separately."
        ],
        "paper_measurement_cost": None,
    }
    payload["result_digest"] = _digest(payload)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    result = run()
    print(json.dumps({
        "polishing_success": result["polishing"]["success"],
        "acceptance": None if result["acceptance"] is None else result["acceptance"]["accepted"],
    }, sort_keys=True))

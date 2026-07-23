"""V5-S8 deployable recycled-curvature width-one runner for late H4.

This is ablation C: risk-aware single-candidate Pareto screening, sequential
commit/rebuild, recycled inverse Hessian, and the unchanged independent
acceptance gates.  Fresh-Hessian/HVP evidence is deliberately absent here.
"""

from __future__ import annotations

from dataclasses import asdict, replace
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from .baseline import ROOT
from .block_ir import enumerate_candidates, recover_dvg_blocks
from .calibration import least_squares_native_coordinates, obs_warm_start
from .composition import compose_registered_candidates
from .identity import canonical_json_bytes
from .resources import AnsatzStructure, evaluate_full_circuit_resources, paper_era_backend
from .s8_probe import _algorithm, _optimize_target, _state_vector
from .stationarity import GradientAgreementPolicy, audit_gradient_paths
from .telemetry import WorkCounters
from .transaction import (
    AcceptanceCriteria,
    AcceptanceEvidence,
    CompressionRuntime,
    OptimizerOutcome,
    evaluate_acceptance,
)
from .v4_lih import _energy, _gradient
from .v5_ledger import V5WorkCounters, versioned_id
from .v5_nested_transaction import PathCheckpointStore
from .v5_pareto import RiskAwareCandidate, RiskDiagnostics, select_risk_aware_pareto
from .v5_sequential import (
    CatalogSnapshot,
    SequentialCandidate,
    SequentialExecution,
    WidthOneConfig,
    run_width_one,
)


RUNNER_VERSION = "v5-s8-h4-width1-recycled-v1"
CASE_ID = "h4-1.5-iteration-12-or-convergence"
CHECKPOINT = ROOT / "artifacts/s8-1/later-checkpoint-calibration-bundle/checkpoint-h4-1.5-iteration-12-or-convergence.json"
OUTPUT = ROOT / "artifacts/v5/s8/h4-width1-recycled"
REQUIRED_THREADS = {"OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}


class V5S8H4WidthOneError(RuntimeError):
    """Raised when a molecular sequential run cannot be trusted."""


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _optimizer(path: Mapping[str, Any]) -> OptimizerOutcome:
    value = path["optimizer"]
    return OptimizerOutcome(
        bool(value["success"]), str(value["status"]), str(value["message"]), True
    )


def _state_id(runtime: CompressionRuntime) -> str:
    return versioned_id("state-v1", {
        "ansatz_indices": list(runtime.ansatz.indices),
        "ansatz_coefficients_float64_hex": [
            np.float64(value).tobytes().hex() for value in runtime.ansatz.coefficients
        ],
        "iteration_counts": list(runtime.ansatz.cumulative_parameter_counts),
        "generator_definition": "pinned-paper-era-ceo-pool",
        "qubit_mapping": "pinned-upstream-jordan-wigner",
        "resource_structure_digest": runtime.metadata["resource_structure_digest"],
    })


def _measurement_id(state_id: str, problem_id: str) -> str:
    return versioned_id("measurement-v1", {
        "state_preparation_id": state_id,
        "problem_id": problem_id,
        "observable_set": "energy-and-analytic-gradient",
        "measurement_plan_version": "exact-statevector-v1",
        "grouping_strategy": "not-applicable-exact-statevector",
        "estimator_version": "pinned-upstream-exact-v1",
        "backend_context": "noise-free-statevector",
    })


class H4WidthOneAdapter:
    def __init__(
        self,
        algorithm: Any,
        pool: Any,
        *,
        problem_id: str,
        screening_budget_hartree: float = 1e-4,
    ) -> None:
        self.algorithm = algorithm
        self.pool = pool
        self.problem_id = problem_id
        self.screening_budget_hartree = screening_budget_hartree
        self.work = V5WorkCounters()
        self._catalog_cache: dict[str, CatalogSnapshot] = {}
        self._selection_cache: dict[str, dict[str, Any]] = {}

    def _build(self, runtime: CompressionRuntime) -> CatalogSnapshot:
        runtime_digest = runtime.snapshot().snapshot_digest
        if runtime_digest in self._catalog_cache:
            return self._catalog_cache[runtime_digest]
        source = runtime.ansatz
        before = evaluate_full_circuit_resources(self.pool, source, paper_era_backend())
        if before.snapshot.structure_digest != runtime.metadata["resource_structure_digest"]:
            raise V5S8H4WidthOneError("runtime and full resource recount disagree")
        blocks = recover_dvg_blocks(
            self.pool, source.indices, source.coefficients, source.cumulative_parameter_counts
        )
        representatives: dict[str, Any] = {}
        for candidate in enumerate_candidates(self.pool, blocks):
            representatives.setdefault(candidate.equivalence_class_id, candidate)
        risk_candidates: list[RiskAwareCandidate] = []
        by_semantic: dict[str, dict[str, Any]] = {}
        numerical_failures: list[dict[str, str]] = []
        for candidate in sorted(representatives.values(), key=lambda item: item.candidate_id):
            try:
                plan = compose_registered_candidates(source, blocks, (candidate,))
                initial, target_inverse, prediction = obs_warm_start(
                    source.coefficients,
                    runtime.gradient,
                    runtime.inverse_hessian,
                    plan.transformation,
                )
                target = AnsatzStructure.create(
                    plan.target_indices,
                    [1.0] * len(plan.target_indices),
                    plan.target_iteration_counts,
                )
                recount = evaluate_full_circuit_resources(
                    self.pool,
                    target,
                    paper_era_backend(),
                    coefficient_policy="deterministic-structural",
                )
                condition = float(np.linalg.cond(np.asarray(target_inverse, dtype=np.float64)))
                predicted = max(0.0, float(prediction.predicted_change_from_current))
                if not math.isfinite(condition) or not math.isfinite(predicted):
                    raise V5S8H4WidthOneError("non-finite recycled predictor diagnostic")
                quality_passed = condition <= 1e12
                stratum = "good" if condition <= 1e8 else "boundary" if quality_passed else "poor"
                evidence = {
                    "runner_version": RUNNER_VERSION,
                    "candidate_id": candidate.candidate_id,
                    "constraint_semantic_id": plan.state.constraint_semantic_id,
                    "constraint_numerical_id": plan.state.constraint_numerical_id,
                    "target_inverse_condition_number": condition,
                    "predictor": "recycled-general-constraint-obs",
                }
                risk = RiskAwareCandidate(
                    candidate_ids=(candidate.candidate_id,),
                    constraint_semantic_id=plan.state.constraint_semantic_id,
                    constraint_numerical_id=plan.state.constraint_numerical_id,
                    predicted_loss_hartree=predicted,
                    resources=recount.snapshot,
                    diagnostics=RiskDiagnostics(
                        quality_gate_passed=quality_passed,
                        uncertainty_margin_hartree=0.0,
                        quality_stratum=stratum,
                        refinement_required=stratum != "good",
                        evidence_digest=_digest(evidence),
                    ),
                    full_resource_recount_succeeded=True,
                    semantics_validated=True,
                )
                risk_candidates.append(risk)
                by_semantic[plan.state.constraint_semantic_id] = {
                    "candidate": candidate,
                    "initial": np.asarray(initial).tolist(),
                    "target_inverse_hessian": np.asarray(target_inverse).tolist(),
                    "prediction": predicted,
                    "constraint_numerical_id": plan.state.constraint_numerical_id,
                }
            except Exception as error:  # fail one candidate closed, preserve category
                numerical_failures.append({
                    "candidate_id": candidate.candidate_id,
                    "error_type": type(error).__name__,
                    "error": str(error),
                })
        selection = select_risk_aware_pareto(
            risk_candidates,
            before.snapshot,
            screening_budget_hartree=self.screening_budget_hartree,
            top_k_per_endpoint=2,
            maximum_unique_attempts=4,
            require_no_component_regression=True,
        )
        queue: list[SequentialCandidate] = []
        for semantic_id in selection["unique_attempt_semantic_ids"]:
            stored = by_semantic[semantic_id]
            candidate = stored["candidate"]
            evidence = {
                "atomic_candidate_ids": [candidate.candidate_id],
                "constraint_semantic_id": semantic_id,
                "constraint_numerical_id": stored["constraint_numerical_id"],
                "selection_digest": selection["selection_digest"],
                "predictor": "recycled-general-constraint-obs",
            }
            queue.append(SequentialCandidate(
                versioned_id("candidate-v5", evidence),
                float(stored["prediction"]),
                evidence,
            ))
        catalog = CatalogSnapshot.create(runtime_digest, queue)
        self._catalog_cache[runtime_digest] = catalog
        self._selection_cache[runtime_digest] = {
            "selection": selection,
            "candidate_count": len(representatives),
            "numerical_failures": numerical_failures,
        }
        self.work = replace(
            self.work,
            full_resource_recounts=self.work.full_resource_recounts + 1 + len(risk_candidates),
            expanded_search_states=self.work.expanded_search_states + len(representatives),
        )
        return catalog

    def catalog_builder(self, runtime: CompressionRuntime) -> CatalogSnapshot:
        return self._build(runtime)

    def candidate_executor(
        self,
        runtime: CompressionRuntime,
        candidate: SequentialCandidate,
        round_index: int,
        exact_attempt: int,
    ) -> SequentialExecution:
        source = runtime.ansatz
        before = evaluate_full_circuit_resources(self.pool, source, paper_era_backend())
        source_energy = float(runtime.energy_hartree)
        source_state = np.asarray(runtime.statevector, dtype=np.complex128)
        blocks = recover_dvg_blocks(
            self.pool, source.indices, source.coefficients, source.cumulative_parameter_counts
        )
        representatives: dict[str, Any] = {}
        for item in enumerate_candidates(self.pool, blocks):
            representatives.setdefault(item.equivalence_class_id, item)
        by_id = {item.candidate_id: item for item in representatives.values()}
        atomic_ids = tuple(candidate.evidence["atomic_candidate_ids"])
        if any(value not in by_id for value in atomic_ids):
            raise V5S8H4WidthOneError("frozen sequential candidate is absent from current catalog")
        plan = compose_registered_candidates(source, blocks, tuple(by_id[value] for value in atomic_ids))
        if (
            plan.state.constraint_semantic_id != candidate.evidence["constraint_semantic_id"]
            or plan.state.constraint_numerical_id != candidate.evidence["constraint_numerical_id"]
        ):
            raise V5S8H4WidthOneError("frozen candidate constraint identity drift")
        initial, target_inverse, _ = obs_warm_start(
            source.coefficients, runtime.gradient, runtime.inverse_hessian, plan.transformation
        )
        fallback_initial = least_squares_native_coordinates(
            np.asarray(source.coefficients, dtype=np.float64), plan.transformation
        )
        primary = _optimize_target(
            self.algorithm, plan.target_indices, initial, target_inverse, source_state
        )
        fallback = None
        selected = primary
        if not primary["optimizer"]["success"]:
            fallback = _optimize_target(
                self.algorithm,
                plan.target_indices,
                fallback_initial,
                target_inverse,
                source_state,
            )
            selected = fallback
        coordinates = np.asarray(selected["coordinates"], dtype=np.float64)
        target = AnsatzStructure.create(
            plan.target_indices, coordinates, plan.target_iteration_counts
        )
        physical = evaluate_full_circuit_resources(self.pool, target, paper_era_backend())
        structural = evaluate_full_circuit_resources(
            self.pool, target, paper_era_backend(), coefficient_policy="deterministic-structural"
        )
        certificate = audit_gradient_paths(
            coordinates,
            plan.transformation,
            lambda value: _gradient(self.algorithm, value, plan.target_indices),
            lambda value: _gradient(self.algorithm, value, source.indices),
            target_state=lambda value: _state_vector(self.algorithm, value, plan.target_indices),
            source_state=lambda value: _state_vector(self.algorithm, value, source.indices),
            target_energy=lambda value: _energy(self.algorithm, value, plan.target_indices),
            source_energy=lambda value: _energy(self.algorithm, value, source.indices),
            policy=GradientAgreementPolicy(),
        )
        mapped = plan.transformation.offset + plan.transformation.jacobian @ coordinates
        residual = float(np.max(np.abs(
            plan.transformation.constraint_matrix @ mapped
            - plan.transformation.constraint_rhs
        ))) if plan.transformation.constraint_matrix.shape[0] else 0.0
        criteria = AcceptanceCriteria(
            cumulative_energy_budget_hartree=self.screening_budget_hartree,
            guard_logical_block_count=True,
        )
        semantics = bool(
            certificate["passed"]
            and certificate["source_target_state_fidelity"] >= criteria.minimum_state_fidelity
            and certificate["source_target_energy_difference_hartree"]
            <= criteria.independent_energy_tolerance_hartree
        )
        decision = evaluate_acceptance(AcceptanceEvidence(
            source_energy_hartree=source_energy,
            budget_reference_energy_hartree=float(runtime.metadata["budget_reference_energy_hartree"]),
            candidate_energy_hartree=float(selected["energy_hartree"]),
            independent_energy_hartree=float(selected["independent_energy_hartree"]),
            independent_state_fidelity=float(selected["independent_state_recomputation_fidelity"]),
            constraint_residual=residual,
            kkt_residual=float(selected["gradient_infinity"]),
            before_resources=before.snapshot,
            after_resources=physical.snapshot,
            full_resource_recount_succeeded=physical.snapshot == structural.snapshot,
            transformation_semantics_validated=semantics,
            primary_optimizer=_optimizer(primary),
            fallback_optimizer=None if fallback is None else _optimizer(fallback),
        ), criteria)

        runtime.ansatz = target
        runtime.energy_hartree = float(selected["energy_hartree"])
        runtime.gradient = np.asarray(selected["gradient"], dtype=np.float64)
        runtime.inverse_hessian = np.asarray(selected["final_inverse_hessian"], dtype=np.float64)
        runtime.statevector = _state_vector(self.algorithm, coordinates, plan.target_indices)
        runtime.metadata["resource_structure_digest"] = physical.snapshot.structure_digest
        paths = [primary] if fallback is None else [primary, fallback]
        optimizer_energy = sum(int(path["optimizer"]["function_evaluations"]) + 2 for path in paths)
        optimizer_gradients = sum(int(path["optimizer"]["gradient_vector_evaluations"]) + 1 for path in paths)
        self.work = replace(
            self.work,
            energy_evaluations=self.work.energy_evaluations + optimizer_energy + 2,
            gradient_vector_evaluations=self.work.gradient_vector_evaluations + optimizer_gradients + 2,
            gradient_component_equivalents=(
                self.work.gradient_component_equivalents
                + optimizer_gradients * len(plan.target_indices)
                + len(plan.target_indices) + len(source.indices)
            ),
            exact_vqe_attempts=exact_attempt,
            optimizer_iterations=self.work.optimizer_iterations + sum(int(path["optimizer"]["iterations"]) for path in paths),
            optimizer_starts=self.work.optimizer_starts + len(paths),
            full_resource_recounts=self.work.full_resource_recounts + 2,
            attempted_rounds=round_index,
            accepted_rounds=self.work.accepted_rounds + (1 if decision.accepted else 0),
            statevector_evaluations=self.work.statevector_evaluations + 2 * len(paths) + 3,
        )
        state_id = _state_id(runtime)
        return SequentialExecution(
            candidate.candidate_id,
            decision,
            self.work,
            state_id,
            self.problem_id,
            _measurement_id(state_id, self.problem_id),
            physical.snapshot,
        )


def _load_checkpoint() -> dict[str, Any]:
    checkpoint = json.loads(CHECKPOINT.read_text(encoding="utf-8"))
    observed = checkpoint.pop("checkpoint_digest")
    if _digest(checkpoint) != observed:
        raise V5S8H4WidthOneError("H4 checkpoint digest mismatch")
    checkpoint["checkpoint_digest"] = observed
    return checkpoint


def run(output: Path = OUTPUT) -> dict[str, Any]:
    threads = {name: os.environ.get(name) for name in REQUIRED_THREADS}
    if threads != REQUIRED_THREADS:
        raise V5S8H4WidthOneError(f"single-thread freeze missing: {threads}")
    if output.exists():
        raise V5S8H4WidthOneError("output already exists; refusing overwrite")
    checkpoint = _load_checkpoint()
    algorithm, pool = _algorithm(CASE_ID)
    algorithm.initialize()
    source = AnsatzStructure.create(
        checkpoint["ansatz_indices"], checkpoint["ansatz_coefficients"], checkpoint["iteration_counts"]
    )
    source_resources = evaluate_full_circuit_resources(pool, source, paper_era_backend())
    source_state = _state_vector(algorithm, source.coefficients, source.indices)
    runtime = CompressionRuntime.create(
        ansatz=source,
        energy_hartree=float(checkpoint["energy_hartree"]),
        gradient=checkpoint["gradient"],
        inverse_hessian=checkpoint["recycled_inverse_hessian"],
        statevector=source_state,
        work=WorkCounters(),
        adapt_iteration=len(checkpoint["iteration_counts"]),
        metadata={
            "run_id": "v5-s8-h4-width1-recycled",
            "resource_structure_digest": source_resources.snapshot.structure_digest,
            "budget_reference_energy_hartree": float(checkpoint["energy_hartree"]),
            "checkpoint_digest": checkpoint["checkpoint_digest"],
        },
    )
    problem_id = versioned_id("problem-v1", {
        "case_id": CASE_ID,
        "hamiltonian_context": "stored-pinned-h4-linear-1.5-angstrom-sto-3g",
        "checkpoint_digest": checkpoint["checkpoint_digest"],
    })
    adapter = H4WidthOneAdapter(algorithm, pool, problem_id=problem_id)
    source_catalog = adapter.catalog_builder(runtime)
    path_id = versioned_id("path-v5", {
        "runner_version": RUNNER_VERSION,
        "case_id": CASE_ID,
        "checkpoint_digest": checkpoint["checkpoint_digest"],
    })
    store = PathCheckpointStore(output / "path", path_id)
    source_state_id = _state_id(runtime)
    store.initialize(
        runtime,
        work=adapter.work,
        state_preparation_id=source_state_id,
        problem_id=problem_id,
        measurement_context_id=_measurement_id(source_state_id, problem_id),
        catalog_digest=source_catalog.catalog_digest,
        resource_snapshot=source_resources.snapshot,
    )
    result = run_width_one(
        runtime,
        store,
        catalog_builder=adapter.catalog_builder,
        candidate_executor=adapter.candidate_executor,
        config=WidthOneConfig(2, 2, 1e-4),
    )
    payload = {
        "schema_version": "1.0.0",
        "artifact_kind": "v5-s8-h4-width1-recycled",
        "runner_version": RUNNER_VERSION,
        "case_id": CASE_ID,
        "checkpoint_digest": checkpoint["checkpoint_digest"],
        "source_energy_hartree": checkpoint["energy_hartree"],
        "source_resources": asdict(source_resources.snapshot),
        "result": result,
        "catalog_diagnostics_by_runtime": adapter._selection_cache,
        "claim_boundary": [
            "Development H4 ablation C only; not a molecular superiority claim.",
            "Uses recycled curvature only; no exact Hessian or HVP enters screening.",
            "All rejected exact work remains counted although state rollback is exact.",
            "paper_measurement_cost is undefined and not inferred from work counters.",
        ],
        "paper_measurement_cost": None,
    }
    payload["result_digest"] = _digest(payload)
    output.mkdir(parents=True, exist_ok=True)
    (output / "summary.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return payload


if __name__ == "__main__":
    run()

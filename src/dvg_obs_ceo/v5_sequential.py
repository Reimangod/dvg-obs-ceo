"""V5-S3 deterministic width-one sequential compression kernel."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from typing import Any, Callable, Sequence

from .identity import canonical_json_bytes
from .telemetry import ResourceSnapshot
from .transaction import AcceptanceDecision, CompressionRuntime
from .v5_ledger import V5WorkCounters
from .v5_nested_transaction import NestedRoundTransaction, PathCheckpointStore


class V5SequentialError(RuntimeError):
    """Raised when width-one execution violates its frozen contract."""


@dataclass(frozen=True)
class SequentialCandidate:
    candidate_id: str
    predicted_loss_hartree: float
    evidence: dict[str, Any]

    def __post_init__(self) -> None:
        if not self.candidate_id.startswith("candidate-v5:"):
            raise V5SequentialError("sequential candidate ID is invalid")
        if not math.isfinite(self.predicted_loss_hartree) or self.predicted_loss_hartree < -1e-12:
            raise V5SequentialError("sequential predicted loss is invalid")
        canonical_json_bytes(self.evidence)


@dataclass(frozen=True)
class CatalogSnapshot:
    runtime_snapshot_digest: str
    candidates: tuple[SequentialCandidate, ...]
    catalog_digest: str

    @classmethod
    def create(cls, runtime_snapshot_digest: str, candidates: Sequence[SequentialCandidate]) -> "CatalogSnapshot":
        ordered = tuple(candidates)
        if len({candidate.candidate_id for candidate in ordered}) != len(ordered):
            raise V5SequentialError("sequential catalog contains duplicate candidate IDs")
        payload = {
            "version": "v5-width1-catalog-v1",
            "runtime_snapshot_digest": runtime_snapshot_digest,
            "candidates": [
                {
                    "candidate_id": item.candidate_id,
                    "predicted_loss_hartree": item.predicted_loss_hartree,
                    "evidence": item.evidence,
                }
                for item in ordered
            ],
        }
        return cls(runtime_snapshot_digest, ordered, hashlib.sha256(canonical_json_bytes(payload)).hexdigest())


@dataclass(frozen=True)
class SequentialExecution:
    candidate_id: str
    decision: AcceptanceDecision
    work: V5WorkCounters
    state_preparation_id: str
    problem_id: str
    measurement_context_id: str
    resource_snapshot: ResourceSnapshot


@dataclass(frozen=True)
class WidthOneConfig:
    maximum_attempted_rounds: int
    maximum_exact_attempts: int
    cumulative_energy_budget_hartree: float = 1e-4

    def __post_init__(self) -> None:
        if self.maximum_attempted_rounds <= 0 or self.maximum_exact_attempts <= 0:
            raise V5SequentialError("sequential work caps must be positive")
        if not math.isfinite(self.cumulative_energy_budget_hartree) or self.cumulative_energy_budget_hartree < 0:
            raise V5SequentialError("sequential energy budget is invalid")


CatalogBuilder = Callable[[CompressionRuntime], CatalogSnapshot]
CandidateExecutor = Callable[[CompressionRuntime, SequentialCandidate, int, int], SequentialExecution]


def run_width_one(
    runtime: CompressionRuntime,
    store: PathCheckpointStore,
    *,
    catalog_builder: CatalogBuilder,
    candidate_executor: CandidateExecutor,
    config: WidthOneConfig,
) -> dict[str, Any]:
    source_reference = float(runtime.metadata["budget_reference_energy_hartree"])
    exact_attempts = store.latest().work["exact_vqe_attempts"]
    trajectory: list[dict[str, Any]] = []
    stop_reason = "maximum-attempted-rounds"

    for round_index in range(store.latest().round_index + 1, config.maximum_attempted_rounds + 1):
        latest = store.latest()
        current_digest = runtime.snapshot().snapshot_digest
        if latest.runtime().snapshot_digest != current_digest:
            raise V5SequentialError("runtime drifted from the committed path head")
        catalog = catalog_builder(runtime)
        if catalog.runtime_snapshot_digest != current_digest:
            raise V5SequentialError("catalog is not bound to the current runtime")
        if catalog.catalog_digest != latest.catalog_digest:
            raise V5SequentialError("catalog rebuild differs from the committed catalog")
        if not catalog.candidates:
            stop_reason = "no-eligible-candidate"
            break
        if exact_attempts >= config.maximum_exact_attempts:
            stop_reason = "maximum-exact-attempts"
            break

        candidate = catalog.candidates[0]
        current_increase = runtime.energy_hartree - source_reference
        if current_increase + max(0.0, candidate.predicted_loss_hartree) > config.cumulative_energy_budget_hartree:
            stop_reason = "predicted-cumulative-energy-budget"
            break

        exact_attempts += 1
        with NestedRoundTransaction(
            runtime,
            store,
            round_index,
            transaction_id=f"width1-round-{round_index:04d}-{candidate.candidate_id.split(':', 1)[1][:12]}",
        ) as transaction:
            execution = candidate_executor(runtime, candidate, round_index, exact_attempts)
            if execution.candidate_id != candidate.candidate_id:
                raise V5SequentialError("exact executor returned a different candidate identity")
            if execution.work.exact_vqe_attempts != exact_attempts or execution.work.attempted_rounds < round_index:
                raise V5SequentialError("sequential exact/round work is inconsistent")
            if not execution.decision.accepted:
                transaction.rollback(";".join(execution.decision.rejection_reasons) or "independent-acceptance-rejected")
                trajectory.append({
                    "round_index": round_index,
                    "candidate_id": candidate.candidate_id,
                    "accepted": False,
                    "rejection_reasons": list(execution.decision.rejection_reasons),
                    "parent_checkpoint_digest": latest.checkpoint_digest,
                })
                stop_reason = "width-one-candidate-rejected"
                break

            post_catalog = catalog_builder(runtime)
            if post_catalog.runtime_snapshot_digest != runtime.snapshot().snapshot_digest:
                raise V5SequentialError("post-commit catalog is not bound to candidate runtime")
            committed = transaction.commit(
                execution.decision,
                work=execution.work,
                state_preparation_id=execution.state_preparation_id,
                problem_id=execution.problem_id,
                measurement_context_id=execution.measurement_context_id,
                catalog_digest=post_catalog.catalog_digest,
                resource_snapshot=execution.resource_snapshot,
            )
            trajectory.append({
                "round_index": round_index,
                "candidate_id": candidate.candidate_id,
                "accepted": True,
                "actual_cumulative_energy_increase_hartree": runtime.energy_hartree - source_reference,
                "parent_checkpoint_digest": latest.checkpoint_digest,
                "checkpoint_digest": committed.checkpoint_digest,
                "catalog_digest_before": catalog.catalog_digest,
                "catalog_digest_after": post_catalog.catalog_digest,
                "resources": {
                    "cnot_count": execution.resource_snapshot.cnot_count,
                    "cnot_depth": execution.resource_snapshot.cnot_depth,
                    "total_depth": execution.resource_snapshot.total_depth,
                    "parameter_count": execution.resource_snapshot.parameter_count,
                    "logical_block_count": execution.resource_snapshot.logical_block_count,
                },
            })

    result = {
        "version": "v5-sequential-width1-v1",
        "stop_reason": stop_reason,
        "source_reference_energy_hartree": source_reference,
        "final_energy_hartree": runtime.energy_hartree,
        "actual_cumulative_energy_increase_hartree": runtime.energy_hartree - source_reference,
        "exact_attempts": exact_attempts,
        "accepted_rounds": store.latest().round_index,
        "final_checkpoint_digest": store.latest().checkpoint_digest,
        "trajectory": trajectory,
    }
    result["result_digest"] = hashlib.sha256(canonical_json_bytes(result)).hexdigest()
    return result

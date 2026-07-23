"""V5-S7 deterministic, budgeted multi-trajectory search kernel."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import math
from typing import Any, Callable, Mapping, Sequence

from .identity import canonical_json_bytes
from .telemetry import ResourceSnapshot


MULTITRAJECTORY_VERSION = "v5-budgeted-multitrajectory-v1"
RESOURCE_FIELDS = (
    "cnot_count", "parameter_count", "total_depth", "cnot_depth", "logical_block_count",
)
ENDPOINTS = ("cnot_count", "parameter_count", "total_depth", "cnot_depth")


class V5MultiTrajectoryError(RuntimeError):
    """Raised when multi-trajectory execution cannot be trusted."""


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _require_id(name: str, value: str, prefix: str) -> None:
    digest = value.split(":", 1)[1] if value.startswith(prefix + ":") else ""
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise V5MultiTrajectoryError(f"{name} is invalid")


@dataclass(frozen=True)
class TrajectoryState:
    path_id: str
    state_preparation_id: str
    problem_id: str
    checkpoint_digest: str
    cumulative_energy_increase_hartree: float
    resources: ResourceSnapshot
    candidate_history: tuple[str, ...]
    diversity_key: str

    def __post_init__(self) -> None:
        _require_id("path ID", self.path_id, "path-v5")
        _require_id("StatePreparationID", self.state_preparation_id, "state-v1")
        _require_id("ProblemID", self.problem_id, "problem-v1")
        if (
            len(self.checkpoint_digest) != 64
            or any(character not in "0123456789abcdef" for character in self.checkpoint_digest)
            or not math.isfinite(self.cumulative_energy_increase_hartree)
        ):
            raise V5MultiTrajectoryError("trajectory checkpoint or energy is invalid")
        if not self.diversity_key:
            raise V5MultiTrajectoryError("trajectory diversity key is empty")


@dataclass(frozen=True)
class ExpansionProposal:
    proposal_id: str
    parent_path_id: str
    candidate_id: str
    exact_task_id: str
    proposed_state_preparation_id: str
    endpoint: str
    screening_rank: int
    predicted_loss_hartree: float

    @classmethod
    def create(
        cls,
        *,
        parent_path_id: str,
        candidate_id: str,
        exact_task_payload: Mapping[str, Any],
        proposed_state_preparation_id: str,
        endpoint: str,
        screening_rank: int,
        predicted_loss_hartree: float,
    ) -> "ExpansionProposal":
        exact_task_id = "exact-task-v5:" + _digest(exact_task_payload)
        payload = {
            "parent_path_id": parent_path_id,
            "candidate_id": candidate_id,
            "exact_task_id": exact_task_id,
            "proposed_state_preparation_id": proposed_state_preparation_id,
            "endpoint": endpoint,
            "screening_rank": screening_rank,
            "predicted_loss_hartree": predicted_loss_hartree,
        }
        return cls("proposal-v5:" + _digest(payload), **payload)

    def __post_init__(self) -> None:
        _require_id("proposal ID", self.proposal_id, "proposal-v5")
        _require_id("parent path ID", self.parent_path_id, "path-v5")
        _require_id("exact task ID", self.exact_task_id, "exact-task-v5")
        _require_id("proposed StatePreparationID", self.proposed_state_preparation_id, "state-v1")
        if (
            not self.candidate_id
            or self.endpoint not in ENDPOINTS
            or not isinstance(self.screening_rank, int)
            or self.screening_rank < 0
            or not math.isfinite(self.predicted_loss_hartree)
            or self.predicted_loss_hartree < -1e-12
        ):
            raise V5MultiTrajectoryError("expansion proposal is invalid")
        payload = {
            "parent_path_id": self.parent_path_id,
            "candidate_id": self.candidate_id,
            "exact_task_id": self.exact_task_id,
            "proposed_state_preparation_id": self.proposed_state_preparation_id,
            "endpoint": self.endpoint,
            "screening_rank": self.screening_rank,
            "predicted_loss_hartree": self.predicted_loss_hartree,
        }
        if self.proposal_id != "proposal-v5:" + _digest(payload):
            raise V5MultiTrajectoryError("proposal ID does not bind proposal content")


@dataclass(frozen=True)
class ExpansionOutcome:
    proposal_id: str
    accepted: bool
    final_state_preparation_id: str | None
    checkpoint_digest: str | None
    cumulative_energy_increase_hartree: float | None
    resources: ResourceSnapshot | None
    diversity_key: str | None
    work: dict[str, int]
    rejection_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_id("outcome proposal ID", self.proposal_id, "proposal-v5")
        if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in self.work.values()):
            raise V5MultiTrajectoryError("expansion outcome work is invalid")
        complete = (
            self.final_state_preparation_id is not None
            and self.checkpoint_digest is not None
            and self.cumulative_energy_increase_hartree is not None
            and self.resources is not None
            and self.diversity_key is not None
        )
        if self.accepted != complete or (self.accepted and self.rejection_reasons):
            raise V5MultiTrajectoryError("accepted expansion evidence is incomplete")
        if not self.accepted and not self.rejection_reasons:
            raise V5MultiTrajectoryError("rejected expansion requires an explicit reason")
        if self.work.get("exact_vqe_attempts") != 1:
            raise V5MultiTrajectoryError("each exact executor outcome must count one exact VQE attempt")
        if self.accepted:
            _require_id("final StatePreparationID", str(self.final_state_preparation_id), "state-v1")
            if len(str(self.checkpoint_digest)) != 64 or not math.isfinite(float(self.cumulative_energy_increase_hartree)):
                raise V5MultiTrajectoryError("accepted expansion state is invalid")


@dataclass(frozen=True)
class MultiTrajectoryConfig:
    width: int
    top_k_per_parent: int
    maximum_rounds: int
    maximum_exact_attempts: int
    endpoint_quota: int = 1
    cumulative_energy_budget_hartree: float = 1e-4

    def validate(self) -> None:
        integers = (
            self.width, self.top_k_per_parent, self.maximum_rounds,
            self.maximum_exact_attempts, self.endpoint_quota,
        )
        if any(not isinstance(value, int) or value <= 0 for value in integers):
            raise V5MultiTrajectoryError("multi-trajectory integer budgets must be positive")
        if self.width not in (1, 2, 4, 8):
            raise V5MultiTrajectoryError("width must be one of the preregistered values {1,2,4,8}")
        if not math.isfinite(self.cumulative_energy_budget_hartree) or self.cumulative_energy_budget_hartree < 0:
            raise V5MultiTrajectoryError("multi-trajectory energy budget is invalid")


CatalogBuilder = Callable[[TrajectoryState], Sequence[ExpansionProposal]]
ExactExecutor = Callable[[ExpansionProposal, TrajectoryState, int], ExpansionOutcome]


def _proposal_key(proposal: ExpansionProposal) -> tuple[Any, ...]:
    return (
        proposal.screening_rank,
        ENDPOINTS.index(proposal.endpoint),
        proposal.predicted_loss_hartree,
        proposal.candidate_id,
        proposal.parent_path_id,
        proposal.proposal_id,
    )


def _resource_values(state: TrajectoryState) -> tuple[int, ...]:
    return tuple(int(getattr(state.resources, field)) for field in RESOURCE_FIELDS)


def _dominates_resources(left: TrajectoryState, right: TrajectoryState) -> bool:
    a, b = _resource_values(left), _resource_values(right)
    return all(x <= y for x, y in zip(a, b)) and any(x < y for x, y in zip(a, b))


def _winner_key(state: TrajectoryState) -> tuple[Any, ...]:
    return (
        state.resources.cnot_count,
        state.resources.parameter_count,
        state.resources.total_depth,
        state.resources.cnot_depth,
        state.cumulative_energy_increase_hartree,
        state.path_id,
    )


def _select_beam(states: Sequence[TrajectoryState], config: MultiTrajectoryConfig) -> list[TrajectoryState]:
    by_state: dict[tuple[str, str], TrajectoryState] = {}
    for state in states:
        key = (state.problem_id, state.state_preparation_id)
        incumbent = by_state.get(key)
        if incumbent is None or _winner_key(state) < _winner_key(incumbent):
            by_state[key] = state
    unique = list(by_state.values())
    pareto = _nondominated(unique)
    selected: list[TrajectoryState] = []
    seen_paths: set[str] = set()
    seen_diversity: set[str] = set()
    for endpoint in ENDPOINTS:
        ranked = sorted(
            pareto,
            key=lambda state, endpoint=endpoint: (
                getattr(state.resources, endpoint), _winner_key(state)
            ),
        )
        taken = 0
        for state in ranked:
            if taken >= config.endpoint_quota or len(selected) >= config.width:
                break
            if state.path_id not in seen_paths and state.diversity_key not in seen_diversity:
                selected.append(state)
                seen_paths.add(state.path_id)
                seen_diversity.add(state.diversity_key)
                taken += 1
    for state in sorted(pareto, key=_winner_key):
        if len(selected) >= config.width:
            break
        if state.path_id not in seen_paths:
            selected.append(state)
            seen_paths.add(state.path_id)
    return selected


def _nondominated(states: Sequence[TrajectoryState]) -> list[TrajectoryState]:
    return sorted(
        [
            state for state in states
            if not any(_dominates_resources(other, state) for other in states if other is not state)
        ],
        key=_winner_key,
    )


def run_multitrajectory(
    source: TrajectoryState,
    *,
    catalog_builder: CatalogBuilder,
    exact_executor: ExactExecutor,
    config: MultiTrajectoryConfig,
) -> dict[str, Any]:
    """Expand frozen per-round queues with global exact-task/state deduplication."""

    config.validate()
    active = [source]
    all_states = [source]
    exact_tasks_seen: set[str] = set()
    proposed_states_seen: set[tuple[str, str]] = {
        (source.problem_id, source.state_preparation_id)
    }
    final_states_seen: set[tuple[str, str]] = {(source.problem_id, source.state_preparation_id)}
    exact_attempts = 0
    aggregate_work: dict[str, int] = {}
    trajectory: list[dict[str, Any]] = []
    stop_reason = "maximum-rounds"

    for round_index in range(1, config.maximum_rounds + 1):
        frozen: list[ExpansionProposal] = []
        duplicate_tasks = 0
        for parent in sorted(active, key=lambda state: state.path_id):
            proposals = list(catalog_builder(parent))
            if any(proposal.parent_path_id != parent.path_id for proposal in proposals):
                raise V5MultiTrajectoryError("catalog proposal is bound to a different parent")
            ordered = sorted(proposals, key=_proposal_key)[: config.top_k_per_parent]
            frozen.extend(ordered)
        frozen = sorted(frozen, key=_proposal_key)
        unique_tasks: list[ExpansionProposal] = []
        round_seen: set[str] = set()
        round_states_seen: set[tuple[str, str]] = set()
        for proposal in frozen:
            parent_problem = next(
                state.problem_id for state in active if state.path_id == proposal.parent_path_id
            )
            proposed_key = (parent_problem, proposal.proposed_state_preparation_id)
            if (
                proposal.exact_task_id in exact_tasks_seen
                or proposal.exact_task_id in round_seen
                or proposed_key in proposed_states_seen
                or proposed_key in round_states_seen
            ):
                duplicate_tasks += 1
                continue
            round_seen.add(proposal.exact_task_id)
            round_states_seen.add(proposed_key)
            unique_tasks.append(proposal)
        if not unique_tasks:
            stop_reason = "no-new-exact-task"
            break

        parent_by_id = {state.path_id: state for state in active}
        accepted: list[TrajectoryState] = []
        attempts: list[dict[str, Any]] = []
        for proposal in unique_tasks:
            if exact_attempts >= config.maximum_exact_attempts:
                stop_reason = "maximum-exact-attempts"
                break
            exact_attempts += 1
            exact_tasks_seen.add(proposal.exact_task_id)
            parent = parent_by_id[proposal.parent_path_id]
            proposed_states_seen.add(
                (parent.problem_id, proposal.proposed_state_preparation_id)
            )
            outcome = exact_executor(proposal, parent, exact_attempts)
            if outcome.proposal_id != proposal.proposal_id:
                raise V5MultiTrajectoryError("exact executor returned a different proposal identity")
            if outcome.resources is not None and outcome.resources.counter_version != source.resources.counter_version:
                raise V5MultiTrajectoryError("resource counter version changed inside multi-trajectory search")
            for name, value in outcome.work.items():
                aggregate_work[name] = aggregate_work.get(name, 0) + value
            record = {
                "proposal_id": proposal.proposal_id,
                "candidate_id": proposal.candidate_id,
                "parent_path_id": parent.path_id,
                "exact_task_id": proposal.exact_task_id,
                "accepted": outcome.accepted,
                "rejection_reasons": list(outcome.rejection_reasons),
                "work": dict(outcome.work),
            }
            if outcome.accepted:
                assert outcome.final_state_preparation_id is not None
                assert outcome.resources is not None
                assert outcome.cumulative_energy_increase_hartree is not None
                if outcome.cumulative_energy_increase_hartree > config.cumulative_energy_budget_hartree:
                    raise V5MultiTrajectoryError("executor accepted a state outside the cumulative energy budget")
                path_payload = {
                    "parent_path_id": parent.path_id,
                    "candidate_id": proposal.candidate_id,
                    "final_state_preparation_id": outcome.final_state_preparation_id,
                }
                child = TrajectoryState(
                    "path-v5:" + _digest(path_payload),
                    outcome.final_state_preparation_id,
                    parent.problem_id,
                    str(outcome.checkpoint_digest),
                    outcome.cumulative_energy_increase_hartree,
                    outcome.resources,
                    parent.candidate_history + (proposal.candidate_id,),
                    str(outcome.diversity_key),
                )
                state_key = (child.problem_id, child.state_preparation_id)
                record["final_state_duplicate"] = state_key in final_states_seen
                if state_key not in final_states_seen:
                    final_states_seen.add(state_key)
                    proposed_states_seen.add(state_key)
                    accepted.append(child)
                    all_states.append(child)
                record["child_path_id"] = child.path_id
            attempts.append(record)
        if not accepted:
            if stop_reason != "maximum-exact-attempts":
                stop_reason = "no-accepted-expansion"
            trajectory.append({
                "round_index": round_index,
                "frozen_proposal_ids": [proposal.proposal_id for proposal in frozen],
                "unique_exact_task_ids": [proposal.exact_task_id for proposal in unique_tasks],
                "duplicate_exact_tasks_skipped": duplicate_tasks,
                "attempts": attempts,
                "active_path_ids_after": [],
            })
            break
        active = _select_beam(accepted, config)
        trajectory.append({
            "round_index": round_index,
            "frozen_proposal_ids": [proposal.proposal_id for proposal in frozen],
            "unique_exact_task_ids": [proposal.exact_task_id for proposal in unique_tasks],
            "duplicate_exact_tasks_skipped": duplicate_tasks,
            "attempts": attempts,
            "active_path_ids_after": [state.path_id for state in active],
        })
        if exact_attempts >= config.maximum_exact_attempts:
            stop_reason = "maximum-exact-attempts"
            break

    endpoints = _nondominated(all_states[1:] or [source])
    winner = min(endpoints, key=_winner_key)
    result = {
        "version": MULTITRAJECTORY_VERSION,
        "config": asdict(config),
        "stop_reason": stop_reason,
        "winner_path_id": winner.path_id,
        "winner_state_preparation_id": winner.state_preparation_id,
        "winner_candidate_history": list(winner.candidate_history),
        "winner_resources": asdict(winner.resources),
        "winner_cumulative_energy_increase_hartree": winner.cumulative_energy_increase_hartree,
        "frontier_path_ids": [state.path_id for state in endpoints],
        "exact_attempts": exact_attempts,
        "unique_exact_tasks": len(exact_tasks_seen),
        "unique_proposed_states": len(proposed_states_seen),
        "unique_final_states": len(final_states_seen),
        "aggregate_work": aggregate_work,
        "trajectory": trajectory,
        "winner_rule": (
            "accepted resource nondominance; minimum CNOT, parameters, total depth, "
            "CNOT depth, actual source-relative energy, canonical path ID"
        ),
        "diversity_rule": (
            "endpoint-quota first pass requires distinct diversity keys; deterministic "
            "resource-ranked fill may reuse a diversity key only to fill remaining width"
        ),
        "paper_measurement_cost": None,
    }
    result["result_digest"] = _digest(result)
    return result

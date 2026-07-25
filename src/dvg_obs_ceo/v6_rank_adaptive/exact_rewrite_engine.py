"""Deterministic, bounded, evidence-registered exact rewrite engine for V6."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import struct
import sys
from typing import Any, Iterable, Mapping, Sequence

from dvg_obs_ceo.artifact_io import atomic_write_new_json
from dvg_obs_ceo.baseline import ROOT, _load_upstream
from dvg_obs_ceo.block_ir import DVGBlock, recover_dvg_blocks
from dvg_obs_ceo.identity import canonical_json_bytes, sha256_hex
from dvg_obs_ceo.resources import (
    AnsatzStructure,
    FullCircuitResources,
    evaluate_full_circuit_resources,
    paper_era_backend,
)
from dvg_obs_ceo.v5_1_exact_fusion import (
    ExactFusionCandidate,
    ExactFusionError,
    apply_exact_fusion,
    enumerate_exact_fusions,
)

from .evidence import (
    ContextScope,
    EvidenceRecord,
    EvidenceStatus,
    EvidenceStrength,
    EvidenceType,
    SemanticScope,
)
from .math_evidence import ExactPauliOperator, exact_operators_commute


DEFAULT_SOURCE = (
    ROOT / "artifacts/v4.1/multisystem/h6-1.5/summary.json"
)
DEFAULT_OUTPUT = ROOT / "artifacts/v6/s6/exact-rewrite-trace-v1.json"
ENGINE_VERSION = "v6-bounded-exact-rewrite-engine-v1"


class ExactRewriteEngineError(RuntimeError):
    """Raised when rewrite evidence, state, or bounded execution is invalid."""


class RewriteRuleKind(str, Enum):
    ZERO_COORDINATE = "ZERO_COORDINATE"
    IDENTICAL_FUSION = "IDENTICAL_FUSION"
    IDENTICAL_CANCELLATION = "IDENTICAL_CANCELLATION"
    OVP_MVP_ABSORPTION = "OVP_MVP_ABSORPTION"


class RewriteRuleStatus(str, Enum):
    VERIFIED = "VERIFIED"
    PROPOSED = "PROPOSED"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class RewriteRuleDefinition:
    rule_id: str
    kind: RewriteRuleKind
    proof_method_id: str
    evidence_id: str | None
    maximum_corridor_blocks: int
    status: RewriteRuleStatus

    def __post_init__(self) -> None:
        if not self.rule_id.startswith("v6-rewrite:"):
            raise ExactRewriteEngineError("rewrite rule ID must be versioned")
        if not self.proof_method_id or self.maximum_corridor_blocks < 0:
            raise ExactRewriteEngineError(
                "rewrite proof and corridor bound must be explicit"
            )
        if self.status is RewriteRuleStatus.VERIFIED:
            if (
                self.evidence_id is None
                or not self.evidence_id.startswith("v6-evidence-v1:")
            ):
                raise ExactRewriteEngineError(
                    "verified rewrite rule requires evidence"
                )
        elif self.evidence_id is not None:
            raise ExactRewriteEngineError(
                "unverified rewrite rule cannot bind executable evidence"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "kind": self.kind.value,
            "proof_method_id": self.proof_method_id,
            "evidence_id": self.evidence_id,
            "maximum_corridor_blocks": self.maximum_corridor_blocks,
            "status": self.status.value,
        }


class ExactRewriteRegistry:
    """Construction-only mutable registry, frozen before enumeration."""

    def __init__(self) -> None:
        self._rules: dict[str, RewriteRuleDefinition] = {}
        self._frozen = False

    def register(self, definition: RewriteRuleDefinition) -> None:
        if self._frozen:
            raise ExactRewriteEngineError("rewrite registry is frozen")
        if definition.rule_id in self._rules:
            raise ExactRewriteEngineError("duplicate rewrite rule ID")
        if any(
            item.kind is definition.kind for item in self._rules.values()
        ):
            raise ExactRewriteEngineError("duplicate rewrite rule kind")
        self._rules[definition.rule_id] = definition

    def freeze(self) -> str:
        self._frozen = True
        return self.registry_digest

    @property
    def registry_digest(self) -> str:
        return sha256_hex(
            [self._rules[key].to_dict() for key in sorted(self._rules)]
        )

    def executable_rules(self) -> tuple[RewriteRuleDefinition, ...]:
        if not self._frozen:
            raise ExactRewriteEngineError(
                "rewrite enumeration requires a frozen registry"
            )
        rules = tuple(self._rules[key] for key in sorted(self._rules))
        if any(
            item.status is not RewriteRuleStatus.VERIFIED for item in rules
        ):
            raise ExactRewriteEngineError(
                "registry contains a non-verified executable rule"
            )
        return rules

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0.0",
            "artifact_kind": "v6-exact-rewrite-registry",
            "frozen": self._frozen,
            "registry_digest": self.registry_digest,
            "rules": [
                self._rules[key].to_dict() for key in sorted(self._rules)
            ],
        }


def _rule_evidence(
    kind: RewriteRuleKind,
    method_id: str,
    premises: Sequence[str],
) -> EvidenceRecord:
    details = {
        "rule_kind": kind.value,
        "premises": list(premises),
        "claim": (
            "The rewrite is familywise exact only when every enumerated "
            "premise is established for the concrete proposal."
        ),
    }
    return EvidenceRecord(
        evidence_type=EvidenceType.CONTEXTUAL_REWRITE,
        status=EvidenceStatus.PASSED,
        strength=EvidenceStrength.SYMBOLICALLY_PROVEN,
        semantic_scope=SemanticScope.FAMILYWISE_UNITARY,
        context_scope=ContextScope.ARBITRARY_CIRCUIT_CONTEXT,
        method_id=method_id,
        source_semantic_id=f"v6-rewrite-source:{kind.value}",
        target_semantic_id=f"v6-rewrite-target:{kind.value}",
        input_digest=sha256_hex(details["premises"]),
        output_digest=sha256_hex(details),
        details=details,
    )


def default_registry(
    *,
    maximum_corridor_blocks: int = 16,
    definition_order: Sequence[RewriteRuleKind] | None = None,
) -> tuple[ExactRewriteRegistry, tuple[EvidenceRecord, ...]]:
    if maximum_corridor_blocks < 0:
        raise ExactRewriteEngineError("corridor bound must be non-negative")
    specifications = {
        RewriteRuleKind.ZERO_COORDINATE: (
            "v6-zero-coordinate-identity-proof-v1",
            ("every block coordinate is exactly binary-float zero",),
        ),
        RewriteRuleKind.IDENTICAL_FUSION: (
            "v6-identical-generator-fusion-proof-v1",
            (
                "ordered generator semantics are identical",
                "generators within the repeated block commute exactly",
                "intervening blocks have disjoint support",
                "the corridor is within the frozen bound",
            ),
        ),
        RewriteRuleKind.IDENTICAL_CANCELLATION: (
            "v6-identical-inverse-cancellation-proof-v1",
            (
                "identical fusion premises hold",
                "paired coordinates are exact additive inverses",
            ),
        ),
        RewriteRuleKind.OVP_MVP_ABSORPTION: (
            "v6-registered-ovp-mvp-absorption-proof-v1",
            (
                "registered signed OVP parent relation holds",
                "OVP and MVP parent generators commute",
                "intervening blocks have disjoint support",
                "the corridor is within the frozen bound",
            ),
        ),
    }
    order = tuple(definition_order or tuple(RewriteRuleKind))
    if set(order) != set(RewriteRuleKind) or len(order) != len(
        RewriteRuleKind
    ):
        raise ExactRewriteEngineError(
            "default registry order must contain every rule exactly once"
        )
    evidence_by_kind = {
        kind: _rule_evidence(kind, *specifications[kind])
        for kind in RewriteRuleKind
    }
    registry = ExactRewriteRegistry()
    for kind in order:
        evidence = evidence_by_kind[kind]
        registry.register(
            RewriteRuleDefinition(
                rule_id=f"v6-rewrite:{kind.value.lower()}-v1",
                kind=kind,
                proof_method_id=evidence.method_id,
                evidence_id=evidence.evidence_id,
                maximum_corridor_blocks=maximum_corridor_blocks,
                status=RewriteRuleStatus.VERIFIED,
            )
        )
    registry.freeze()
    return registry, tuple(
        evidence_by_kind[kind] for kind in sorted(
            RewriteRuleKind,
            key=lambda item: item.value,
        )
    )


@dataclass(frozen=True)
class RewriteLimits:
    maximum_steps: int = 16
    maximum_states: int = 17
    maximum_candidates_per_state: int = 128

    def __post_init__(self) -> None:
        if (
            self.maximum_steps < 0
            or self.maximum_states < 1
            or self.maximum_candidates_per_state < 1
            or self.maximum_states < self.maximum_steps + 1
        ):
            raise ExactRewriteEngineError(
                "rewrite limits are inconsistent or non-positive"
            )

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass(frozen=True)
class RewriteProposal:
    proposal_id: str
    rule_id: str
    kind: RewriteRuleKind
    source_state_digest: str
    payload: Mapping[str, Any]
    application: Any

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "rule_id": self.rule_id,
            "kind": self.kind.value,
            "source_state_digest": self.source_state_digest,
            "payload": dict(self.payload),
        }


def _float_hex(value: float) -> str:
    number = 0.0 if float(value) == 0.0 else float(value)
    if not math.isfinite(number):
        raise ExactRewriteEngineError("rewrite state coefficient is not finite")
    return struct.pack(">d", number).hex()


def state_digest(structure: AnsatzStructure) -> str:
    return sha256_hex(
        {
            "indices": list(structure.indices),
            "coefficient_float64_hex": [
                _float_hex(value) for value in structure.coefficients
            ],
            "iteration_counts": list(
                structure.cumulative_parameter_counts
            ),
        }
    )


def _block_signature(block: DVGBlock) -> tuple[Any, ...]:
    return (
        block.family,
        block.pool_indices,
        block.generator_digests,
        block.support_qubits,
        block.normalization,
        block.orientation,
        block.circuit_implementation_id,
    )


def _small_exact_fraction(value: float) -> Fraction:
    if not math.isfinite(value):
        raise ExactRewriteEngineError(
            "generator coefficient is not finite"
        )
    result = Fraction(value).limit_denominator(1 << 20)
    if float(result) != value:
        raise ExactRewriteEngineError(
            "generator coefficient is not an exact small rational"
        )
    return result


def _exact_pool_operator(pool: Any, index: int) -> ExactPauliOperator:
    terms = getattr(pool.get_q_op(index), "terms", None)
    if not isinstance(terms, dict):
        raise ExactRewriteEngineError(
            "pool generator lacks canonical Pauli terms"
        )
    return ExactPauliOperator.create(
        {
            tuple(
                sorted(
                    (int(qubit), str(pauli))
                    for qubit, pauli in word
                )
            ): (
                _small_exact_fraction(complex(coefficient).real),
                _small_exact_fraction(complex(coefficient).imag),
            )
            for word, coefficient in terms.items()
        }
    )


def _block_generators_commute_exactly(pool: Any, block: DVGBlock) -> bool:
    generators = tuple(
        _exact_pool_operator(pool, index)
        for index in block.pool_indices
    )
    return all(
        exact_operators_commute(left, right)
        for position, left in enumerate(generators)
        for right in generators[position + 1 :]
    )


def _proposal(
    *,
    rule: RewriteRuleDefinition,
    kind: RewriteRuleKind,
    source_digest: str,
    payload: Mapping[str, Any],
    application: Any,
) -> RewriteProposal:
    semantic = {
        "engine_version": ENGINE_VERSION,
        "rule_id": rule.rule_id,
        "kind": kind.value,
        "source_state_digest": source_digest,
        "payload": dict(payload),
    }
    return RewriteProposal(
        proposal_id="v6-rewrite-proposal:" + sha256_hex(semantic),
        rule_id=rule.rule_id,
        kind=kind,
        source_state_digest=source_digest,
        payload=dict(payload),
        application=application,
    )


def enumerate_proposals(
    pool: Any,
    source: AnsatzStructure,
    registry: ExactRewriteRegistry,
) -> tuple[RewriteProposal, ...]:
    blocks = recover_dvg_blocks(
        pool,
        source.indices,
        source.coefficients,
        source.cumulative_parameter_counts,
    )
    digest = state_digest(source)
    proposals: list[RewriteProposal] = []
    commutation_cache: dict[tuple[Any, ...], bool] = {}
    for rule in registry.executable_rules():
        if rule.kind is RewriteRuleKind.ZERO_COORDINATE:
            for block in blocks:
                if block.coefficients and all(
                    value == 0.0 for value in block.coefficients
                ):
                    proposals.append(
                        _proposal(
                            rule=rule,
                            kind=rule.kind,
                            source_digest=digest,
                            payload={
                                "block_id": block.block_id,
                                "positions": list(block.ansatz_positions),
                            },
                            application=block,
                        )
                    )
        elif rule.kind in {
            RewriteRuleKind.IDENTICAL_FUSION,
            RewriteRuleKind.IDENTICAL_CANCELLATION,
        }:
            for left_index, left in enumerate(blocks):
                for right_index in range(left_index + 1, len(blocks)):
                    right = blocks[right_index]
                    corridor = blocks[left_index + 1 : right_index]
                    if len(corridor) > rule.maximum_corridor_blocks:
                        continue
                    if _block_signature(left) != _block_signature(right):
                        continue
                    signature = _block_signature(left)
                    if signature not in commutation_cache:
                        commutation_cache[signature] = (
                            _block_generators_commute_exactly(pool, left)
                        )
                    if not commutation_cache[signature]:
                        continue
                    if any(
                        set(left.support_qubits) & set(item.support_qubits)
                        for item in corridor
                    ):
                        continue
                    cancellation = all(
                        left_value == -right_value
                        for left_value, right_value in zip(
                            left.coefficients,
                            right.coefficients,
                        )
                    )
                    expected_kind = (
                        RewriteRuleKind.IDENTICAL_CANCELLATION
                        if cancellation
                        else RewriteRuleKind.IDENTICAL_FUSION
                    )
                    if rule.kind is not expected_kind:
                        continue
                    proposals.append(
                        _proposal(
                            rule=rule,
                            kind=expected_kind,
                            source_digest=digest,
                            payload={
                                "left_block_id": left.block_id,
                                "right_block_id": right.block_id,
                                "left_positions": list(
                                    left.ansatz_positions
                                ),
                                "right_positions": list(
                                    right.ansatz_positions
                                ),
                                "intervening_block_ids": [
                                    item.block_id for item in corridor
                                ],
                            },
                            application=(left, right),
                        )
                    )
        elif rule.kind is RewriteRuleKind.OVP_MVP_ABSORPTION:
            try:
                fusions = enumerate_exact_fusions(pool, blocks)
            except ExactFusionError as error:
                raise ExactRewriteEngineError(
                    "V5.1 fusion enumeration failed closed"
                ) from error
            for candidate in fusions:
                if (
                    len(candidate.intervening_block_ids)
                    > rule.maximum_corridor_blocks
                ):
                    continue
                proposals.append(
                    _proposal(
                        rule=rule,
                        kind=rule.kind,
                        source_digest=digest,
                        payload={
                            "legacy_candidate_id": candidate.candidate_id,
                            "ovp_block_id": candidate.ovp_block_id,
                            "mvp_block_id": candidate.mvp_block_id,
                            "intervening_block_ids": list(
                                candidate.intervening_block_ids
                            ),
                        },
                        application=candidate,
                    )
                )
    by_id: dict[str, RewriteProposal] = {}
    for item in proposals:
        if item.proposal_id in by_id and by_id[item.proposal_id] != item:
            raise ExactRewriteEngineError(
                "rewrite proposal ID collision"
            )
        by_id[item.proposal_id] = item
    return tuple(by_id[key] for key in sorted(by_id))


def _remove_positions(
    source: AnsatzStructure,
    positions: Iterable[int],
    removal_iterations: Sequence[int],
    replacement_coefficients: Mapping[int, float] | None = None,
) -> AnsatzStructure:
    removed = set(int(value) for value in positions)
    coefficients = list(source.coefficients)
    for position, value in (replacement_coefficients or {}).items():
        coefficients[int(position)] = float(value)
    indices = tuple(
        value
        for position, value in enumerate(source.indices)
        if position not in removed
    )
    target_coefficients = tuple(
        value
        for position, value in enumerate(coefficients)
        if position not in removed
    )
    counts = tuple(
        count
        - sum(
            removal_iteration <= iteration
            for removal_iteration in removal_iterations
        )
        for iteration, count in enumerate(
            source.cumulative_parameter_counts,
            1,
        )
    )
    return AnsatzStructure.create(indices, target_coefficients, counts)


def apply_proposal(
    pool: Any,
    source: AnsatzStructure,
    proposal: RewriteProposal,
) -> AnsatzStructure:
    if proposal.source_state_digest != state_digest(source):
        raise ExactRewriteEngineError("rewrite proposal is stale")
    if proposal.kind is RewriteRuleKind.ZERO_COORDINATE:
        block: DVGBlock = proposal.application
        if any(value != 0.0 for value in block.coefficients):
            raise ExactRewriteEngineError(
                "zero-coordinate premise no longer holds"
            )
        return _remove_positions(
            source,
            block.ansatz_positions,
            (block.selection_iterations[0],) * len(block.ansatz_positions),
        )
    if proposal.kind in {
        RewriteRuleKind.IDENTICAL_FUSION,
        RewriteRuleKind.IDENTICAL_CANCELLATION,
    }:
        left, right = proposal.application
        if _block_signature(left) != _block_signature(right):
            raise ExactRewriteEngineError(
                "identical-block premise no longer holds"
            )
        if proposal.kind is RewriteRuleKind.IDENTICAL_CANCELLATION:
            if not all(
                left_value == -right_value
                for left_value, right_value in zip(
                    left.coefficients,
                    right.coefficients,
                )
            ):
                raise ExactRewriteEngineError(
                    "exact cancellation premise no longer holds"
                )
            return _remove_positions(
                source,
                (*left.ansatz_positions, *right.ansatz_positions),
                (
                    *left.selection_iterations,
                    *right.selection_iterations,
                ),
            )
        replacements = {
            right_position: left_value + right_value
            for right_position, left_value, right_value in zip(
                right.ansatz_positions,
                left.coefficients,
                right.coefficients,
            )
        }
        return _remove_positions(
            source,
            left.ansatz_positions,
            left.selection_iterations,
            replacements,
        )
    if proposal.kind is RewriteRuleKind.OVP_MVP_ABSORPTION:
        candidate: ExactFusionCandidate = proposal.application
        try:
            return apply_exact_fusion(pool, source, candidate)
        except ExactFusionError as error:
            raise ExactRewriteEngineError(
                "registered OVP-MVP absorption failed closed"
            ) from error
    raise ExactRewriteEngineError("unknown rewrite proposal kind")


def _resources(
    pool: Any,
    structure: AnsatzStructure,
) -> tuple[FullCircuitResources, FullCircuitResources]:
    backend = paper_era_backend()
    physical = evaluate_full_circuit_resources(pool, structure, backend)
    structural = evaluate_full_circuit_resources(
        pool,
        structure,
        backend,
        coefficient_policy="deterministic-structural",
    )
    return physical, structural


def _snapshot(resources: FullCircuitResources) -> dict[str, Any]:
    return asdict(resources.snapshot)


def _resource_decision(
    before: FullCircuitResources,
    after: FullCircuitResources,
    structural_after: FullCircuitResources,
) -> tuple[bool, dict[str, int], tuple[str, ...]]:
    before_value = _snapshot(before)
    after_value = _snapshot(after)
    fields = (
        "parameter_count",
        "logical_block_count",
        "cnot_count",
        "cnot_depth",
        "total_depth",
    )
    delta = {
        field: int(after_value[field] - before_value[field])
        for field in fields
    }
    reasons = []
    if after.snapshot != structural_after.snapshot:
        reasons.append("coefficient-dependent-resource-count")
    for field in ("cnot_count", "cnot_depth", "total_depth"):
        if delta[field] > 0:
            reasons.append(f"{field}-regression")
    if not any(
        delta[field] < 0
        for field in (
            "logical_block_count",
            "cnot_count",
            "cnot_depth",
            "total_depth",
        )
    ):
        reasons.append("no-strict-physical-circuit-gain")
    return not reasons, delta, tuple(sorted(reasons))


@dataclass(frozen=True)
class RewriteRunResult:
    source: AnsatzStructure
    target: AnsatzStructure
    source_resources: Mapping[str, Any]
    target_resources: Mapping[str, Any]
    registry: Mapping[str, Any]
    evidence: tuple[Mapping[str, Any], ...]
    limits: RewriteLimits
    trace: tuple[Mapping[str, Any], ...]
    stop_reason: str
    complete: bool
    work: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0.0",
            "artifact_kind": "v6-s6-exact-rewrite-run",
            "engine_version": ENGINE_VERSION,
            "source_state_digest": state_digest(self.source),
            "target_state_digest": state_digest(self.target),
            "source": {
                "indices": list(self.source.indices),
                "coefficient_float64_hex": [
                    _float_hex(value) for value in self.source.coefficients
                ],
                "iteration_counts": list(
                    self.source.cumulative_parameter_counts
                ),
                "resources": dict(self.source_resources),
            },
            "target": {
                "indices": list(self.target.indices),
                "coefficient_float64_hex": [
                    _float_hex(value) for value in self.target.coefficients
                ],
                "iteration_counts": list(
                    self.target.cumulative_parameter_counts
                ),
                "resources": dict(self.target_resources),
            },
            "registry": dict(self.registry),
            "evidence": [dict(item) for item in self.evidence],
            "limits": self.limits.to_dict(),
            "trace": [dict(item) for item in self.trace],
            "stop_reason": self.stop_reason,
            "complete": self.complete,
            "work": dict(self.work),
            "paper_measurement_cost": None,
            "claim_boundary": (
                "Exact registered rewrite and resource result only; zero "
                "energy evaluations do not mean zero search/recount work and "
                "do not establish a matched-work performance advantage."
            ),
        }


class ExactRewriteEngine:
    def __init__(
        self,
        registry: ExactRewriteRegistry,
        evidence: Sequence[EvidenceRecord],
        limits: RewriteLimits = RewriteLimits(),
    ) -> None:
        registry_rules = registry.executable_rules()
        evidence_ids = {item.evidence_id for item in evidence}
        if any(
            item.evidence_id not in evidence_ids for item in registry_rules
        ):
            raise ExactRewriteEngineError(
                "rewrite registry evidence inventory is incomplete"
            )
        self.registry = registry
        self.evidence = tuple(evidence)
        self.limits = limits

    def run(self, pool: Any, source: AnsatzStructure) -> RewriteRunResult:
        current = source
        current_physical, current_structural = _resources(pool, current)
        if current_physical.snapshot != current_structural.snapshot:
            raise ExactRewriteEngineError(
                "source physical and structural resources disagree"
            )
        source_resources = _snapshot(current_physical)
        trace: list[dict[str, Any]] = []
        seen = {state_digest(current)}
        work = {
            "rewrite_states": 1,
            "rewrite_proposals_generated": 0,
            "rewrite_proposals_verified": 0,
            "rewrite_proposals_accepted": 0,
            "rewrite_proposals_rejected": 0,
            "full_resource_recounts": 2,
            "energy_evaluations": 0,
            "statevector_evaluations": 0,
            "optimizer_starts": 0,
            "optimizer_iterations": 0,
            "paper_measurement_cost": None,
        }
        stop_reason = "SATURATED"
        complete = True
        for step in range(1, self.limits.maximum_steps + 1):
            proposals = enumerate_proposals(
                pool,
                current,
                self.registry,
            )
            work["rewrite_proposals_generated"] += len(proposals)
            truncated = (
                len(proposals)
                > self.limits.maximum_candidates_per_state
            )
            if truncated:
                proposals = proposals[
                    : self.limits.maximum_candidates_per_state
                ]
                complete = False
            if not proposals:
                stop_reason = "SATURATED"
                break
            evaluated = []
            for proposal in proposals:
                target = apply_proposal(pool, current, proposal)
                target_digest = state_digest(target)
                if target_digest in seen:
                    decision = {
                        **proposal.to_dict(),
                        "step": step,
                        "accepted": False,
                        "eligible": False,
                        "rejection_reasons": ["duplicate-state"],
                        "target_state_digest": target_digest,
                        "resource_delta": None,
                    }
                    trace.append(decision)
                    work["rewrite_proposals_rejected"] += 1
                    continue
                physical, structural = _resources(pool, target)
                work["full_resource_recounts"] += 2
                work["rewrite_proposals_verified"] += 1
                eligible, delta, reasons = _resource_decision(
                    current_physical,
                    physical,
                    structural,
                )
                record = {
                    **proposal.to_dict(),
                    "step": step,
                    "accepted": False,
                    "eligible": eligible,
                    "rejection_reasons": list(reasons),
                    "target_state_digest": target_digest,
                    "resource_delta": delta,
                    "target_resources": _snapshot(physical),
                }
                evaluated.append(
                    (
                        (
                            delta["cnot_count"],
                            delta["cnot_depth"],
                            delta["total_depth"],
                            delta["parameter_count"],
                            target_digest,
                            proposal.proposal_id,
                        ),
                        proposal,
                        target,
                        physical,
                        structural,
                        record,
                    )
                )
            eligible_items = [
                item for item in evaluated if item[-1]["eligible"]
            ]
            if not eligible_items:
                trace.extend(item[-1] for item in evaluated)
                work["rewrite_proposals_rejected"] += len(evaluated)
                stop_reason = (
                    "CANDIDATE_CAP_WITH_NO_ELIGIBLE"
                    if truncated
                    else "NO_RESOURCE_IMPROVING_REWRITE"
                )
                break
            winner = min(eligible_items, key=lambda item: item[0])
            for item in evaluated:
                record = item[-1]
                if item is winner:
                    record["accepted"] = True
                elif record["eligible"]:
                    record["rejection_reasons"] = [
                        "eligible-not-selected"
                    ]
                trace.append(record)
            work["rewrite_proposals_accepted"] += 1
            work["rewrite_proposals_rejected"] += len(evaluated) - 1
            _, _, current, current_physical, current_structural, _ = winner
            seen.add(state_digest(current))
            work["rewrite_states"] += 1
            if work["rewrite_states"] >= self.limits.maximum_states:
                stop_reason = "STATE_CAP"
                complete = False
                break
            if truncated:
                complete = False
        else:
            stop_reason = "STEP_CAP"
            complete = False
        return RewriteRunResult(
            source=source,
            target=current,
            source_resources=source_resources,
            target_resources=_snapshot(current_physical),
            registry=self.registry.to_dict(),
            evidence=tuple(item.to_dict() for item in self.evidence),
            limits=self.limits,
            trace=tuple(trace),
            stop_reason=stop_reason,
            complete=complete,
            work=work,
        )


def build_h6_report() -> dict[str, Any]:
    _, DVG_CEO, _, _ = _load_upstream()
    source_artifact = json.loads(DEFAULT_SOURCE.read_text(encoding="utf-8"))
    attempt = next(
        item
        for item in source_artifact["attempts"]
        if item["attempt_number"] == 1
    )
    if (
        attempt["transaction_status"] != "accepted"
        or attempt["fallback"] is not None
    ):
        raise ExactRewriteEngineError(
            "registered H6 source attempt is not the primary accepted path"
        )
    source = AnsatzStructure.create(
        attempt["frozen_sentinel"]["target_indices"],
        attempt["primary"]["coordinates"],
        attempt["frozen_sentinel"]["target_iteration_counts"],
    )
    registry, evidence = default_registry(maximum_corridor_blocks=16)
    engine = ExactRewriteEngine(
        registry,
        evidence,
        RewriteLimits(
            maximum_steps=8,
            maximum_states=9,
            maximum_candidates_per_state=64,
        ),
    )
    result = engine.run(DVG_CEO(n=12), source)
    report = {
        **result.to_dict(),
        "case_id": "h6-1.5",
        "development_only": True,
        "source_artifact": str(DEFAULT_SOURCE.relative_to(ROOT)),
        "source_artifact_sha256": hashlib.sha256(
            DEFAULT_SOURCE.read_bytes()
        ).hexdigest(),
    }
    report["report_digest"] = sha256_hex(report)
    return report


def main() -> None:
    try:
        report = build_h6_report()
        atomic_write_new_json(DEFAULT_OUTPUT, report)
    except (
        ExactRewriteEngineError,
        ExactFusionError,
        ImportError,
        KeyError,
        OSError,
        TypeError,
        ValueError,
    ) as error:
        print(f"V6 S6 exact rewrite failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    print(
        json.dumps(
            {
                "complete": report["complete"],
                "stop_reason": report["stop_reason"],
                "source_resources": report["source"]["resources"],
                "target_resources": report["target"]["resources"],
                "work": report["work"],
                "report_digest": report["report_digest"],
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()

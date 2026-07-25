"""Deterministic S7 rank-candidate catalog with native full-circuit recount."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import struct
import sys
from typing import Any, Mapping, Sequence

from dvg_obs_ceo.artifact_io import atomic_write_new_json
from dvg_obs_ceo.baseline import ROOT, _load_upstream
from dvg_obs_ceo.block_ir import DVGBlock, recover_dvg_blocks
from dvg_obs_ceo.identity import sha256_hex
from dvg_obs_ceo.resources import AnsatzStructure

from .evidence import (
    EvidenceRecord,
    EvidenceType,
    HumanClassification,
    NativeSynthesisScope,
    OptimizationRequirement,
    ResourceDeltaEvidence,
    ResourceVector,
    SemanticScope,
)
from .exact_rewrite_engine import state_digest
from .native_rank2_feasibility import (
    COUNTER_VERSION,
    NATIVE_SYNTHESIS_ID,
    TRANSITION_ID,
    _compose_checkpoint_circuit,
    _qasm_resources,
    derive_conditional_rotation,
)
from .transition_registry import (
    ParameterMapKind,
    TransitionDefinition,
    TransitionRegistry,
    TransitionStatus,
)


DEFAULT_SOURCE = ROOT / "artifacts/v6/s6/exact-rewrite-trace-v1.json"
DEFAULT_EVIDENCE = ROOT / "artifacts/v6/s5/native-rank2-feasibility-v1.json"
DEFAULT_OUTPUT = ROOT / "artifacts/v6/s7/rank-candidate-catalog-v1.json"
CATALOG_VERSION = "v6-rank-candidate-catalog-v1"
COMPILER_CONFIGURATION = (
    "uncompiled-barrier-preserving-paper-era-qasm-v1"
)


class RankCandidateCatalogError(RuntimeError):
    """Raised when S7 candidate evidence or recount is inconsistent."""


def _decode_float64(value: str) -> float:
    if (
        not isinstance(value, str)
        or len(value) != 16
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise RankCandidateCatalogError(
            "coefficient is not canonical float64 hexadecimal data"
        )
    return struct.unpack(">d", bytes.fromhex(value))[0]


def load_s6_source(path: Path = DEFAULT_SOURCE) -> AnsatzStructure:
    artifact = json.loads(path.read_text(encoding="utf-8"))
    if (
        artifact.get("artifact_kind") != "v6-s6-exact-rewrite-run"
        or artifact.get("complete") is not True
        or artifact.get("stop_reason") != "SATURATED"
    ):
        raise RankCandidateCatalogError(
            "S7 requires a complete saturated S6 source"
        )
    target = artifact["target"]
    structure = AnsatzStructure.create(
        target["indices"],
        [_decode_float64(value) for value in target["coefficient_float64_hex"]],
        target["iteration_counts"],
    )
    if state_digest(structure) != artifact["target_state_digest"]:
        raise RankCandidateCatalogError("S6 target state digest mismatch")
    return structure


def _transition_from_dict(value: Mapping[str, Any]) -> TransitionDefinition:
    return TransitionDefinition(
        transition_id=value["transition_id"],
        source_family=value["source_family"],
        target_family=value["target_family"],
        allowed_constituent_counts=tuple(value["allowed_constituent_counts"]),
        target_rank=int(value["target_rank"]),
        parameter_map_kind=ParameterMapKind(value["parameter_map_kind"]),
        parameter_map_id=value["parameter_map_id"],
        generator_relation_id=value["generator_relation_id"],
        native_synthesis_id=value["native_synthesis_id"],
        native_synthesis_scope=NativeSynthesisScope(
            value["native_synthesis_scope"]
        ),
        semantic_scope=SemanticScope(value["semantic_scope"]),
        status=TransitionStatus(value["status"]),
        evidence_ids=tuple(value["evidence_ids"]),
    )


def load_s5_registry(
    path: Path = DEFAULT_EVIDENCE,
) -> tuple[
    TransitionRegistry,
    dict[str, EvidenceRecord],
    dict[tuple[int, int], str],
]:
    artifact = json.loads(path.read_text(encoding="utf-8"))
    if artifact.get("decision") != "GO":
        raise RankCandidateCatalogError("S5 transition did not pass its gate")
    definitions = [
        _transition_from_dict(item)
        for item in artifact["transition_registry"]["transitions"]
    ]
    registry = TransitionRegistry.from_definitions(definitions)
    if (
        registry.registry_digest
        != artifact["transition_registry"]["registry_digest"]
    ):
        raise RankCandidateCatalogError("S5 transition registry digest mismatch")
    evidence = {
        item.evidence_id: item
        for item in (
            EvidenceRecord.from_dict(value)
            for value in artifact["evidence"]
        )
    }
    transition = registry.require_executable(TRANSITION_ID)
    if set(transition.evidence_ids) != set(evidence):
        raise RankCandidateCatalogError(
            "transition and evidence inventories disagree"
        )
    embedding_by_kept_slots = {
        tuple(value["kept_slots"]): value["target_embedding_evidence_id"]
        for value in artifact["canonical_model"]["parameter_maps"]
    }
    if set(embedding_by_kept_slots) != {(0, 1), (0, 2), (1, 2)}:
        raise RankCandidateCatalogError(
            "S5 does not cover all rank-three ordered subsets"
        )
    return registry, evidence, embedding_by_kept_slots


def _resource_vector(value: Mapping[str, Any]) -> ResourceVector:
    return ResourceVector(
        parameter_count=int(value["parameter_count"]),
        logical_block_count=int(value["logical_block_count"]),
        cnot_count=int(value["cnot_count"]),
        cnot_depth=int(value["cnot_depth"]),
        total_depth=int(value["total_depth"]),
    )


def _screen_resource_evidence(
    evidence: ResourceDeltaEvidence,
) -> tuple[str, tuple[str, ...]]:
    reasons = ()
    if not evidence.physical_circuit_gain:
        reasons = ("no-strict-physical-circuit-gain",)
    return (
        (
            "ELIGIBLE_NATIVE_PHYSICAL_GAIN"
            if not reasons
            else "REJECTED_NO_PHYSICAL_GAIN"
        ),
        reasons,
    )


def _demoted_seed(
    source: AnsatzStructure,
    block: DVGBlock,
    omitted_slot: int,
) -> AnsatzStructure:
    position = block.ansatz_positions[omitted_slot]
    iteration = block.selection_iterations[omitted_slot]
    indices = tuple(
        value
        for current, value in enumerate(source.indices)
        if current != position
    )
    coefficients = tuple(
        value
        for current, value in enumerate(source.coefficients)
        if current != position
    )
    counts = tuple(
        value - int(current >= iteration)
        for current, value in enumerate(
            source.cumulative_parameter_counts,
            1,
        )
    )
    return AnsatzStructure.create(indices, coefficients, counts)


@dataclass(frozen=True)
class NativeRankCandidate:
    candidate_id: str
    equivalence_class_id: str
    transition_id: str
    source_state_digest: str
    source_block_id: str
    source_ansatz_positions: tuple[int, ...]
    source_pool_indices: tuple[int, ...]
    omitted_source_slot: int
    omitted_pool_index: int
    kept_source_slots: tuple[int, ...]
    target_pool_indices: tuple[int, ...]
    target_seed_state_digest: str
    target_embedding_evidence_id: str
    native_synthesis_evidence_id: str
    contextual_rewrite_evidence_id: str
    native_mapping: tuple[Mapping[str, Any], ...]
    resources: ResourceDeltaEvidence
    screening_status: str
    rejection_reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "source_ansatz_positions": list(self.source_ansatz_positions),
            "source_pool_indices": list(self.source_pool_indices),
            "kept_source_slots": list(self.kept_source_slots),
            "target_pool_indices": list(self.target_pool_indices),
            "native_mapping": [dict(item) for item in self.native_mapping],
            "resources": self.resources.to_dict(),
            "rejection_reasons": list(self.rejection_reasons),
            "human_classification": (
                HumanClassification.APPROXIMATE_RANK_DEMOTION.value
            ),
            "equivalence_scope": (
                "NATIVE_RESOURCE_ONLY_NOT_HAMILTONIAN_STATE_OR_ENERGY"
            ),
            "optimization_requirement": (
                OptimizationRequirement.FULL_REOPTIMIZATION.value
            ),
            "source_parameter_membership": "NOT_ESTABLISHED",
            "source_state_equivalence": "NOT_ESTABLISHED",
            "energy_evaluated": False,
            "paper_measurement_cost": None,
        }


def _candidate_identity(
    *,
    registry_digest: str,
    source_digest: str,
    block: DVGBlock,
    omitted_slot: int,
    target_pool_indices: Sequence[int],
) -> tuple[str, str]:
    locus = {
        "catalog_version": CATALOG_VERSION,
        "transition_id": TRANSITION_ID,
        "transition_registry_digest": registry_digest,
        "source_state_digest": source_digest,
        "source_block_id": block.block_id,
        "source_ansatz_positions": list(block.ansatz_positions),
        "omitted_source_slot": omitted_slot,
        "target_generator_digests": [
            block.generator_digests[index]
            for index in range(len(block.generator_digests))
            if index != omitted_slot
        ],
        "native_synthesis_id": NATIVE_SYNTHESIS_ID,
    }
    equivalence = {
        "catalog_version": CATALOG_VERSION,
        "transition_id": TRANSITION_ID,
        "equivalence_scope": "NATIVE_RESOURCE_ORBIT_ONLY",
        "source_constituent_count": len(block.pool_indices),
        "target_constituent_count": len(target_pool_indices),
        "support_size": len(block.support_qubits),
        "native_synthesis_id": NATIVE_SYNTHESIS_ID,
    }
    return (
        "v6-rank-candidate:" + sha256_hex(locus),
        "v6-rank-equivalence:" + sha256_hex(equivalence),
    )


def enumerate_native_rank_candidates(
    pool: Any,
    source: AnsatzStructure,
    registry: TransitionRegistry,
    evidence: Mapping[str, EvidenceRecord],
    embedding_by_kept_slots: Mapping[tuple[int, int], str],
    *,
    traversal_block_ids: Sequence[str] | None = None,
    omitted_slot_order: Sequence[int] = (0, 1, 2),
) -> tuple[NativeRankCandidate, ...]:
    transition = registry.require_executable(TRANSITION_ID)
    if (
        transition.source_family != "MVP"
        or transition.target_family != "SPARSE_UCRY_RANK2"
        or transition.allowed_constituent_counts != (3,)
        or transition.target_rank != 2
        or transition.native_synthesis_id != NATIVE_SYNTHESIS_ID
    ):
        raise RankCandidateCatalogError(
            "S7 received an unsupported executable transition"
        )
    if any(item not in evidence for item in transition.evidence_ids):
        raise RankCandidateCatalogError(
            "candidate generation lacks transition evidence"
        )
    blocks = recover_dvg_blocks(
        pool,
        source.indices,
        source.coefficients,
        source.cumulative_parameter_counts,
    )
    by_id = {block.block_id: block for block in blocks}
    traversal = (
        tuple(traversal_block_ids)
        if traversal_block_ids is not None
        else tuple(block.block_id for block in blocks)
    )
    if any(block_id not in by_id for block_id in traversal):
        raise RankCandidateCatalogError("traversal references an unknown block")
    slot_order = tuple(int(value) for value in omitted_slot_order)
    if set(slot_order) != {0, 1, 2} or len(slot_order) != 3:
        raise RankCandidateCatalogError(
            "rank-three omitted-slot order must be a permutation of 0,1,2"
        )
    source_circuit, source_parameters = _compose_checkpoint_circuit(
        pool,
        blocks,
    )
    source_resources = _qasm_resources(
        source_circuit,
        parameter_count=source_parameters,
        logical_block_count=len(blocks),
    )
    source_vector = _resource_vector(source_resources)
    source_digest = state_digest(source)
    native_evidence = next(
        (
            item
            for item in evidence.values()
            if item.evidence_type is EvidenceType.NATIVE_SYNTHESIS
        ),
        None,
    )
    context_evidence = next(
        (
            item
            for item in evidence.values()
            if item.evidence_type is EvidenceType.CONTEXTUAL_REWRITE
        ),
        None,
    )
    if native_evidence is None or context_evidence is None:
        raise RankCandidateCatalogError(
            "native or contextual evidence is missing"
        )
    candidates: dict[str, NativeRankCandidate] = {}
    for block_id in traversal:
        block = by_id[block_id]
        if (
            block.family != transition.source_family
            or len(block.pool_indices)
            not in transition.allowed_constituent_counts
        ):
            continue
        for omitted_slot in slot_order:
            kept_slots = tuple(
                slot
                for slot in range(len(block.pool_indices))
                if slot != omitted_slot
            )
            embedding_id = embedding_by_kept_slots.get(kept_slots)
            if (
                embedding_id is None
                or embedding_id not in evidence
                or evidence[embedding_id].evidence_type
                is not EvidenceType.TARGET_EMBEDDING
            ):
                raise RankCandidateCatalogError(
                    "candidate lacks its ordered-subset embedding proof"
                )
            target_pool_indices = tuple(
                block.pool_indices[slot] for slot in kept_slots
            )
            target_circuit, target_parameters = _compose_checkpoint_circuit(
                pool,
                blocks,
                target_block_id=block.block_id,
                omitted_pool_index=block.pool_indices[omitted_slot],
            )
            target_resources = _qasm_resources(
                target_circuit,
                parameter_count=target_parameters,
                logical_block_count=len(blocks),
            )
            target_vector = _resource_vector(target_resources)
            resource_evidence = ResourceDeltaEvidence(
                before=source_vector,
                after=target_vector,
                resource_counter_version=COUNTER_VERSION,
                native_synthesizer_version=NATIVE_SYNTHESIS_ID,
                compiler_configuration=COMPILER_CONFIGURATION,
                qubit_order=tuple(range(pool.n)),
                before_digest=source_resources["circuit_qasm_digest"],
                after_digest=target_resources["circuit_qasm_digest"],
                primary_resource="total_depth",
            )
            screening_status, reasons = _screen_resource_evidence(
                resource_evidence
            )
            candidate_id, equivalence_id = _candidate_identity(
                registry_digest=registry.registry_digest,
                source_digest=source_digest,
                block=block,
                omitted_slot=omitted_slot,
                target_pool_indices=target_pool_indices,
            )
            seed = _demoted_seed(source, block, omitted_slot)
            candidate = NativeRankCandidate(
                candidate_id=candidate_id,
                equivalence_class_id=equivalence_id,
                transition_id=transition.transition_id,
                source_state_digest=source_digest,
                source_block_id=block.block_id,
                source_ansatz_positions=block.ansatz_positions,
                source_pool_indices=block.pool_indices,
                omitted_source_slot=omitted_slot,
                omitted_pool_index=block.pool_indices[omitted_slot],
                kept_source_slots=kept_slots,
                target_pool_indices=target_pool_indices,
                target_seed_state_digest=state_digest(seed),
                target_embedding_evidence_id=embedding_id,
                native_synthesis_evidence_id=native_evidence.evidence_id,
                contextual_rewrite_evidence_id=context_evidence.evidence_id,
                native_mapping=tuple(
                    derive_conditional_rotation(
                        pool,
                        pool_index,
                        block.support_qubits,
                    )[0].to_dict()
                    for pool_index in target_pool_indices
                ),
                resources=resource_evidence,
                screening_status=screening_status,
                rejection_reasons=reasons,
            )
            previous = candidates.get(candidate_id)
            if previous is not None and previous != candidate:
                raise RankCandidateCatalogError(
                    "canonical candidate ID collision"
                )
            candidates[candidate_id] = candidate
    return tuple(candidates[key] for key in sorted(candidates))


def _source_recount_checks(
    observed: Mapping[str, Any],
    expected: Mapping[str, Any],
) -> dict[str, bool]:
    fields = (
        "parameter_count",
        "logical_block_count",
        "cnot_count",
        "cnot_depth",
        "total_depth",
    )
    checks = {
        f"{field}_matches_s6": observed[field] == expected[field]
        for field in fields
    }
    checks["base_counter_implementation_matches_s6"] = (
        observed["counter_version"].split(":")[-1]
        == expected["counter_version"].split(":")[-1]
    )
    return checks


def build_report(
    source_path: Path = DEFAULT_SOURCE,
    evidence_path: Path = DEFAULT_EVIDENCE,
) -> dict[str, Any]:
    _, DVG_CEO, _, _ = _load_upstream()
    source_artifact = json.loads(source_path.read_text(encoding="utf-8"))
    source = load_s6_source(source_path)
    registry, evidence, embeddings = load_s5_registry(evidence_path)
    pool = DVG_CEO(n=12)
    blocks = recover_dvg_blocks(
        pool,
        source.indices,
        source.coefficients,
        source.cumulative_parameter_counts,
    )
    circuit, parameter_count = _compose_checkpoint_circuit(pool, blocks)
    recounted_source = _qasm_resources(
        circuit,
        parameter_count=parameter_count,
        logical_block_count=len(blocks),
    )
    source_checks = _source_recount_checks(
        recounted_source,
        source_artifact["target"]["resources"],
    )
    if not all(source_checks.values()):
        raise RankCandidateCatalogError(
            "S7 source recount disagrees with the frozen S6 target"
        )
    candidates = enumerate_native_rank_candidates(
        pool,
        source,
        registry,
        evidence,
        embeddings,
    )
    eligible = [
        item
        for item in candidates
        if item.screening_status == "ELIGIBLE_NATIVE_PHYSICAL_GAIN"
    ]
    registered_counts = sorted(
        {
            count
            for item in registry.to_dict()["transitions"]
            for count in item["allowed_constituent_counts"]
        }
    )
    report = {
        "schema_version": "1.0.0",
        "artifact_kind": "v6-s7-rank-candidate-catalog",
        "catalog_version": CATALOG_VERSION,
        "development_only": True,
        "source_artifact": str(source_path.relative_to(ROOT)),
        "source_artifact_sha256": hashlib.sha256(
            source_path.read_bytes()
        ).hexdigest(),
        "evidence_artifact": str(evidence_path.relative_to(ROOT)),
        "evidence_artifact_sha256": hashlib.sha256(
            evidence_path.read_bytes()
        ).hexdigest(),
        "source_state_digest": state_digest(source),
        "source_recount": recounted_source,
        "source_counter_label_comparison": {
            "s7_wrapper": recounted_source["counter_version"],
            "s6_wrapper": source_artifact["target"]["resources"][
                "counter_version"
            ],
            "interpretation": (
                "Wrapper labels differ, while the pinned underlying "
                "paper-era QASM counter implementation ID is identical."
            ),
        },
        "source_recount_checks": source_checks,
        "transition_registry": registry.to_dict(),
        "registered_source_constituent_counts": registered_counts,
        "eligible_source_block_count": len(
            {item.source_block_id for item in candidates}
        ),
        "parent_effect": (
            "The saturated S6 parent contains one eligible rank-three MVP "
            "block; S7 therefore has three registered ordered-subset edges. "
            "The earlier S5 checkpoint had two such blocks before exact "
            "OVP-to-MVP absorption."
        ),
        "unregistered_edges_not_enumerated": [
            {
                "source_constituent_count": 2,
                "target_rank": 1,
                "reason": (
                    "no S1-S5 verified native transition is registered"
                ),
            }
        ],
        "candidate_count": len(candidates),
        "eligible_candidate_count": len(eligible),
        "rejected_candidate_count": len(candidates) - len(eligible),
        "candidates": [item.to_dict() for item in candidates],
        "equivalence_classes": {
            equivalence_id: sorted(
                item.candidate_id
                for item in candidates
                if item.equivalence_class_id == equivalence_id
            )
            for equivalence_id in sorted(
                {item.equivalence_class_id for item in candidates}
            )
        },
        "equivalence_policy": (
            "Candidates in one class share only the registered native "
            "synthesis/resource orbit. They remain separate candidates "
            "because Hamiltonian, checkpoint-state, and energy equivalence "
            "are not established."
        ),
        "work": {
            "rank_blocks_inspected": len(blocks),
            "native_candidates_synthesized": len(candidates),
            "full_resource_recounts": 1 + len(candidates),
            "energy_evaluations": 0,
            "gradient_vector_evaluations": 0,
            "optimizer_starts": 0,
            "paper_measurement_cost": None,
        },
        "claim_boundary": (
            "Deterministic development candidate generation, registered "
            "family embedding, native synthesis, and full-circuit resource "
            "recount only. Demoted checkpoint seeds are not claimed state- "
            "or energy-equivalent and require later full reoptimization."
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
        ImportError,
        KeyError,
        OSError,
        TypeError,
        ValueError,
        RankCandidateCatalogError,
    ) as error:
        print(f"V6 S7 rank catalog failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    print(
        json.dumps(
            {
                "candidate_count": report["candidate_count"],
                "eligible_candidate_count": (
                    report["eligible_candidate_count"]
                ),
                "report_digest": report["report_digest"],
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()

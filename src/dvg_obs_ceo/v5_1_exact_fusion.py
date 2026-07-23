"""Exact cross-iteration CEO fusion candidates for the conditional V5.1 gate.

This module does not perform generic circuit compilation.  It recognizes only
an OVP and an MVP built from the same registered parent QEs when every block
between them has disjoint qubit support.  The OVP can then commute to the MVP
and its signed coordinate can be absorbed into the MVP coordinates exactly.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import itertools
from typing import Any, Sequence

import numpy as np
from numpy.typing import NDArray
from scipy.linalg import expm

from .block_ir import (
    BlockIRError,
    DVGBlock,
    _registered_ovp_relation,
    recover_dvg_blocks,
)
from .identity import canonical_json_bytes
from .resources import AnsatzStructure, ResourceEvaluationError


ComplexArray = NDArray[np.complex128]
FUSION_IR_VERSION = "v5.1-exact-cross-iteration-ceo-fusion-v1"


class ExactFusionError(RuntimeError):
    """Raised when an alleged fusion is not symbolically and physically safe."""


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


@dataclass(frozen=True)
class ExactFusionCandidate:
    candidate_id: str
    ovp_block_id: str
    mvp_block_id: str
    ovp_numerical_context_digest: str
    mvp_numerical_context_digest: str
    ovp_position: int
    mvp_positions: tuple[int, ...]
    intervening_block_ids: tuple[str, ...]
    support_qubits: tuple[int, ...]
    parent_pool_indices: tuple[int, ...]
    exact_signed_relation: tuple[int, ...]
    source_parameter_count: int
    target_parameter_count: int
    symbolic_provenance: str = "registered-OVP-parent-metadata"

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "ir_version": FUSION_IR_VERSION,
            "ovp_block_id": self.ovp_block_id,
            "mvp_block_id": self.mvp_block_id,
            "ovp_numerical_context_digest": self.ovp_numerical_context_digest,
            "mvp_numerical_context_digest": self.mvp_numerical_context_digest,
            "ovp_position": self.ovp_position,
            "mvp_positions": list(self.mvp_positions),
            "intervening_block_ids": list(self.intervening_block_ids),
            "support_qubits": list(self.support_qubits),
            "parent_pool_indices": list(self.parent_pool_indices),
            "exact_signed_relation": list(self.exact_signed_relation),
            "source_parameter_count": self.source_parameter_count,
            "target_parameter_count": self.target_parameter_count,
            "symbolic_provenance": self.symbolic_provenance,
        }


def enumerate_exact_fusions(
    pool: Any,
    blocks: Sequence[DVGBlock],
) -> tuple[ExactFusionCandidate, ...]:
    """Enumerate registered OVP-to-MVP absorptions across disjoint blocks."""

    candidates: list[ExactFusionCandidate] = []
    for left_index, left in enumerate(blocks):
        for right_index in range(left_index + 1, len(blocks)):
            right = blocks[right_index]
            families = {left.family, right.family}
            if families != {"OVP", "MVP"}:
                continue
            ovp = left if left.family == "OVP" else right
            mvp = right if right.family == "MVP" else left
            if len(ovp.pool_indices) != 1 or len(mvp.pool_indices) < 2:
                continue
            if ovp.support_qubits != mvp.support_qubits:
                continue
            intervening = tuple(blocks[left_index + 1 : right_index])
            protected_support = set(ovp.support_qubits)
            if any(protected_support & set(block.support_qubits) for block in intervening):
                continue
            target = pool.operators[ovp.pool_indices[0]]
            try:
                relation = _registered_ovp_relation(mvp.pool_indices, target, pool)
            except BlockIRError as error:
                raise ExactFusionError(
                    "registered OVP metadata is malformed in a fusion candidate"
                ) from error
            if relation is None or sum(value != 0 for value in relation) != 2:
                continue
            if any(value not in (-1, 0, 1) for value in relation):
                raise ExactFusionError("fusion relation is not an exact signed parent map")
            structural = {
                "ir_version": FUSION_IR_VERSION,
                "ovp_block_id": ovp.block_id,
                "mvp_block_id": mvp.block_id,
                "intervening_block_ids": [block.block_id for block in intervening],
                "support_qubits": list(ovp.support_qubits),
                "parent_pool_indices": list(mvp.pool_indices),
                "exact_signed_relation": list(relation),
            }
            candidates.append(
                ExactFusionCandidate(
                    candidate_id="fusion-v1:" + _digest(structural),
                    ovp_block_id=ovp.block_id,
                    mvp_block_id=mvp.block_id,
                    ovp_numerical_context_digest=ovp.numerical_context_digest,
                    mvp_numerical_context_digest=mvp.numerical_context_digest,
                    ovp_position=ovp.ansatz_positions[0],
                    mvp_positions=mvp.ansatz_positions,
                    intervening_block_ids=tuple(
                        block.block_id for block in intervening
                    ),
                    support_qubits=ovp.support_qubits,
                    parent_pool_indices=mvp.pool_indices,
                    exact_signed_relation=relation,
                    source_parameter_count=1 + len(mvp.pool_indices),
                    target_parameter_count=len(mvp.pool_indices),
                )
            )
    identifiers = [candidate.candidate_id for candidate in candidates]
    if len(identifiers) != len(set(identifiers)):
        raise ExactFusionError("fusion candidate IDs are not unique")
    return tuple(candidates)


def apply_exact_fusion(
    pool: Any,
    source: AnsatzStructure,
    candidate: ExactFusionCandidate,
) -> AnsatzStructure:
    """Apply the exact old-to-new coordinate map and remove the OVP circuit."""

    blocks = recover_dvg_blocks(
        pool,
        source.indices,
        source.coefficients,
        source.cumulative_parameter_counts,
    )
    by_id = {block.block_id: block for block in blocks}
    ovp = by_id.get(candidate.ovp_block_id)
    mvp = by_id.get(candidate.mvp_block_id)
    if ovp is None or mvp is None or ovp.family != "OVP" or mvp.family != "MVP":
        raise ExactFusionError("fusion source blocks are absent or have changed family")
    if (
        ovp.numerical_context_digest != candidate.ovp_numerical_context_digest
        or mvp.numerical_context_digest != candidate.mvp_numerical_context_digest
    ):
        raise ExactFusionError("fusion candidate numerical context is stale")
    refreshed = {
        item.candidate_id: item for item in enumerate_exact_fusions(pool, blocks)
    }.get(candidate.candidate_id)
    if refreshed != candidate:
        raise ExactFusionError("fusion provenance no longer matches the source structure")

    coefficients = list(source.coefficients)
    ovp_coordinate = coefficients[candidate.ovp_position]
    for position, weight in zip(
        candidate.mvp_positions, candidate.exact_signed_relation
    ):
        coefficients[position] += float(weight) * ovp_coordinate

    del coefficients[candidate.ovp_position]
    indices = list(source.indices)
    del indices[candidate.ovp_position]
    ovp_iteration = ovp.selection_iterations[0]
    counts = tuple(
        count if iteration < ovp_iteration else count - 1
        for iteration, count in enumerate(source.cumulative_parameter_counts, 1)
    )
    try:
        return AnsatzStructure.create(indices, coefficients, counts)
    except ResourceEvaluationError as error:
        raise ExactFusionError("fusion produced an invalid ansatz structure") from error


def validate_exact_fusion_generators(
    candidate: ExactFusionCandidate,
    ovp_generator: ComplexArray,
    parent_generators: Sequence[ComplexArray],
    *,
    samples: int = 7,
    seed: int = 0,
    tolerance: float = 1e-10,
) -> None:
    """Numerically audit the symbolic generator and unitary identities."""

    ovp = np.asarray(ovp_generator, dtype=np.complex128)
    parents = tuple(
        np.asarray(generator, dtype=np.complex128)
        for generator in parent_generators
    )
    if len(parents) != len(candidate.exact_signed_relation) or not parents:
        raise ExactFusionError("fusion generator dimensions do not match provenance")
    dimension = ovp.shape[0]
    if ovp.shape != (dimension, dimension) or any(
        generator.shape != ovp.shape for generator in parents
    ):
        raise ExactFusionError("fusion generators must be equally sized and square")
    if any(
        np.linalg.norm(generator + generator.conj().T) > tolerance
        for generator in (ovp, *parents)
    ):
        raise ExactFusionError("fusion generator is not anti-Hermitian")
    if any(
        np.linalg.norm(left @ right - right @ left) > tolerance
        for left, right in itertools.combinations(parents, 2)
    ):
        raise ExactFusionError("registered MVP parent generators do not commute")
    reconstructed = sum(
        (
            weight * generator
            for weight, generator in zip(
                candidate.exact_signed_relation, parents
            )
        ),
        np.zeros_like(ovp),
    )
    if np.linalg.norm(ovp - reconstructed) > tolerance:
        raise ExactFusionError("registered OVP generator identity failed")

    rng = np.random.default_rng(seed)
    for _ in range(samples):
        ovp_coordinate = float(rng.uniform(-0.7, 0.7))
        mvp_coordinates = rng.uniform(-0.7, 0.7, len(parents))
        source = expm(ovp_coordinate * ovp)
        for coordinate, generator in zip(mvp_coordinates, parents):
            source = expm(float(coordinate) * generator) @ source
        fused_coordinates = mvp_coordinates + (
            ovp_coordinate * np.asarray(candidate.exact_signed_relation)
        )
        target = np.eye(dimension, dtype=np.complex128)
        for coordinate, generator in zip(fused_coordinates, parents):
            target = expm(float(coordinate) * generator) @ target
        if np.linalg.norm(source - target) > tolerance:
            raise ExactFusionError("fusion source and target unitaries differ")


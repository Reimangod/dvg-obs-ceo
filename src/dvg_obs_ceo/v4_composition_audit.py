"""Full H2/H4 compatibility and circuit-construction audit for V4-S2."""

from __future__ import annotations

import argparse
from collections import Counter
from itertools import combinations
import json
import os
from pathlib import Path
import subprocess
from typing import Any

from openfermion import get_sparse_operator

from .baseline import ROOT
from .block_ir import (
    enumerate_candidates,
    recover_dvg_blocks,
    validate_candidate_semantics,
)
from .composition import compose_registered_candidates, pairwise_compatibility
from .resources import AnsatzStructure
from .s8_probe import _algorithm
from .v3_gradient_audit import _load_and_verify
from .v3_protocol import _write_exclusive
from .v4_protocol import audit_manifest


PROTOCOL_TAG = "dvg-obs-v4-s2-composition-v1.1"
REQUIRED_THREADS = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
}


class V4CompositionAuditError(RuntimeError):
    """Raised when a registered joint rewrite fails global validation."""


def _git(*arguments: str) -> str:
    return subprocess.check_output(["git", "-C", str(ROOT), *arguments], text=True).strip()


def verify_freeze() -> dict[str, Any]:
    head = _git("rev-parse", "HEAD")
    tagged = _git("rev-parse", f"{PROTOCOL_TAG}^{{}}")
    dirty = _git("status", "--porcelain")
    threads = {name: os.environ.get(name) for name in REQUIRED_THREADS}
    if head != tagged or dirty or threads != REQUIRED_THREADS:
        raise V4CompositionAuditError(
            f"V4-S2 requires clean tagged code and canonical threads: head={head}, "
            f"tag={tagged}, dirty={bool(dirty)}, threads={threads}"
        )
    return {"head": head, "protocol_tag": PROTOCOL_TAG, "threads": threads}


def run(artifact_path: Path) -> dict[str, Any]:
    freeze = verify_freeze()
    s0 = audit_manifest()
    _, _, checkpoints = _load_and_verify(
        ROOT / "manifests" / "v3-s1-gradient-audit-v1.json"
    )
    records: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    semantic_checks = 0

    for case_id in sorted(checkpoints):
        checkpoint = checkpoints[case_id]
        _, pool = _algorithm(case_id)
        source = AnsatzStructure.create(
            checkpoint["ansatz_indices"], checkpoint["ansatz_coefficients"], checkpoint["iteration_counts"]
        )
        blocks = recover_dvg_blocks(
            pool, source.indices, source.coefficients, source.cumulative_parameter_counts
        )
        block_by_id = {block.block_id: block for block in blocks}
        representatives: dict[str, Any] = {}
        for candidate in enumerate_candidates(pool, blocks):
            representatives.setdefault(candidate.equivalence_class_id, candidate)
        candidates = tuple(sorted(representatives.values(), key=lambda value: value.candidate_id))
        for candidate in candidates:
            block = block_by_id[candidate.source_block_id]
            sources = [
                get_sparse_operator(pool.get_q_op(index), n_qubits=pool.n).toarray()
                for index in block.pool_indices
            ]
            targets = [
                get_sparse_operator(pool.get_q_op(index), n_qubits=pool.n).toarray()
                for index in candidate.target_pool_indices
            ]
            validate_candidate_semantics(candidate, sources, targets, samples=2, seed=31)
            semantic_checks += 1

        def validate_circuit(indices):
            structural_coefficients = [0.125 + 0.001 * index for index in range(len(indices))]
            pool.get_circuit(list(indices), structural_coefficients)

        for size in (2, 3):
            for batch in combinations(candidates, size):
                counts[f"{case_id}:considered_size_{size}"] += 1
                pairwise = [
                    pairwise_compatibility(
                        left,
                        block_by_id[left.source_block_id],
                        right,
                        block_by_id[right.source_block_id],
                    )
                    for left, right in combinations(batch, 2)
                ]
                if not all(value.compatible for value in pairwise):
                    counts[f"{case_id}:pairwise_rejected_size_{size}"] += 1
                    continue
                plan = compose_registered_candidates(
                    source, blocks, batch, circuit_validator=validate_circuit
                )
                replay = compose_registered_candidates(
                    source, blocks, tuple(reversed(batch)), circuit_validator=validate_circuit
                )
                order_invariant = bool(
                    plan.state.constraint_semantic_id == replay.state.constraint_semantic_id
                    and plan.state.constraint_numerical_id == replay.state.constraint_numerical_id
                    and plan.target_indices == replay.target_indices
                    and plan.target_iteration_counts == replay.target_iteration_counts
                )
                if not order_invariant:
                    raise V4CompositionAuditError("candidate application order changed joint state")
                counts[f"{case_id}:completed_size_{size}"] += 1
                records.append(
                    {
                        "case_id": case_id,
                        "size": size,
                        "candidate_ids": list(plan.candidate_ids),
                        "constraint_semantic_id": plan.state.constraint_semantic_id,
                        "constraint_numerical_id": plan.state.constraint_numerical_id,
                        "target_dimension": len(plan.target_indices),
                        "order_invariant": order_invariant,
                        "actual_circuit_constructed": True,
                    }
                )
    identifiers = [record["constraint_semantic_id"] for record in records]
    checks = {
        "s0_audit": s0["passed"],
        "atomic_semantics_checked": semantic_checks == 17,
        "joint_batches_completed": bool(records),
        "joint_semantic_ids_unique": len(identifiers) == len(set(identifiers)),
        "application_order_invariant": all(record["order_invariant"] for record in records),
        "actual_circuit_constructed": all(record["actual_circuit_constructed"] for record in records),
        "pairs_and_triples_covered": {record["size"] for record in records} == {2, 3},
    }
    failed = [name for name, passed in checks.items() if not passed]
    artifact = {
        "schema_version": "1.0.0",
        "artifact_kind": "v4-s2-global-composition-audit",
        "execution_freeze": freeze,
        "passed": not failed,
        "checks": checks,
        "failed_checks": failed,
        "atomic_semantic_checks": semantic_checks,
        "counts": dict(sorted(counts.items())),
        "completed_joint_batches": len(records),
        "work": {
            "vqe_energy_evaluations": 0,
            "ordinary_gsd_adapt_iterations": 0,
            "ceo_star_adapt_iterations": 0,
            "paper_measurement_cost": None,
        },
        "claim_boundary": "Compatibility, exact composition, and circuit construction only; no energy or performance evaluation.",
        "records": records,
    }
    if failed:
        raise V4CompositionAuditError("V4-S2 audit failed: " + ", ".join(failed))
    _write_exclusive(artifact_path, artifact)
    return artifact


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-path", type=Path, required=True)
    arguments = parser.parse_args()
    result = run(arguments.artifact_path)
    print(json.dumps({
        "passed": result["passed"],
        "atomic_semantic_checks": result["atomic_semantic_checks"],
        "completed_joint_batches": result["completed_joint_batches"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()

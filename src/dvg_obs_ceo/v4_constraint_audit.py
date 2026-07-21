"""Audit exact/numerical ConstraintState identities on stored H2/H4 candidates."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
import os
from pathlib import Path
import subprocess
from typing import Any

from .baseline import ROOT
from .block_ir import enumerate_candidates, recover_dvg_blocks
from .constraint_state import CanonicalConstraintState, exact_atomic_constraint
from .resources import AnsatzStructure
from .s8_probe import _algorithm
from .v3_gradient_audit import _load_and_verify
from .v3_protocol import _write_exclusive
from .v4_protocol import DEFAULT_MANIFEST as V4_MANIFEST, audit_manifest


PROTOCOL_TAG = "dvg-obs-v4-s1-constraint-ir-v1.1"
REQUIRED_THREADS = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
}


class V4ConstraintAuditError(RuntimeError):
    """Raised when exact candidate identities fail on stored calibration data."""


def _git(*arguments: str) -> str:
    return subprocess.check_output(["git", "-C", str(ROOT), *arguments], text=True).strip()


def verify_freeze() -> dict[str, Any]:
    head = _git("rev-parse", "HEAD")
    tagged = _git("rev-parse", f"{PROTOCOL_TAG}^{{}}")
    dirty = _git("status", "--porcelain")
    threads = {name: os.environ.get(name) for name in REQUIRED_THREADS}
    if head != tagged or dirty or threads != REQUIRED_THREADS:
        raise V4ConstraintAuditError(
            f"V4-S1 requires clean tagged code and canonical threads: head={head}, "
            f"tag={tagged}, dirty={bool(dirty)}, threads={threads}"
        )
    return {"head": head, "protocol_tag": PROTOCOL_TAG, "threads": threads}


def run(artifact_path: Path) -> dict[str, Any]:
    freeze = verify_freeze()
    s0 = audit_manifest(V4_MANIFEST)
    manifest = json.loads(V4_MANIFEST.read_text(encoding="utf-8"))
    s1_manifest_path = ROOT / "manifests" / "v3-s1-gradient-audit-v1.json"
    _, rows, checkpoints = _load_and_verify(s1_manifest_path)
    records: list[dict[str, Any]] = []
    kinds: Counter[str] = Counter()
    equivalence_to_semantic: dict[str, set[str]] = defaultdict(set)
    semantic_to_equivalence: dict[str, set[str]] = defaultdict(set)

    for case_id in sorted(checkpoints):
        checkpoint = checkpoints[case_id]
        _, pool = _algorithm(case_id)
        source = AnsatzStructure.create(
            checkpoint["ansatz_indices"], checkpoint["ansatz_coefficients"], checkpoint["iteration_counts"]
        )
        blocks = recover_dvg_blocks(
            pool, source.indices, source.coefficients, source.cumulative_parameter_counts
        )
        candidates = {
            candidate.candidate_id: candidate for candidate in enumerate_candidates(pool, blocks)
        }
        case_rows = sorted(
            (row for row in rows if row["case_id"] == case_id),
            key=lambda row: row["candidate"]["candidate_id"],
        )
        for row in case_rows:
            candidate = candidates[row["candidate"]["candidate_id"]]
            exact = exact_atomic_constraint(candidate)
            state = CanonicalConstraintState.create(
                exact.system, candidate.transformation, [exact.primitive]
            )
            equivalence_to_semantic[candidate.equivalence_class_id].add(
                state.constraint_semantic_id
            )
            semantic_to_equivalence[state.constraint_semantic_id].add(
                candidate.equivalence_class_id
            )
            kinds[candidate.kind] += 1
            records.append(
                {
                    "case_id": case_id,
                    "candidate_id": candidate.candidate_id,
                    "equivalence_class_id": candidate.equivalence_class_id,
                    "kind": candidate.kind,
                    "semantic_primitive": exact.primitive,
                    "audit_provenance": exact.audit_provenance,
                    "state": state.to_dict(),
                }
            )
    required = set(manifest["supported_atomic_transformations"])
    observed_relation = {
        record["semantic_primitive"]["generator_relation"] for record in records
    }
    checks = {
        "s0_audit": s0["passed"],
        "candidate_count": len(records) == 17,
        "candidate_ids_unique": len({record["candidate_id"] for record in records}) == 17,
        "all_registered_kinds_present": set(kinds) == {
            "block-deletion",
            "mvp-whole-deletion",
            "mvp-constituent-deletion",
            "mvp-to-ovp-sum",
            "mvp-to-ovp-diff",
        },
        "registered_relations_present": observed_relation == {
            "empty",
            "identity-subset",
            "existing-ovp-sum",
            "existing-ovp-difference",
        },
        "semantic_primitives_exclude_candidate_labels": all(
            "candidate_id" not in record["semantic_primitive"]
            and "kind" not in record["semantic_primitive"]
            for record in records
        ),
        "equivalence_maps_to_one_semantic_id": all(
            len(values) == 1 for values in equivalence_to_semantic.values()
        ),
        "semantic_id_maps_to_one_equivalence_class": all(
            len(values) == 1 for values in semantic_to_equivalence.values()
        ),
        "exact_rref_contains_no_float": all(
            isinstance(value, str)
            for record in records
            for row in record["state"]["exact_system"]["augmented_rref"]
            for value in row
        ),
        "numerical_residuals": all(
            record["state"]["diagnostics"]["offset_constraint_residual_infinity"] <= 1e-10
            and record["state"]["diagnostics"]["jacobian_constraint_residual_infinity"] <= 1e-10
            for record in records
        ),
        "protocol_lists_supported_scope": len(required) == 5,
    }
    failed = [name for name, passed in checks.items() if not passed]
    artifact = {
        "schema_version": "1.0.0",
        "artifact_kind": "v4-s1-constraint-state-audit",
        "execution_freeze": freeze,
        "passed": not failed,
        "checks": checks,
        "failed_checks": failed,
        "kind_counts": dict(sorted(kinds.items())),
        "candidate_count": len(records),
        "equivalence_class_count": len(equivalence_to_semantic),
        "semantic_state_count": len(semantic_to_equivalence),
        "work": {
            "ordinary_gsd_adapt_iterations": 0,
            "ceo_star_adapt_iterations": 0,
            "vqe_energy_evaluations": 0,
            "paper_measurement_cost": None,
        },
        "claim_boundary": "Exact identity audit only; no search, energy evaluation, or performance claim.",
        "records": records,
    }
    if failed:
        raise V4ConstraintAuditError("V4-S1 audit failed: " + ", ".join(failed))
    _write_exclusive(artifact_path, artifact)
    return artifact


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-path", type=Path, required=True)
    arguments = parser.parse_args()
    result = run(arguments.artifact_path)
    print(json.dumps({
        "passed": result["passed"],
        "candidate_count": result["candidate_count"],
        "semantic_state_count": result["semantic_state_count"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()

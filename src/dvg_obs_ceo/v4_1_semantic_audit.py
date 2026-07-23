"""V4.1-S2 audit of exact registered MVP-to-OVP semantics."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Any

from .baseline import ROOT
from .block_ir import enumerate_candidates, recover_dvg_blocks
from .composition import compose_registered_candidates
from .constraint_state import exact_atomic_constraint
from .identity import canonical_json_bytes
from .multisystem_checkpoint import _algorithm
from .resources import AnsatzStructure
from .v3_protocol import _write_exclusive
from .v4_1_protocol import DEFAULT_MANIFEST, audit_manifest


class V41SemanticAuditError(RuntimeError):
    """Raised when registered exact semantics fail replay."""


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def run(manifest_path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    s0 = audit_manifest(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    cases: list[dict[str, Any]] = []
    for case_record in manifest["cases"]:
        checkpoint = json.loads(
            (ROOT / case_record["checkpoint_path"]).read_text(encoding="utf-8")
        )
        algorithm, pool = _algorithm(checkpoint["case"])
        algorithm.initialize()
        source = AnsatzStructure.create(
            checkpoint["ansatz_indices"],
            checkpoint["ansatz_coefficients"],
            checkpoint["iteration_counts"],
        )
        blocks = recover_dvg_blocks(
            pool,
            source.indices,
            source.coefficients,
            source.cumulative_parameter_counts,
        )
        representatives: dict[str, Any] = {}
        for candidate in enumerate_candidates(pool, blocks):
            representatives.setdefault(candidate.equivalence_class_id, candidate)
        candidates = tuple(representatives.values())
        kind_histogram = Counter(candidate.kind for candidate in candidates)
        source_dimension_histogram: Counter[str] = Counter()
        exact_relation_histogram: Counter[str] = Counter()
        semantic_ids: set[str] = set()
        numerical_ids: set[str] = set()
        composition_count = 0
        for candidate in candidates:
            exact = exact_atomic_constraint(candidate)
            plan = compose_registered_candidates(source, blocks, [candidate])
            if exact.system.rank != (
                len(candidate.transformation.source_slots)
                - len(candidate.transformation.target_slots)
            ):
                raise V41SemanticAuditError("atomic exact constraint has wrong nullity")
            semantic_ids.add(plan.state.constraint_semantic_id)
            numerical_ids.add(plan.state.constraint_numerical_id)
            composition_count += 1
            if candidate.kind in {"mvp-to-ovp-sum", "mvp-to-ovp-diff"}:
                relation = candidate.exact_generator_relation
                if relation is None:
                    raise V41SemanticAuditError("OVP candidate lacks exact relation")
                source_dimension_histogram[str(len(relation))] += 1
                exact_relation_histogram[",".join(str(value) for value in relation)] += 1

        old_summary = json.loads(
            (ROOT / case_record["v4_summary_path"]).read_text(encoding="utf-8")
        )
        checks = {
            "catalog_cardinality_preserved": len(candidates)
            == old_summary["catalog"]["candidate_count"],
            "all_atomic_semantics_replayed": composition_count == len(candidates),
            "semantic_ids_unique": len(semantic_ids) == len(candidates),
            "numerical_ids_unique": len(numerical_ids) == len(candidates),
            "three_constituent_ovp_supported": source_dimension_histogram["3"] > 0
            if case_record["case_id"].startswith("h6")
            else source_dimension_histogram["3"] == 0,
        }
        failures = [name for name, passed in checks.items() if not passed]
        if failures:
            raise V41SemanticAuditError(
                f"{case_record['case_id']} S2 checks failed: {', '.join(failures)}"
            )
        cases.append(
            {
                "case_id": case_record["case_id"],
                "checkpoint_sha256": case_record["checkpoint_sha256"],
                "block_count": len(blocks),
                "candidate_count": len(candidates),
                "kind_histogram": dict(sorted(kind_histogram.items())),
                "ovp_source_dimension_histogram": dict(
                    sorted(source_dimension_histogram.items())
                ),
                "exact_relation_histogram": dict(sorted(exact_relation_histogram.items())),
                "atomic_semantic_replay_count": composition_count,
                "unknown_semantic_failure_count": 0,
                "checks": checks,
            }
        )
    result: dict[str, Any] = {
        "schema_version": "1.0.0",
        "artifact_kind": "v4.1-s2-exact-semantic-audit",
        "protocol_id": manifest["protocol_id"],
        "s0_manifest_sha256": s0["manifest_sha256"],
        "cases": cases,
        "passed": True,
        "claim_boundary": (
            "Exact atomic and single-candidate composition replay only; no Hessian "
            "screening, search, resource selection, or VQE execution."
        ),
    }
    result["artifact_digest"] = _digest(result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--artifact-path", type=Path)
    arguments = parser.parse_args()
    result = run(arguments.manifest)
    if arguments.artifact_path is not None:
        _write_exclusive(arguments.artifact_path, result)
    print(
        json.dumps(
            {
                "passed": result["passed"],
                "cases": {
                    case["case_id"]: case["candidate_count"] for case in result["cases"]
                },
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()

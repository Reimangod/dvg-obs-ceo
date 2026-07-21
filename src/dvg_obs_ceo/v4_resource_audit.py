"""Recount and replay the V4-S5 full-resource Pareto selector."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import subprocess
from typing import Any

from .baseline import ROOT
from .block_ir import enumerate_candidates, recover_dvg_blocks
from .composition import compose_registered_candidates
from .global_selector import GlobalResourceCandidate, select_global_candidates
from .resources import (
    AnsatzStructure,
    evaluate_full_circuit_resources,
    paper_era_backend,
)
from .s8_probe import _algorithm
from .telemetry import ResourceSnapshot
from .v3_gradient_audit import _load_and_verify
from .v3_protocol import _write_exclusive
from .v4_protocol import audit_manifest


PROTOCOL_TAG = "dvg-obs-v4-s5-full-resource-v1"
SEARCH_ARTIFACT = ROOT / "artifacts" / "v4" / "s4-deterministic-search-audit-v1.json"
REQUIRED_THREADS = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
}


class V4ResourceAuditError(RuntimeError):
    """Raised when full-resource or selector replay evidence fails."""


def _git(*arguments: str) -> str:
    return subprocess.check_output(["git", "-C", str(ROOT), *arguments], text=True).strip()


def verify_freeze() -> dict[str, Any]:
    head = _git("rev-parse", "HEAD")
    tagged = _git("rev-parse", f"{PROTOCOL_TAG}^{{}}")
    dirty = _git("status", "--porcelain")
    threads = {name: os.environ.get(name) for name in REQUIRED_THREADS}
    if head != tagged or dirty or threads != REQUIRED_THREADS:
        raise V4ResourceAuditError(
            f"V4-S5 requires clean tagged code and canonical threads: head={head}, "
            f"tag={tagged}, dirty={bool(dirty)}, threads={threads}"
        )
    return {"head": head, "protocol_tag": PROTOCOL_TAG, "threads": threads}


def _snapshot(record: dict[str, Any]) -> ResourceSnapshot:
    return ResourceSnapshot(**record)


def _run_case(
    case_id: str,
    checkpoint: dict[str, Any],
    search_case: dict[str, Any],
) -> dict[str, Any]:
    _, pool = _algorithm(case_id)
    backend = paper_era_backend()
    source = AnsatzStructure.create(
        checkpoint["ansatz_indices"], checkpoint["ansatz_coefficients"], checkpoint["iteration_counts"]
    )
    before = evaluate_full_circuit_resources(
        pool, source, backend, coefficient_policy="deterministic-structural"
    ).snapshot
    blocks = recover_dvg_blocks(
        pool, source.indices, source.coefficients, source.cumulative_parameter_counts
    )
    representatives: dict[str, Any] = {}
    for candidate in enumerate_candidates(pool, blocks):
        representatives.setdefault(candidate.equivalence_class_id, candidate)
    by_id = {candidate.candidate_id: candidate for candidate in representatives.values()}
    resource_cache: dict[tuple[tuple[int, ...], tuple[int, ...]], ResourceSnapshot] = {}
    candidates: list[GlobalResourceCandidate] = []
    records: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for search_record in search_case["exhaustive"]["records"]:
        evaluation = search_record["evaluation"]
        if evaluation["status"] != "valid":
            continue
        candidate_ids = tuple(search_record["candidate_ids"])
        try:
            plan = compose_registered_candidates(
                source, blocks, tuple(by_id[identifier] for identifier in candidate_ids)
            )
            cache_key = (plan.target_indices, plan.target_iteration_counts)
            if cache_key not in resource_cache:
                target = AnsatzStructure.create(
                    plan.target_indices,
                    [1.0] * len(plan.target_indices),
                    plan.target_iteration_counts,
                )
                resource_cache[cache_key] = evaluate_full_circuit_resources(
                    pool, target, backend, coefficient_policy="deterministic-structural"
                ).snapshot
            after = resource_cache[cache_key]
            candidate = GlobalResourceCandidate(
                candidate_ids,
                evaluation["constraint_semantic_id"],
                evaluation["constraint_numerical_id"],
                float(evaluation["predicted_loss_hartree"]),
                after,
            )
            candidates.append(candidate)
            records.append({
                "candidate_ids": list(candidate_ids),
                "constraint_semantic_id": candidate.constraint_semantic_id,
                "constraint_numerical_id": candidate.constraint_numerical_id,
                "predicted_loss_hartree": candidate.predicted_loss_hartree,
                "resources": asdict(after),
                "resource_delta": {
                    field: int(getattr(after, field) - getattr(before, field))
                    for field in ("parameter_count", "cnot_count", "cnot_depth", "total_depth")
                },
            })
        except Exception as error:
            failures.append({"candidate_ids": list(candidate_ids), "error": repr(error)})
    selection = select_global_candidates(candidates, before)
    replay = select_global_candidates(list(reversed(candidates)), before)
    return {
        "case_id": case_id,
        "source_resources": asdict(before),
        "valid_search_state_count": sum(
            record["evaluation"]["status"] == "valid"
            for record in search_case["exhaustive"]["records"]
        ),
        "full_recount_state_count": len(records),
        "unique_circuit_recounts": len(resource_cache),
        "failures": failures,
        "selection": selection,
        "selector_replay_equal": selection == replay,
        "records": records,
    }


def run(artifact_path: Path) -> dict[str, Any]:
    freeze = verify_freeze()
    s0 = audit_manifest()
    search = json.loads(SEARCH_ARTIFACT.read_text(encoding="utf-8"))
    if not search["passed"]:
        raise V4ResourceAuditError("S4 search evidence did not pass")
    _, _, checkpoints = _load_and_verify(ROOT / "manifests" / "v3-s1-gradient-audit-v1.json")
    search_by_case = {case["case_id"]: case for case in search["cases"]}
    cases = [
        _run_case(case_id, checkpoints[case_id], search_by_case[case_id])
        for case_id in sorted(checkpoints)
    ]
    checks = {
        "s0_audit": s0["passed"],
        "s4_input": search["passed"],
        "all_valid_states_recounted": all(
            case["valid_search_state_count"] == case["full_recount_state_count"]
            for case in cases
        ),
        "no_resource_failures": all(not case["failures"] for case in cases),
        "selector_replay": all(case["selector_replay_equal"] for case in cases),
        "formal_selection_matches_s4": all(
            case["selection"]["eligible_count"]
            == len(search_by_case[case["case_id"]]["exhaustive_eligible_semantic_ids"])
            for case in cases
        ),
        "top_k_bounds": all(
            len(case["selection"]["unique_attempt_semantic_ids"]) <= 4 for case in cases
        ),
    }
    failed = [name for name, passed in checks.items() if not passed]
    artifact = {
        "schema_version": "1.0.0",
        "artifact_kind": "v4-s5-full-resource-pareto-audit",
        "execution_freeze": freeze,
        "passed": not failed,
        "checks": checks,
        "failed_checks": failed,
        "cases": cases,
        "work": {
            "full_resource_recounts": sum(case["unique_circuit_recounts"] + 1 for case in cases),
            "vqe_energy_evaluations": 0,
            "ordinary_gsd_adapt_iterations": 0,
            "ceo_star_adapt_iterations": 0,
            "paper_measurement_cost": None,
        },
        "claim_boundary": (
            "All H2/H4 surrogate states are structurally recounted for integration evidence. "
            "Only states passing the preregistered prediction and componentwise resource guards "
            "are formal selector inputs; actual energy is never a ranking input."
        ),
    }
    if failed:
        raise V4ResourceAuditError("V4-S5 audit failed: " + ", ".join(failed))
    _write_exclusive(artifact_path, artifact)
    return artifact


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-path", type=Path, required=True)
    arguments = parser.parse_args()
    result = run(arguments.artifact_path)
    print(json.dumps({
        "passed": result["passed"],
        "work": result["work"],
        "cases": [
            {
                "case_id": case["case_id"],
                "states": case["full_recount_state_count"],
                "unique_circuits": case["unique_circuit_recounts"],
                "eligible": case["selection"]["eligible_count"],
                "pareto": len(case["selection"]["pareto_semantic_ids"]),
            }
            for case in result["cases"]
        ],
    }, sort_keys=True))


if __name__ == "__main__":
    main()

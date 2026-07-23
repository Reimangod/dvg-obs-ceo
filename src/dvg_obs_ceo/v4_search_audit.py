"""Exhaustive equivalence audit for the deterministic V4-S4 search."""

from __future__ import annotations

import argparse
from collections import Counter
import json
import math
import os
from pathlib import Path
import subprocess
from typing import Any

from .baseline import ROOT
from .block_ir import enumerate_candidates, recover_dvg_blocks
from .composition import GlobalCompatibilityError, compose_registered_candidates
from .joint_prediction import JointPredictionError, joint_obs_prediction, secant_pairs_from_capture
from .resources import AnsatzStructure
from .s8_probe import _algorithm
from .search import SearchCandidate, SearchConfig, SearchEvaluation, deterministic_search
from .v3_gradient_audit import _load_and_verify
from .v3_protocol import _write_exclusive
from .v4_protocol import audit_manifest


PROTOCOL_TAG = "dvg-obs-v4-s4-search-v1"
REQUIRED_THREADS = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
}


class V4SearchAuditError(RuntimeError):
    """Raised when search completeness or execution-freeze checks fail."""


def _git(*arguments: str) -> str:
    return subprocess.check_output(["git", "-C", str(ROOT), *arguments], text=True).strip()


def verify_freeze() -> dict[str, Any]:
    head = _git("rev-parse", "HEAD")
    tagged = _git("rev-parse", f"{PROTOCOL_TAG}^{{}}")
    dirty = _git("status", "--porcelain")
    threads = {name: os.environ.get(name) for name in REQUIRED_THREADS}
    if head != tagged or dirty or threads != REQUIRED_THREADS:
        raise V4SearchAuditError(
            f"V4-S4 requires clean tagged code and canonical threads: head={head}, "
            f"tag={tagged}, dirty={bool(dirty)}, threads={threads}"
        )
    return {"head": head, "protocol_tag": PROTOCOL_TAG, "threads": threads}


def _run_case(case_id: str, checkpoint: dict[str, Any]) -> dict[str, Any]:
    _, pool = _algorithm(case_id)
    source = AnsatzStructure.create(
        checkpoint["ansatz_indices"],
        checkpoint["ansatz_coefficients"],
        checkpoint["iteration_counts"],
    )
    blocks = recover_dvg_blocks(
        pool, source.indices, source.coefficients, source.cumulative_parameter_counts
    )
    representatives: dict[str, Any] = {}
    for candidate in enumerate_candidates(pool, blocks):
        representatives.setdefault(candidate.equivalence_class_id, candidate)
    by_id = {candidate.candidate_id: candidate for candidate in representatives.values()}
    search_candidates = tuple(
        SearchCandidate(candidate.candidate_id, candidate.source_block_id)
        for candidate in by_id.values()
    )
    internal = secant_pairs_from_capture(
        checkpoint["hessian_capture"]["secant_pairs"], required_source="internal-bfgs"
    )

    def evaluator(candidate_ids: tuple[str, ...]) -> SearchEvaluation:
        try:
            plan = compose_registered_candidates(
                source, blocks, tuple(by_id[identifier] for identifier in candidate_ids)
            )
        except GlobalCompatibilityError as error:
            return SearchEvaluation(
                "semantic-infeasible", None, None, None, reason=str(error)
            )
        try:
            prediction = joint_obs_prediction(
                checkpoint["ansatz_coefficients"],
                checkpoint["gradient"],
                checkpoint["recycled_inverse_hessian"],
                plan.transformation,
                internal_pairs=internal,
                held_out_pairs=(),
            )
        except JointPredictionError as error:
            return SearchEvaluation(
                "candidate-numerical-failure", None, None, None, reason=str(error)
            )
        return SearchEvaluation(
            "valid",
            plan.state.constraint_semantic_id,
            plan.state.constraint_numerical_id,
            float(prediction["predicted_change_from_current_hartree"]),
        )

    limits = SearchConfig(math.inf, 100_000, 100_000, 100_000)
    bounded_limits = SearchConfig(1e-4, 100_000, 100_000, 100_000)
    exhaustive = deterministic_search(search_candidates, evaluator, limits)
    bounded = deterministic_search(search_candidates, evaluator, bounded_limits)
    exhaustive_eligible = sorted(
        str(record["evaluation"]["constraint_semantic_id"])
        for record in exhaustive["records"]
        if record["evaluation"]["status"] == "valid"
        and record["evaluation"]["predicted_loss_hartree"] <= 1e-4
    )
    group_sizes = Counter(candidate.group_id for candidate in search_candidates)
    expected_states = math.prod(size + 1 for size in group_sizes.values()) - 1
    return {
        "case_id": case_id,
        "candidate_count": len(search_candidates),
        "group_count": len(group_sizes),
        "group_sizes": dict(sorted(group_sizes.items())),
        "expected_exhaustive_states": expected_states,
        "exhaustive": exhaustive,
        "bounded": bounded,
        "exhaustive_eligible_semantic_ids": exhaustive_eligible,
        "eligible_sets_equal": bounded["eligible_semantic_ids"] == exhaustive_eligible,
    }


def run(artifact_path: Path) -> dict[str, Any]:
    freeze = verify_freeze()
    s0 = audit_manifest()
    _, _, checkpoints = _load_and_verify(
        ROOT / "manifests" / "v3-s1-gradient-audit-v1.json"
    )
    cases = [_run_case(case_id, checkpoints[case_id]) for case_id in sorted(checkpoints)]
    checks = {
        "s0_audit": s0["passed"],
        "exhaustive_state_counts": all(
            case["exhaustive"]["counts"]["completed"]
            == case["expected_exhaustive_states"]
            for case in cases
        ),
        "exhaustive_status": all(case["exhaustive"]["status"] == "exhaustive" for case in cases),
        "bounded_not_truncated": all(
            case["bounded"]["status"] in {"exhaustive", "surrogate-complete"}
            for case in cases
        ),
        "eligible_sets_equal": all(case["eligible_sets_equal"] for case in cases),
        "no_numerical_failures": all(
            case[mode]["counts"]["candidate_numerical_failures"] == 0
            for case in cases for mode in ("exhaustive", "bounded")
        ),
        "canonical_no_duplicate_evaluations": all(
            len({tuple(record["candidate_ids"]) for record in case["exhaustive"]["records"]})
            == len(case["exhaustive"]["records"])
            for case in cases
        ),
    }
    failed = [name for name, passed in checks.items() if not passed]
    work = {
        "quadratic_solves": sum(
            case[mode]["counts"]["quadratic_solves"]
            for case in cases for mode in ("exhaustive", "bounded")
        ),
        "vqe_energy_evaluations": 0,
        "ordinary_gsd_adapt_iterations": 0,
        "ceo_star_adapt_iterations": 0,
        "paper_measurement_cost": None,
    }
    artifact = {
        "schema_version": "1.0.0",
        "artifact_kind": "v4-s4-deterministic-search-audit",
        "execution_freeze": freeze,
        "passed": not failed,
        "checks": checks,
        "failed_checks": failed,
        "screening_budget_hartree": 1e-4,
        "cases": cases,
        "work": work,
        "claim_boundary": (
            "Completeness is proved only for the frozen quadratic surrogate and registered "
            "H2/H4 candidate catalog. No actual energy, VQE optimum, or molecular superiority "
            "claim is made."
        ),
    }
    if failed:
        raise V4SearchAuditError("V4-S4 audit failed: " + ", ".join(failed))
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
                "states": case["expected_exhaustive_states"],
                "eligible": len(case["exhaustive_eligible_semantic_ids"]),
                "bounded_counts": case["bounded"]["counts"],
            }
            for case in result["cases"]
        ],
    }, sort_keys=True))


if __name__ == "__main__":
    main()

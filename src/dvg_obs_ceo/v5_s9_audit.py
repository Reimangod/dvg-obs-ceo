"""Independent S9 audit and strict V4.1 frontier comparison."""

from __future__ import annotations

from dataclasses import asdict
import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import numpy as np

from .baseline import ROOT
from .block_ir import enumerate_candidates, recover_dvg_blocks
from .composition import compose_registered_candidates
from .identity import canonical_json_bytes
from .multisystem_checkpoint import _algorithm
from .resources import AnsatzStructure, evaluate_full_circuit_resources, paper_era_backend
from .s8_probe import _state_vector
from .v4_lih import _energy, _gradient
from .v5_s8_lih_energy_aware_audit import _selected_coordinates
from .v5_s8_lih_multitrajectory import _load_checkpoint_path
from .v5_ledger import versioned_id


CASES = {
    "h6-1.5": {
        "result": ROOT / "artifacts/v5/s9/h6-1.5-v1/summary.json",
        "checkpoint": ROOT / "artifacts/full-figures/ceo-star/h6-1.5/checkpoint.json",
        "v4": ROOT / "artifacts/v4.1/multisystem/h6-1.5/summary.json",
        "tag": "dvg-obs-v5-h6-1p5-development-v1",
    },
    "h6-3.0": {
        "result": ROOT / "artifacts/v5/s9/h6-3.0-v1/summary.json",
        "checkpoint": ROOT / "artifacts/full-figures/ceo-star/h6-3.0/checkpoint.json",
        "v4": ROOT / "artifacts/v4.1/multisystem/h6-3.0/summary.json",
        "tag": "dvg-obs-v5-h6-3p0-development-v1",
    },
    "beh2-3.0": {
        "result": ROOT / "artifacts/v5/s9/beh2-3.0-v1/summary.json",
        "checkpoint": ROOT / "artifacts/full-figures/ceo-star/beh2-3.0/checkpoint.json",
        "v4": ROOT / "artifacts/v4.1/multisystem/beh2-3.0/summary.json",
        "tag": "dvg-obs-v5-beh2-3p0-development-v1",
    },
}
RESOURCE_FIELDS = (
    "cnot_count",
    "parameter_count",
    "total_depth",
    "cnot_depth",
    "logical_block_count",
)


class V5S9AuditError(RuntimeError):
    pass


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _sum_work(items: list[dict[str, int]]) -> dict[str, int]:
    names = set().union(*(item.keys() for item in items))
    return {
        name: sum(int(item.get(name, 0)) for item in items)
        for name in sorted(names)
    }


def _strict_pair(v5: dict[str, Any], v4: dict[str, Any]) -> bool:
    return bool(
        v5["energy_increase_hartree"] <= v4["energy_increase_hartree"]
        and all(v5[field] <= v4[field] for field in RESOURCE_FIELDS)
        and (
            v5["cnot_count"] < v4["cnot_count"]
            or v5["parameter_count"] < v4["parameter_count"]
        )
    )


def _point(resources: dict[str, Any], energy: float, identifier: str) -> dict[str, Any]:
    return {
        "id": identifier,
        "energy_increase_hartree": float(energy),
        **{field: int(resources[field]) for field in RESOURCE_FIELDS},
    }


def run_audit(case_id: str, *, recompute_quantum: bool = True) -> dict[str, Any]:
    if case_id not in CASES:
        raise V5S9AuditError(f"unknown case: {case_id}")
    paths = CASES[case_id]
    summary = json.loads(paths["result"].read_text(encoding="utf-8"))
    content = dict(summary)
    observed_summary_digest = content.pop("result_digest")
    result = summary["result"]
    result_content = dict(result)
    observed_result_digest = result_content.pop("result_digest")
    branches = summary["branch_records"]
    checkpoint = _load_checkpoint_path(paths["checkpoint"])
    v4 = json.loads(paths["v4"].read_text(encoding="utf-8"))

    exact_sum = _sum_work([record["work"] for record in branches])
    catalog_entries = result["catalog_work_by_path"]
    catalog_sum = _sum_work(list(catalog_entries.values()))
    aggregate_sum = _sum_work([exact_sum, catalog_sum])
    diagnostics = summary["catalog_diagnostics_by_path"]
    catalog_checks = []
    for path_id, work in catalog_entries.items():
        diagnostic = next(iter(diagnostics[path_id].values()))
        catalog_checks.append(
            work["expanded_search_states"]
            == diagnostic["joint_search"]["counts"]["expanded"]
            and work["full_resource_recounts"]
            == 1 + diagnostic["selection"]["input_count"]
            and work["exact_vqe_attempts"] == 0
        )

    v5_points = [
        _point(
            record["attempt_record"]["physical_resources"],
            record["decision"]["candidate_energy_hartree"]
            - summary["source_energy_hartree"],
            record["proposal_id"],
        )
        for record in branches
        if record["decision"]["accepted"]
    ]
    v4_points = [
        _point(
            attempt["physical_resources"]["snapshot"],
            float((attempt["fallback"] or attempt["primary"])["energy_hartree"])
            - summary["source_energy_hartree"],
            attempt["constraint_semantic_id"],
        )
        for attempt in v4["attempts"]
        if attempt["transaction_status"] == "accepted"
    ]
    strict_pairs = [
        {"v5_id": left["id"], "v4_id": right["id"]}
        for left in v5_points
        for right in v4_points
        if _strict_pair(left, right)
    ]
    code_commit = subprocess.check_output(
        ["git", "-C", str(ROOT), "rev-parse", "dvg-obs-v5-s9-frozen-code-v1^{}"],
        text=True,
    ).strip()
    child_path_ids = {
        attempt["child_path_id"]
        for round_record in result["trajectory"]
        for attempt in round_record["attempts"]
        if attempt["accepted"]
    }
    source_parent_ids = {
        record["parent_path_id"] for record in branches
    } - child_path_ids
    expected_execution_freeze = {
        "head": code_commit,
        "code_tag": "dvg-obs-v5-s9-frozen-code-v1",
        "code_commit": code_commit,
        "checks": {
            "manifest_s8_hash": True,
            "checkpoint_hash": True,
            "output_absent": True,
        },
    }
    expected_source_path_id = versioned_id(
        "path-v5",
        {
            "runner_version": summary["runner_version"],
            "execution_freeze": expected_execution_freeze,
            "checkpoint_digest": checkpoint["checkpoint_digest"],
            "role": "source",
        },
    )
    checks = {
        "summary_digest": observed_summary_digest == _digest(content),
        "nested_result_digest": observed_result_digest == _digest(result_content),
        "case_identity": summary["case_id"] == case_id,
        "result_tag_is_ancestor": subprocess.run(
            [
                "git", "-C", str(ROOT), "merge-base", "--is-ancestor",
                paths["tag"], "HEAD",
            ],
            check=False,
        ).returncode == 0,
        "execution_freeze_cryptographically_bound_to_source_path": (
            source_parent_ids == {expected_source_path_id}
        ),
        "source_runtime_unchanged": summary["source_runtime_unchanged"] is True,
        "source_resource_identity": (
            summary["source_resources"] == checkpoint["resources"]["snapshot"]
            == v4["checkpoint"]["resources"]["snapshot"]
        ),
        "bounded_exact_attempts": (
            0 < result["exact_attempts"] <= 6
            and result["exact_attempts"] == len(branches)
            and result["unique_exact_tasks"] == len(branches)
        ),
        "bounded_rounds_and_width": (
            0 < len(result["trajectory"]) <= 3
            and all(
                len(round_record["active_path_ids_after"]) <= 2
                for round_record in result["trajectory"]
            )
        ),
        "all_branch_parents_isolated": all(
            record["parent_runtime_unchanged"] is True for record in branches
        ),
        "all_physical_structural_recounts": all(
            record["attempt_record"]["physical_resources"]
            == record["attempt_record"]["structural_resources"]
            for record in branches
        ),
        "accepted_branches_pass_all_gates": all(
            not record["decision"]["accepted"]
            or all(record["decision"]["checks"].values())
            for record in branches
        ),
        "rejected_branches_have_reasons": all(
            record["decision"]["accepted"]
            or bool(record["decision"]["rejection_reasons"])
            for record in branches
        ),
        "chemical_accuracy_guard": (
            summary["energy_guard"]["chemical_accuracy_enforced"] is True
            and all(
                record["decision"]["candidate_energy_hartree"]
                <= checkpoint["exact_energy_hartree"]
                + checkpoint["chemical_accuracy_hartree"]
                for record in branches
                if record["decision"]["accepted"]
            )
        ),
        "exact_attempt_work_complete": exact_sum == result["exact_attempt_work"],
        "catalog_work_complete": catalog_sum == result["catalog_work"],
        "aggregate_work_complete": aggregate_sum == result["aggregate_work"],
        "all_catalog_work_matches_diagnostics": all(catalog_checks),
        "paper_measurement_cost_undefined": (
            summary["paper_measurement_cost"] is None
            and result["paper_measurement_cost"] is None
        ),
    }

    recomputations: list[dict[str, Any]] = []
    if recompute_quantum:
        algorithm, pool = _algorithm(checkpoint["case"])
        algorithm.initialize()
        source = AnsatzStructure.create(
            checkpoint["ansatz_indices"],
            checkpoint["ansatz_coefficients"],
            checkpoint["iteration_counts"],
        )
        source_state = _state_vector(
            algorithm, source.coefficients, source.indices
        )
        source_energy = _energy(
            algorithm, np.asarray(source.coefficients), source.indices
        )
        source_resources = evaluate_full_circuit_resources(
            pool, source, paper_era_backend()
        ).snapshot
        checks.update(
            {
                "independent_source_energy": (
                    abs(source_energy - checkpoint["energy_hartree"]) <= 1e-10
                ),
                "independent_source_state": (
                    hashlib.sha256(
                        np.asarray(source_state, dtype=">c16").tobytes()
                    ).hexdigest()
                    == checkpoint["statevector_sha256"]
                ),
                "independent_source_resources": (
                    asdict(source_resources) == checkpoint["resources"]["snapshot"]
                ),
            }
        )
        child_by_proposal = {
            attempt["proposal_id"]: attempt["child_path_id"]
            for round_record in result["trajectory"]
            for attempt in round_record["attempts"]
            if attempt["accepted"]
        }
        source_parents = {
            record["parent_path_id"] for record in branches
        } - set(child_by_proposal.values())
        if len(source_parents) != 1:
            raise V5S9AuditError("cannot identify unique source path")
        ansatz_by_path = {next(iter(source_parents)): source}
        for record in branches:
            parent = ansatz_by_path[record["parent_path_id"]]
            blocks = recover_dvg_blocks(
                pool,
                parent.indices,
                parent.coefficients,
                parent.cumulative_parameter_counts,
            )
            representatives: dict[str, Any] = {}
            for candidate in enumerate_candidates(pool, blocks):
                representatives.setdefault(candidate.equivalence_class_id, candidate)
            by_id = {
                candidate.candidate_id: candidate
                for candidate in representatives.values()
            }
            attempt = record["attempt_record"]
            plan = compose_registered_candidates(
                parent,
                blocks,
                tuple(
                    by_id[candidate_id]
                    for candidate_id in attempt["atomic_candidate_ids"]
                ),
            )
            coordinates = _selected_coordinates(attempt)
            target = AnsatzStructure.create(
                plan.target_indices, coordinates, plan.target_iteration_counts
            )
            energy = _energy(algorithm, coordinates, plan.target_indices)
            gradient = _gradient(algorithm, coordinates, plan.target_indices)
            resources = evaluate_full_circuit_resources(
                pool, target, paper_era_backend()
            ).snapshot
            recomputations.append(
                {
                    "proposal_id": record["proposal_id"],
                    "accepted": record["decision"]["accepted"],
                    "energy_difference_hartree": abs(
                        energy - record["decision"]["candidate_energy_hartree"]
                    ),
                    "gradient_infinity": float(np.max(np.abs(gradient))),
                    "resources": asdict(resources),
                }
            )
            if record["decision"]["accepted"]:
                ansatz_by_path[child_by_proposal[record["proposal_id"]]] = target
        checks.update(
            {
                "independent_all_branch_energies": all(
                    item["energy_difference_hartree"] <= 1e-10
                    for item in recomputations
                ),
                "independent_accepted_gradients": all(
                    not item["accepted"] or item["gradient_infinity"] <= 1e-8
                    for item in recomputations
                ),
                "independent_all_branch_resources": all(
                    item["resources"]
                    == branches[index]["attempt_record"]["physical_resources"]
                    for index, item in enumerate(recomputations)
                ),
            }
        )

    audit = {
        "schema_version": "1.0.0",
        "artifact_kind": "v5-s9-independent-case-audit",
        "case_id": case_id,
        "passed": all(checks.values()),
        "checks": checks,
        "independent_recomputations": recomputations,
        "strict_primary_success": bool(strict_pairs),
        "strict_primary_success_pairs": strict_pairs,
        "v5_accepted_frontier_inputs": v5_points,
        "v4_1_accepted_frontier_inputs": v4_points,
        "winner": {
            "resources": result["winner_resources"],
            "energy_increase_hartree": (
                result["winner_cumulative_energy_increase_hartree"]
            ),
        },
        "work": result["aggregate_work"],
        "provenance_incident": {
            "type": "human-readable-execution-freeze-serialization-omission",
            "scientific_result_affected": False,
            "reexecution_required": False,
            "mitigation": (
                "The exact freeze record is independently reconstructed and "
                "verified against the cryptographically bound source path ID."
            ),
        },
        "claim_boundary": (
            "Development-case exact-statevector comparison only. Strict success "
            "requires no larger actual energy increase and componentwise nonworse "
            "guarded resources with a strict CNOT or parameter improvement."
        ),
        "paper_measurement_cost": None,
    }
    audit["audit_digest"] = _digest(audit)
    if not audit["passed"]:
        failed = [name for name, passed in checks.items() if not passed]
        raise V5S9AuditError(
            f"{case_id} audit failed: " + ", ".join(failed)
        )
    return audit


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("case_id", choices=tuple(CASES))
    parser.add_argument("--no-quantum", action="store_true")
    arguments = parser.parse_args()
    audit = run_audit(
        arguments.case_id, recompute_quantum=not arguments.no_quantum
    )
    output = ROOT / f"artifacts/v5/s9/{arguments.case_id}-v1-audit.json"
    if output.exists():
        raise FileExistsError(output)
    output.write_text(
        json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "case_id": arguments.case_id,
                "passed": audit["passed"],
                "checks": len(audit["checks"]),
                "strict_primary_success": audit["strict_primary_success"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()

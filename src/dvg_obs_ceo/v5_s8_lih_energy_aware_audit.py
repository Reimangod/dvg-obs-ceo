"""Independent audit of the accounting-corrected LiH energy-aware beam run."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import subprocess
from typing import Any

import numpy as np

from .baseline import ROOT
from .block_ir import enumerate_candidates, recover_dvg_blocks
from .composition import compose_registered_candidates
from .identity import canonical_json_bytes
from .resources import AnsatzStructure, evaluate_full_circuit_resources, paper_era_backend
from .s10_lih import _algorithm as _lih_algorithm
from .v4_lih import _energy, _gradient
from .v5_s8_lih_multitrajectory_audit import _selected_coordinates
from .v5_s8_lih_width1 import _load_checkpoint


RESULT = ROOT / "artifacts/v5/s8/lih-energy-aware-width2-v2/summary.json"
OUTPUT = ROOT / "artifacts/v5/s8/lih-energy-aware-width2-v2-audit.json"
CODE_TAG = "dvg-obs-v5-s8-lih-energy-aware-width2-code-v2"


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _sum_work(items: list[dict[str, int]]) -> dict[str, int]:
    names = set().union(*(item.keys() for item in items))
    return {
        name: sum(int(item.get(name, 0)) for item in items)
        for name in sorted(names)
    }


def run_audit(
    *,
    recompute_quantum: bool = True,
    result_path=RESULT,
    code_tag: str = CODE_TAG,
    expected_attempts: int = 4,
    expected_rounds: int = 2,
    expected_active_width: int = 2,
    expected_terminal_catalogs: int = 1,
    terminal_catalog_expected_work: tuple[int, int] | None = (17, 1),
    scientific_status: str = "valid-accounting-complete-no-endpoint-improvement",
) -> dict[str, Any]:
    summary = json.loads(result_path.read_text(encoding="utf-8"))
    content = dict(summary)
    observed_summary_digest = content.pop("result_digest")
    result = summary["result"]
    result_content = dict(result)
    observed_result_digest = result_content.pop("result_digest")
    branches = summary["branch_records"]
    exact_sum = _sum_work([record["work"] for record in branches])
    catalog_entries = result["catalog_work_by_path"]
    catalog_sum = _sum_work(list(catalog_entries.values()))
    total_sum = _sum_work([exact_sum, catalog_sum])
    diagnostics = summary["catalog_diagnostics_by_path"]
    catalog_diagnostic_checks = []
    for path_id, work in catalog_entries.items():
        diagnostic = next(iter(diagnostics[path_id].values()))
        catalog_diagnostic_checks.append(
            work["expanded_search_states"]
            == diagnostic["joint_search"]["counts"]["expanded"]
            and work["full_resource_recounts"]
            == 1 + diagnostic["selection"]["input_count"]
            and work["exact_vqe_attempts"] == 0
        )
    terminal_paths = sorted(set(catalog_entries) - {
        record["parent_path_id"] for record in branches
    })
    checks = {
        "summary_digest": observed_summary_digest == _digest(content),
        "nested_result_digest": observed_result_digest == _digest(result_content),
        "code_tag_is_ancestor": subprocess.run(
            ["git", "-C", str(ROOT), "merge-base", "--is-ancestor", code_tag, "HEAD"],
            check=False,
        ).returncode == 0,
        "source_runtime_unchanged": summary["source_runtime_unchanged"] is True,
        "expected_unique_exact_attempts": (
            result["exact_attempts"] == expected_attempts
            and result["unique_exact_tasks"] == expected_attempts
            and len(branches) == expected_attempts
        ),
        "all_exact_branches_accepted": all(
            record["decision"]["accepted"]
            and all(record["decision"]["checks"].values())
            for record in branches
        ),
        "branch_parents_isolated": all(
            record["parent_runtime_unchanged"] is True for record in branches
        ),
        "physical_structural_recounts": all(
            record["attempt_record"]["physical_resources"]
            == record["attempt_record"]["structural_resources"]
            for record in branches
        ),
        "source_relative_energy_budget": all(
            record["decision"]["candidate_energy_hartree"]
            - summary["source_energy_hartree"]
            <= 1e-4
            for record in branches
        ),
        "exact_attempt_work_complete": exact_sum == result["exact_attempt_work"],
        "catalog_work_complete": catalog_sum == result["catalog_work"],
        "aggregate_work_complete": total_sum == result["aggregate_work"],
        "catalog_work_matches_diagnostics": all(catalog_diagnostic_checks),
        "terminal_catalog_work_retained": (
            len(terminal_paths) == expected_terminal_catalogs
            and (
                terminal_catalog_expected_work is None
                or all(
                    catalog_entries[path_id]["expanded_search_states"]
                    == terminal_catalog_expected_work[0]
                    and catalog_entries[path_id]["full_resource_recounts"]
                    == terminal_catalog_expected_work[1]
                    for path_id in terminal_paths
                )
            )
        ),
        "energy_aware_beam_retained_expected_width": (
            result["config"]["beam_dominance"] == "resources-plus-energy"
            and len(result["trajectory"]) == expected_rounds
            and all(
                len(round_record["active_path_ids_after"]) == expected_active_width
                for round_record in result["trajectory"]
            )
        ),
        "known_endpoint_not_exceeded": (
            result["winner_resources"]["cnot_count"] == 58
            and result["winner_resources"]["parameter_count"] == 8
            and result["winner_resources"]["total_depth"] == 92
            and result["winner_resources"]["cnot_depth"] == 30
        ),
        "paper_measurement_cost_undefined": (
            summary["paper_measurement_cost"] is None
            and result["paper_measurement_cost"] is None
        ),
    }
    recomputations: list[dict[str, Any]] = []
    if recompute_quantum:
        checkpoint = _load_checkpoint()
        algorithm, pool, _ = _lih_algorithm()
        algorithm.initialize()
        source = AnsatzStructure.create(
            checkpoint["ansatz_indices"],
            checkpoint["ansatz_coefficients"],
            checkpoint["iteration_counts"],
        )
        child_by_proposal = {
            attempt["proposal_id"]: attempt["child_path_id"]
            for round_record in result["trajectory"]
            for attempt in round_record["attempts"]
            if attempt["accepted"]
        }
        source_parent_ids = {
            record["parent_path_id"] for record in branches
        } - set(child_by_proposal.values())
        if len(source_parent_ids) != 1:
            raise RuntimeError("cannot identify the unique source path")
        ansatz_by_path = {next(iter(source_parent_ids)): source}
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
                    "candidate_id": record["candidate_id"],
                    "energy_difference_hartree": abs(
                        energy - record["decision"]["candidate_energy_hartree"]
                    ),
                    "gradient_infinity": float(np.max(np.abs(gradient))),
                    "resources": asdict(resources),
                }
            )
            ansatz_by_path[child_by_proposal[record["proposal_id"]]] = target
        checks.update(
            {
                "independent_branch_energies": all(
                    item["energy_difference_hartree"] <= 1e-10
                    for item in recomputations
                ),
                "independent_branch_gradients": all(
                    item["gradient_infinity"] <= 1e-8 for item in recomputations
                ),
                "independent_branch_resources": all(
                    item["resources"]
                    == branches[index]["attempt_record"]["physical_resources"]
                    for index, item in enumerate(recomputations)
                ),
            }
        )
    audit = {
        "schema_version": "1.0.0",
        "artifact_kind": "v5-s8-lih-energy-aware-width2-v2-independent-audit",
        "passed": all(checks.values()),
        "checks": checks,
        "independent_branch_recomputations": recomputations,
        "scientific_result": {
            "status": scientific_status,
            "winner_energy_increase_hartree": (
                result["winner_cumulative_energy_increase_hartree"]
            ),
            "winner_resources": result["winner_resources"],
            "aggregate_work": result["aggregate_work"],
        },
        "interpretation": (
            "Energy-aware retention enabled the low-energy branch to continue and "
            "reach the same 58-CNOT endpoint, but two rounds did not exceed it."
        ),
        "claim_boundary": (
            "Known LiH calibration only. Work counters are implementation-defined "
            "and are not the paper Measurement Cost."
        ),
        "paper_measurement_cost": None,
    }
    audit["audit_digest"] = _digest(audit)
    if not audit["passed"]:
        failed = [name for name, passed in checks.items() if not passed]
        raise RuntimeError("energy-aware audit failed: " + ", ".join(failed))
    return audit


if __name__ == "__main__":
    audit = run_audit()
    if OUTPUT.exists():
        raise FileExistsError(OUTPUT)
    OUTPUT.write_text(
        json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {"passed": audit["passed"], "checks": len(audit["checks"])},
            sort_keys=True,
        )
    )

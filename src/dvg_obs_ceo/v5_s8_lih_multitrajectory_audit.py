"""Independent audit of the frozen LiH width-two calibration."""

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
from .v5_s8_lih_width1 import _load_checkpoint


RESULT = ROOT / "artifacts/v5/s8/lih-width2-multitrajectory-v1/summary.json"
OUTPUT = ROOT / "artifacts/v5/s8/lih-width2-multitrajectory-v1-audit.json"
CODE_TAG = "dvg-obs-v5-s8-lih-width2-code-v1"
RESOURCE_FIELDS = (
    "cnot_count",
    "parameter_count",
    "total_depth",
    "cnot_depth",
    "logical_block_count",
)


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _selected_coordinates(attempt: dict[str, Any]) -> np.ndarray:
    selected = attempt["selected_optimizer_path"]
    if selected == "recycled-obs":
        values = attempt["primary"]["coordinates"]
    elif selected == "least-squares-fallback":
        values = attempt["fallback"]["coordinates"]
    elif selected == "conditional-target-native-polishing":
        values = attempt["conditional_polishing"]["target_coordinates"]
    else:
        raise RuntimeError(f"unknown selected optimizer path: {selected}")
    return np.asarray(values, dtype=np.float64)


def _dominates(left: dict[str, Any], right: dict[str, Any]) -> bool:
    a = tuple(int(left[field]) for field in RESOURCE_FIELDS)
    b = tuple(int(right[field]) for field in RESOURCE_FIELDS)
    return all(x <= y for x, y in zip(a, b)) and any(x < y for x, y in zip(a, b))


def run_audit(*, recompute_quantum: bool = True) -> dict[str, Any]:
    summary = json.loads(RESULT.read_text(encoding="utf-8"))
    content = dict(summary)
    observed_digest = content.pop("result_digest")
    result = summary["result"]
    branches = summary["branch_records"]
    first_round = result["trajectory"][0]
    work_names = set(result["aggregate_work"])
    independently_summed_work = {
        name: sum(int(record["work"].get(name, 0)) for record in branches)
        for name in work_names
    }
    branch_resources = [
        record["attempt_record"]["physical_resources"] for record in branches
    ]
    checks = {
        "summary_digest": observed_digest == _digest(content),
        "code_tag_is_ancestor": subprocess.run(
            ["git", "-C", str(ROOT), "merge-base", "--is-ancestor", CODE_TAG, "HEAD"],
            check=False,
        ).returncode == 0,
        "source_runtime_unchanged": summary["source_runtime_unchanged"] is True,
        "two_unique_exact_attempts": (
            result["exact_attempts"] == 2
            and result["unique_exact_tasks"] == 2
            and len(branches) == 2
        ),
        "both_branches_accepted": all(
            record["decision"]["accepted"]
            and all(record["decision"]["checks"].values())
            for record in branches
        ),
        "parents_isolated": all(
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
        "rejected_work_not_hidden": (
            independently_summed_work == result["aggregate_work"]
        ),
        "beam_effectively_collapsed_to_one": (
            len(first_round["attempts"]) == 2
            and len(first_round["active_path_ids_after"]) == 1
        ),
        "collapse_explained_by_resource_dominance": (
            _dominates(branch_resources[0], branch_resources[1])
            or _dominates(branch_resources[1], branch_resources[0])
        ),
        "known_width_one_endpoint_reproduced": result["winner_resources"] == {
            "cnot_count": 58,
            "cnot_depth": 30,
            "counter_version": (
                "paper-era-full-circuit-resource-v1:"
                "paper-era-qasm-counter-a3f89d0"
            ),
            "logical_block_count": 8,
            "parameter_count": 8,
            "structure_digest": (
                "802e9bc3b364b62ee12c32adaec63c33"
                "a3614cebb3887a8763e8cee54555cc52"
            ),
            "total_depth": 92,
        },
        "stopped_without_threshold_relaxation": (
            result["stop_reason"] == "no-new-exact-task"
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
        blocks = recover_dvg_blocks(
            pool,
            source.indices,
            source.coefficients,
            source.cumulative_parameter_counts,
        )
        representatives: dict[str, Any] = {}
        for candidate in enumerate_candidates(pool, blocks):
            representatives.setdefault(candidate.equivalence_class_id, candidate)
        by_id = {
            candidate.candidate_id: candidate for candidate in representatives.values()
        }
        for record in branches:
            attempt = record["attempt_record"]
            plan = compose_registered_candidates(
                source,
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
                    item["resources"] == branch_resources[index]
                    for index, item in enumerate(recomputations)
                ),
            }
        )
    audit = {
        "schema_version": "1.0.0",
        "artifact_kind": "v5-s8-lih-width2-independent-audit",
        "passed": all(checks.values()),
        "checks": checks,
        "independent_branch_recomputations": recomputations,
        "scientific_result": {
            "status": "valid-negative-width-two-calibration",
            "reason": (
                "resource-only nondominance collapsed the nominal width-two beam "
                "to one path after the first round"
            ),
            "winner_energy_increase_hartree": (
                result["winner_cumulative_energy_increase_hartree"]
            ),
            "winner_resources": result["winner_resources"],
        },
        "claim_boundary": (
            "Known LiH calibration only. This run validates accounting and isolation "
            "but does not demonstrate a resource improvement beyond V4.1."
        ),
        "paper_measurement_cost": None,
    }
    audit["audit_digest"] = _digest(audit)
    if not audit["passed"]:
        failed = [name for name, passed in checks.items() if not passed]
        raise RuntimeError("width-two audit failed: " + ", ".join(failed))
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

"""PRA S5 outcome-free source generation and applicability census."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import random
import subprocess
import time
from typing import Any

import numpy as np

from dvg_obs_ceo.artifact_io import atomic_write_new_json
from dvg_obs_ceo.baseline import ROOT, _environment, _load_upstream, _nested_sum
from dvg_obs_ceo.block_ir import recover_dvg_blocks
from dvg_obs_ceo.identity import sha256_hex
from dvg_obs_ceo.resources import AnsatzStructure
from dvg_obs_ceo.v6_rank_adaptive.native_synthesis_pipeline import (
    NS1_OUTPUT,
    NS3_OUTPUT,
    NS4_OUTPUT,
    _compose_context,
    _primary_gate,
    _resource_delta,
)
from dvg_obs_ceo.v6_rank_adaptive.native_rank2_feasibility import (
    _qasm_resources,
)


S4_OUTPUT = ROOT / "artifacts/pra_path/s4/prior-art-novelty-audit-v1.json"
OUTPUT_ROOT = ROOT / "artifacts/pra_path/s5"
CENSUS_OUTPUT = OUTPUT_ROOT / "outcome-free-applicability-census-v1.json"
SOURCE_GRADIENT_TOLERANCE = 1e-8
REQUIRED_THREADS = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
}

DEVELOPMENT_CASES = (
    {
        "case_id": "h4-1.0",
        "molecule": "H4",
        "distance_angstrom": 1.0,
        "role": "development-low-cost-reproducibility",
        "gradient_threshold": 1e-6,
    },
    {
        "case_id": "h4-2.0",
        "molecule": "H4",
        "distance_angstrom": 2.0,
        "role": "development-low-cost-reproducibility",
        "gradient_threshold": 1e-6,
    },
    {
        "case_id": "h5-1.5",
        "molecule": "H5",
        "distance_angstrom": 1.5,
        "role": "development-cross-system",
        "gradient_threshold": 1e-6,
    },
)

# Molecules here have no performance outcome in the S0 evidence ledger.
# Both geometries of one molecule must pass the later frozen source and
# structural-applicability checks before that molecule can be selected.
PROSPECTIVE_ORDER = (
    {
        "molecule": "H7",
        "geometries_angstrom": [1.5, 3.0],
        "factory": "adaptvqe.molecules.create_h7",
    },
    {
        "molecule": "H3",
        "geometries_angstrom": [1.5, 3.0],
        "factory": "adaptvqe.molecules.create_h3",
    },
)


class S5CensusError(RuntimeError):
    """Raised when S5 violates its information firewall or source protocol."""


def _git(*arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _source_path(case_id: str) -> Path:
    return OUTPUT_ROOT / "sources" / f"{case_id}.json"


def _case(case_id: str) -> dict[str, Any]:
    try:
        return next(item for item in DEVELOPMENT_CASES if item["case_id"] == case_id)
    except StopIteration as error:
        raise S5CensusError(f"unregistered development case: {case_id}") from error


def _verify_execution_freeze() -> dict[str, Any]:
    s4 = json.loads(S4_OUTPUT.read_text(encoding="utf-8"))
    if s4["authorization"]["s5"] is not True:
        raise S5CensusError("S4 did not authorize S5")
    threads = {name: os.environ.get(name) for name in REQUIRED_THREADS}
    if threads != REQUIRED_THREADS:
        raise S5CensusError(f"noncanonical BLAS thread environment: {threads}")
    if _git("status", "--porcelain"):
        raise S5CensusError("S5 execution requires a clean worktree")
    return {
        "git_commit": _git("rev-parse", "HEAD"),
        "threads": threads,
        "s4_report_digest": s4["report_digest"],
    }


def _algorithm(case: dict[str, Any]) -> tuple[Any, Any]:
    LinAlgAdapt, DVG_CEO, _, _ = _load_upstream()
    molecules = importlib.import_module("adaptvqe.molecules")
    factory = getattr(molecules, f"create_{case['molecule'].lower()}")
    molecule = factory(float(case["distance_angstrom"]))
    pool = DVG_CEO(molecule)
    algorithm = LinAlgAdapt(
        pool=pool,
        molecule=molecule,
        verbose=False,
        max_adapt_iter=100,
        max_opt_iter=10000,
        full_opt=True,
        threshold=float(case["gradient_threshold"]),
        convergence_criterion="total_g_norm",
        tetris=True,
        progressive_opt=False,
        candidates=1,
        sel_criterion="gradient",
        recycle_hessian=True,
        penalize_cnots=False,
        rand_degenerate=False,
        shots=None,
    )
    return algorithm, pool


def _structural_census(pool: Any, structure: AnsatzStructure) -> dict[str, Any]:
    ns1 = json.loads(NS1_OUTPUT.read_text(encoding="utf-8"))
    ns3 = json.loads(NS3_OUTPUT.read_text(encoding="utf-8"))
    ns4 = json.loads(NS4_OUTPUT.read_text(encoding="utf-8"))
    family_by_id = {item["family_id"]: item for item in ns1["families"]}
    candidate_by_id = {item["candidate_id"]: item for item in ns3["candidates"]}
    certified = [
        item for item in ns4["certifications"] if item["familywise_certified"]
    ]
    blocks = recover_dvg_blocks(
        pool,
        structure.indices,
        structure.coefficients,
        structure.cumulative_parameter_counts,
    )
    source_circuit, source_parameters = _compose_context(pool, blocks)
    source_resources = _qasm_resources(
        source_circuit,
        parameter_count=source_parameters,
        logical_block_count=len(blocks),
    )
    rank3 = [
        block
        for block in blocks
        if block.family == "MVP" and len(block.pool_indices) == 3
    ]
    transition_count = 0
    primary_count = 0
    deltas: list[dict[str, int]] = []
    for block in rank3:
        for certification in certified:
            synthesis = candidate_by_id[certification["candidate_id"]]
            family = family_by_id[synthesis["family_id"]]
            target_circuit, target_parameters = _compose_context(
                pool,
                blocks,
                target_block_id=block.block_id,
                parameter_map=np.asarray(family["parameter_map"], dtype=np.int64),
            )
            target_resources = _qasm_resources(
                target_circuit,
                parameter_count=target_parameters,
                logical_block_count=len(blocks),
            )
            delta = _resource_delta(source_resources, target_resources)
            transition_count += 1
            deltas.append(delta)
            primary_count += int(_primary_gate(delta))
    return {
        "qubit_count": int(pool.n),
        "logical_block_count": len(blocks),
        "parameter_count": len(structure.indices),
        "rank_three_mvp_block_count": len(rank3),
        "familywise_native_certified_count": len(certified),
        "registered_native_transition_count": transition_count,
        "structurally_primary_eligible_transition_count": primary_count,
        "source_resources": source_resources,
        "structural_resource_deltas": deltas,
        "candidate_energy_evaluated": False,
    }


def generate_source(case_id: str) -> dict[str, Any]:
    freeze = _verify_execution_freeze()
    case = _case(case_id)
    output = _source_path(case_id)
    if output.exists():
        raise S5CensusError(f"refusing to overwrite source: {output}")
    random.seed(0)
    np.random.seed(0)
    started = time.perf_counter()
    algorithm, pool = _algorithm(case)
    algorithm.initialize()
    counts: list[int] = []
    termination = None
    while algorithm.data.iteration_counter < algorithm.max_adapt_iter:
        before = int(algorithm.data.iteration_counter)
        finished = bool(algorithm.run_iteration())
        after = int(algorithm.data.iteration_counter)
        if after > before:
            counts.append(len(algorithm.indices))
        if finished:
            termination = "adapt-converged"
            break
        if after == before:
            raise S5CensusError("ADAPT made no progress without convergence")
    if termination is None:
        raise S5CensusError("maximum ADAPT iterations reached")
    structure = AnsatzStructure.create(
        algorithm.indices,
        algorithm.coefficients,
        counts,
    )
    gradient = np.asarray(algorithm.gradients, dtype=np.float64)
    gradient_infinity = float(np.max(np.abs(gradient))) if gradient.size else 0.0
    if not np.isfinite(gradient_infinity) or gradient_infinity > SOURCE_GRADIENT_TOLERANCE:
        raise S5CensusError(
            "source parameter stationarity failed: "
            f"{gradient_infinity} > {SOURCE_GRADIENT_TOLERANCE}"
        )
    independent_energy = float(
        algorithm.evaluate_energy(
            list(structure.coefficients),
            list(structure.indices),
        )
    )
    if abs(independent_energy - float(algorithm.energy)) > 1e-10:
        raise S5CensusError("independent source energy mismatch")
    state = np.asarray(
        algorithm.compute_state(
            list(structure.coefficients),
            list(structure.indices),
        ).toarray()
    ).ravel()
    state /= np.linalg.norm(state)
    census = _structural_census(pool, structure)
    report: dict[str, Any] = {
        "schema": "dvg-obs-ceo.pra-path.s5-source.v1",
        "case": case,
        "execution_freeze": freeze,
        "environment": _environment(),
        "source_protocol": {
            "role": "stationarity_normalized_source",
            "termination": termination,
            "parameter_gradient_infinity": gradient_infinity,
            "parameter_gradient_tolerance": SOURCE_GRADIENT_TOLERANCE,
            "independent_energy_agreement_tolerance": 1e-10,
        },
        "ansatz_indices": list(structure.indices),
        "ansatz_coefficients": list(structure.coefficients),
        "iteration_counts": list(structure.cumulative_parameter_counts),
        "source_energy_hartree": float(algorithm.energy),
        "independent_source_energy_hartree": independent_energy,
        "statevector_sha256": hashlib.sha256(
            np.asarray(state, dtype=">c16").tobytes()
        ).hexdigest(),
        "coefficient_digest": sha256_hex(list(structure.coefficients)),
        "structural_census": census,
        "information_firewall": {
            "post_demotion_energy_evaluated": False,
            "exact_reference_read_or_stored": False,
            "exact_reference_used_for_selection": False,
            "factory_computes_fci_as_an_unavoidable_upstream_side_effect": True,
            "source_energy_used_for_case_selection": False,
            "selection_uses_only_structural_census": True,
        },
        "work": {
            "source_optimizer_energy_evaluations": _nested_sum(
                algorithm.data.evolution.nfevs
            ),
            "source_gradient_component_equivalent": _nested_sum(
                algorithm.data.evolution.ngevs
            ),
            "independent_source_energy_evaluations": 1,
            "full_resource_recounts": 1 + census[
                "registered_native_transition_count"
            ],
            "wall_time_seconds": time.perf_counter() - started,
        },
        "claim_boundary": (
            "Source-generation and structural-applicability evidence only; no "
            "post-demotion accuracy or performance result."
        ),
    }
    report["report_digest"] = sha256_hex(report)
    atomic_write_new_json(output, report)
    return report


def build_census() -> dict[str, Any]:
    freeze = _verify_execution_freeze()
    records = []
    for case in DEVELOPMENT_CASES:
        path = _source_path(case["case_id"])
        if not path.exists():
            raise S5CensusError(f"missing frozen source: {path}")
        source = json.loads(path.read_text(encoding="utf-8"))
        if source["information_firewall"]["post_demotion_energy_evaluated"]:
            raise S5CensusError("S5 source contains a candidate energy")
        structural = source["structural_census"]
        records.append(
            {
                "case_id": case["case_id"],
                "role": case["role"],
                "source_generation_succeeded": True,
                "source_path": str(path.relative_to(ROOT)),
                "source_report_digest": source["report_digest"],
                "qubit_count": structural["qubit_count"],
                "rank_three_mvp_block_count": structural[
                    "rank_three_mvp_block_count"
                ],
                "registered_native_transition_count": structural[
                    "registered_native_transition_count"
                ],
                "structurally_primary_eligible_transition_count": structural[
                    "structurally_primary_eligible_transition_count"
                ],
                "estimated_work": source["work"],
                "candidate_energy_evaluated": False,
            }
        )
    low_cost = [r for r in records if "low-cost" in r["role"]]
    cross_system = [r for r in records if r["role"] == "development-cross-system"]
    has_h4 = any(r["rank_three_mvp_block_count"] > 0 for r in low_cost)
    has_non_h4 = any(r["rank_three_mvp_block_count"] > 0 for r in cross_system)
    decision = (
        "GO_S6_STRUCTURAL_QUEUES_FROZEN"
        if has_h4 and has_non_h4
        else "NO_GO_INSUFFICIENT_STRUCTURAL_APPLICABILITY"
    )
    report: dict[str, Any] = {
        "schema": "dvg-obs-ceo.pra-path.s5-applicability-census.v1",
        "decision": decision,
        "execution_freeze": freeze,
        "development_records": records,
        "development_execution_order": [
            case["case_id"] for case in DEVELOPMENT_CASES
        ],
        "prospective_molecule_order": list(PROSPECTIVE_ORDER),
        "prospective_selection_rule": (
            "At S8, select the first ordered molecule for which both frozen "
            "geometries are statevector-feasible, source generation succeeds, "
            "and at least one registered native structurally primary-eligible "
            "transition exists at each geometry. Retain all screen-outs."
        ),
        "information_firewall": {
            "post_demotion_energy_available": False,
            "optimizer_outcome_used_for_case_ranking": False,
            "fidelity_or_reachability_used": False,
            "exact_reference_used": False,
            "final_pareto_status_used": False,
            "structural_fields_only": True,
        },
        "conditional_applicability_population": True,
        "authorization": {
            "s6": decision == "GO_S6_STRUCTURAL_QUEUES_FROZEN",
            "performance_execution": decision == "GO_S6_STRUCTURAL_QUEUES_FROZEN",
        },
        "claim_boundary": (
            "Outcome-free structural census. Prospective applicability is "
            "conditional and its future screen-out rate must be reported."
        ),
    }
    report["report_digest"] = sha256_hex(report)
    return report


def write_census() -> dict[str, Any]:
    if CENSUS_OUTPUT.exists():
        raise S5CensusError("refusing to overwrite S5 census")
    report = build_census()
    atomic_write_new_json(CENSUS_OUTPUT, report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action",
        choices=("source", "census"),
    )
    parser.add_argument(
        "case_id",
        nargs="?",
        choices=tuple(case["case_id"] for case in DEVELOPMENT_CASES),
    )
    arguments = parser.parse_args()
    if arguments.action == "source":
        if arguments.case_id is None:
            raise S5CensusError("source action requires case_id")
        result = generate_source(arguments.case_id)
        print(
            json.dumps(
                {
                    "case_id": arguments.case_id,
                    "rank_three_mvp_block_count": result[
                        "structural_census"
                    ]["rank_three_mvp_block_count"],
                    "registered_native_transition_count": result[
                        "structural_census"
                    ]["registered_native_transition_count"],
                    "wall_time_seconds": result["work"]["wall_time_seconds"],
                },
                sort_keys=True,
            )
        )
    else:
        if arguments.case_id is not None:
            raise S5CensusError("census action takes no case_id")
        result = write_census()
        print(json.dumps({"decision": result["decision"]}, sort_keys=True))


if __name__ == "__main__":
    main()

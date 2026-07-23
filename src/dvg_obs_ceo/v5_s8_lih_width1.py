"""Frozen V5-S8 LiH transfer using the H2/H4-selected ablation C."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path

import numpy as np

from .baseline import ROOT
from .identity import canonical_json_bytes
from .resources import AnsatzStructure, evaluate_full_circuit_resources, paper_era_backend
from .s8_probe import _state_vector
from .s10_lih import _algorithm as _lih_algorithm
from .telemetry import WorkCounters
from .transaction import CompressionRuntime
from .v4_lih import _energy
from .v5_ledger import versioned_id
from .v5_conditional_polishing import ConditionalPolishingConfig
from .v5_nested_transaction import PathCheckpointStore
from .v5_s8_h4_width1 import (
    MolecularWidthOneAdapter,
    _measurement_id,
    _state_id,
)
from .v5_sequential import WidthOneConfig, run_width_one


RUNNER_VERSION = "v5-s8-lih-width1-transfer-v1"
CASE_ID = "lih-3.0"
CHECKPOINT = ROOT / "artifacts/s10/lih-3a-first-accuracy-primary-v1-2/checkpoint.json"
OUTPUT = ROOT / "artifacts/v5/s8/lih-width1-transfer-v1"
REQUIRED_THREADS = {"OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}


class V5S8LiHWidthOneError(RuntimeError):
    """Raised when the frozen LiH transfer cannot be trusted."""


def _digest(value):
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _load_checkpoint() -> dict:
    checkpoint = json.loads(CHECKPOINT.read_text(encoding="utf-8"))
    observed = checkpoint.pop("checkpoint_digest")
    if _digest(checkpoint) != observed:
        raise V5S8LiHWidthOneError("LiH checkpoint digest mismatch")
    checkpoint["checkpoint_digest"] = observed
    return checkpoint


def run(
    output: Path = OUTPUT,
    *,
    runner_version: str = RUNNER_VERSION,
    enable_conditional_polishing: bool = False,
    polishing_config: ConditionalPolishingConfig = ConditionalPolishingConfig(),
    enable_joint_search: bool = False,
) -> dict:
    threads = {name: os.environ.get(name) for name in REQUIRED_THREADS}
    if threads != REQUIRED_THREADS:
        raise V5S8LiHWidthOneError(f"single-thread freeze missing: {threads}")
    if output.exists():
        raise V5S8LiHWidthOneError("output already exists; refusing overwrite")
    checkpoint = _load_checkpoint()
    algorithm, pool, _ = _lih_algorithm()
    algorithm.initialize()
    source = AnsatzStructure.create(
        checkpoint["ansatz_indices"], checkpoint["ansatz_coefficients"], checkpoint["iteration_counts"]
    )
    source_state = _state_vector(algorithm, source.coefficients, source.indices)
    state_sha = hashlib.sha256(np.asarray(source_state, dtype=">c16").tobytes()).hexdigest()
    source_energy = _energy(algorithm, np.asarray(source.coefficients), source.indices)
    source_resources = evaluate_full_circuit_resources(pool, source, paper_era_backend())
    if (
        state_sha != checkpoint["statevector_sha256"]
        or abs(source_energy - float(checkpoint["energy_hartree"])) > 1e-10
        or asdict(source_resources.snapshot) != checkpoint["resources"]["snapshot"]
    ):
        raise V5S8LiHWidthOneError("independent LiH source reconstruction drift")
    runtime = CompressionRuntime.create(
        ansatz=source,
        energy_hartree=float(checkpoint["energy_hartree"]),
        gradient=checkpoint["gradient"],
        inverse_hessian=checkpoint["recycled_inverse_hessian"],
        statevector=source_state,
        work=WorkCounters(),
        adapt_iteration=int(checkpoint["adapt_iteration"]),
        metadata={
            "run_id": "v5-s8-lih-width1-transfer",
            "resource_structure_digest": source_resources.snapshot.structure_digest,
            "budget_reference_energy_hartree": float(checkpoint["energy_hartree"]),
            "checkpoint_digest": checkpoint["checkpoint_digest"],
        },
    )
    problem_id = versioned_id("problem-v1", {
        "case_id": CASE_ID,
        "hamiltonian_context": "stored-pinned-lih-3.0-angstrom-sto-3g",
        "checkpoint_digest": checkpoint["checkpoint_digest"],
    })
    adapter = MolecularWidthOneAdapter(
        algorithm,
        pool,
        problem_id=problem_id,
        enable_conditional_polishing=enable_conditional_polishing,
        polishing_config=polishing_config,
        enable_joint_search=enable_joint_search,
    )
    source_catalog = adapter.catalog_builder(runtime)
    path_id = versioned_id("path-v5", {
        "runner_version": runner_version,
        "case_id": CASE_ID,
        "checkpoint_digest": checkpoint["checkpoint_digest"],
    })
    store = PathCheckpointStore(output / "path", path_id)
    source_state_id = _state_id(runtime)
    store.initialize(
        runtime,
        work=adapter.work,
        state_preparation_id=source_state_id,
        problem_id=problem_id,
        measurement_context_id=_measurement_id(source_state_id, problem_id),
        catalog_digest=source_catalog.catalog_digest,
        resource_snapshot=source_resources.snapshot,
    )
    result = run_width_one(
        runtime,
        store,
        catalog_builder=adapter.catalog_builder,
        candidate_executor=adapter.candidate_executor,
        config=WidthOneConfig(2, 2, 1e-4),
    )
    payload = {
        "schema_version": "1.0.0",
        "artifact_kind": (
            "v5-s8-lih-joint-sequential-integration"
            if enable_joint_search
            else (
                "v5-s8-lih-width1-conditional-polishing-integration"
                if enable_conditional_polishing else "v5-s8-lih-width1-transfer"
            )
        ),
        "runner_version": runner_version,
        "case_id": CASE_ID,
        "checkpoint_digest": checkpoint["checkpoint_digest"],
        "source_energy_hartree": checkpoint["energy_hartree"],
        "source_reconstruction": {
            "independent_energy_hartree": source_energy,
            "energy_difference_hartree": abs(source_energy - float(checkpoint["energy_hartree"])),
            "statevector_sha256": state_sha,
            "matches_checkpoint_statevector": state_sha == checkpoint["statevector_sha256"],
        },
        "source_resources": asdict(source_resources.snapshot),
        "result": result,
        "catalog_diagnostics_by_runtime": adapter._selection_cache,
        "exact_attempt_records": adapter.attempt_records,
        "claim_boundary": [
            "Held-out development transfer after the H2/H4 choice; not confirmatory.",
            "Uses recycled curvature only; no LiH outcome selected a threshold.",
            "No CEO-star or ordinary-ADAPT rerun and no measurement-cost claim."
        ],
        "paper_measurement_cost": None,
    }
    payload["result_digest"] = _digest(payload)
    output.mkdir(parents=True, exist_ok=True)
    (output / "summary.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return payload


if __name__ == "__main__":
    run()

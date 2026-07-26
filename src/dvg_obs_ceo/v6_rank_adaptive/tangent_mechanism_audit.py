"""V6.1-T2 frozen retrospective tangent-mechanism audit."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from typing import Any, Mapping, Sequence

import numpy as np

from dvg_obs_ceo.artifact_io import atomic_write_new_json
from dvg_obs_ceo.baseline import ROOT
from dvg_obs_ceo.block_ir import recover_dvg_blocks
from dvg_obs_ceo.identity import canonical_float64_hex, sha256_hex

from .native_synthesis_pipeline import CONTEXTS, _load_context_structure
from .native_synthesis_pipeline import _parameter_map
from .ns7_energy_certification import (
    DEFAULT_OUTPUT as NS7_OUTPUT,
    _algorithm_for,
    affine_embedding,
)
from .ns9_sequential_pilot import RESULT_OUTPUT as NS9_OUTPUT
from .tangent_geometry import (
    central_projective_tangents,
    conditional_geometry,
    normalized_rayleigh,
    normalized_state,
    null_space_alignment,
    ordered_eigensystem,
    projective_tangent,
)


PROTOCOL = ROOT / "artifacts/v6_1/t0/protocol-v1.json"
OUTPUT = ROOT / "artifacts/v6_1/t2/mechanism-audit-v1.json"
REQUIRED_THREADS = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
}


class TangentMechanismAuditError(RuntimeError):
    """Raised when the frozen T2 audit cannot be certified."""


def _stage_authorization(decision: str) -> dict[str, bool]:
    return {
        "t3_t4": decision == "GO_DEVELOPMENT_MECHANISM_SEPARATED",
        "t5_t6_performance": False,
    }


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _float64_hex(values: Sequence[str]) -> np.ndarray:
    return np.asarray(
        [np.frombuffer(bytes.fromhex(value), dtype=">f8")[0] for value in values],
        dtype=np.float64,
    )


def _context(context_id: str) -> Mapping[str, Any]:
    return next(item for item in CONTEXTS if item["case_id"] == context_id)


def _state_function(algorithm: Any, indices: Sequence[int], embedding: np.ndarray):
    def compute(coordinates: np.ndarray) -> np.ndarray:
        mapped = embedding @ np.asarray(coordinates, dtype=np.float64)
        return np.asarray(
            algorithm.compute_state(list(mapped), list(indices)).toarray()
        ).ravel()

    return compute


def _selected_tangents(
    function: Any,
    coordinates: np.ndarray,
    positions: Sequence[int],
    step: float,
) -> np.ndarray:
    psi = normalized_state(function(coordinates.copy()))
    columns = []
    for position in positions:
        plus = coordinates.copy()
        minus = coordinates.copy()
        plus[position] += step
        minus[position] -= step
        derivative = (
            normalized_state(function(plus)) - normalized_state(function(minus))
        ) / (2.0 * step)
        columns.append(projective_tangent(psi, derivative))
    return np.column_stack(columns)


def _score_record(
    *,
    record_id: str,
    stage: str,
    context_id: str,
    accepted: bool,
    normal: Sequence[int],
    function: Any,
    coordinates: np.ndarray,
    block_positions: Sequence[int],
    protocol: Mapping[str, Any],
    lineage: Mapping[str, Any],
) -> dict[str, Any]:
    metric = protocol["metric"]
    primary_step = float(metric["finite_difference_primary_step"])
    _, tangents = central_projective_tangents(
        function, coordinates, step=primary_step
    )
    geometry = conditional_geometry(
        tangents,
        block_positions,
        relative_cutoff=float(metric["svd_relative_cutoff"]),
    )
    local_values, _ = ordered_eigensystem(geometry.local_gram)
    conditional_values, _ = ordered_eigensystem(geometry.conditional_gram)
    primary_score = normalized_rayleigh(
        geometry.conditional_gram, normal
    )
    alignment, null_dimension = null_space_alignment(
        geometry.conditional_gram,
        normal,
        relative_cutoff=float(metric["svd_relative_cutoff"]),
    )
    rest = tuple(
        index for index in range(tangents.shape[1])
        if index not in set(block_positions)
    )
    sensitivity: dict[str, float] = {}
    for step in metric["finite_difference_sensitivity_steps"]:
        alternate_block = _selected_tangents(
            function, coordinates, block_positions, float(step)
        )
        mixed = tangents.copy()
        mixed[:, list(block_positions)] = alternate_block
        alternate = conditional_geometry(
            mixed,
            block_positions,
            relative_cutoff=float(metric["svd_relative_cutoff"]),
        )
        sensitivity[str(step)] = normalized_rayleigh(
            alternate.conditional_gram, normal
        )
    del rest
    return {
        "record_id": record_id,
        "stage": stage,
        "context_id": context_id,
        "observed_outcome": "accepted" if accepted else "rejected",
        "normal": list(normal),
        "coordinate_count": int(coordinates.size),
        "block_coordinate_positions": list(block_positions),
        "coordinate_digest": sha256_hex(canonical_float64_hex(coordinates)),
        "state_digest": hashlib.sha256(
            normalized_state(function(coordinates)).tobytes()
        ).hexdigest(),
        "local_eigenvalues": local_values.tolist(),
        "conditional_eigenvalues": conditional_values.tolist(),
        "conditional_rho": primary_score,
        "conditional_null_alignment": alignment,
        "conditional_null_dimension": null_dimension,
        "rest_numerical_rank": geometry.rest_rank,
        "rest_singular_values": geometry.rest_singular_values.tolist(),
        "sensitivity_rho": sensitivity,
        "lineage": dict(lineage),
        "statevector_evaluations": int(
            1 + 2 * coordinates.size + 2 * len(block_positions)
            * len(metric["finite_difference_sensitivity_steps"]) + 1
        ),
    }


def build_report() -> dict[str, Any]:
    if OUTPUT.exists():
        raise TangentMechanismAuditError("T2 output already exists")
    if _git("status", "--porcelain"):
        raise TangentMechanismAuditError("T2 requires a clean worktree")
    threads = {name: os.environ.get(name) for name in REQUIRED_THREADS}
    if threads != REQUIRED_THREADS:
        raise TangentMechanismAuditError(
            f"T2 requires canonical single-thread settings: {threads}"
        )
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    ns7 = json.loads(NS7_OUTPUT.read_text(encoding="utf-8"))
    ns9 = json.loads(NS9_OUTPUT.read_text(encoding="utf-8"))
    records: list[dict[str, Any]] = []
    runtime_cache: dict[str, tuple[Any, Any, Any, list[Any]]] = {}

    def runtime(context_id: str):
        if context_id not in runtime_cache:
            algorithm, pool = _algorithm_for(context_id)
            source = _load_context_structure(_context(context_id))
            blocks = recover_dvg_blocks(
                pool,
                source.indices,
                source.coefficients,
                source.cumulative_parameter_counts,
            )
            runtime_cache[context_id] = (algorithm, pool, source, blocks)
        return runtime_cache[context_id]

    for attempt in ns7["attempts"]:
        context_id = attempt["queue_item"]["context_id"]
        algorithm, _, source, blocks = runtime(context_id)
        block = next(
            item for item in blocks
            if item.block_id == attempt["queue_item"]["source_block_id"]
        )
        embedding = np.eye(len(source.coefficients), dtype=np.float64)
        function = _state_function(algorithm, source.indices, embedding)
        records.append(
            _score_record(
                record_id=attempt["attempt_id"],
                stage="ns7-original-source",
                context_id=context_id,
                accepted=bool(attempt["acceptance"]["accepted"]),
                normal=attempt["normal"],
                function=function,
                coordinates=np.asarray(source.coefficients, dtype=np.float64),
                block_positions=block.ansatz_positions,
                protocol=protocol,
                lineage={"source_block_id": block.block_id},
            )
        )

    algorithm, _, source, blocks = runtime("h4-1.5-late")
    block_by_id = {item.block_id: item for item in blocks}
    root_cache: dict[tuple[str, tuple[int, ...]], tuple[Any, np.ndarray, tuple[int, ...]]] = {}
    for attempt in ns9["attempts"]:
        item = attempt["queue_item"]
        key = (item["root_attempt_id"], tuple(item["root_normal"]))
        if key not in root_cache:
            root = block_by_id[item["root_block_id"]]
            embedding, slots = affine_embedding(
                len(source.coefficients),
                root.ansatz_positions,
                _parameter_map(item["root_normal"]),
            )
            mapped = _float64_hex(item["root_source_coordinates_float64_hex"])
            coordinates, _, rank, _ = np.linalg.lstsq(
                embedding, mapped, rcond=None
            )
            if rank != embedding.shape[1] or not np.allclose(
                embedding @ coordinates, mapped, atol=1e-10, rtol=0.0
            ):
                raise TangentMechanismAuditError(
                    "root constrained coordinates cannot be reconstructed"
                )
            root_cache[key] = (
                _state_function(algorithm, source.indices, embedding),
                np.asarray(coordinates, dtype=np.float64),
                slots,
            )
        function, coordinates, slots = root_cache[key]
        child = block_by_id[item["child_block_id"]]
        positions = tuple(
            slots.index(f"source-{position}")
            for position in child.ansatz_positions
        )
        records.append(
            _score_record(
                record_id=attempt["attempt_id"],
                stage="ns9-constrained-parent-source",
                context_id="h4-1.5-late-after-first-demotion",
                accepted=bool(attempt["acceptance"]["accepted"]),
                normal=item["child_normal"],
                function=function,
                coordinates=coordinates,
                block_positions=positions,
                protocol=protocol,
                lineage={
                    "root_attempt_id": item["root_attempt_id"],
                    "root_normal": item["root_normal"],
                    "child_block_id": item["child_block_id"],
                },
            )
        )

    accepted = [item["conditional_rho"] for item in records
                if item["observed_outcome"] == "accepted"]
    rejected = [item["conditional_rho"] for item in records
                if item["observed_outcome"] == "rejected"]
    gate = protocol["gate"]
    finite = all(
        np.isfinite(value)
        for item in records
        for value in [
            item["conditional_rho"],
            item["conditional_null_alignment"],
            *item["sensitivity_rho"].values(),
        ]
    )
    sensitivity_stable = all(
        (
            max([item["conditional_rho"], *item["sensitivity_rho"].values()])
            <= gate["accepted_rho_max"]
            if item["observed_outcome"] == "accepted"
            else min([item["conditional_rho"], *item["sensitivity_rho"].values()])
            >= gate["rejected_rho_min"]
        )
        for item in records
    )
    accepted_bound = bool(accepted) and max(accepted) <= gate["accepted_rho_max"]
    rejected_bound = bool(rejected) and min(rejected) >= gate["rejected_rho_min"]
    ratio = float(
        min(rejected) / max(max(accepted), np.finfo(float).eps)
        if accepted and rejected else 0.0
    )
    checks = {
        "finite": finite,
        "sensitivity_classification_stable": sensitivity_stable,
        "all_accepted_below_bound": accepted_bound,
        "all_rejected_above_bound": rejected_bound,
        "minimum_separation_ratio": bool(
            ratio >= gate["minimum_separation_ratio"]
        ),
    }
    checks = {name: bool(value) for name, value in checks.items()}
    decision = (
        "GO_DEVELOPMENT_MECHANISM_SEPARATED"
        if all(checks.values())
        else "NO_GO_MECHANISM_NOT_SEPARATED"
    )
    report = {
        "schema": "dvg-obs-ceo.v6_1.t2.mechanism-audit.v1",
        "decision": decision,
        "checks": checks,
        "observed": {
            "accepted_count": len(accepted),
            "rejected_count": len(rejected),
            "maximum_accepted_rho": max(accepted),
            "minimum_rejected_rho": min(rejected),
            "separation_ratio": ratio,
        },
        "records": records,
        "inputs": {
            str(path.relative_to(ROOT)): _sha256(path)
            for path in (PROTOCOL, NS7_OUTPUT, NS9_OUTPUT)
        },
        "execution": {
            "git_commit": _git("rev-parse", "HEAD"),
            "threads": threads,
            "statevector_evaluations": sum(
                item["statevector_evaluations"] for item in records
            ),
        },
        "authorization": _stage_authorization(decision),
        "claim_boundary": (
            "Retrospective, outcome-aware development diagnostic only; "
            "not prospective selector validation or performance evidence."
        ),
    }
    report["report_digest"] = sha256_hex(report)
    return report


def main() -> None:
    started = time.perf_counter()
    report = build_report()
    report["execution"]["wall_time_seconds"] = time.perf_counter() - started
    atomic_write_new_json(OUTPUT, report)


if __name__ == "__main__":
    main()

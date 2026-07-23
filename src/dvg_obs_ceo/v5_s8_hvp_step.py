"""Preregistered finite-difference HVP step study on H2 and H4."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
from typing import Any, Callable

import numpy as np
from numpy.typing import NDArray

from .baseline import ROOT
from .identity import canonical_json_bytes
from .s8_probe import _algorithm
from .v3_protocol import _write_exclusive
from .v5_s8_protocol import DEFAULT_MANIFEST, audit_manifest


FloatArray = NDArray[np.float64]
CODE_TAG = "dvg-obs-v5-s8-hvp-step-code-v1"
REQUIRED_THREADS = {"OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
CASES = ("h2-1.5-iteration-1", "h4-1.5-first-chemical-accuracy")


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _git(*arguments: str) -> str:
    return subprocess.check_output(["git", "-C", str(ROOT), *arguments], text=True).strip()


def verify_freeze() -> dict[str, Any]:
    head = _git("rev-parse", "HEAD")
    tagged = _git("rev-parse", f"{CODE_TAG}^{{}}")
    dirty = _git("status", "--porcelain")
    threads = {name: os.environ.get(name) for name in REQUIRED_THREADS}
    checks = {
        "head_is_code_tag": head == tagged,
        "clean_worktree": not dirty,
        "canonical_threads": threads == REQUIRED_THREADS,
    }
    if not all(checks.values()):
        raise RuntimeError("HVP step execution freeze failed: " + ",".join(name for name, passed in checks.items() if not passed))
    return {"head": head, "tag": CODE_TAG, "threads": threads, "checks": checks}


def central_hvp(
    point: FloatArray,
    direction: FloatArray,
    gradient: Callable[[FloatArray], FloatArray],
    relative_step: float,
) -> tuple[FloatArray, float]:
    norm = float(np.linalg.norm(direction))
    if norm == 0:
        raise ValueError("HVP study direction must be nonzero")
    step = relative_step * max(1.0, float(np.linalg.norm(point))) / norm
    plus = np.asarray(gradient(point + step * direction), dtype=np.float64)
    minus = np.asarray(gradient(point - step * direction), dtype=np.float64)
    if plus.shape != point.shape or minus.shape != point.shape or not np.all(np.isfinite(plus)) or not np.all(np.isfinite(minus)):
        raise RuntimeError("HVP step gradient evaluation is invalid")
    return np.asarray((plus - minus) / (2.0 * step), dtype=np.float64), step


def _directions(dimension: int) -> list[tuple[str, FloatArray]]:
    values = [(f"basis-{index}", np.eye(dimension)[index]) for index in range(dimension)]
    extras = (
        ("ones", np.ones(dimension)),
        ("alternating", (-1.0) ** np.arange(dimension)),
    )
    for name, vector in extras:
        normalized = np.asarray(vector / np.linalg.norm(vector), dtype=np.float64)
        if not any(np.array_equal(normalized, existing) or np.array_equal(normalized, -existing) for _, existing in values):
            values.append((name, normalized))
    return values


def _case_record(case_id: str, manifest: dict[str, Any], multipliers: list[float]) -> dict[str, Any]:
    input_record = next(item for item in manifest["inputs"] if item["case_id"] == case_id)
    checkpoint = json.loads((ROOT / input_record["checkpoint_path"]).read_text(encoding="utf-8"))
    if checkpoint["exact_hessian"] is None:
        raise RuntimeError(f"registered exact Hessian unavailable: {case_id}")
    theta = np.asarray(checkpoint["ansatz_coefficients"], dtype=np.float64)
    indices = list(checkpoint["ansatz_indices"])
    exact = np.asarray(checkpoint["exact_hessian"], dtype=np.float64)
    algorithm, _ = _algorithm(case_id)
    algorithm.initialize()
    observed_energy = float(algorithm.evaluate_energy(theta.tolist(), indices))
    observed_gradient = np.asarray(
        algorithm.estimate_gradients(theta.tolist(), indices, method="an"), dtype=np.float64
    )
    if abs(observed_energy - float(checkpoint["energy_hartree"])) > 1e-10 or not np.allclose(
        observed_gradient, checkpoint["gradient"], atol=1e-8, rtol=1e-8
    ):
        raise RuntimeError(f"HVP checkpoint reconstruction drift: {case_id}")

    gradient_evaluations = 1

    def gradient(value: FloatArray) -> FloatArray:
        nonlocal gradient_evaluations
        gradient_evaluations += 1
        return np.asarray(
            algorithm.estimate_gradients(value.tolist(), indices, method="an"), dtype=np.float64
        )

    base = float(np.finfo(np.float64).eps ** (1.0 / 3.0))
    directions = _directions(theta.size)
    studies: dict[str, Any] = {}
    for multiplier in multipliers:
        relative_step = base * multiplier
        records = []
        basis_columns = []
        for name, direction in directions:
            observed, absolute_step = central_hvp(theta, direction, gradient, relative_step)
            reverse, _ = central_hvp(theta, -direction, gradient, relative_step)
            expected = exact @ direction
            denominator = max(float(np.linalg.norm(expected)), np.finfo(np.float64).tiny)
            relative_error = float(np.linalg.norm(observed - expected) / denominator)
            reversal_error = float(np.linalg.norm(observed + reverse) / max(float(np.linalg.norm(observed)), 1.0))
            if name.startswith("basis-"):
                basis_columns.append(observed)
            records.append({
                "direction": name,
                "absolute_step": absolute_step,
                "relative_error": relative_error,
                "direction_reversal_relative_error": reversal_error,
                "finite": bool(np.all(np.isfinite(observed)) and np.all(np.isfinite(reverse))),
            })
        approximate = np.column_stack(basis_columns)
        symmetry = float(
            np.linalg.norm(approximate - approximate.T, ord=2)
            / max(1.0, float(np.linalg.norm(approximate, ord=2)))
        )
        errors = np.asarray([record["relative_error"] for record in records])
        studies[f"{multiplier:.12g}"] = {
            "relative_step": relative_step,
            "direction_count": len(records),
            "maximum_relative_error": float(np.max(errors)),
            "rms_relative_error": float(np.sqrt(np.mean(np.square(errors)))),
            "maximum_direction_reversal_relative_error": max(record["direction_reversal_relative_error"] for record in records),
            "basis_symmetry_relative_error": symmetry,
            "records": records,
        }
    return {
        "case_id": case_id,
        "dimension": theta.size,
        "checkpoint_digest": checkpoint["checkpoint_digest"],
        "studies": studies,
        "work": {
            "checkpoint_gradient_vector_evaluations": 1,
            "finite_difference_gradient_vector_evaluations": gradient_evaluations - 1,
            "finite_difference_hvp_calls": (gradient_evaluations - 1) // 2,
            "paper_measurement_cost": None,
        },
    }


def run(manifest_path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    freeze = verify_freeze()
    protocol = audit_manifest(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    multipliers = [float(value) for value in manifest["sensitivity_grid"]["finite_difference_relative_step_multipliers"]]
    cases = {case_id: _case_record(case_id, manifest, multipliers) for case_id in CASES}
    ranking = []
    for multiplier in multipliers:
        key = f"{multiplier:.12g}"
        maximum = max(cases[case_id]["studies"][key]["maximum_relative_error"] for case_id in CASES)
        rms = math.sqrt(sum(cases[case_id]["studies"][key]["rms_relative_error"] ** 2 for case_id in CASES) / len(CASES))
        ranking.append((maximum, rms, abs(math.log2(multiplier)), multiplier))
    selected = min(ranking)[-1]
    checks = {
        "all_multipliers_executed": all(len(case["studies"]) == len(multipliers) for case in cases.values()),
        "both_cases_influence_choice": len(cases) == 2,
        "all_values_finite": all(
            record["finite"]
            for case in cases.values()
            for study in case["studies"].values()
            for record in study["records"]
        ),
        "direction_reversal_checked": all(
            study["maximum_direction_reversal_relative_error"] <= 1e-12
            for case in cases.values() for study in case["studies"].values()
        ),
        "all_gradient_work_counted": all(
            case["work"]["finite_difference_gradient_vector_evaluations"]
            == 4 * len(_directions(case["dimension"])) * len(multipliers)
            for case in cases.values()
        ),
        "measurement_cost_not_relabelled": all(case["work"]["paper_measurement_cost"] is None for case in cases.values()),
    }
    result = {
        "schema_version": "1.0.0",
        "artifact_kind": "v5-s8-hvp-finite-difference-step-study",
        "passed": all(checks.values()),
        "checks": checks,
        "execution_freeze": freeze,
        "protocol_manifest_sha256": protocol["manifest_sha256"],
        "base_relative_step": float(np.finfo(np.float64).eps ** (1.0 / 3.0)),
        "multipliers": multipliers,
        "cases": cases,
        "combined_ranking": [
            {"maximum_relative_error": item[0], "rms_relative_error": item[1], "log2_distance_from_one": item[2], "multiplier": item[3]}
            for item in sorted(ranking)
        ],
        "selected_multiplier": selected,
        "selection_rule": "minimum cross-case maximum relative error, then pooled RMS, then distance from 1, then multiplier",
        "paper_measurement_cost": None,
        "claim_boundary": "H2/H4 analytic-gradient numerical calibration only; no molecular resource improvement claim.",
    }
    result["result_digest"] = _digest(result)
    if not result["passed"]:
        raise RuntimeError("V5-S8 HVP step study failed")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--artifact-path", type=Path, required=True)
    arguments = parser.parse_args()
    result = run(arguments.manifest)
    _write_exclusive(arguments.artifact_path, result)
    print(json.dumps({"passed": result["passed"], "selected_multiplier": result["selected_multiplier"]}, sort_keys=True))


if __name__ == "__main__":
    main()

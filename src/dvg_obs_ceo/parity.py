"""Fail-closed comparison of a fresh baseline artifact to its preregistered reference."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np


class ParityError(RuntimeError):
    """Raised when a baseline differs from the registered reference."""


def compare(result: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    expected = manifest["expected_reference"]
    tolerances = manifest["parity_tolerances"]
    checks: dict[str, dict[str, Any]] = {}

    exact_fields = (
        "first_chemical_accuracy_iteration",
        "parameter_count",
        "cnot_count",
        "cnot_depth",
        "ansatz_indices",
        "cnot_counts_by_iteration",
        "cnot_depths_by_iteration",
    )
    expected_names = {
        "first_chemical_accuracy_iteration": "adapt_iteration",
    }
    for field in exact_fields:
        expected_value = expected[expected_names.get(field, field)]
        observed = result[field]
        checks[field] = {
            "passed": observed == expected_value,
            "observed": observed,
            "expected": expected_value,
            "comparison": "exact",
        }

    energy_tolerance = float(tolerances["energy_absolute_hartree"])
    for field in ("energy_hartree", "fci_energy_hartree", "absolute_error_hartree"):
        difference = abs(float(result[field]) - float(expected[field]))
        checks[field] = {
            "passed": difference <= energy_tolerance,
            "observed": result[field],
            "expected": expected[field],
            "absolute_difference": difference,
            "tolerance": energy_tolerance,
        }

    coefficient_tolerance = float(tolerances["coefficient_absolute"])
    observed_coefficients = np.asarray(result["ansatz_coefficients"], dtype=float)
    expected_coefficients = np.asarray(expected["ansatz_coefficients"], dtype=float)
    same_shape = observed_coefficients.shape == expected_coefficients.shape
    maximum_difference = (
        float(np.max(np.abs(observed_coefficients - expected_coefficients)))
        if same_shape and observed_coefficients.size
        else float("inf")
    )
    checks["ansatz_coefficients"] = {
        "passed": same_shape and maximum_difference <= coefficient_tolerance,
        "same_shape": same_shape,
        "maximum_absolute_difference": maximum_difference,
        "tolerance": coefficient_tolerance,
    }

    passed = all(item["passed"] for item in checks.values())
    return {
        "schema_version": "1.0.0",
        "artifact_kind": "baseline-parity-report",
        "passed": passed,
        "checks": checks,
        "claim_boundary": [
            "Parity establishes reproducibility of the pinned baseline only.",
            "Parity does not establish performance of DVG-OBS-CEO.",
        ],
    }


def _write_once(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():
        raise ParityError(f"refusing to overwrite parity report: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("manifests/baseline-lih-3a-v1.json"),
    )
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    result = json.loads(arguments.result.read_text(encoding="utf-8"))
    manifest = json.loads(arguments.manifest.read_text(encoding="utf-8"))
    report = compare(result, manifest)
    _write_once(arguments.output, report)
    if not report["passed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()


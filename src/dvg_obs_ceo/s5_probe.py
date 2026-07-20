"""Registered H2 observer OFF/ON parity and Hessian-quality probe."""

from __future__ import annotations

import argparse
import importlib
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping

from .baseline import _load_upstream, run_case, verify_upstream
from .hessian import HESSIAN_DIAGNOSTICS_VERSION, HessianCaptureSession, capture_to_dict


PARITY_FIELDS = (
    "energy_hartree",
    "fci_energy_hartree",
    "absolute_error_hartree",
    "first_chemical_accuracy_iteration",
    "ansatz_indices",
    "ansatz_coefficients",
    "parameter_count",
    "cnot_count",
    "cnot_depth",
    "cnot_counts_by_iteration",
    "cnot_depths_by_iteration",
    "trajectory",
    "scientific_state_digest",
)
WORK_FIELDS = ("nfev", "ngev_component_equivalent", "paper_measurement_cost")


def compare_off_on(reference: Mapping[str, Any], observed: Mapping[str, Any]) -> dict[str, Any]:
    comparisons: list[dict[str, Any]] = []
    for field in PARITY_FIELDS:
        equal = reference.get(field) == observed.get(field)
        comparisons.append(
            {
                "field": field,
                "reference": reference.get(field),
                "observed": observed.get(field),
                "exact_equal": equal,
            }
        )
    for field in WORK_FIELDS:
        reference_value = reference["work"].get(field)
        observed_value = observed["work"].get(field)
        comparisons.append(
            {
                "field": f"work.{field}",
                "reference": reference_value,
                "observed": observed_value,
                "exact_equal": reference_value == observed_value,
            }
        )
    return {
        "passed": all(item["exact_equal"] for item in comparisons),
        "comparisons": comparisons,
        "excluded_fields": [
            "work.wall_time_seconds",
            "environment",
        ],
        "exclusion_reason": "observer overhead changes wall time; platform metadata is provenance, not trajectory",
    }


def _write_once(path: Path, value: dict[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite S5 artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def run_probe(reference_path: Path, baseline_path: Path, report_path: Path) -> dict[str, Any]:
    provenance = verify_upstream()
    reference = json.loads(reference_path.read_text(encoding="utf-8"))
    _load_upstream()
    adapt_module = importlib.import_module("adaptvqe.algorithms.adapt_vqe")
    with HessianCaptureSession(adapt_module) as capture:
        observed = run_case("h2-smoke", baseline_path)
    parity = compare_off_on(reference, observed)
    if not parity["passed"]:
        raise RuntimeError("Hessian observer changed registered H2 scientific trajectory or work")
    records = [capture_to_dict(record) for record in capture.records]
    if not records:
        raise RuntimeError("Hessian observer captured no optimizer invocation")
    report = {
        "schema_version": "1.0.0",
        "artifact_kind": "h2-hessian-capture-off-on-parity",
        "upstream": provenance,
        "diagnostics_version": HESSIAN_DIAGNOSTICS_VERSION,
        "case_id": "h2-smoke",
        "observer_off_artifact": str(reference_path),
        "observer_on_artifact": str(baseline_path),
        "parity": parity,
        "capture": {
            "optimizer_invocations": len(records),
            "records": records,
            "additional_energy_evaluations": 0,
            "additional_gradient_evaluations": 0,
            "held_out_secant_policy": "none captured internally; must be supplied independently"
        },
        "claim_boundary": [
            "S5 capture is observational and preserved registered H2 trajectory/work exactly.",
            "Internal BFGS secants are not labeled held-out validation data.",
            "H2 parity does not establish recycled-Hessian predictive fidelity on LiH."
        ]
    }
    _write_once(report_path, report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference-off", type=Path, required=True)
    parser.add_argument("--baseline-artifact", type=Path, required=True)
    parser.add_argument("--report-artifact", type=Path, required=True)
    arguments = parser.parse_args()
    sys.argv[:] = [sys.argv[0]]
    result = run_probe(arguments.reference_off, arguments.baseline_artifact, arguments.report_artifact)
    print(json.dumps({"report": str(arguments.report_artifact), "parity": result["parity"]["passed"], "captures": result["capture"]["optimizer_invocations"]}))


if __name__ == "__main__":
    main()

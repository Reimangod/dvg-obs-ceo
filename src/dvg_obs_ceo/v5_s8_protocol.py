"""Audit the preregistered V5-S8 development-calibration inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from .baseline import ROOT
from .v3_protocol import _write_exclusive


DEFAULT_MANIFEST = ROOT / "manifests/v5-s8-calibration-protocol-v1.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit_manifest(path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    checks: dict[str, bool] = {
        "protocol_identity": manifest["protocol_id"] == "dvg-obs-v5-s8-calibration-protocol-v1",
        "parent_protocol_identity": manifest["parent_protocol_id"] == "dvg-obs-v5-risk-aware-sequential-protocol-v1",
        "development_only": manifest["study_status"] == "development-calibration",
        "fixed_energy_budget": manifest["fixed_scientific_gates"]["source_relative_energy_budget_hartree"] == 1e-4,
        "fixed_gradient_gate": manifest["fixed_scientific_gates"]["target_gradient_infinity_max"] == 1e-8,
        "information_firewall": manifest["fixed_scientific_gates"]["actual_or_fci_energy_in_screening"] is False,
        "measurement_cost_remains_null": manifest["fixed_scientific_gates"]["paper_measurement_cost"] is None,
        "width_grid_preregistered": manifest["sensitivity_grid"]["beam_widths"] == [1, 2, 4, 8],
        "ablation_order_complete": list(manifest["ablation_matrix"]) == list("ABCDEF"),
        "lih_is_held_out_until_small_system_choice": manifest["inputs"][-1]["role"] == "held-out-development-transfer-after-small-system-choice",
    }
    inputs: dict[str, Any] = {}
    for record in manifest["inputs"]:
        case_id = record["case_id"]
        if "checkpoint_path" in record:
            checkpoint = ROOT / record["checkpoint_path"]
            rows = sorted((ROOT / record["rows_directory"]).glob(record["row_prefix"] + "*.json"))
            case_checks = {
                "checkpoint_exists": checkpoint.is_file(),
                "checkpoint_sha256": checkpoint.is_file() and _sha256(checkpoint) == record["checkpoint_sha256"],
                "row_count": len(rows) == record["expected_row_count"],
                "row_case_identity": all(
                    json.loads(row.read_text(encoding="utf-8"))["case_id"] == case_id
                    for row in rows
                ),
            }
            inputs[case_id] = {
                "checks": case_checks,
                "row_count": len(rows),
                "row_set_digest": hashlib.sha256(
                    "".join(_sha256(row) for row in rows).encode("ascii")
                ).hexdigest(),
            }
        else:
            summary = ROOT / record["summary_path"]
            case_checks = {
                "summary_exists": summary.is_file(),
                "summary_sha256": summary.is_file() and _sha256(summary) == record["summary_sha256"],
            }
            inputs[case_id] = {"checks": case_checks}
        checks[f"input_{case_id}"] = all(inputs[case_id]["checks"].values())
    result = {
        "schema_version": "1.0.0",
        "artifact_kind": "v5-s8-calibration-protocol-audit",
        "passed": all(checks.values()),
        "checks": checks,
        "inputs": inputs,
        "manifest_path": str(path.relative_to(ROOT)),
        "manifest_sha256": _sha256(path),
        "claim_boundary": manifest["claim_boundary"],
    }
    if not result["passed"]:
        failed = sorted(name for name, passed in checks.items() if not passed)
        raise RuntimeError(f"V5-S8 protocol audit failed: {failed}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--artifact-path", type=Path)
    arguments = parser.parse_args()
    result = audit_manifest(arguments.manifest)
    if arguments.artifact_path is not None:
        _write_exclusive(arguments.artifact_path, result)
    print(json.dumps({"passed": result["passed"], "checks": len(result["checks"])}, sort_keys=True))


if __name__ == "__main__":
    main()

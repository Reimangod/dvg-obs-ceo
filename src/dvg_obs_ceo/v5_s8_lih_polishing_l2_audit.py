"""Audit the successful norm-aligned LiH polishing probe."""

from __future__ import annotations

import hashlib
import json
import subprocess
from typing import Any

from .baseline import ROOT
from .identity import canonical_json_bytes


RESULT = ROOT / "artifacts/v5/s8/lih-polishing-l2-alignment-probe-v1.json"
MANIFEST = ROOT / "manifests/v5-s8-lih-polishing-l2-alignment-probe-v1.json"
CODE_TAG = "dvg-obs-v5-s8-lih-polishing-l2-alignment-code-v1"


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def run_audit() -> dict:
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    content = dict(result)
    observed = content.pop("result_digest")
    optimizer = result["polishing"]["attempts"][0]["result"]
    acceptance = result["acceptance"]
    evidence = result["independent_acceptance_evidence"]
    source = result["original_c_work"]
    before = json.loads(
        (ROOT / "artifacts/v5/s8/lih-width1-transfer-v1/summary.json").read_text()
    )["source_resources"]
    after = evidence["physical_resources"]
    checks = {
        "result_digest": observed == _digest(content),
        "code_tag_is_ancestor": subprocess.run(
            ["git", "-C", str(ROOT), "merge-base", "--is-ancestor", CODE_TAG, "HEAD"],
            check=False,
        ).returncode == 0,
        "single_registered_change": (
            manifest["single_change"]["before"] == 5e-9
            and manifest["single_change"]["after"] == 1e-8
            and manifest["unchanged"]["scientific_gradient_infinity_gate"] == 1e-8
        ),
        "l2_implies_infinity_certificate": (
            optimizer["gradient_l2"] <= 1e-8
            and optimizer["gradient_infinity"] <= optimizer["gradient_l2"]
            and evidence["gradient_infinity"] <= 1e-8
        ),
        "operational_success_is_status_zero": (
            result["polishing"]["success"] is True
            and optimizer["success"] is True
            and optimizer["status"] == 0
        ),
        "all_independent_acceptance_checks_pass": (
            acceptance["accepted"] is True and all(acceptance["checks"].values())
        ),
        "physical_structural_recounts_match": (
            evidence["physical_resources"] == evidence["structural_resources"]
        ),
        "componentwise_resource_nonregression": all(
            after[field] <= before[field]
            for field in ("cnot_count", "cnot_depth", "total_depth", "parameter_count", "logical_block_count")
        ),
        "strict_resource_improvement": any(
            after[field] < before[field]
            for field in ("cnot_count", "cnot_depth", "total_depth", "parameter_count", "logical_block_count")
        ),
        "original_c_work_retained": source["exact_vqe_attempts"] == 1,
        "incremental_hvp_work_counted": (
            result["incremental_work"]["hessian_vector_products"] == 25
            and result["incremental_work"]["hessian_vector_gradient_evaluations"] == 50
        ),
        "measurement_cost_undefined": result["paper_measurement_cost"] is None,
    }
    audit = {
        "schema_version": "1.0.0",
        "artifact_kind": "v5-s8-lih-polishing-l2-alignment-probe-audit",
        "passed": all(checks.values()),
        "checks": checks,
        "scientific_result": {
            "status": "successful-causal-probe-requires-fresh-sequential-integration",
            "energy_hartree": evidence["energy_hartree"],
            "gradient_infinity": evidence["gradient_infinity"],
            "resources": after,
        },
        "claim_boundary": "Successful causal probe only; no committed path or final V5 claim until fresh integration rerun.",
        "paper_measurement_cost": None,
    }
    audit["audit_digest"] = _digest(audit)
    if not audit["passed"]:
        raise RuntimeError(
            "L2 alignment audit failed: "
            + ", ".join(key for key, passed in checks.items() if not passed)
        )
    return audit


if __name__ == "__main__":
    audit = run_audit()
    output = ROOT / "artifacts/v5/s8/lih-polishing-l2-alignment-probe-v1-audit.json"
    if output.exists():
        raise FileExistsError(output)
    output.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"passed": audit["passed"], "checks": len(audit["checks"])}, sort_keys=True))

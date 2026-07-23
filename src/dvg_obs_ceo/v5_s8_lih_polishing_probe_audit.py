"""Audit the fail-closed LiH conditional-polishing causal probe."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

from .baseline import ROOT
from .identity import canonical_json_bytes


RESULT = ROOT / "artifacts/v5/s8/lih-conditional-polishing-probe-v1.json"
MANIFEST = ROOT / "manifests/v5-s8-lih-conditional-polishing-probe-v1.json"
CODE_TAG = "dvg-obs-v5-s8-lih-polishing-probe-code-v1"


def _digest(value):
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def run_audit() -> dict:
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    content = dict(result)
    observed = content.pop("result_digest")
    attempt = result["polishing"]["attempts"][0]["result"]
    work = result["polishing"]["work"]
    trigger = manifest["trigger_evidence"]
    checks = {
        "result_digest": observed == _digest(content),
        "code_tag_is_ancestor": subprocess.run(
            ["git", "-C", str(ROOT), "merge-base", "--is-ancestor", CODE_TAG, "HEAD"],
            check=False,
        ).returncode == 0,
        "trigger_result_still_bound": hashlib.sha256(
            (ROOT / trigger["result_path"]).read_bytes()
        ).hexdigest() == trigger["result_sha256"],
        "trigger_audit_still_bound": hashlib.sha256(
            (ROOT / trigger["audit_path"]).read_bytes()
        ).hexdigest() == trigger["audit_sha256"],
        "candidate_not_reselected": manifest["algorithm"]["candidate_reselection"] is False,
        "threshold_not_relaxed": (
            manifest["algorithm"]["threshold_relaxation"] is False
            and attempt["preflight"]["threshold"] == 1e-8
        ),
        "status_failure_remains_fail_closed": (
            result["polishing"]["success"] is False
            and attempt["success"] is False
            and attempt["status"] == 2
            and result["acceptance"] is None
        ),
        "diagnostic_gradient_not_misreported_as_success": (
            attempt["gradient_infinity"] <= 1e-8
            and result["polishing"]["selected_start"] is None
        ),
        "all_incremental_work_counted": (
            work["energy_evaluations"] == 4
            and work["gradient_vector_evaluations"] == 81
            and work["hessian_vector_products"] == 39
            and work["hessian_vector_gradient_evaluations"] == 78
        ),
        "measurement_cost_undefined": (
            result["paper_measurement_cost"] is None
            and work["paper_measurement_cost"] is None
        ),
    }
    audit = {
        "schema_version": "1.0.0",
        "artifact_kind": "v5-s8-lih-conditional-polishing-probe-audit",
        "passed": all(checks.values()),
        "checks": checks,
        "scientific_result": {
            "status": "valid-negative-polishing-probe",
            "optimizer_status": attempt["status"],
            "diagnostic_gradient_infinity": attempt["gradient_infinity"],
            "accepted": False,
        },
        "claim_boundary": "The certified gradient alone does not override the frozen optimizer-status gate.",
        "paper_measurement_cost": None,
    }
    audit["audit_digest"] = _digest(audit)
    if not audit["passed"]:
        raise RuntimeError(
            "polishing probe audit failed: "
            + ", ".join(key for key, passed in checks.items() if not passed)
        )
    return audit


if __name__ == "__main__":
    audit = run_audit()
    output = ROOT / "artifacts/v5/s8/lih-conditional-polishing-probe-v1-audit.json"
    if output.exists():
        raise FileExistsError(output)
    output.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"passed": audit["passed"], "checks": len(audit["checks"])}, sort_keys=True))

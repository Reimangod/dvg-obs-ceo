"""Independent, read-only audit of a V3-S1 calibration artifact."""

from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import subprocess
from typing import Any

import numpy as np

from .baseline import ROOT
from .v3_gradient_audit import DEFAULT_MANIFEST, PROTOCOL_ID, _sha256


DEFAULT_RESULT = ROOT / "artifacts" / "v3" / "s1-gradient-calibration-v1.json"


class V3GradientResultAuditError(RuntimeError):
    """Raised when a saved S1 result is internally inconsistent."""


def _git(*arguments: str) -> str:
    return subprocess.check_output(["git", "-C", str(ROOT), *arguments], text=True).strip()


def audit_result(
    result_path: Path = DEFAULT_RESULT,
    manifest_path: Path = DEFAULT_MANIFEST,
) -> dict[str, Any]:
    artifact = json.loads(result_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    checks: dict[str, bool] = {
        "protocol_id": artifact.get("protocol_id") == PROTOCOL_ID,
        "manifest_sha256": artifact.get("manifest_sha256") == _sha256(manifest_path),
        "expected_result_count": len(artifact.get("results", []))
        == manifest["input"]["candidate_rows"]["expected_rows"],
        "paper_measurement_cost_unclaimed": artifact.get("work", {}).get(
            "paper_measurement_cost"
        )
        is None,
        "baseline_not_reexecuted": artifact.get("work", {}).get(
            "ordinary_gsd_adapt_iterations"
        )
        == 0
        and artifact.get("work", {}).get("ceo_star_adapt_iterations") == 0,
    }
    results = artifact.get("results", [])
    identifiers = [entry.get("candidate_id") for entry in results]
    checks["candidate_ids_unique"] = len(identifiers) == len(set(identifiers))

    case_counts: Counter[str] = Counter()
    kind_counts: Counter[str] = Counter()
    failed: list[str] = []
    gradient_maxima: list[float] = []
    fidelities: list[float] = []
    energy_differences: list[float] = []
    entries_consistent = True
    for entry in results:
        certificate = entry["certificate"]
        difference = np.asarray(certificate["componentwise_difference"], dtype=float)
        limits = np.asarray(certificate["componentwise_limit"], dtype=float)
        components = np.asarray(certificate["componentwise_pass"], dtype=bool)
        recomputed_components = np.abs(difference) <= limits
        certificate_passed = bool(np.all(recomputed_components))
        recomputed = bool(
            certificate_passed
            and entry["state_fidelity_passed"]
            and entry["energy_agreement_passed"]
        )
        entries_consistent &= bool(
            np.array_equal(components, recomputed_components)
            and certificate["passed"] == certificate_passed
            and entry["passed"] == recomputed
            and math.isclose(
                certificate["difference_infinity"],
                float(np.max(np.abs(difference))) if difference.size else 0.0,
                rel_tol=0.0,
                abs_tol=0.0,
            )
        )
        if not recomputed:
            failed.append(entry["candidate_id"])
        case_counts[entry["case_id"]] += 1
        kind_counts[entry["kind"]] += 1
        gradient_maxima.append(float(certificate["difference_infinity"]))
        fidelities.append(float(certificate["source_target_state_fidelity"]))
        energy_differences.append(
            float(certificate["source_target_energy_difference_hartree"])
        )
    checks["entry_recomputation"] = entries_consistent
    checks["case_counts"] = dict(sorted(case_counts.items())) == artifact["case_counts"]
    checks["kind_counts"] = dict(sorted(kind_counts.items())) == artifact["kind_counts"]
    checks["failed_ids"] = failed == artifact["failed_candidate_ids"]
    checks["aggregate_gradient_max"] = bool(gradient_maxima) and max(
        gradient_maxima
    ) == artifact["maximum_gradient_difference_infinity"]
    checks["aggregate_fidelity_min"] = bool(fidelities) and min(fidelities) == artifact[
        "minimum_source_target_state_fidelity"
    ]
    checks["aggregate_energy_max"] = bool(energy_differences) and max(
        energy_differences
    ) == artifact["maximum_source_target_energy_difference_hartree"]
    execution = artifact.get("execution_freeze", {})
    try:
        checks["execution_tag"] = _git(
            "rev-parse", f"{execution['protocol_tag']}^{{}}"
        ) == execution["head"]
    except (KeyError, subprocess.CalledProcessError):
        checks["execution_tag"] = False
    checks["overall_pass"] = artifact.get("passed") is True and not failed

    failed_checks = [name for name, passed in checks.items() if not passed]
    result = {
        "schema_version": "1.0.0",
        "artifact_kind": "v3-s1-independent-result-audit",
        "result_sha256": _sha256(result_path),
        "passed": not failed_checks,
        "checks": checks,
        "failed_checks": failed_checks,
    }
    if failed_checks:
        raise V3GradientResultAuditError(
            "S1 independent result audit failed: " + ", ".join(failed_checks)
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result-file", type=Path, default=DEFAULT_RESULT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    arguments = parser.parse_args()
    print(json.dumps(audit_result(arguments.result_file, arguments.manifest), sort_keys=True))


if __name__ == "__main__":
    main()

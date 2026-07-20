"""Independent compact audit for S12 reuse probe artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from .baseline import ROOT


class S12AuditError(RuntimeError):
    """Raised when S12 evidence is inconsistent."""


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit() -> dict[str, Any]:
    cases = {}
    for case, relative in (
        ("h2-1.5", "h2-1.5-exact-reuse-v1-1"),
        ("lih-3.0", "lih-3.0-exact-reuse-v1-1"),
    ):
        summary_path = ROOT / "artifacts" / "s12" / relative / "summary.json"
        value = _read(summary_path)
        inventory = value["observable_inventory"]
        off = value["branches"]["reuse_off"]["ledger"]
        on = value["branches"]["reuse_on"]["ledger"]
        checks = {
            "probe_passed": value["passed"] is True and all(value["checks"].values()),
            "requests_match_inventory": off["requests"] == on["requests"]
            == inventory["energy_nonidentity_pauli_terms"] + inventory["ogm_gradient_union_nonidentity_pauli_terms"],
            "off_all_fresh": off["fresh_pauli_expectation_evaluations"] == off["requests"] and off["cache_hits"] == 0,
            "on_accounting_closes": on["fresh_pauli_expectation_evaluations"] + on["cache_hits"] == on["requests"],
            "hits_equal_cross_context_overlap": on["cache_hits"] == inventory["cross_context_overlap_terms"],
            "fresh_reduction_equals_hits": off["fresh_pauli_expectation_evaluations"] - on["fresh_pauli_expectation_evaluations"] == on["cache_hits"],
            "gradient_digest_equal": value["branches"]["reuse_off"]["gradient_vector_digest"] == value["branches"]["reuse_on"]["gradient_vector_digest"],
            "paper_cost_unclaimed": value["paper_measurement_cost"] is None,
        }
        failed = [name for name, passed in checks.items() if not passed]
        cases[case] = {
            "checks": checks,
            "passed": not failed,
            "failed_checks": failed,
            "summary_sha256": _sha(summary_path),
            "fresh_reduction": off["fresh_pauli_expectation_evaluations"] - on["fresh_pauli_expectation_evaluations"],
            "fresh_reduction_fraction": (
                off["fresh_pauli_expectation_evaluations"] - on["fresh_pauli_expectation_evaluations"]
            ) / off["fresh_pauli_expectation_evaluations"],
        }
    manifest_path = ROOT / "artifacts" / "s12" / "lih-3.0-exact-reuse-v1-1" / "raw-ledger-manifest.json"
    manifest = _read(manifest_path)
    raw_root = ROOT / manifest["local_root"]
    expected_event_digests = {
        "reuse_off-ledger.json": _read(ROOT / "artifacts" / "s12" / "lih-3.0-exact-reuse-v1-1" / "summary.json")["branches"]["reuse_off"]["ledger"]["event_ledger_digest"],
        "reuse_on-ledger.json": _read(ROOT / "artifacts" / "s12" / "lih-3.0-exact-reuse-v1-1" / "summary.json")["branches"]["reuse_on"]["ledger"]["event_ledger_digest"],
    }
    manifest_consistent = all(
        entry["event_ledger_digest"] == expected_event_digests[entry["name"]]
        and len(entry["sha256"]) == 64
        and entry["bytes"] > 0
        for entry in manifest["files"]
    )
    raw_checks = {}
    for entry in manifest["files"]:
        path = raw_root / entry["name"]
        raw_checks[entry["name"]] = (
            path.stat().st_size == entry["bytes"] and _sha(path) == entry["sha256"]
        ) if path.is_file() else None
    available = [value for value in raw_checks.values() if value is not None]
    no_partial_raw_set = len(available) in (0, len(raw_checks))
    raw_integrity_passed = no_partial_raw_set and all(available)
    passed = (
        all(case["passed"] for case in cases.values())
        and manifest_consistent
        and raw_integrity_passed
    )
    result = {
        "schema_version": "1.0.0",
        "artifact_kind": "s12-independent-reuse-audit",
        "cases": cases,
        "raw_ledger_manifest_consistent": manifest_consistent,
        "raw_ledger_checks": raw_checks,
        "raw_ledgers_verified_locally": len(available) == len(raw_checks) and all(available),
        "passed": passed,
        "claim_boundary": [
            "The reduction fraction concerns fresh exact Pauli expectation kernels only.",
            "It is not a shot, commuting-collection, wall-time, or paper Measurement Cost reduction.",
        ],
    }
    if not passed:
        raise S12AuditError("S12 independent audit failed")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    result = audit()
    if arguments.output.exists():
        raise FileExistsError(arguments.output)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(arguments.output), "passed": result["passed"]}, sort_keys=True))


if __name__ == "__main__":
    main()

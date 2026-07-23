"""Independent static release audit for the frozen V5/V5.1 evidence chain."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .baseline import ROOT
from .identity import canonical_json_bytes


SUMMARY = ROOT / "artifacts/v5/release/summary-v1.json"


class V5ReleaseAuditError(RuntimeError):
    pass


def _digest_without(record: dict[str, Any], field: str) -> str:
    content = dict(record)
    observed = content.pop(field)
    calculated = hashlib.sha256(canonical_json_bytes(content)).hexdigest()
    if calculated != observed:
        raise V5ReleaseAuditError(f"internal digest mismatch: {field}")
    return calculated


def audit() -> dict[str, Any]:
    summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
    loaded: dict[str, dict[str, Any]] = {}
    checks: dict[str, bool] = {}
    for item in summary["inputs"]:
        path = ROOT / item["path"]
        checks[f"{item['stage']}:sha256"] = (
            hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]
        )
        loaded[item["stage"]] = json.loads(path.read_text(encoding="utf-8"))
    s9 = loaded["V5-S9"]
    s10 = loaded["V5-S10"]
    s11 = loaded["V5.1-S11"]
    s11b = loaded["V5.1-S11b"]
    checks.update(
        {
            "s10_digest": bool(_digest_without(s10, "result_digest")),
            "s11_digest": bool(_digest_without(s11, "result_digest")),
            "s11b_digest": bool(_digest_without(s11b, "result_digest")),
            "core_v5_success_list": (
                s9["performance_gates"]["primary_success_cases"]
                == summary["core_v5_gate"]["strict_success_cases"]
            ),
            "core_v5_strong_false": (
                s9["performance_gates"]["strong_development_success_passed"]
                is False
                and summary["core_v5_gate"]["strong_development_success_passed"]
                is False
            ),
            "s10_two_certified": (
                s10["certified_candidate_count"] == 2
                and s10["adoption_gate_passed"] is True
            ),
            "s11_passed": s11["passed"] is True and all(s11["checks"].values()),
            "s11b_passed": s11b["passed"] is True and all(s11b["checks"].values()),
            "fusion_no_optimizer": (
                s11["work"]["optimizer_starts"] == 0
                and s11b["work"]["optimizer_starts"] == 0
            ),
            "measurement_cost_undefined": (
                summary["paper_measurement_cost"] is None
                and s9["paper_measurement_cost"] is None
                and s10["paper_measurement_cost"] is None
                and s11["work"]["paper_measurement_cost"] is None
                and s11b["work"]["paper_measurement_cost"] is None
            ),
            "outcome_informed_not_confirmatory": (
                summary["v5_1_extension_gate"]["outcome_informed_cases"]
                == ["h6-1.5"]
                and summary["v5_1_extension_gate"]["confirmatory_cases"] == []
                and summary["v5_1_extension_gate"][
                    "global_superiority_established"
                ]
                is False
            ),
            "old_artifacts_declared_immutable": (
                summary["safety"]["old_v4_1_and_v5_artifacts_modified"] is False
            ),
        }
    )
    front = summary["h6_1_5_pareto_front"]
    checks["pareto_values"] = (
        [item["cnot_count"] for item in front] == [840, 840]
        and [item["parameter_count"] for item in front] == [129, 130]
        and front[0]["energy_increase_hartree"]
        == s11["target"]["energy_increase_from_ceo_source_hartree"]
        and front[1]["energy_increase_hartree"]
        == s11b["target"]["energy_increase_from_ceo_source_hartree"]
    )
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise V5ReleaseAuditError("release audit failed: " + ", ".join(failed))
    return {
        "schema_version": "1.0.0",
        "artifact_kind": "v5-v5.1-release-audit",
        "checks": checks,
        "passed": True,
        "summary_sha256": hashlib.sha256(SUMMARY.read_bytes()).hexdigest(),
        "paper_measurement_cost": None,
    }

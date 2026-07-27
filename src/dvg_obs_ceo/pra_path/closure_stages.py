"""Fail-closed S7--S10 artifacts after the frozen S6 NO-GO."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
from typing import Any

from dvg_obs_ceo.artifact_io import atomic_write_new_json
from dvg_obs_ceo.baseline import ROOT
from dvg_obs_ceo.identity import sha256_hex


S6_AUDIT = ROOT / "artifacts/pra_path/s6/result-audit-v1.json"
OUTPUTS = {
    "s7": ROOT / "artifacts/pra_path/s7/not-authorized-v1.json",
    "s8": ROOT / "artifacts/pra_path/s8/not-authorized-v1.json",
    "s9": ROOT / "artifacts/pra_path/s9/not-authorized-v1.json",
    "s10": ROOT / "artifacts/pra_path/s10/scientific-editorial-gate-v1.json",
}


class ClosureStageError(RuntimeError):
    """Raised when a dependent stage is incorrectly authorized."""


def _git(*arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _verified(path: Path, digest_field: str) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    content = dict(payload)
    digest = content.pop(digest_field, None)
    if digest != sha256_hex(content):
        raise ClosureStageError(f"digest mismatch: {path}")
    return payload


def _base(stage: str, input_path: Path, input_digest: str) -> dict[str, Any]:
    return {
        "schema": f"dvg-obs-ceo.pra-path.{stage}-closure.v1",
        "stage": stage.upper(),
        "status": "NOT_AUTHORIZED",
        "decision": f"NOT_AUTHORIZED_{stage.upper()}_UPSTREAM_GATE_FAILED",
        "input": {
            "path": str(input_path.relative_to(ROOT)),
            "digest": input_digest,
        },
        "execution": {"git_commit": _git("rev-parse", "HEAD")},
        "scientific_actions_executed": False,
        "threshold_or_optimizer_changed": False,
        "historical_or_development_outcomes_discarded": False,
    }


def build_s7() -> dict[str, Any]:
    s6 = _verified(S6_AUDIT, "audit_digest")
    if s6["authorization"]["s7"]:
        raise ClosureStageError("S6 unexpectedly authorized S7")
    report = _base("s7", S6_AUDIT, s6["audit_digest"])
    report.update(
        {
            "reason": (
                "S6 did not establish a certified non-H4 development "
                "condition; the preregistered matched-work entry gate failed."
            ),
            "matched_work_executed": False,
            "causal_ablation_executed": False,
            "paper_measurement_cost": None,
            "authorization": {"s8": False, "s9": False},
            "claim_boundary": (
                "No matched-work superiority or causal-ablation result exists."
            ),
        }
    )
    report["report_digest"] = sha256_hex(report)
    return report


def build_s8() -> dict[str, Any]:
    s7 = _verified(OUTPUTS["s7"], "report_digest")
    if s7["authorization"]["s8"]:
        raise ClosureStageError("S7 unexpectedly authorized S8")
    report = _base("s8", OUTPUTS["s7"], s7["report_digest"])
    report.update(
        {
            "reason": (
                "The matched-work development gate was not reached, so no "
                "prospective scientific protocol may be activated."
            ),
            "prospective_manifest_frozen": False,
            "prospective_molecule_selected": False,
            "prospective_queue_created": False,
            "development_data_relabelled_prospective": False,
            "authorization": {"s9": False},
            "claim_boundary": (
                "The structural H7/H3 order from S5 remains planning metadata "
                "and is not an activated prospective protocol."
            ),
        }
    )
    report["report_digest"] = sha256_hex(report)
    return report


def build_s9() -> dict[str, Any]:
    s8 = _verified(OUTPUTS["s8"], "report_digest")
    if s8["authorization"]["s9"]:
        raise ClosureStageError("S8 unexpectedly authorized S9")
    report = _base("s9", OUTPUTS["s8"], s8["report_digest"])
    report.update(
        {
            "reason": "No prospective protocol or molecule was authorized.",
            "molecule_or_geometry_executed": [],
            "candidate_energy_evaluations": 0,
            "matched_work_comparators_executed": 0,
            "reruns": 0,
            "prospective_result_exists": False,
            "authorization": {"positive_pra_performance_claim": False},
            "claim_boundary": "No prospective validation evidence exists.",
        }
    )
    report["report_digest"] = sha256_hex(report)
    return report


def build_s10() -> dict[str, Any]:
    s6 = _verified(S6_AUDIT, "audit_digest")
    s7 = _verified(OUTPUTS["s7"], "report_digest")
    s8 = _verified(OUTPUTS["s8"], "report_digest")
    s9 = _verified(OUTPUTS["s9"], "report_digest")
    criteria = {
        "distinct_methodological_contribution_supported_by_bounded_prior_art": True,
        "native_physical_cnot_or_depth_reduction_independently_verified": True,
        "two_independent_development_conditions_add_matched_work_pareto_points": False,
        "one_prospective_geometry_adds_matched_work_pareto_point": False,
        "negative_and_null_outcomes_retained": True,
        "causal_ablation_separates_mechanisms": False,
        "accepted_points_pass_all_certification_layers": True,
        "clean_environment_reproduces_submission_tables_and_figures": False,
    }
    report: dict[str, Any] = {
        "schema": "dvg-obs-ceo.pra-path.s10-scientific-editorial-gate.v1",
        "stage": "S10",
        "status": "COMPLETE",
        "decision": "NO_GO_PRA_PERFORMANCE_SUBMISSION_PACKAGE",
        "inputs": {
            "s6_audit_digest": s6["audit_digest"],
            "s7_report_digest": s7["report_digest"],
            "s8_report_digest": s8["report_digest"],
            "s9_report_digest": s9["report_digest"],
        },
        "criteria": criteria,
        "criteria_passed": sum(criteria.values()),
        "criteria_total": len(criteria),
        "strength_assessment": {
            "positive": (
                "The registered native method is technically distinct under "
                "the bounded audit and reproduces certified H4 reductions at "
                "two new geometries."
            ),
            "limitation": (
                "Cross-system certification, matched-work comparison, causal "
                "ablation, and prospective validation are absent."
            ),
            "submission_recommendation": (
                "Do not submit a general performance-improvement PRA claim "
                "from this evidence package."
            ),
        },
        "research_integrity": {
            "failed_gate_overridden": False,
            "negative_result_retained": True,
            "post_outcome_tuning_performed": False,
            "prospective_label_misused": False,
        },
        "authorization": {
            "pra_performance_manuscript": False,
            "s11_negative_result_release": True,
        },
        "execution": {"git_commit": _git("rev-parse", "HEAD")},
        "claim_boundary": (
            "Editorial/scientific closure decision, not a journal acceptance "
            "prediction and not a claim that future preregistered work cannot "
            "succeed."
        ),
    }
    report["report_digest"] = sha256_hex(report)
    return report


BUILDERS = {
    "s7": build_s7,
    "s8": build_s8,
    "s9": build_s9,
    "s10": build_s10,
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=tuple(BUILDERS))
    arguments = parser.parse_args()
    output = OUTPUTS[arguments.stage]
    if output.exists():
        raise ClosureStageError(f"refusing to overwrite {output}")
    if _git("status", "--porcelain"):
        raise ClosureStageError("closure stage requires a clean worktree")
    report = BUILDERS[arguments.stage]()
    atomic_write_new_json(output, report)
    print(json.dumps({"stage": arguments.stage, "decision": report["decision"]}))


if __name__ == "__main__":
    main()

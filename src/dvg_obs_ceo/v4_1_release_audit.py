"""S10 cross-case audit and transparent V4/V4.1 comparison release."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any, Mapping

from .baseline import ROOT
from .identity import canonical_json_bytes
from .v3_protocol import _write_exclusive
from .v4_1_bundle import CaseRunLease, audit_case_state, validate_complete_bundle
from .v4_1_exact_audit import audit_case
from .v4_1_exact_multisystem import EXACT_CODE_TAG, OUTPUT_ROOT, S5_ROOT, _read_summary
from .v4_1_protocol import DEFAULT_MANIFEST, audit_manifest


S10_CODE_TAG = "dvg-obs-v4.1-s10-audit-code-v1"
S10_ROOT = ROOT / "artifacts/v4.1"
S10_CASE_ID = "s10-release-v1"
CASES = ("h6-1.5", "h6-3.0", "beh2-3.0")
RESULT_TAGS = {
    "h6-1.5": "dvg-obs-v4.1-h6-1p5-result-v1",
    "h6-3.0": "dvg-obs-v4.1-h6-3p0-result-v1",
    "beh2-3.0": "dvg-obs-v4.1-beh2-3p0-result-v1",
}
V4_LIH = ROOT / "artifacts/v4/s7-lih-development-v1-2/summary.json"
V41_LIH = ROOT / "artifacts/v4.1/s6-regression/lih-3.0/summary.json"
LIH_OFFLINE = ROOT / "artifacts/s10/lih-3a-first-accuracy-primary-v1-2/summary.json"
V4_LIH_SHA256 = "f07ecc935f1edd26b27dc4c36868d394a9b9215266a823b098eb1991c8f875ad"
REQUIRED_THREADS = {"OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}


class V41ReleaseAuditError(RuntimeError):
    """Raised when an S10 release claim is not supported by stored evidence."""


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _git(*arguments: str) -> str:
    return subprocess.check_output(["git", "-C", str(ROOT), *arguments], text=True).strip()


def _summary(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    stored = value.pop("summary_digest")
    if _digest(value) != stored:
        raise V41ReleaseAuditError(f"summary digest mismatch: {path}")
    value["summary_digest"] = stored
    return value


def _legacy_lih_summary() -> dict[str, Any]:
    if hashlib.sha256(V4_LIH.read_bytes()).hexdigest() != V4_LIH_SHA256:
        raise V41ReleaseAuditError("legacy V4 LiH summary file drift")
    return json.loads(V4_LIH.read_text(encoding="utf-8"))


def verify_release_freeze() -> dict[str, Any]:
    head = _git("rev-parse", "HEAD")
    code_commit = _git("rev-parse", f"{S10_CODE_TAG}^{{}}")
    dirty = _git("status", "--porcelain")
    threads = {name: os.environ.get(name) for name in REQUIRED_THREADS}
    tag_commits = {case: _git("rev-parse", f"{tag}^{{}}") for case, tag in RESULT_TAGS.items()}
    checks = {
        "head_is_s10_code_tag": head == code_commit,
        "clean_worktree": not dirty,
        "canonical_threads": threads == REQUIRED_THREADS,
        "result_tags_are_ancestors": all(
            subprocess.run(
                ["git", "-C", str(ROOT), "merge-base", "--is-ancestor", commit, head],
                check=False,
            ).returncode == 0
            for commit in tag_commits.values()
        ),
        "result_tags_contain_bundles": all(
            subprocess.run(
                [
                    "git", "-C", str(ROOT), "cat-file", "-e",
                    f"{tag_commits[case]}:artifacts/v4.1/multisystem/{case}/bundle-manifest.json",
                ],
                check=False,
            ).returncode == 0
            for case in CASES
        ),
        "release_absent": audit_case_state(S10_ROOT, S10_CASE_ID)["safe_to_start"],
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise V41ReleaseAuditError("S10 release freeze failed: " + ", ".join(failed))
    return {
        "head": head,
        "s10_code_tag": S10_CODE_TAG,
        "s10_code_commit": code_commit,
        "exact_code_tag": EXACT_CODE_TAG,
        "result_tags": RESULT_TAGS,
        "result_tag_commits": tag_commits,
        "threads": threads,
        "checks": checks,
    }


def _selected(attempt: Mapping[str, Any]) -> Mapping[str, Any]:
    return attempt["fallback"] or attempt["primary"]


def _resource_projection(snapshot: Mapping[str, Any]) -> dict[str, int]:
    return {
        key: int(snapshot[key])
        for key in ("parameter_count", "logical_block_count", "cnot_count", "cnot_depth", "total_depth")
    }


def _resource_delta(source: Mapping[str, Any], final: Mapping[str, Any]) -> dict[str, int]:
    return {key: int(source[key]) - int(final[key]) for key in _resource_projection(source)}


def _maximum_cardinality(search: Mapping[str, Any]) -> int:
    return max((len(record["candidate_ids"]) for record in search["records"]), default=0)


def _new_attempt_work(summary: Mapping[str, Any], checkpoint: Mapping[str, Any]) -> dict[str, int]:
    base = {
        "energy_evaluations": int(checkpoint["work"]["baseline_optimizer_energy_evaluations"]) + 1,
        "gradient_component_evaluations": int(checkpoint["work"]["baseline_gradient_component_equivalent"]),
        "gradient_vector_evaluations": 0,
        "statevector_kernels": 1,
        "optimizer_iterations": 0,
    }
    fields = tuple(base)
    return {
        field: sum(int(attempt["work_after_attempt"][field]) - base[field] for attempt in summary["attempts"])
        for field in fields
    }


def _v4_multisystem_row(case_id: str) -> dict[str, Any]:
    summary = _summary(ROOT / f"artifacts/v4/multisystem/{case_id}/summary.json")
    checkpoint = json.loads((ROOT / summary["checkpoint"]["path"]).read_text(encoding="utf-8"))
    source = summary["checkpoint"]["resources"]["snapshot"]
    winner_id = summary["endpoint_winners"]["circuit_primary"]
    winner = next((item for item in summary["attempts"] if item["constraint_semantic_id"] == winner_id), None)
    final_energy = summary["checkpoint"]["energy_hartree"] if winner is None else _selected(winner)["energy_hartree"]
    final_resources = source if winner is None else winner["physical_resources"]["snapshot"]
    exact = summary["checkpoint"]["exact_energy_hartree"]
    return {
        "case_id": case_id,
        "method": "V4",
        "primary_endpoint": "circuit_primary",
        "winner_semantic_id": winner_id,
        "source_energy_hartree": summary["checkpoint"]["energy_hartree"],
        "final_energy_hartree": final_energy,
        "exact_energy_hartree": exact,
        "source_absolute_error_hartree": abs(summary["checkpoint"]["energy_hartree"] - exact),
        "final_absolute_error_hartree": abs(final_energy - exact),
        "energy_increase_hartree": final_energy - summary["checkpoint"]["energy_hartree"],
        "source_resources": _resource_projection(source),
        "final_resources": _resource_projection(final_resources),
        "resource_reductions": _resource_delta(source, final_resources),
        "catalog_count": summary["catalog"]["candidate_count"],
        "evaluated_state_count": summary["search"]["counts"]["completed"],
        "maximum_cardinality": _maximum_cardinality(summary["search"]),
        "semantic_failures": summary["search"]["counts"]["semantic_composition_failures"],
        "numerical_failures": summary["search"]["counts"]["candidate_numerical_failures"],
        "quality_failures": len(summary["quality_rejections"]),
        "optimizer_failures": sum(not item["primary"]["optimizer"]["success"] for item in summary["attempts"]),
        "acceptance_failures": sum(item["transaction_status"] != "accepted" for item in summary["attempts"]),
        "quadratic_solves": summary["search"]["counts"]["quadratic_solves"],
        "full_resource_recounts": summary["work"]["full_resource_recounts"],
        "exact_vqe_attempts": summary["work"]["exact_vqe_attempts"],
        "exact_stage_work": _new_attempt_work(summary, checkpoint),
        "source_wall_time_seconds": checkpoint["work"]["wall_time_seconds"],
        "exact_stage_wall_time_seconds": summary["work"].get("wall_time_seconds"),
        "wall_time_seconds": (
            checkpoint["work"]["wall_time_seconds"] + summary["work"]["wall_time_seconds"]
            if summary["work"].get("wall_time_seconds") is not None else None
        ),
        "search_status": summary["search"]["status"],
        "paper_measurement_cost": None,
    }


def _v41_multisystem_row(case_id: str) -> dict[str, Any]:
    summary = _read_summary(OUTPUT_ROOT / case_id / "summary.json")
    s5 = _read_summary(S5_ROOT / case_id / "summary.json")
    checkpoint = json.loads((ROOT / summary["checkpoint"]["path"]).read_text(encoding="utf-8"))
    source = summary["checkpoint"]["resources"]["snapshot"]
    winner_id = summary["endpoint_winners"]["cnot_primary"]
    winner = next((item for item in summary["attempts"] if item["constraint_semantic_id"] == winner_id), None)
    final_energy = summary["checkpoint"]["energy_hartree"] if winner is None else _selected(winner)["energy_hartree"]
    final_resources = source if winner is None else winner["physical_resources"]["snapshot"]
    exact = summary["checkpoint"]["exact_energy_hartree"]
    return {
        "case_id": case_id,
        "method": "V4.1",
        "primary_endpoint": "cnot_primary",
        "winner_semantic_id": winner_id,
        "source_energy_hartree": summary["checkpoint"]["energy_hartree"],
        "final_energy_hartree": final_energy,
        "exact_energy_hartree": exact,
        "source_absolute_error_hartree": abs(summary["checkpoint"]["energy_hartree"] - exact),
        "final_absolute_error_hartree": abs(final_energy - exact),
        "energy_increase_hartree": final_energy - summary["checkpoint"]["energy_hartree"],
        "source_resources": _resource_projection(source),
        "final_resources": _resource_projection(final_resources),
        "resource_reductions": _resource_delta(source, final_resources),
        "catalog_count": s5["catalog"]["candidate_count"],
        "evaluated_state_count": s5["search"]["counts"]["completed"],
        "maximum_cardinality": _maximum_cardinality(s5["search"]),
        "semantic_failures": s5["search"]["counts"]["semantic_composition_failures"],
        "numerical_failures": s5["search"]["counts"]["candidate_numerical_failures"],
        "quality_failures": len(s5["quality_rejections"]),
        "optimizer_failures": sum(not item["primary"]["optimizer"]["success"] for item in summary["attempts"]),
        "acceptance_failures": sum(item["transaction_status"] != "accepted" for item in summary["attempts"]),
        "quadratic_solves": s5["search"]["counts"]["quadratic_solves"],
        "full_resource_recounts": summary["work"]["full_resource_recounts_screening"],
        "exact_vqe_attempts": summary["work"]["exact_vqe_attempts"],
        "exact_stage_work": _new_attempt_work(summary, checkpoint),
        "source_wall_time_seconds": checkpoint["work"]["wall_time_seconds"],
        "exact_stage_wall_time_seconds": summary["work"]["wall_time_seconds"],
        "wall_time_seconds": checkpoint["work"]["wall_time_seconds"] + summary["work"]["wall_time_seconds"],
        "search_status": summary["search_completeness"],
        "paper_measurement_cost": None,
    }


def _lih_rows() -> list[dict[str, Any]]:
    v4 = _legacy_lih_summary()
    s6 = _summary(V41_LIH)
    offline = json.loads(LIH_OFFLINE.read_text(encoding="utf-8"))
    checkpoint = json.loads((ROOT / v4["checkpoint"]["path"]).read_text(encoding="utf-8"))
    exact = offline["offline_evaluation"]["fci_energy_hartree"]
    winner_id = v4["endpoint_winners"]["circuit_primary"]
    winner = next(item for item in v4["attempts"] if item["constraint_semantic_id"] == winner_id)
    final_energy = _selected(winner)["energy_hartree"]
    source = v4["checkpoint"]["resources"]["snapshot"]
    final_resources = winner["physical_resources"]["snapshot"]
    common = {
        "case_id": "lih-3.0",
        "primary_endpoint": "circuit_primary",
        "winner_semantic_id": winner_id,
        "source_energy_hartree": v4["checkpoint"]["energy_hartree"],
        "final_energy_hartree": final_energy,
        "exact_energy_hartree": exact,
        "source_absolute_error_hartree": abs(v4["checkpoint"]["energy_hartree"] - exact),
        "final_absolute_error_hartree": abs(final_energy - exact),
        "energy_increase_hartree": final_energy - v4["checkpoint"]["energy_hartree"],
        "source_resources": _resource_projection(source),
        "final_resources": _resource_projection(final_resources),
        "resource_reductions": _resource_delta(source, final_resources),
        "catalog_count": v4["catalog"]["candidate_count"],
        "evaluated_state_count": v4["search"]["counts"]["completed"],
        "maximum_cardinality": _maximum_cardinality(v4["search"]),
        "semantic_failures": v4["search"]["counts"].get("semantic_composition_failures"),
        "numerical_failures": v4["search"]["counts"]["candidate_numerical_failures"],
        "quality_failures": (
            sum(bool(record["eligible"]) for record in v4["search"]["records"])
            - v4["quality_passed_resource_candidate_count"]
            - len(v4["resource_failures"])
        ),
        "optimizer_failures": sum(not item["primary"]["optimizer"]["success"] for item in v4["attempts"]),
        "acceptance_failures": sum(item["transaction_status"] != "accepted" for item in v4["attempts"]),
        "quadratic_solves": v4["search"]["counts"]["quadratic_solves"],
        "full_resource_recounts": v4["work"]["full_resource_recounts"],
        "exact_vqe_attempts": v4["work"]["exact_vqe_attempts"],
        "exact_stage_work": _new_attempt_work(v4, checkpoint),
        "source_wall_time_seconds": checkpoint["work"]["wall_time_seconds"],
        "exact_stage_wall_time_seconds": v4["work"].get("wall_time_seconds"),
        "wall_time_seconds": (
            checkpoint["work"]["wall_time_seconds"] + v4["work"]["wall_time_seconds"]
            if v4["work"].get("wall_time_seconds") is not None else None
        ),
        "search_status": v4["search"]["status"],
        "paper_measurement_cost": None,
    }
    if not (
        s6["passed"]
        and s6["lih"]["v4_final_energy_delta_hartree"] == 0.0
        and s6["lih"]["v4_resource_snapshot_equal"] is True
    ):
        raise V41ReleaseAuditError("LiH V4.1 regression is not exactly bound to V4")
    return [{**common, "method": "V4"}, {**common, "method": "V4.1-regression"}]


def _markdown(rows: list[dict[str, Any]]) -> str:
    lines = [
        "# V4.1 S10 audited comparison",
        "",
        "Primary comparison uses `cnot_primary` for V4.1 and the preregistered `circuit_primary` for V4. LiH V4.1 is an exact regression replay of V4.",
        "",
        "| Case | Method | Source abs. error (Ha) | Final abs. error (Ha) | E increase (Ha) | CNOT | ΔCNOT | CNOT depth | ΔCNOT depth | Depth | ΔDepth | Params | ΔParams | Blocks | ΔBlocks | Attempts | Accepted | Search |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        reductions = row["resource_reductions"]
        final = row["final_resources"]
        accepted = row["exact_vqe_attempts"] - row["acceptance_failures"]
        lines.append(
            f"| {row['case_id']} | {row['method']} | {row['source_absolute_error_hartree']:.12g} | "
            f"{row['final_absolute_error_hartree']:.12g} | {row['energy_increase_hartree']:.12g} | "
            f"{final['cnot_count']} | {reductions['cnot_count']} | "
            f"{final['cnot_depth']} | {reductions['cnot_depth']} | {final['total_depth']} | {reductions['total_depth']} | "
            f"{final['parameter_count']} | {reductions['parameter_count']} | {final['logical_block_count']} | "
            f"{reductions['logical_block_count']} | {row['exact_vqe_attempts']} | {accepted} | {row['search_status']} |"
        )
    lines.extend([
        "",
        "`Δ` is source minus final, so a positive number is a reduction. Exact/FCI energy is offline reporting only and was absent from S5 screening and ranking.",
        "",
        "| Case | Method | Catalog | Evaluated | Max card. | Semantic fail | Numerical fail | Quality fail | Optimizer fail | Acceptance fail | Recounts | Exact attempts | Energy eval. | Grad vectors | Grad components | Statevectors | Source wall (s) | Exact wall (s) |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for row in rows:
        work = row["exact_stage_work"]
        semantic = "n/a" if row["semantic_failures"] is None else str(row["semantic_failures"])
        exact_wall = "n/a" if row["exact_stage_wall_time_seconds"] is None else f"{row['exact_stage_wall_time_seconds']:.6g}"
        lines.append(
            f"| {row['case_id']} | {row['method']} | {row['catalog_count']} | {row['evaluated_state_count']} | "
            f"{row['maximum_cardinality']} | {semantic} | {row['numerical_failures']} | {row['quality_failures']} | "
            f"{row['optimizer_failures']} | {row['acceptance_failures']} | {row['full_resource_recounts']} | "
            f"{row['exact_vqe_attempts']} | {work['energy_evaluations']} | {work['gradient_vector_evaluations']} | "
            f"{work['gradient_component_evaluations']} | {work['statevector_kernels']} | "
            f"{row['source_wall_time_seconds']:.6g} | {exact_wall} |"
        )
    lines.extend([
        "",
        "Paper-equivalent Measurement Cost remains `null`; quadratic solves, simulator work, and wall time are not substitutes.",
    ])
    return "\n".join(lines) + "\n"


def run() -> dict[str, Any]:
    freeze = verify_release_freeze()
    s0 = audit_manifest(DEFAULT_MANIFEST)
    independent: dict[str, Any] = {}
    for case_id in CASES:
        independent[case_id] = audit_case(case_id)
    rows = _lih_rows()
    for case_id in CASES:
        rows.extend((_v4_multisystem_row(case_id), _v41_multisystem_row(case_id)))
    checks = {
        "all_case_audits_pass": all(value["passed"] for value in independent.values()),
        "all_result_bundles_complete": all(
            validate_complete_bundle(OUTPUT_ROOT / case_id)["case_id"] == case_id for case_id in CASES
        ),
        "same_source_per_v4_pair": all(
            next(row for row in rows if row["case_id"] == case and row["method"] == "V4")["source_energy_hartree"]
            == next(row for row in rows if row["case_id"] == case and row["method"] == "V4.1")["source_energy_hartree"]
            for case in CASES
        ),
        "v41_has_exact_attempts": all(
            next(row for row in rows if row["case_id"] == case and row["method"] == "V4.1")["exact_vqe_attempts"] > 0
            for case in CASES
        ),
        "measurement_cost_unclaimed": all(row["paper_measurement_cost"] is None for row in rows),
        "all_search_labels_explicit": all(
            row["search_status"] in {"surrogate-complete", "budget-truncated", "exhaustive"} for row in rows
        ),
    }
    failed = [name for name, passed in checks.items() if not passed]
    audit: dict[str, Any] = {
        "schema_version": "1.0.0",
        "artifact_kind": "v4.1-s10-independent-multisystem-audit",
        "freeze": freeze,
        "s0_manifest_sha256": s0["manifest_sha256"],
        "case_audits": independent,
        "checks": checks,
        "failed_checks": failed,
        "passed": not failed,
        "paper_measurement_cost": None,
        "claim_boundary": (
            "Observed development-case comparison; no global optimum, unseen generalization, "
            "hardware-noise, shot-cost, or paper Measurement Cost claim."
        ),
    }
    audit["artifact_digest"] = _digest(audit)
    comparison = {
        "schema_version": "1.0.0",
        "artifact_kind": "v4-v4.1-audited-comparison",
        "primary_endpoint_policy": {"V4": "circuit_primary", "V4.1": "cnot_primary"},
        "rows": rows,
        "paper_measurement_cost": None,
        "claim_boundary": audit["claim_boundary"],
    }
    comparison["artifact_digest"] = _digest(comparison)
    if failed:
        raise V41ReleaseAuditError("S10 audit failed: " + ", ".join(failed))
    with CaseRunLease(
        S10_ROOT, S10_CASE_ID, s0["manifest_sha256"],
        hashlib.sha256(canonical_json_bytes(freeze["result_tag_commits"])).hexdigest(),
    ) as lease:
        _write_exclusive(lease.staging / "multisystem-audit.json", audit)
        _write_exclusive(lease.staging / "comparison.json", comparison)
        markdown_path = lease.staging / "comparison.md"
        descriptor = os.open(markdown_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", closefd=False) as handle:
                handle.write(_markdown(rows))
                handle.flush()
                os.fsync(handle.fileno())
        finally:
            os.close(descriptor)
        lease.finalize()
        canonical = lease.promote()
    return {"passed": True, "canonical": str(canonical), "rows": rows, "audit_digest": audit["artifact_digest"]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.parse_args()
    result = run()
    print(json.dumps({"passed": result["passed"], "rows": len(result["rows"]), "canonical": result["canonical"]}, sort_keys=True))


if __name__ == "__main__":
    main()

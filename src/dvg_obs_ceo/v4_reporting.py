"""Build machine-readable tables and figures for the V4 development result."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any

from .baseline import ROOT
from .block_ir import enumerate_candidates, recover_dvg_blocks
from .composition import compose_registered_candidates
from .resources import AnsatzStructure, evaluate_full_circuit_resources, paper_era_backend
from .s10_lih import _algorithm as _lih_algorithm


REPORT_TAG = "dvg-obs-v4-s9-report-v1"
S7_SUMMARY = ROOT / "artifacts" / "v4" / "s7-lih-development-v1-2" / "summary.json"
V2_SUMMARY = ROOT / "artifacts" / "s10" / "lih-3a-first-accuracy-primary-v1-2" / "summary.json"
V2_TRIAL = ROOT / "artifacts" / "s10" / "lih-3a-first-accuracy-primary-v1-2" / "selected-trial.json"
V3_RESULT = ROOT / "artifacts" / "v3" / "s2-polishing-calibration-v1-2.json"
S4_RESULT = ROOT / "artifacts" / "v4" / "s4-deterministic-search-audit-v1.json"
REQUIRED_THREADS = {"OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}


class V4ReportingError(RuntimeError):
    """Raised when reporting cannot reproduce the frozen evidence."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _verify_freeze() -> dict[str, Any]:
    head = subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip()
    tag = subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", f"{REPORT_TAG}^{{}}"], text=True).strip()
    dirty = subprocess.check_output(["git", "-C", str(ROOT), "status", "--porcelain"], text=True).strip()
    threads = {name: os.environ.get(name) for name in REQUIRED_THREADS}
    if head != tag or dirty or threads != REQUIRED_THREADS:
        raise V4ReportingError("S9 reporting requires clean tagged code and canonical threads")
    return {"head": head, "report_tag": REPORT_TAG, "threads": threads}


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise V4ReportingError(f"cannot write empty report table: {path.name}")
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
        stream.flush()
        os.fsync(stream.fileno())


def _selected_path(attempt: dict[str, Any]) -> dict[str, Any]:
    return attempt["fallback"] or attempt["primary"]


def run(output: Path) -> dict[str, Any]:
    freeze = _verify_freeze()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite S9 report: {output}")
    staging = output.with_name(f".{output.name}.staging")
    if staging.exists():
        raise FileExistsError(f"orphan S9 staging requires audit: {staging}")
    staging.mkdir(parents=True)
    s7 = json.loads(S7_SUMMARY.read_text(encoding="utf-8"))
    v2 = json.loads(V2_SUMMARY.read_text(encoding="utf-8"))
    v2_trial = json.loads(V2_TRIAL.read_text(encoding="utf-8"))
    v3 = json.loads(V3_RESULT.read_text(encoding="utf-8"))
    s4 = json.loads(S4_RESULT.read_text(encoding="utf-8"))
    source = s7["checkpoint"]["resources"]["snapshot"]
    winner_id = s7["endpoint_winners"]["circuit_primary"]
    attempt_by_id = {item["constraint_semantic_id"]: item for item in s7["attempts"]}
    winner = attempt_by_id[winner_id]
    winner_path = _selected_path(winner)
    v2_selected = v2_trial["fallback"] or v2_trial["primary"]
    v2_resources = v2_trial["physical_resources"]["snapshot"]
    comparison_rows = [
        {
            "method": "stored-ceo-star-reference", "status": "reference",
            "energy_hartree": s7["checkpoint"]["energy_hartree"], "energy_change_hartree": 0.0,
            "parameters": source["parameter_count"], "cnot": source["cnot_count"],
            "cnot_depth": source["cnot_depth"], "total_depth": source["total_depth"],
            "paper_measurement_cost": "N/A",
        },
        {
            "method": "v2-counterfactual", "status": "rolled-back-kkt",
            "energy_hartree": v2_selected["energy_hartree"],
            "energy_change_hartree": v2_selected["energy_hartree"] - s7["checkpoint"]["energy_hartree"],
            "parameters": v2_resources["parameter_count"], "cnot": v2_resources["cnot_count"],
            "cnot_depth": v2_resources["cnot_depth"], "total_depth": v2_resources["total_depth"],
            "paper_measurement_cost": "N/A",
        },
        {
            "method": "v4-global-obs", "status": "accepted-development",
            "energy_hartree": winner_path["energy_hartree"],
            "energy_change_hartree": winner_path["energy_hartree"] - s7["checkpoint"]["energy_hartree"],
            "parameters": winner["physical_resources"]["snapshot"]["parameter_count"],
            "cnot": winner["physical_resources"]["snapshot"]["cnot_count"],
            "cnot_depth": winner["physical_resources"]["snapshot"]["cnot_depth"],
            "total_depth": winner["physical_resources"]["snapshot"]["total_depth"],
            "paper_measurement_cost": "N/A",
        },
    ]
    attempt_rows = []
    for item in s7["attempts"]:
        selected = _selected_path(item)
        snapshot = item["physical_resources"]["snapshot"]
        attempt_rows.append({
            "attempt": item["attempt_number"], "semantic_id": item["constraint_semantic_id"],
            "atomic_constraints": len(item["candidate_ids"]),
            "predicted_loss_hartree": item["prediction"]["predicted_change_from_current_hartree"],
            "actual_loss_hartree": selected["energy_hartree"] - s7["checkpoint"]["energy_hartree"],
            "kkt_residual": selected["gradient_infinity"], "status": item["transaction_status"],
            "parameters": snapshot["parameter_count"], "cnot": snapshot["cnot_count"],
            "cnot_depth": snapshot["cnot_depth"], "total_depth": snapshot["total_depth"],
        })
    checkpoint = json.loads((ROOT / s7["checkpoint"]["path"]).read_text(encoding="utf-8"))
    resource_series = checkpoint["resources"]
    trajectory_rows = []
    for index, item in enumerate(checkpoint["trajectory"], 1):
        trajectory_rows.append({
            "event": "ceo-star-adapt", "adapt_iteration": item["adapt_iteration"],
            "compression_iteration": 0, "energy_hartree": item["energy_hartree"],
            "absolute_error_hartree": item["absolute_error_hartree"],
            "parameters": item["parameter_count"],
            "cnot": resource_series["cnot_count_by_iteration"][index],
            "cnot_depth": resource_series["cnot_depth_by_iteration"][index],
            "total_depth": resource_series["total_depth_by_iteration"][index],
            "wall_time_seconds": "N/A", "energy_evaluations": "N/A",
            "gradient_vector_evaluations": "N/A", "gradient_component_equivalent": "N/A",
            "operators_or_blocks": "N/A", "paper_measurement_cost": "N/A",
        })
    fci = float(v2["offline_evaluation"]["fci_energy_hartree"])
    trajectory_rows.append({
        "event": "v4-global-obs-accepted", "adapt_iteration": checkpoint["adapt_iteration"],
        "compression_iteration": 1, "energy_hartree": winner_path["energy_hartree"],
        "absolute_error_hartree": abs(winner_path["energy_hartree"] - fci),
        "parameters": winner["physical_resources"]["snapshot"]["parameter_count"],
        "cnot": winner["physical_resources"]["snapshot"]["cnot_count"],
        "cnot_depth": winner["physical_resources"]["snapshot"]["cnot_depth"],
        "total_depth": winner["physical_resources"]["snapshot"]["total_depth"],
        "wall_time_seconds": winner_path["wall_time_seconds"],
        "energy_evaluations": winner["work_after_attempt"]["energy_evaluations"],
        "gradient_vector_evaluations": winner["work_after_attempt"]["gradient_vector_evaluations"],
        "gradient_component_equivalent": winner["work_after_attempt"]["gradient_component_evaluations"],
        "operators_or_blocks": winner["physical_resources"]["snapshot"]["logical_block_count"],
        "paper_measurement_cost": "N/A",
    })

    # Reconstruct the eight selected structures to expose the full development Pareto table.
    _, pool, _ = _lih_algorithm()
    source_structure = AnsatzStructure.create(
        checkpoint["ansatz_indices"], checkpoint["ansatz_coefficients"], checkpoint["iteration_counts"]
    )
    blocks = recover_dvg_blocks(pool, source_structure.indices, source_structure.coefficients, source_structure.cumulative_parameter_counts)
    representatives: dict[str, Any] = {}
    for candidate in enumerate_candidates(pool, blocks):
        representatives.setdefault(candidate.equivalence_class_id, candidate)
    by_id = {candidate.candidate_id: candidate for candidate in representatives.values()}
    assessment = {item["constraint_semantic_id"]: item for item in s7["selection"]["assessments"]}
    pareto_rows = []
    for record in s7["search"]["records"]:
        if not record["eligible"]:
            continue
        plan = compose_registered_candidates(
            source_structure, blocks, tuple(by_id[value] for value in record["candidate_ids"])
        )
        target = AnsatzStructure.create(plan.target_indices, [1.0] * len(plan.target_indices), plan.target_iteration_counts)
        resources = evaluate_full_circuit_resources(pool, target, paper_era_backend(), coefficient_policy="deterministic-structural").snapshot
        item = assessment.get(plan.state.constraint_semantic_id)
        if item is None or item["structure_digest"] != resources.structure_digest:
            raise V4ReportingError("Pareto reconstruction differs from the frozen selector")
        pareto_rows.append({
            "semantic_id": plan.state.constraint_semantic_id,
            "atomic_constraints": len(record["candidate_ids"]),
            "predicted_loss_hartree": record["evaluation"]["predicted_loss_hartree"],
            "parameters": resources.parameter_count, "cnot": resources.cnot_count,
            "cnot_depth": resources.cnot_depth, "total_depth": resources.total_depth,
            "pareto": plan.state.constraint_semantic_id in s7["selection"]["pareto_semantic_ids"],
        })
    if len(pareto_rows) != s7["selection"]["eligible_count"]:
        raise V4ReportingError("Pareto reconstruction count differs from selector")
    branch_rows = []
    for case in s4["cases"]:
        branch_rows.append({
            "case_id": case["case_id"],
            "exhaustive_completed": case["exhaustive"]["counts"]["completed"],
            "branch_bound_completed": case["bounded"]["counts"]["completed"],
            "branch_bound_expanded": case["bounded"]["counts"]["expanded"],
            "eligible_count": len(case["exhaustive_eligible_semantic_ids"]),
            "eligible_sets_equal": case["eligible_sets_equal"],
        })
    _write_csv(staging / "comparison.csv", comparison_rows)
    _write_csv(staging / "exact-attempts.csv", attempt_rows)
    _write_csv(staging / "trajectory.csv", trajectory_rows)
    _write_csv(staging / "pareto-candidates.csv", pareto_rows)
    _write_csv(staging / "branch-bound-ablation.csv", branch_rows)

    import matplotlib.pyplot as plt

    metrics = [("parameters", "Parameters"), ("cnot", "CNOT"), ("cnot_depth", "CNOT depth"), ("total_depth", "Total depth")]
    fig, axes = plt.subplots(1, 4, figsize=(12, 3.2))
    labels = ["CEO* source", "V2 rejected", "V4 accepted"]
    colors = ["#737373", "#d95f02", "#1b9e77"]
    for axis, (field, title) in zip(axes, metrics):
        values = [row[field] for row in comparison_rows]
        axis.bar(labels, values, color=colors)
        axis.set_title(title)
        axis.tick_params(axis="x", rotation=35)
        for index, value in enumerate(values):
            axis.text(index, value, str(value), ha="center", va="bottom", fontsize=8)
    fig.tight_layout()
    fig.savefig(staging / "resource-comparison.png", dpi=180)
    plt.close(fig)

    fig, axis = plt.subplots(figsize=(5.2, 4.2))
    predicted = [row["predicted_loss_hartree"] for row in attempt_rows]
    actual = [row["actual_loss_hartree"] for row in attempt_rows]
    axis.scatter(predicted, actual, c=["#1b9e77" if row["status"] == "accepted" else "#d95f02" for row in attempt_rows], s=70)
    upper = max([1e-4, *predicted, *actual]) * 1.1
    axis.plot([0, upper], [0, upper], "--", color="black", linewidth=1, label="prediction = actual")
    axis.axhline(1e-4, color="#7570b3", linestyle=":", label="acceptance budget")
    axis.set(xlabel="Predicted loss (Ha)", ylabel="Actual loss (Ha)", xlim=(0, upper), ylim=(0, upper))
    axis.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(staging / "prediction-vs-actual.png", dpi=180)
    plt.close(fig)

    fig, axis = plt.subplots(figsize=(5.2, 4.2))
    scatter = axis.scatter([row["parameters"] for row in pareto_rows], [row["cnot"] for row in pareto_rows], c=[row["predicted_loss_hartree"] for row in pareto_rows], cmap="viridis_r", s=[80 if row["pareto"] else 35 for row in pareto_rows])
    axis.scatter([source["parameter_count"]], [source["cnot_count"]], marker="x", s=100, color="red", label="CEO* source")
    axis.set(xlabel="Parameters", ylabel="CNOT", title="LiH eligible Global OBS structures")
    axis.legend(fontsize=8)
    fig.colorbar(scatter, ax=axis, label="Predicted loss (Ha)")
    fig.tight_layout()
    fig.savefig(staging / "pareto-parameters-cnot.png", dpi=180)
    plt.close(fig)

    output_hashes = {path.name: _sha256(path) for path in sorted(staging.iterdir()) if path.is_file()}
    report = {
        "schema_version": "1.0.0", "artifact_kind": "v4-s9-report-bundle",
        "report_freeze": freeze, "source_sha256": {
            "s7_summary": _sha256(S7_SUMMARY), "v2_summary": _sha256(V2_SUMMARY),
            "v2_trial": _sha256(V2_TRIAL), "v3_result": _sha256(V3_RESULT), "s4_result": _sha256(S4_RESULT),
        },
        "output_sha256": output_hashes,
        "headline": {
            "energy_change_hartree": winner_path["energy_hartree"] - s7["checkpoint"]["energy_hartree"],
            "parameter_reduction": source["parameter_count"] - winner["physical_resources"]["snapshot"]["parameter_count"],
            "cnot_reduction": source["cnot_count"] - winner["physical_resources"]["snapshot"]["cnot_count"],
            "cnot_depth_reduction": source["cnot_depth"] - winner["physical_resources"]["snapshot"]["cnot_depth"],
            "total_depth_reduction": source["total_depth"] - winner["physical_resources"]["snapshot"]["total_depth"],
        },
        "ablations": {
            "confidence_filter_before": len(s7["search"]["eligible_semantic_ids"]),
            "confidence_filter_after": s7["quality_passed_resource_candidate_count"],
            "v3_passed": v3["passed"], "branch_bound_matches_exhaustive_h2_h4": all(row["eligible_sets_equal"] for row in branch_rows),
        },
        "paper_measurement_cost": None,
        "claim_boundary": "LiH development reporting only; no blind validation, generality, or paper Measurement Cost claim.",
    }
    with (staging / "report.json").open("w", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
        stream.flush(); os.fsync(stream.fileno())
    os.replace(staging, output)
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    result = run(arguments.output)
    print(json.dumps({"headline": result["headline"], "ablations": result["ablations"]}, sort_keys=True))


if __name__ == "__main__":
    main()

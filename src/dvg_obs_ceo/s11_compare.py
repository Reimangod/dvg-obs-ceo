"""Audit and assemble the direct LiH GSD/CEO*/V2 comparison."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
from typing import Any, Iterable

from .baseline import ROOT
from .s11_gsd import CHEMICAL_ACCURACY_HARTREE, PAPER_REFERENCE, validate_summary


COMPARISON_ID = "dvg-obs-s11-lih-matched-comparison-v1"
COMPARISON_TAG = "dvg-obs-s11-lih-comparison-protocol-v1"
GSD_BUNDLE = ROOT / "artifacts" / "s11" / "gsd-lih-3a-first-accuracy-v1"
S10_BUNDLE = ROOT / "artifacts" / "s10" / "lih-3a-first-accuracy-primary-v1-2"


class S11ComparisonError(RuntimeError):
    """Raised when source evidence cannot support the S11 comparison."""


def _git(*arguments: str) -> str:
    return subprocess.check_output(["git", "-C", str(ROOT), *arguments], text=True).strip()


def verify_comparison_freeze() -> dict[str, str]:
    head = _git("rev-parse", "HEAD")
    try:
        tagged = _git("rev-parse", f"{COMPARISON_TAG}^{{}}")
    except subprocess.CalledProcessError as error:
        raise S11ComparisonError(f"missing comparison execution tag: {COMPARISON_TAG}") from error
    dirty = _git("status", "--porcelain")
    if head != tagged or dirty:
        raise S11ComparisonError(
            f"comparison assembly requires clean tagged code: head={head}, tag={tagged}, dirty={bool(dirty)}"
        )
    return {"head": head, "protocol_tag": COMPARISON_TAG}


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_exclusive(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, indent=2, sort_keys=True, allow_nan=False).encode() + b"\n"
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise S11ComparisonError("comparison write made no progress")
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _strictly_sequential(values: Iterable[int]) -> bool:
    sequence = list(values)
    return sequence == list(range(1, len(sequence) + 1))


def audit_sources() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    gsd_path = GSD_BUNDLE / "summary.json"
    jsonl_path = GSD_BUNDLE / "trajectory.jsonl"
    s10_path = S10_BUNDLE / "summary.json"
    checkpoint_path = S10_BUNDLE / "checkpoint.json"
    for path in (gsd_path, jsonl_path, s10_path, checkpoint_path):
        if not path.is_file():
            raise S11ComparisonError(f"missing source evidence: {path}")
    gsd = _read_json(gsd_path)
    validate_summary(gsd)
    jsonl = [json.loads(line) for line in jsonl_path.read_text(encoding="utf-8").splitlines()]
    s10 = _read_json(s10_path)
    checkpoint = _read_json(checkpoint_path)
    gsd_rows = gsd["trajectory"]
    ceo_rows = checkpoint["trajectory"]
    ceo_segments = checkpoint["resources"]["segments"]
    trial = s10["dvg_obs_ceo"]["trial"]
    checks = {
        "gsd_schema_valid": True,
        "gsd_jsonl_exactly_matches_summary": jsonl == gsd_rows,
        "gsd_iterations_sequential": _strictly_sequential(row["adapt_iteration"] for row in gsd_rows),
        "gsd_one_parameter_per_iteration": all(
            row["parameter_count"] == row["adapt_iteration"] for row in gsd_rows
        ),
        "gsd_energy_nonincreasing": all(
            right["energy_hartree"] <= left["energy_hartree"] + 1e-12
            for left, right in zip(gsd_rows, gsd_rows[1:])
        ),
        "gsd_resources_nondecreasing": all(
            right[key] >= left[key]
            for key in ("cnot_count", "cnot_depth", "total_depth")
            for left, right in zip(gsd_rows, gsd_rows[1:])
        ),
        "gsd_final_row_matches_summary": all(
            gsd_rows[-1][key] == gsd[key]
            for key in ("energy_hartree", "fci_error_hartree")
        ),
        "gsd_reaches_chemical_accuracy": gsd["reached_chemical_accuracy"] is True
        and gsd["fci_error_hartree"] < CHEMICAL_ACCURACY_HARTREE,
        "gsd_reproduces_paper_cnot": gsd["resources"]["snapshot"]["cnot_count"]
        == PAPER_REFERENCE["cnot_count"],
        "gsd_reproduces_paper_cnot_depth": gsd["resources"]["snapshot"]["cnot_depth"]
        == PAPER_REFERENCE["cnot_depth"],
        "measurement_cost_not_relabelled": gsd["work"]["paper_measurement_cost"] is None,
        "ceo_trajectory_resource_alignment": len(ceo_rows) == len(ceo_segments)
        and all(row["adapt_iteration"] == segment["adapt_iteration"] for row, segment in zip(ceo_rows, ceo_segments)),
        "ceo_reaches_chemical_accuracy": ceo_rows[-1]["absolute_error_hartree"]
        < CHEMICAL_ACCURACY_HARTREE,
        "v2_primary_is_rollback": s10["dvg_obs_ceo"]["status"] == "rolled-back"
        and s10["dvg_obs_ceo"]["accepted"] is False,
        "counterfactual_is_rejected": trial["transaction_status"] == "rolled-back"
        and trial["acceptance"]["accepted"] is False,
        "counterfactual_failed_kkt_only": trial["acceptance"]["rejection_reasons"] == ["kkt"],
        "all_reported_scalars_finite": all(
            math.isfinite(float(row[key]))
            for row in gsd_rows + ceo_rows
            for key in ("energy_hartree",)
        ),
    }
    failed = [name for name, passed in checks.items() if not passed]
    audit = {
        "schema_version": "1.0.0",
        "artifact_kind": "s11-lih-comparison-source-audit",
        "comparison_id": COMPARISON_ID,
        "checks": checks,
        "passed": not failed,
        "failed_checks": failed,
        "source_sha256": {
            "gsd_summary": _digest(gsd_path),
            "gsd_trajectory_jsonl": _digest(jsonl_path),
            "s10_summary": _digest(s10_path),
            "s10_checkpoint": _digest(checkpoint_path),
        },
    }
    if failed:
        raise S11ComparisonError(f"S11 source audit failed: {failed}")
    return gsd, s10, audit


def _ceo_trajectory(checkpoint: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            **row,
            "cnot_count": segment["cumulative_cnot_count"],
            "cnot_depth": segment["cumulative_cnot_depth"],
            "total_depth": segment["cumulative_total_depth"],
        }
        for row, segment in zip(checkpoint["trajectory"], checkpoint["resources"]["segments"])
    ]


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if path.exists():
        raise FileExistsError(path)
    with path.open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
        handle.flush()
        os.fsync(handle.fileno())


def _plot(bundle: Path, gsd_rows: list[dict[str, Any]], ceo_rows: list[dict[str, Any]], candidate: dict[str, Any]) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    colors = {"GSD": "#4c78a8", "CEO": "#f58518", "V2": "#54a24b"}
    figure, axes = plt.subplots(1, 3, figsize=(13.5, 4.2))
    for rows, label, color, error_key in (
        (gsd_rows, "GSD-ADAPT (direct)", colors["GSD"], "fci_error_hartree"),
        (ceo_rows, "CEO* = accepted V2", colors["CEO"], "absolute_error_hartree"),
    ):
        x = [row["adapt_iteration"] for row in rows]
        axes[0].semilogy(x, [row[error_key] for row in rows], marker="o", label=label, color=color)
        axes[1].plot(x, [row["cnot_count"] for row in rows], marker="o", label=label, color=color)
        axes[2].plot(x, [row["cnot_depth"] for row in rows], marker="o", label=label, color=color)
    axes[0].axhline(CHEMICAL_ACCURACY_HARTREE, color="black", linestyle="--", linewidth=1, label="chemical accuracy")
    axes[1].scatter([5], [candidate["cnot_count"]], facecolors="none", edgecolors=colors["V2"], marker="s", s=70, linewidth=1.8, label="V2 candidate (rejected)")
    axes[2].scatter([5], [candidate["cnot_depth"]], facecolors="none", edgecolors=colors["V2"], marker="s", s=70, linewidth=1.8, label="V2 candidate (rejected)")
    for axis, ylabel in zip(axes, ("|E - FCI| (Ha)", "CNOT count", "CNOT depth")):
        axis.set_xlabel("ADAPT iteration")
        axis.set_ylabel(ylabel)
        axis.grid(alpha=0.25)
    handles, labels = axes[1].get_legend_handles_labels()
    figure.legend(handles, labels, loc="upper center", ncol=3, frameon=False)
    figure.suptitle("LiH 3 Å: Fig. 14-style direct comparison", y=1.03)
    figure.tight_layout()
    for suffix in ("svg", "png"):
        figure.savefig(bundle / f"fig14_style.{suffix}", dpi=180, bbox_inches="tight")
    plt.close(figure)

    figure, axes = plt.subplots(1, 2, figsize=(9.5, 4.2))
    axes[0].semilogy(
        [row["parameter_count"] for row in gsd_rows],
        [row["fci_error_hartree"] for row in gsd_rows],
        marker="o", color=colors["GSD"], label="GSD-ADAPT (direct)",
    )
    axes[0].semilogy(
        [row["parameter_count"] for row in ceo_rows],
        [row["absolute_error_hartree"] for row in ceo_rows],
        marker="o", color=colors["CEO"], label="CEO* = accepted V2",
    )
    axes[0].scatter(
        [candidate["parameter_count"]], [candidate["fci_error_hartree"]],
        facecolors="none", edgecolors=colors["V2"], marker="s", s=70,
        linewidth=1.8, label="V2 candidate (rejected)",
    )
    axes[0].axhline(CHEMICAL_ACCURACY_HARTREE, color="black", linestyle="--", linewidth=1)
    axes[0].set(xlabel="Parameter count", ylabel="|E - FCI| (Ha)")
    axes[0].grid(alpha=0.25)
    axes[0].legend(frameon=False, fontsize=8)
    axes[1].axis("off")
    axes[1].text(
        0.5, 0.58,
        "Measurement-cost panel intentionally omitted\n\n"
        "Paper reference: GSD 50,468; CEO* 560\n"
        "Current pinned code does not expose the paper-era\n"
        "measurement-cost accounting implementation.\n"
        "Local evaluation counters are not equivalent.",
        ha="center", va="center", fontsize=10,
        bbox={"boxstyle": "round", "facecolor": "#f5f5f5", "edgecolor": "#777777"},
    )
    figure.suptitle("LiH 3 Å: Fig. 15-style comparison with claim boundary")
    figure.tight_layout()
    for suffix in ("svg", "png"):
        figure.savefig(bundle / f"fig15_style.{suffix}", dpi=180, bbox_inches="tight")
    plt.close(figure)


def assemble(bundle: Path) -> dict[str, Any]:
    execution_freeze = verify_comparison_freeze()
    if bundle.exists():
        raise FileExistsError(f"refusing to overwrite comparison bundle: {bundle}")
    staging = bundle.with_name(f".{bundle.name}.staging")
    if staging.exists():
        raise FileExistsError(f"orphan comparison staging requires audit: {staging}")
    staging.mkdir(parents=True)
    _fsync_directory(staging.parent)
    gsd, s10, audit = audit_sources()
    checkpoint = _read_json(S10_BUNDLE / "checkpoint.json")
    gsd_rows = gsd["trajectory"]
    ceo_rows = _ceo_trajectory(checkpoint)
    trial = s10["dvg_obs_ceo"]["trial"]
    candidate_snapshot = trial["physical_resources"]["snapshot"]
    candidate_energy = trial["acceptance"]["candidate_energy_hartree"]
    fci = gsd["fci_energy_hartree"]
    candidate = {
        **candidate_snapshot,
        "energy_hartree": candidate_energy,
        "fci_error_hartree": abs(candidate_energy - fci),
        "status": "rejected-counterfactual",
        "rejection_reasons": trial["acceptance"]["rejection_reasons"],
    }
    final_rows = [
        {
            "series": "GSD-ADAPT",
            "evidence_status": "direct-accepted",
            "adapt_iterations": gsd["first_chemical_accuracy_iteration"],
            "energy_hartree": gsd["energy_hartree"],
            "fci_error_hartree": gsd["fci_error_hartree"],
            **{key: gsd["resources"]["snapshot"][key] for key in ("parameter_count", "cnot_count", "cnot_depth", "total_depth")},
        },
        {
            "series": "CEO*",
            "evidence_status": "direct-accepted",
            "adapt_iterations": checkpoint["adapt_iteration"],
            "energy_hartree": checkpoint["energy_hartree"],
            "fci_error_hartree": checkpoint["trajectory"][-1]["absolute_error_hartree"],
            **{key: checkpoint["resources"]["snapshot"][key] for key in ("parameter_count", "cnot_count", "cnot_depth", "total_depth")},
        },
        {
            "series": "V2-primary",
            "evidence_status": "direct-accepted-after-rollback",
            "adapt_iterations": checkpoint["adapt_iteration"],
            "energy_hartree": s10["dvg_obs_ceo"]["energy_hartree"],
            "fci_error_hartree": s10["offline_evaluation"]["v2_absolute_error_hartree"],
            **{key: s10["dvg_obs_ceo"]["resources"]["snapshot"][key] for key in ("parameter_count", "cnot_count", "cnot_depth", "total_depth")},
        },
        {
            "series": "V2-candidate",
            "evidence_status": "rejected-counterfactual-kkt",
            "adapt_iterations": checkpoint["adapt_iteration"],
            "energy_hartree": candidate_energy,
            "fci_error_hartree": candidate["fci_error_hartree"],
            **{key: candidate_snapshot[key] for key in ("parameter_count", "cnot_count", "cnot_depth", "total_depth")},
        },
    ]
    result = {
        "schema_version": "1.0.0",
        "artifact_kind": "s11-lih-direct-comparison",
        "comparison_id": COMPARISON_ID,
        "execution_freeze": execution_freeze,
        "problem": {"molecule": "LiH", "distance_angstrom": 3.0, "noise": None, "shots": None},
        "chemical_accuracy_hartree": CHEMICAL_ACCURACY_HARTREE,
        "source_audit": audit,
        "final_comparison": final_rows,
        "trajectories": {"gsd_adapt": gsd_rows, "ceo_star": ceo_rows},
        "v2_rejected_counterfactual": candidate,
        "work": {
            "gsd_adapt": gsd["work"],
            "ceo_star": checkpoint["work"],
            "v2_trial": trial["work_after_attempt"],
            "per_iteration_ceo_work_available": False,
        },
        "paper_reference": {
            "gsd": PAPER_REFERENCE,
            "ceo_star": {"cnot_count": 107, "cnot_depth": 30, "measurement_cost": 560},
        },
        "claim_boundary": [
            "GSD and CEO* are direct pinned-code executions at their first chemical-accuracy iterations.",
            "The accepted V2 result equals CEO* because the only selected compression trial was rolled back.",
            "The 98-CNOT V2 candidate is counterfactual evidence, not an accepted performance result.",
            "Paper measurement costs are cited references only; local work counters are not equivalent.",
            "CEO* per-iteration wall time and work were not captured and are not inferred.",
        ],
    }
    _write_exclusive(staging / "comparison.json", result)
    _write_exclusive(staging / "source-audit.json", audit)
    _write_csv(staging / "final-comparison.csv", final_rows)
    _plot(staging, gsd_rows, ceo_rows, candidate)
    _fsync_directory(staging)
    os.replace(staging, bundle)
    _fsync_directory(bundle.parent)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    arguments = parser.parse_args()
    result = assemble(arguments.bundle)
    print(json.dumps({
        "bundle": str(arguments.bundle),
        "source_audit_passed": result["source_audit"]["passed"],
        "series": [row["series"] for row in result["final_comparison"]],
    }, sort_keys=True))


if __name__ == "__main__":
    main()

"""Generate LiH 3 A figures corresponding to paper Figs. 11, 14, and 15."""

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


FIGURE_TAG = "dvg-obs-v4-paper-equivalent-figures-protocol-v1"
S11_COMPARISON = ROOT / "artifacts" / "s11" / "lih-3a-direct-comparison-v1-1" / "comparison.json"
V4_SUMMARY = ROOT / "artifacts" / "v4" / "s7-lih-development-v1-2" / "summary.json"
V4_REPORT = ROOT / "artifacts" / "v4" / "s9-report-v1-1" / "report.json"


class PaperEquivalentFigureError(RuntimeError):
    """Raised when figure inputs or publication invariants are invalid."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _strict_json(path: Path) -> Any:
    def reject(value: str) -> None:
        raise ValueError(f"non-finite JSON token {value} in {path}")

    return json.loads(path.read_text(encoding="utf-8"), parse_constant=reject)


def _git(*arguments: str) -> str:
    return subprocess.check_output(["git", "-C", str(ROOT), *arguments], text=True).strip()


def verify_freeze() -> dict[str, str]:
    head = _git("rev-parse", "HEAD")
    tag = _git("rev-parse", f"{FIGURE_TAG}^{{}}")
    dirty = _git("status", "--porcelain")
    if head != tag or dirty:
        raise PaperEquivalentFigureError("figure generation requires clean tagged code")
    return {"head": head, "protocol_tag": FIGURE_TAG}


def load_figure_data() -> dict[str, Any]:
    comparison = _strict_json(S11_COMPARISON)
    v4 = _strict_json(V4_SUMMARY)
    report = _strict_json(V4_REPORT)
    if not comparison["source_audit"]["passed"]:
        raise PaperEquivalentFigureError("S11 source audit is not passed")
    if report["paper_measurement_cost"] is not None:
        raise PaperEquivalentFigureError("unexpected paper Measurement Cost in V4 report")
    gsd = comparison["trajectories"]["gsd_adapt"]
    ceo = comparison["trajectories"]["ceo_star"]
    winner_id = v4["endpoint_winners"]["circuit_primary"]
    winner = next(item for item in v4["attempts"] if item["constraint_semantic_id"] == winner_id)
    selected = winner["fallback"] or winner["primary"]
    resources = winner["physical_resources"]["snapshot"]
    fci_from_ceo = ceo[-1]["energy_hartree"] - ceo[-1]["absolute_error_hartree"]
    fci_from_gsd = gsd[-1]["energy_hartree"] - gsd[-1]["fci_error_hartree"]
    if abs(fci_from_ceo - fci_from_gsd) > 1e-12:
        raise PaperEquivalentFigureError("stored S11 trajectories disagree on FCI energy")
    # FCI is reconstructed only for post-result reporting. It never enters V4
    # screening, ranking, optimization, or acceptance.
    expected_fci = fci_from_ceo
    v4_point = {
        "series": "V4 Global OBS",
        "adapt_iteration": ceo[-1]["adapt_iteration"],
        "compression_iteration": 1,
        "energy_hartree": selected["energy_hartree"],
        "error_hartree": abs(selected["energy_hartree"] - expected_fci),
        "parameter_count": resources["parameter_count"],
        "cnot_count": resources["cnot_count"],
        "cnot_depth": resources["cnot_depth"],
        "total_depth": resources["total_depth"],
        "evidence_status": "accepted-development",
        "paper_measurement_cost": None,
    }
    normalized_gsd = [
        {
            **row,
            "series": "GSD-ADAPT",
            "error_hartree": row["fci_error_hartree"],
            "compression_iteration": 0,
            "evidence_status": "direct-accepted-trajectory",
        }
        for row in gsd
    ]
    normalized_ceo = [
        {
            **row,
            "series": "CEO-ADAPT-VQE*",
            "error_hartree": row["absolute_error_hartree"],
            "compression_iteration": 0,
            "evidence_status": "direct-accepted-trajectory",
        }
        for row in ceo
    ]
    threshold = comparison["chemical_accuracy_hartree"]
    checks = {
        "problem_is_lih_3a": comparison["problem"]["molecule"] == "LiH" and comparison["problem"]["distance_angstrom"] == 3.0,
        "gsd_first_accuracy_matches_paper_cnot": gsd[-1]["cnot_count"] == 392,
        "gsd_first_accuracy_matches_paper_depth": gsd[-1]["cnot_depth"] == 384,
        "ceo_first_accuracy_matches_paper_cnot": ceo[-1]["cnot_count"] == 107,
        "ceo_first_accuracy_matches_paper_depth": ceo[-1]["cnot_depth"] == 30,
        "v4_is_accepted": winner["transaction_status"] == "accepted",
        "v4_within_chemical_accuracy": v4_point["error_hartree"] < threshold,
        "measurement_cost_unavailable": v4_point["paper_measurement_cost"] is None,
    }
    if not all(checks.values()):
        raise PaperEquivalentFigureError(f"figure source checks failed: {checks}")
    return {
        "gsd": normalized_gsd,
        "ceo": normalized_ceo,
        "v4": v4_point,
        "chemical_accuracy_hartree": threshold,
        "paper_measurement_endpoints": comparison["paper_reference"],
        "checks": checks,
    }


def _write_csv(path: Path, data: dict[str, Any]) -> None:
    fields = (
        "series", "evidence_status", "adapt_iteration", "compression_iteration",
        "energy_hartree", "error_hartree", "parameter_count", "cnot_count",
        "cnot_depth", "total_depth", "paper_measurement_cost",
    )
    rows = []
    for row in [*data["gsd"], *data["ceo"], data["v4"]]:
        rows.append({field: row.get(field, "N/A") for field in fields})
    with path.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
        stream.flush()
        os.fsync(stream.fileno())


def _decorate(axis: Any, threshold: float, xlabel: str) -> None:
    axis.axhspan(1e-12, threshold, color="#dbeafe", alpha=0.8, zorder=0)
    axis.axhline(threshold, color="#64748b", linestyle="--", linewidth=1.0)
    axis.set_yscale("log")
    axis.set_ylim(1e-4, 1e-1)
    axis.set_xlabel(xlabel)
    axis.set_ylabel(r"$|E-E_{FCI}|$ (Ha)")
    axis.grid(alpha=0.22, which="both")


def _plot_trajectory(axis: Any, rows: list[dict[str, Any]], xkey: str, label: str, color: str) -> None:
    axis.plot(
        [row[xkey] for row in rows], [row["error_hartree"] for row in rows],
        marker="o", markersize=4.5, linewidth=1.8, color=color, label=label,
    )


def _plot_v4(axis: Any, point: dict[str, Any], xkey: str) -> None:
    axis.scatter(
        [point[xkey]], [point["error_hartree"]], marker="D", s=78,
        color="#059669", edgecolor="white", linewidth=0.9, zorder=5,
        label="V4 Global OBS (accepted development)",
    )


def _save(figure: Any, staging: Path, stem: str, pdf: Any) -> None:
    figure.savefig(staging / f"{stem}.png", dpi=240, bbox_inches="tight")
    figure.savefig(staging / f"{stem}.svg", bbox_inches="tight")
    figure.savefig(staging / f"{stem}.pdf", bbox_inches="tight")
    pdf.savefig(figure, bbox_inches="tight")


def generate(output: Path) -> dict[str, Any]:
    freeze = verify_freeze()
    data = load_figure_data()
    if output.exists():
        raise FileExistsError(output)
    staging = output.with_name(f".{output.name}.staging")
    if staging.exists():
        raise FileExistsError(staging)
    staging.mkdir(parents=True)
    _write_csv(staging / "figure-data.csv", data)

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages

    plt.rcParams.update({
        "font.size": 10,
        "axes.titlesize": 11,
        "axes.labelsize": 10,
        "legend.fontsize": 8.3,
        "figure.titlesize": 13,
    })
    colors = {"GSD": "#f97316", "CEO": "#2563eb"}
    combined_path = staging / "paper-fig11-14-15-equivalents.pdf"
    with PdfPages(combined_path) as combined:
        fig11, axes = plt.subplots(1, 3, figsize=(13.6, 4.3), sharey=True)
        for axis, xkey, xlabel in zip(
            axes,
            ("adapt_iteration", "parameter_count", "cnot_count"),
            ("ADAPT iteration", "Parameter count", "CNOT count"),
        ):
            _plot_trajectory(axis, data["gsd"], xkey, "GSD-ADAPT (stored direct)", colors["GSD"])
            _plot_trajectory(axis, data["ceo"], xkey, "CEO-ADAPT-VQE* (stored direct)", colors["CEO"])
            _plot_v4(axis, data["v4"], xkey)
            _decorate(axis, data["chemical_accuracy_hartree"], xlabel)
        axes[0].legend(frameon=False, loc="lower left")
        fig11.suptitle("Fig. 11-equivalent - LiH at 3 A (available stored comparators)")
        fig11.text(
            0.5, 0.01,
            "V4 is one compression point from CEO* iteration 5; it is not a new ADAPT trajectory. QEB/qubit trajectories are unavailable.",
            ha="center", fontsize=8.5, color="#475569",
        )
        fig11.tight_layout(rect=(0, 0.06, 1, 0.94))
        _save(fig11, staging, "fig11-equivalent-lih3a", combined)
        plt.close(fig11)

        fig14, axes = plt.subplots(1, 3, figsize=(13.6, 4.3), sharey=True)
        for axis, xkey, xlabel in zip(
            axes,
            ("adapt_iteration", "cnot_count", "cnot_depth"),
            ("ADAPT iteration", "Ansatz CNOT count", "Ansatz CNOT depth"),
        ):
            _plot_trajectory(axis, data["gsd"], xkey, "GSD-ADAPT (stored direct)", colors["GSD"])
            _plot_trajectory(axis, data["ceo"], xkey, "CEO-ADAPT-VQE* (stored direct)", colors["CEO"])
            _plot_v4(axis, data["v4"], xkey)
            _decorate(axis, data["chemical_accuracy_hartree"], xlabel)
        axes[0].legend(frameon=False, loc="lower left")
        fig14.suptitle("Fig. 14-equivalent circuit comparison - LiH at 3 A")
        fig14.text(
            0.5, 0.01,
            "Exact noiseless simulator; first-chemical-accuracy stored trajectories; V4 shown as accepted development compression.",
            ha="center", fontsize=8.5, color="#475569",
        )
        fig14.tight_layout(rect=(0, 0.06, 1, 0.94))
        _save(fig14, staging, "fig14-equivalent-lih3a", combined)
        plt.close(fig14)

        fig15, axes = plt.subplots(1, 2, figsize=(10.8, 4.5))
        _plot_trajectory(axes[0], data["gsd"], "parameter_count", "GSD-ADAPT (stored direct)", colors["GSD"])
        _plot_trajectory(axes[0], data["ceo"], "parameter_count", "CEO-ADAPT-VQE* (stored direct)", colors["CEO"])
        _plot_v4(axes[0], data["v4"], "parameter_count")
        _decorate(axes[0], data["chemical_accuracy_hartree"], "Parameter count")
        axes[0].legend(frameon=False, loc="lower left")
        axes[0].set_title("Available parameter-count comparison")
        axes[1].axis("off")
        paper = data["paper_measurement_endpoints"]
        axes[1].text(
            0.5, 0.55,
            "Paper-equivalent Measurement Cost\ntrajectory is not available\n\n"
            f"Paper endpoint references only:\nGSD-ADAPT: {paper['gsd']['measurement_cost']:,}\n"
            f"CEO-ADAPT-VQE*: {paper['ceo_star']['measurement_cost']:,}\nV4: N/A\n\n"
            "Implementation counters are not substituted.",
            ha="center", va="center", fontsize=11,
            bbox={"boxstyle": "round,pad=0.8", "facecolor": "#f8fafc", "edgecolor": "#64748b"},
        )
        axes[1].set_title("Measurement-cost claim boundary")
        fig15.suptitle("Fig. 15-equivalent measurement comparison - LiH at 3 A")
        fig15.tight_layout(rect=(0, 0, 1, 0.94))
        _save(fig15, staging, "fig15-equivalent-lih3a", combined)
        plt.close(fig15)

    output_hashes = {
        path.name: _sha256(path) for path in sorted(staging.iterdir()) if path.is_file()
    }
    manifest = {
        "schema_version": "1.0.0",
        "artifact_kind": "v4-paper-fig11-14-15-equivalent-bundle",
        "generation_freeze": freeze,
        "problem": {"molecule": "LiH", "distance_angstrom": 3.0, "noise": None},
        "source_sha256": {
            "s11_comparison": _sha256(S11_COMPARISON),
            "v4_summary": _sha256(V4_SUMMARY),
            "v4_report": _sha256(V4_REPORT),
        },
        "source_checks": data["checks"],
        "output_sha256": output_hashes,
        "figure_correspondence": {
            "fig11": "error versus ADAPT iteration, parameter count, and CNOT count; available GSD/CEO* trajectories plus V4 point",
            "fig14": "error versus ADAPT iteration, CNOT count, and CNOT depth; stored GSD/CEO* trajectories plus V4 point",
            "fig15": "error versus parameter count; paper Measurement Cost trajectory unavailable and not substituted",
        },
        "claim_boundary": [
            "LiH 3 A development comparison only; not a three-molecule reproduction.",
            "V4 is a single accepted compression point, not an ADAPT growth trajectory.",
            "QEB-ADAPT and qubit-ADAPT trajectories required by the original Fig. 11 are unavailable.",
            "Paper Measurement Cost remains unavailable for V4; endpoint paper references are citations, not recomputed values.",
        ],
    }
    with (staging / "manifest.json").open("x", encoding="utf-8") as stream:
        json.dump(manifest, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(staging, output)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    arguments = parser.parse_args()
    result = generate(arguments.output)
    print(json.dumps({"outputs": len(result["output_sha256"]), "checks": result["source_checks"]}, sort_keys=True))


if __name__ == "__main__":
    main()

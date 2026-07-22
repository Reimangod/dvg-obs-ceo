"""Generate audited paper-comparison figures for stored CEO-star checkpoints."""

from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any

from .baseline import ROOT
from .identity import canonical_json_bytes


PROTOCOL_TAG = "dvg-obs-multisystem-paper-comparison-protocol-v1"
RESULT_ROOT = ROOT / "artifacts" / "full-figures" / "ceo-star"
CASES = {
    "h6-1.5": {"label": "Linear H6 at 1.5 A", "checkpoint": RESULT_ROOT / "h6-1.5" / "checkpoint.json"},
    "h6-3.0": {"label": "Linear H6 at 3 A", "checkpoint": RESULT_ROOT / "h6-3.0" / "checkpoint.json"},
    "beh2-3.0": {"label": "BeH2 at 3 A", "checkpoint": RESULT_ROOT / "beh2-3.0" / "checkpoint.json"},
}
PAPER_TABLE1 = {
    "h6-1.5": {
        "cnot_count": 812,
        "cnot_depth": 282,
        "measurement_cost": 10857,
        "source": "Ramôa et al. (2025), Table 1",
    }
}


class MultiSystemFigureError(RuntimeError):
    """Raised when a comparison input or provenance invariant is invalid."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _strict_json(path: Path) -> dict[str, Any]:
    def reject(value: str) -> None:
        raise ValueError(f"non-finite token {value} in {path}")

    value = json.loads(path.read_text(encoding="utf-8"), parse_constant=reject)
    if not isinstance(value, dict):
        raise MultiSystemFigureError(f"expected object in {path}")
    return value


def _git(*arguments: str) -> str:
    return subprocess.check_output(["git", "-C", str(ROOT), *arguments], text=True).strip()


def verify_freeze() -> dict[str, str]:
    head = _git("rev-parse", "HEAD")
    tag = _git("rev-parse", f"{PROTOCOL_TAG}^{{}}")
    dirty = _git("status", "--porcelain")
    if head != tag or dirty:
        raise MultiSystemFigureError("generation requires clean code at the protocol tag")
    return {"head": head, "protocol_tag": PROTOCOL_TAG}


def load_data() -> dict[str, Any]:
    loaded: dict[str, Any] = {}
    for case_id, definition in CASES.items():
        path = definition["checkpoint"]
        checkpoint = _strict_json(path)
        digest = checkpoint["checkpoint_digest"]
        without_digest = dict(checkpoint)
        without_digest.pop("checkpoint_digest")
        if hashlib.sha256(canonical_json_bytes(without_digest)).hexdigest() != digest:
            raise MultiSystemFigureError(f"checkpoint digest mismatch: {case_id}")
        trajectory = checkpoint["trajectory"]
        progress_path = path.with_suffix(".progress.jsonl")
        progress = [json.loads(line) for line in progress_path.read_text(encoding="utf-8").splitlines() if line]
        if progress != trajectory:
            raise MultiSystemFigureError(f"progress mismatch: {case_id}")
        threshold = checkpoint["chemical_accuracy_hartree"]
        if trajectory[-1]["absolute_error_hartree"] >= threshold:
            raise MultiSystemFigureError(f"final point is outside chemical accuracy: {case_id}")
        if len(trajectory) > 1 and trajectory[-2]["absolute_error_hartree"] < threshold:
            raise MultiSystemFigureError(f"checkpoint is not first accuracy: {case_id}")
        loaded[case_id] = {
            "label": definition["label"],
            "checkpoint": checkpoint,
            "checkpoint_sha256": _sha256(path),
            "progress_sha256": _sha256(progress_path),
        }
    return loaded


def direct_comparison(data: dict[str, Any]) -> dict[str, Any]:
    local = data["h6-1.5"]["checkpoint"]["resources"]["snapshot"]
    paper = PAPER_TABLE1["h6-1.5"]
    return {
        "case": "h6-1.5",
        "comparison_level": "direct_same-molecule-distance-algorithm-and-first-accuracy-objective",
        "local": {
            "cnot_count": local["cnot_count"],
            "cnot_depth": local["cnot_depth"],
            "measurement_cost": None,
        },
        "paper": paper,
        "delta_percent": {
            "cnot_count": 100.0 * (local["cnot_count"] - paper["cnot_count"]) / paper["cnot_count"],
            "cnot_depth": 100.0 * (local["cnot_depth"] - paper["cnot_depth"]) / paper["cnot_depth"],
            "measurement_cost": None,
        },
    }


def _write_csv(path: Path, data: dict[str, Any]) -> None:
    fields = (
        "case", "label", "adapt_iteration", "energy_hartree", "absolute_error_hartree",
        "parameter_count", "cnot_count", "cnot_depth", "total_depth", "elapsed_seconds",
    )
    with path.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for case_id, payload in data.items():
            for row in payload["checkpoint"]["trajectory"]:
                writer.writerow({"case": case_id, "label": payload["label"], **row})
        stream.flush()
        os.fsync(stream.fileno())


def _decorate(axis: Any, threshold: float, xlabel: str) -> None:
    axis.axhspan(1e-5, threshold, color="#dbeafe", alpha=0.8, zorder=0)
    axis.axhline(threshold, color="#64748b", linestyle="--", linewidth=0.9)
    axis.set_yscale("log")
    axis.set_ylim(1e-5, 1.2)
    axis.set_xlabel(xlabel)
    axis.set_ylabel(r"$|E-E_{FCI}|$ (Ha)")
    axis.grid(alpha=0.2, which="both")


def _trajectory(axis: Any, rows: list[dict[str, Any]], xkey: str, label: str | None = None) -> None:
    axis.plot(
        [row[xkey] for row in rows],
        [row["absolute_error_hartree"] for row in rows],
        color="#2563eb", marker="o", markersize=3.8, linewidth=1.7,
        label=label,
    )


def _save(figure: Any, staging: Path, stem: str, combined: Any) -> None:
    figure.savefig(staging / f"{stem}.png", dpi=240, bbox_inches="tight")
    figure.savefig(staging / f"{stem}.svg", bbox_inches="tight")
    figure.savefig(staging / f"{stem}.pdf", bbox_inches="tight")
    combined.savefig(figure, bbox_inches="tight")


def generate(output: Path) -> dict[str, Any]:
    freeze = verify_freeze()
    data = load_data()
    comparison = direct_comparison(data)
    if output.exists():
        raise FileExistsError(output)
    staging = output.with_name(f".{output.name}.staging")
    if staging.exists():
        raise FileExistsError(staging)
    staging.mkdir(parents=True)
    _write_csv(staging / "figure-data.csv", data)
    (staging / "direct-comparison.json").write_text(
        json.dumps(comparison, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages

    plt.rcParams.update({"font.size": 9.5, "axes.titlesize": 10.5, "axes.labelsize": 9.5, "legend.fontsize": 8})
    combined_path = staging / "multisystem-paper-comparison.pdf"
    with PdfPages(combined_path) as combined:
        fig11, axes = plt.subplots(3, 2, figsize=(10.8, 11.2), sharey=True)
        for column, case_id in enumerate(("h6-3.0", "beh2-3.0")):
            payload = data[case_id]
            rows = payload["checkpoint"]["trajectory"]
            threshold = payload["checkpoint"]["chemical_accuracy_hartree"]
            for row, (xkey, xlabel) in enumerate((("adapt_iteration", "ADAPT iteration"), ("parameter_count", "Parameter count"), ("cnot_count", "CNOT count"))):
                axis = axes[row, column]
                _trajectory(axis, rows, xkey, "Local CEO-ADAPT-VQE*" if row == 0 else None)
                _decorate(axis, threshold, xlabel)
                if row == 0:
                    axis.set_title(payload["label"])
                    axis.legend(frameon=False)
        fig11.suptitle("Fig. 11-style local CEO-star trajectories at stretched distances")
        fig11.text(0.5, 0.012, "Paper Fig. 11 uses non-star CEO and a different termination rule; these curves are axis-equivalent, not direct reproductions.", ha="center", fontsize=8.2)
        fig11.tight_layout(rect=(0, 0.035, 1, 0.965))
        _save(fig11, staging, "fig11-style-h6-beh2-3a", combined)
        plt.close(fig11)

        order = ("h6-1.5", "h6-3.0", "beh2-3.0")
        fig14, axes = plt.subplots(3, 3, figsize=(14.2, 10.8), sharey=True)
        for column, case_id in enumerate(order):
            payload = data[case_id]
            rows = payload["checkpoint"]["trajectory"]
            threshold = payload["checkpoint"]["chemical_accuracy_hartree"]
            for row, (xkey, xlabel) in enumerate((("adapt_iteration", "ADAPT iteration"), ("cnot_count", "Ansatz CNOT count"), ("cnot_depth", "Ansatz CNOT depth"))):
                axis = axes[row, column]
                _trajectory(axis, rows, xkey, "Local CEO-ADAPT-VQE*" if row == 0 else None)
                _decorate(axis, threshold, xlabel)
                if row == 0:
                    axis.set_title(payload["label"])
                    axis.legend(frameon=False)
                if case_id == "h6-1.5" and xkey in ("cnot_count", "cnot_depth"):
                    paper_x = PAPER_TABLE1[case_id][xkey]
                    axis.scatter([paper_x], [threshold], marker="D", s=52, color="#db2777", zorder=5, label="Paper Table 1 endpoint")
                    axis.annotate(f"Paper: {paper_x}", (paper_x, threshold), xytext=(5, 8), textcoords="offset points", fontsize=8)
        fig14.suptitle("Fig. 14-style CEO-star circuit trajectories and direct H6 1.5 A reference")
        fig14.text(0.5, 0.012, "Only H6 1.5 A matches the paper CEO-star molecule/distance. The paper endpoint y-value is placed at the chemical-accuracy boundary because its exact error is not tabulated.", ha="center", fontsize=8.2)
        fig14.tight_layout(rect=(0, 0.04, 1, 0.965))
        _save(fig14, staging, "fig14-style-ceo-star-multisystem", combined)
        plt.close(fig14)

        fig15, axes = plt.subplots(2, 3, figsize=(14.2, 7.5))
        for column, case_id in enumerate(order):
            payload = data[case_id]
            rows = payload["checkpoint"]["trajectory"]
            threshold = payload["checkpoint"]["chemical_accuracy_hartree"]
            _trajectory(axes[0, column], rows, "parameter_count", "Local CEO-ADAPT-VQE*")
            _decorate(axes[0, column], threshold, "Parameter count")
            axes[0, column].set_title(payload["label"])
            axes[0, column].legend(frameon=False)
            axes[1, column].axis("off")
            paper_text = ""
            if case_id in PAPER_TABLE1:
                paper_text = f"\nPaper Table 1 endpoint: {PAPER_TABLE1[case_id]['measurement_cost']:,}"
            axes[1, column].text(0.5, 0.55, "Paper-equivalent Measurement Cost\nLocal trajectory: N/A" + paper_text + "\n\nNo substitute counter is plotted.", ha="center", va="center", fontsize=10)
        fig15.suptitle("Fig. 15-style parameter trajectories and Measurement Cost claim boundary")
        fig15.tight_layout(rect=(0, 0, 1, 0.955))
        _save(fig15, staging, "fig15-style-ceo-star-multisystem", combined)
        plt.close(fig15)

        fig_direct, axes = plt.subplots(1, 2, figsize=(9.2, 4.2))
        metrics = (("cnot_count", "CNOT count"), ("cnot_depth", "CNOT depth"))
        for axis, (key, title) in zip(axes, metrics):
            values = [comparison["paper"][key], comparison["local"][key]]
            bars = axis.bar(["Paper Table 1", "Local rerun"], values, color=["#db2777", "#2563eb"])
            axis.bar_label(bars, fmt="%d", padding=3)
            axis.set_title(title)
            axis.set_ylim(0, max(values) * 1.18)
            axis.grid(axis="y", alpha=0.2)
            axis.text(0.5, 0.93, f"Local delta: +{comparison['delta_percent'][key]:.2f}%", transform=axis.transAxes, ha="center")
        fig_direct.suptitle("Direct comparison - CEO-ADAPT-VQE* H6 at 1.5 A, first chemical accuracy")
        fig_direct.tight_layout(rect=(0, 0, 1, 0.92))
        _save(fig_direct, staging, "direct-h6-1.5-table1-comparison", combined)
        plt.close(fig_direct)

    output_hashes = {path.name: _sha256(path) for path in sorted(staging.iterdir()) if path.is_file()}
    manifest = {
        "schema_version": "1.0.0",
        "artifact_kind": "multisystem-paper-comparison-bundle",
        "generation_freeze": freeze,
        "source_hashes": {
            case_id: {
                "checkpoint": payload["checkpoint_sha256"],
                "progress": payload["progress_sha256"],
            }
            for case_id, payload in data.items()
        },
        "paper_reference": {
            "doi": "10.1038/s41534-025-01039-4",
            "table1": PAPER_TABLE1,
            "figure11_boundary": "same H6/BeH2 3 A problems, but paper uses non-star CEO and full convergence",
            "figure14_15_boundary": "direct only for H6 1.5 A; paper BeH2 is 2 A",
        },
        "claim_boundary": [
            "H6 3 A and BeH2 3 A plots are axis-equivalent comparisons to Fig. 11, not algorithm-identical reproductions.",
            "Only H6 1.5 A CNOT count and CNOT depth are direct numerical comparisons to paper Table 1.",
            "Paper-equivalent Measurement Cost is unavailable locally and no proxy is substituted.",
            "All local trajectories stop at first strict chemical accuracy, not full gradient convergence.",
        ],
        "direct_comparison": comparison,
        "outputs_sha256": output_hashes,
    }
    (staging / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    staging.rename(output)
    return manifest


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps(generate(args.output), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

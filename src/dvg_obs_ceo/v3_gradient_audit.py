"""Run the preregistered H2/H4 two-path gradient calibration."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
from typing import Any, Mapping, Sequence

import numpy as np

from .baseline import ROOT, verify_upstream
from .block_ir import enumerate_candidates, recover_dvg_blocks
from .calibration import embed_block_transformation
from .resources import AnsatzStructure, apply_candidate_structure
from .s8_probe import _algorithm, _state_vector
from .stationarity import GradientAgreementPolicy, audit_gradient_paths
from .v3_protocol import _write_exclusive


PROTOCOL_ID = "dvg-obs-v3-s1-gradient-audit-v1"
PROTOCOL_TAG = PROTOCOL_ID
DEFAULT_MANIFEST = ROOT / "manifests" / "v3-s1-gradient-audit-v1.json"
REQUIRED_THREADS = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
}


class V3GradientAuditError(RuntimeError):
    """Raised when the S1 molecular gradient audit cannot be trusted."""


def _git(*arguments: str) -> str:
    return subprocess.check_output(["git", "-C", str(ROOT), *arguments], text=True).strip()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _path(relative: str) -> Path:
    result = (ROOT / relative).resolve()
    try:
        result.relative_to(ROOT.resolve())
    except ValueError as error:
        raise V3GradientAuditError(f"input path escapes repository: {relative}") from error
    return result


def verify_freeze() -> dict[str, Any]:
    head = _git("rev-parse", "HEAD")
    try:
        tagged = _git("rev-parse", f"{PROTOCOL_TAG}^{{}}")
    except subprocess.CalledProcessError as error:
        raise V3GradientAuditError(f"missing protocol tag: {PROTOCOL_TAG}") from error
    threads = {name: os.environ.get(name) for name in REQUIRED_THREADS}
    dirty = _git("status", "--porcelain")
    if head != tagged or dirty or threads != REQUIRED_THREADS:
        raise V3GradientAuditError(
            f"S1 requires clean tagged code and canonical threads: head={head}, "
            f"tag={tagged}, dirty={bool(dirty)}, threads={threads}"
        )
    return {"head": head, "protocol_tag": PROTOCOL_TAG, "threads": threads}


def _load_and_verify(manifest_path: Path) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, dict[str, Any]]]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("protocol_id") != PROTOCOL_ID or manifest.get("execution_tag") != PROTOCOL_TAG:
        raise V3GradientAuditError("S1 protocol identity mismatch")
    if verify_upstream()["commit"] != manifest["upstream_commit"]:
        raise V3GradientAuditError("pinned upstream commit mismatch")
    policy = manifest["agreement_policy"]
    if policy != {
        "absolute_tolerance": 1e-10,
        "relative_tolerance": 1e-8,
        "minimum_source_target_state_fidelity": 1.0 - 1e-10,
        "maximum_source_target_energy_difference_hartree": 1e-10,
    }:
        raise V3GradientAuditError("gradient agreement policy was modified")
    rows_record = manifest["input"]["candidate_rows"]
    rows_path = _path(rows_record["path"])
    if _sha256(rows_path) != rows_record["sha256"]:
        raise V3GradientAuditError("candidate-row input hash mismatch")
    rows = [json.loads(line) for line in rows_path.read_text(encoding="utf-8").splitlines() if line]
    if len(rows) != rows_record["expected_rows"] or any(not isinstance(row, dict) for row in rows):
        raise V3GradientAuditError("candidate-row count or shape mismatch")
    checkpoints: dict[str, dict[str, Any]] = {}
    for case_id, record in manifest["input"]["checkpoints"].items():
        path = _path(record["path"])
        if _sha256(path) != record["sha256"]:
            raise V3GradientAuditError(f"checkpoint hash mismatch: {case_id}")
        checkpoint = json.loads(path.read_text(encoding="utf-8"))
        if checkpoint.get("case_id") != case_id:
            raise V3GradientAuditError(f"checkpoint case mismatch: {case_id}")
        checkpoints[case_id] = checkpoint
    return manifest, rows, checkpoints


def _gradient(algorithm: Any, coordinates: np.ndarray, indices: Sequence[int]) -> np.ndarray:
    if not len(indices):
        return np.zeros(0, dtype=np.float64)
    return np.asarray(
        algorithm.estimate_gradients(list(coordinates), list(indices), method="an"),
        dtype=np.float64,
    )


def _energy(algorithm: Any, coordinates: np.ndarray, indices: Sequence[int]) -> float:
    return float(algorithm.evaluate_energy(list(coordinates), list(indices)))


def run(output: Path, manifest_path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    freeze = verify_freeze()
    manifest, rows, checkpoints = _load_and_verify(manifest_path)
    policy_record = manifest["agreement_policy"]
    policy = GradientAgreementPolicy(
        policy_record["absolute_tolerance"], policy_record["relative_tolerance"]
    )
    results: list[dict[str, Any]] = []
    case_counts: Counter[str] = Counter()
    kind_counts: Counter[str] = Counter()

    for case_id in sorted(checkpoints):
        checkpoint = checkpoints[case_id]
        algorithm, pool = _algorithm(case_id)
        source = AnsatzStructure.create(
            checkpoint["ansatz_indices"],
            checkpoint["ansatz_coefficients"],
            checkpoint["iteration_counts"],
        )
        blocks = recover_dvg_blocks(
            pool, source.indices, source.coefficients, source.cumulative_parameter_counts
        )
        block_by_id = {block.block_id: block for block in blocks}
        candidates = {
            candidate.candidate_id: candidate
            for candidate in enumerate_candidates(pool, blocks)
        }
        case_rows = sorted(
            (row for row in rows if row.get("case_id") == case_id),
            key=lambda row: row["candidate"]["candidate_id"],
        )
        for row in case_rows:
            identity = row["candidate"]
            candidate_id = identity["candidate_id"]
            if candidate_id not in candidates:
                raise V3GradientAuditError(f"stored candidate cannot be reconstructed: {candidate_id}")
            candidate = candidates[candidate_id]
            if candidate.source_block_id != identity["source_block_id"]:
                raise V3GradientAuditError(f"stored candidate block mismatch: {candidate_id}")
            block = block_by_id[candidate.source_block_id]
            embedded = embed_block_transformation(len(source.indices), block, candidate)
            phi = np.asarray(row["paths"]["projection_on"]["coordinates"], dtype=np.float64)
            local = phi[embedded.local_target_slice]
            target = apply_candidate_structure(pool, source, candidate, local)
            target = AnsatzStructure.create(
                target.indices, phi, target.cumulative_parameter_counts
            )
            if len(target.indices) != len(phi):
                raise V3GradientAuditError(f"target dimension mismatch: {candidate_id}")

            certificate = audit_gradient_paths(
                phi,
                embedded.transformation,
                lambda value, indices=target.indices: _gradient(algorithm, value, indices),
                lambda value, indices=source.indices: _gradient(algorithm, value, indices),
                target_state=lambda value, indices=target.indices: _state_vector(algorithm, value, indices),
                source_state=lambda value, indices=source.indices: _state_vector(algorithm, value, indices),
                target_energy=lambda value, indices=target.indices: _energy(algorithm, value, indices),
                source_energy=lambda value, indices=source.indices: _energy(algorithm, value, indices),
                policy=policy,
            )
            state_pass = certificate["source_target_state_fidelity"] >= policy_record[
                "minimum_source_target_state_fidelity"
            ]
            energy_pass = certificate["source_target_energy_difference_hartree"] <= policy_record[
                "maximum_source_target_energy_difference_hartree"
            ]
            passed = bool(certificate["passed"] and state_pass and energy_pass)
            result = {
                "case_id": case_id,
                "candidate_id": candidate_id,
                "equivalence_class_id": candidate.equivalence_class_id,
                "kind": candidate.kind,
                "target_family": candidate.target_family,
                "source_dimension": len(source.indices),
                "target_dimension": len(target.indices),
                "gradient_informative": len(target.indices) > 0,
                "certificate": certificate,
                "state_fidelity_passed": state_pass,
                "energy_agreement_passed": energy_pass,
                "passed": passed,
            }
            results.append(result)
            case_counts[case_id] += 1
            kind_counts[candidate.kind] += 1

    observed_kinds = set(kind_counts)
    required_kinds = set(manifest["required_candidate_kinds"])
    failures = [entry["candidate_id"] for entry in results if not entry["passed"]]
    cases_passed = {
        case: bool(count and all(entry["passed"] for entry in results if entry["case_id"] == case))
        for case, count in case_counts.items()
    }
    passed = (
        not failures
        and len(results) == manifest["input"]["candidate_rows"]["expected_rows"]
        and required_kinds.issubset(observed_kinds)
        and all(cases_passed.values())
    )
    summary = {
        "schema_version": "1.0.0",
        "artifact_kind": "v3-s1-gradient-calibration",
        "protocol_id": PROTOCOL_ID,
        "manifest_sha256": _sha256(manifest_path),
        "execution_freeze": freeze,
        "passed": passed,
        "case_counts": dict(sorted(case_counts.items())),
        "case_passed": cases_passed,
        "kind_counts": dict(sorted(kind_counts.items())),
        "required_kinds_present": required_kinds.issubset(observed_kinds),
        "maximum_gradient_difference_infinity": max(
            float(entry["certificate"]["difference_infinity"]) for entry in results
        ),
        "minimum_source_target_state_fidelity": min(
            float(entry["certificate"]["source_target_state_fidelity"]) for entry in results
        ),
        "maximum_source_target_energy_difference_hartree": max(
            float(entry["certificate"]["source_target_energy_difference_hartree"]) for entry in results
        ),
        "failed_candidate_ids": failures,
        "work": {
            "candidate_audits": len(results),
            "target_gradient_vector_evaluations": sum(
                int(entry["certificate"]["work"]["target_gradient_vector_evaluations"])
                for entry in results
            ),
            "source_gradient_vector_evaluations": sum(
                int(entry["certificate"]["work"]["source_gradient_vector_evaluations"])
                for entry in results
            ),
            "ordinary_gsd_adapt_iterations": 0,
            "ceo_star_adapt_iterations": 0,
            "paper_measurement_cost": None,
        },
        "claim_boundary": (
            "H2/H4 calibration of derivative and transformation consistency only; "
            "no LiH result, compression discovery, or paper Measurement Cost claim."
        ),
        "results": results,
    }
    if not passed:
        raise V3GradientAuditError(
            f"S1 gradient calibration failed: failures={failures}, kinds={sorted(observed_kinds)}"
        )
    _write_exclusive(output, summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    arguments = parser.parse_args()
    result = run(arguments.output, arguments.manifest)
    print(
        json.dumps(
            {
                "passed": result["passed"],
                "candidate_audits": result["work"]["candidate_audits"],
                "maximum_gradient_difference_infinity": result[
                    "maximum_gradient_difference_infinity"
                ],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()

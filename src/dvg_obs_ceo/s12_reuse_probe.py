"""Calibrate exact OGM-term reuse without changing the CEO* algorithm."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Iterable

import numpy as np

from .baseline import ROOT, _load_upstream, verify_upstream
from .identity import (
    MeasurementContextSpec,
    ProblemSpec,
    ScientificIdentityBundle,
    StatePreparationSpec,
    canonical_float64_hex,
    sha256_hex,
)
from .measurement_reuse import ExactPauliRequest, ExactPauliReuseCache


PROTOCOL_ID = "dvg-obs-s12-exact-ogm-reuse-protocol-v1.1"
PROTOCOL_TAG = PROTOCOL_ID
REQUIRED_THREADS = {"OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
BACKEND_CONTEXT_DIGEST = hashlib.sha256(b"pinned-scipy-sparse-exact-statevector-no-shots-v1").hexdigest()


class S12ProbeError(RuntimeError):
    """Raised when the reuse calibration cannot support a scientific claim."""


def _git(*arguments: str) -> str:
    return subprocess.check_output(["git", "-C", str(ROOT), *arguments], text=True).strip()


def verify_freeze() -> dict[str, Any]:
    head = _git("rev-parse", "HEAD")
    try:
        tagged = _git("rev-parse", f"{PROTOCOL_TAG}^{{}}")
    except subprocess.CalledProcessError as error:
        raise S12ProbeError(f"missing S12 protocol tag: {PROTOCOL_TAG}") from error
    dirty = _git("status", "--porcelain")
    threads = {name: os.environ.get(name) for name in REQUIRED_THREADS}
    if head != tagged or dirty or threads != REQUIRED_THREADS:
        raise S12ProbeError(
            f"S12 requires clean tagged code and canonical threads: head={head}, tag={tagged}, dirty={bool(dirty)}, threads={threads}"
        )
    return {"head": head, "protocol_tag": PROTOCOL_TAG, "threads": threads}


def _write_exclusive(path: Path, value: Any) -> None:
    payload = json.dumps(value, indent=2, sort_keys=True, allow_nan=False).encode() + b"\n"
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise S12ProbeError("artifact write made no progress")
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


def _complex_payload(value: complex) -> list[str]:
    return list(canonical_float64_hex((float(value.real), float(value.imag))))


def _term_label(term: tuple[tuple[int, str], ...]) -> str:
    return "I" if not term else " ".join(f"{axis}{index}" for index, axis in term)


def _qop_payload(operator: Any) -> list[dict[str, Any]]:
    return [
        {"pauli": _term_label(term), "coefficient_float64_hex": _complex_payload(complex(coefficient))}
        for term, coefficient in sorted(operator.terms.items(), key=lambda item: _term_label(item[0]))
    ]


def _source(case: str) -> tuple[dict[str, Any], tuple[int, ...]]:
    if case == "h2-1.5":
        path = ROOT / "artifacts" / "s1" / "h2-1.5-smoke.json"
        counts = (1,)
    elif case == "lih-3.0":
        path = ROOT / "artifacts" / "s10" / "lih-3a-first-accuracy-primary-v1-2" / "checkpoint.json"
        counts = (2, 5, 8, 11, 15)
    else:
        raise S12ProbeError(f"unsupported S12 case: {case}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["_source_path"] = str(path.relative_to(ROOT))
    payload["_source_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return payload, counts


def _algorithm(case: str) -> tuple[Any, Any, Any]:
    LinAlgAdapt, DVG_CEO, creators, _ = _load_upstream()
    create_h2, create_lih = creators
    molecule = create_h2(1.5) if case == "h2-1.5" else create_lih(3.0)
    pool = DVG_CEO(molecule)
    algorithm = LinAlgAdapt(
        pool=pool, molecule=molecule, verbose=False, max_adapt_iter=1,
        max_opt_iter=10000, full_opt=True, threshold=1e-6,
        convergence_criterion="total_g_norm", tetris=True,
        progressive_opt=False, candidates=1, sel_criterion="gradient",
        recycle_hessian=True, penalize_cnots=False, rand_degenerate=False,
        shots=None,
    )
    return algorithm, pool, molecule


def _blocks(indices: tuple[int, ...], counts: tuple[int, ...]) -> tuple[tuple[str, tuple[int, ...]], ...]:
    start = 0
    blocks = []
    for iteration, stop in enumerate(counts, 1):
        blocks.append((f"TETRIS-layer-{iteration}", indices[start:stop]))
        start = stop
    if start != len(indices):
        raise S12ProbeError("registered TETRIS layer counts do not cover the ansatz")
    return tuple(blocks)


def _measurement_context(
    state: StatePreparationSpec,
    problem: ProblemSpec,
    observable_payload: Any,
    *,
    plan: str,
    grouping: str,
) -> MeasurementContextSpec:
    return MeasurementContextSpec(
        state.state_preparation_id,
        problem.problem_id,
        sha256_hex(observable_payload),
        plan,
        grouping,
        "exact-statevector-pauli-v1",
        BACKEND_CONTEXT_DIGEST,
    )


def _term_evaluator(state: Any, n_qubits: int) -> Any:
    from openfermion import QubitOperator, get_sparse_operator

    ket = state

    def evaluate(label: str) -> float:
        operator = get_sparse_operator(QubitOperator(label, 1.0), n_qubits=n_qubits)
        value = (ket.transpose().conj().dot(operator.dot(ket)))[0, 0]
        if abs(float(value.imag)) > 1e-12:
            raise S12ProbeError("Hermitian Pauli expectation acquired an imaginary component")
        return float(value.real)

    return evaluate


def _measure_labels(
    labels: Iterable[str],
    cache: ExactPauliReuseCache,
    context: MeasurementContextSpec,
    evaluator: Any,
) -> dict[str, float]:
    return {
        label: cache.evaluate(
            ExactPauliRequest(
                context.state_preparation_id,
                context.problem_id,
                label,
                context.estimator_version,
                context.backend_context_digest,
                context.measurement_context_id,
            ),
            evaluator,
        )
        for label in sorted(labels)
    }


def _expectation(operator: Any, values: dict[str, float]) -> float:
    result = 0j
    for term, coefficient in operator.terms.items():
        expectation = 1.0 if not term else values[_term_label(term)]
        result += complex(coefficient) * expectation
    if abs(result.imag) > 1e-9:
        raise S12ProbeError("observable reconstruction acquired an imaginary component")
    return float(result.real)


def run(case: str, bundle: Path) -> dict[str, Any]:
    freeze = verify_freeze()
    upstream = verify_upstream()
    if bundle.exists():
        raise FileExistsError(f"refusing to overwrite S12 bundle: {bundle}")
    staging = bundle.with_name(f".{bundle.name}.staging")
    if staging.exists():
        raise FileExistsError(f"orphan S12 staging requires audit: {staging}")
    staging.mkdir(parents=True)
    _fsync_directory(staging.parent)
    source, counts = _source(case)
    algorithm, pool, molecule = _algorithm(case)
    indices = tuple(int(value) for value in source["ansatz_indices"])
    coefficients = tuple(float(value) for value in source["ansatz_coefficients"])
    state_vector = algorithm.compute_state(coefficients, indices)
    algorithm.state = state_vector

    from openfermion import get_fermion_operator, jordan_wigner

    hamiltonian = jordan_wigner(get_fermion_operator(molecule.get_molecular_hamiltonian()))
    hamiltonian.compress(abs_tol=1e-12)
    gradient_operators = []
    for index in range(pool.size):
        observable = 2 * hamiltonian * pool.get_q_op(index)
        observable.compress(abs_tol=1e-12)
        gradient_operators.append(observable)
    energy_labels = {_term_label(term) for term in hamiltonian.terms if term}
    gradient_labels = {
        _term_label(term)
        for observable in gradient_operators
        for term in observable.terms
        if term
    }
    generator_digest = sha256_hex([_qop_payload(pool.get_q_op(index)) for index in range(pool.size)])
    state = StatePreparationSpec.create(
        reference_state=tuple(int(value) for value in algorithm.ref_det),
        generator_definition_digest=generator_digest,
        ansatz_block_structure=_blocks(indices, counts),
        ansatz_indices=indices,
        coefficients=coefficients,
        qubit_mapping="jordan-wigner",
        qubit_ordering=range(algorithm.n),
    )
    problem = ProblemSpec(
        sha256_hex(_qop_payload(hamiltonian)),
        "H2" if case == "h2-1.5" else "LiH",
        tuple((str(atom), tuple(float(value) for value in point)) for atom, point in molecule.geometry),
        "sto-3g",
        tuple(range(algorithm.n // 2)),
        (),
        "openfermion-jordan-wigner-v1",
    )
    energy_context = _measurement_context(
        state, problem, _qop_payload(hamiltonian),
        plan="energy-term-plan-v1", grouping="termwise-exact-v1",
    )
    gradient_payload = [_qop_payload(observable) for observable in gradient_operators]
    gradient_context = _measurement_context(
        state, problem, gradient_payload,
        plan="ogm-aware-distinct-term-plan-v1", grouping="ogm-distinct-pauli-union-v1",
    )
    identities = {
        "energy": ScientificIdentityBundle(state, problem, energy_context).to_dict(),
        "gradients": ScientificIdentityBundle(state, problem, gradient_context).to_dict(),
    }
    evaluator = _term_evaluator(state_vector, algorithm.n)
    branches = {}
    reconstructed = {}
    for name, enabled in (("reuse_off", False), ("reuse_on", True)):
        cache = ExactPauliReuseCache(enabled=enabled)
        energy_values = _measure_labels(energy_labels, cache, energy_context, evaluator)
        energy = _expectation(hamiltonian, energy_values)
        gradient_values = _measure_labels(gradient_labels, cache, gradient_context, evaluator)
        gradients = np.asarray(
            [_expectation(observable, gradient_values) for observable in gradient_operators],
            dtype=np.float64,
        )
        reconstructed[name] = (energy, gradients)
        ledger = cache.report(include_events=True)
        _write_exclusive(staging / f"{name}-ledger.json", ledger)
        branches[name] = {
            "energy_hartree": energy,
            "gradient_vector_digest": sha256_hex(canonical_float64_hex(gradients)),
            "total_gradient_norm_excluding_parents": float(np.sqrt(sum(
                gradient ** 2 for index, gradient in enumerate(gradients)
                if index not in pool.parent_range
            ))),
            "maximum_gradient_index": int(np.argmax(np.abs(gradients))),
            "maximum_gradient": float(gradients[int(np.argmax(np.abs(gradients)))]),
            "ledger": cache.report(include_events=False),
        }
    off_energy, off_gradients = reconstructed["reuse_off"]
    on_energy, on_gradients = reconstructed["reuse_on"]
    official_energy = float(algorithm.evaluate_energy(coefficients, indices))
    official_gradients = np.asarray(
        [algorithm.eval_candidate_gradient(index) for index in range(pool.size)],
        dtype=np.float64,
    )
    _, _, official_norm, _ = algorithm.rank_gradients(silent=True)
    thresholded_official_norm = float(np.sqrt(sum(
        gradient ** 2 for index, gradient in enumerate(official_gradients)
        if abs(gradient) >= 1e-8 and index not in pool.parent_range
    )))
    source_energy = float(source["energy_hartree"])
    checks = {
        "reuse_off_on_energy_bitwise_equal": canonical_float64_hex((off_energy,)) == canonical_float64_hex((on_energy,)),
        "reuse_off_on_gradient_bitwise_equal": np.array_equal(off_gradients, on_gradients),
        "termwise_energy_matches_official_sparse": abs(off_energy - official_energy) <= 1e-10,
        "official_sparse_energy_matches_source": abs(official_energy - source_energy) <= 1e-10,
        "termwise_gradient_vector_matches_official_sparse": bool(np.allclose(off_gradients, official_gradients, rtol=0.0, atol=1e-10)),
        "official_rank_norm_matches_thresholded_raw_vector": abs(thresholded_official_norm - float(official_norm)) <= 1e-12,
        "reuse_has_positive_hits": branches["reuse_on"]["ledger"]["cache_hits"] > 0,
        "reuse_reduces_fresh_pauli_evaluations": branches["reuse_on"]["ledger"]["fresh_pauli_expectation_evaluations"] < branches["reuse_off"]["ledger"]["fresh_pauli_expectation_evaluations"],
        "state_id_same_across_contexts": identities["energy"]["state_preparation_id"] == identities["gradients"]["state_preparation_id"],
        "measurement_contexts_distinct": identities["energy"]["measurement_context_id"] != identities["gradients"]["measurement_context_id"],
    }
    failed = [name for name, passed in checks.items() if not passed]
    result = {
        "schema_version": "1.0.0",
        "artifact_kind": "s12-exact-ogm-aware-measurement-reuse-probe",
        "protocol_id": PROTOCOL_ID,
        "case": case,
        "execution_freeze": freeze,
        "upstream": upstream,
        "source": {"path": source["_source_path"], "sha256": source["_source_sha256"]},
        "identities": identities,
        "observable_inventory": {
            "energy_nonidentity_pauli_terms": len(energy_labels),
            "ogm_gradient_union_nonidentity_pauli_terms": len(gradient_labels),
            "cross_context_overlap_terms": len(energy_labels & gradient_labels),
            "pool_operators": pool.size,
        },
        "independent_sparse_parity": {
            "official_energy_hartree": official_energy,
            "maximum_absolute_gradient_difference": float(np.max(np.abs(off_gradients - official_gradients))),
            "official_rank_gradient_norm": float(official_norm),
            "thresholded_raw_gradient_norm": thresholded_official_norm,
            "official_gradient_zero_cutoff": 1e-8
        },
        "branches": branches,
        "checks": checks,
        "passed": not failed,
        "failed_checks": failed,
        "paper_measurement_cost": None,
        "claim_boundary": [
            "Reuse OFF and ON differ only in exact Pauli expectation caching; CEO* state and observables are unchanged.",
            "Cross-context reuse is allowed only for an identical Pauli term under identical StatePreparationID, ProblemID, estimator, and backend.",
            "This simulator probe counts exact Pauli expectation kernels, not shots, commuting collections, or paper-equivalent Measurement Cost.",
            "The referenced shot-efficient method motivates energy-to-next-gradient reuse, but its finite-shot allocation is not implemented here.",
        ],
    }
    if failed:
        _write_exclusive(staging / "failed-summary.json", result)
        _fsync_directory(staging)
        raise S12ProbeError(f"S12 scientific checks failed: {failed}")
    _write_exclusive(staging / "summary.json", result)
    _fsync_directory(staging)
    os.replace(staging, bundle)
    _fsync_directory(bundle.parent)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", choices=("h2-1.5", "lih-3.0"), required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    arguments = parser.parse_args()
    sys.argv[:] = [sys.argv[0]]
    result = run(arguments.case, arguments.bundle)
    print(json.dumps({
        "bundle": str(arguments.bundle),
        "passed": result["passed"],
        "off_fresh": result["branches"]["reuse_off"]["ledger"]["fresh_pauli_expectation_evaluations"],
        "on_fresh": result["branches"]["reuse_on"]["ledger"]["fresh_pauli_expectation_evaluations"],
        "hits": result["branches"]["reuse_on"]["ledger"]["cache_hits"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()

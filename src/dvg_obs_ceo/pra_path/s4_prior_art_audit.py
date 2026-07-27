"""PRA S4 bounded primary-source prior-art and novelty audit."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Any

from dvg_obs_ceo.artifact_io import atomic_write_new_json
from dvg_obs_ceo.baseline import ROOT
from dvg_obs_ceo.identity import sha256_hex


OUTPUT = ROOT / "artifacts/pra_path/s4/prior-art-novelty-audit-v1.json"
S3_OUTPUT = ROOT / "artifacts/pra_path/s3/normal-registry-audit-v1.json"

FEATURES = (
    "ceo_mvp_or_ovp",
    "post_adapt_operator_pruning",
    "parameter_redundancy_removal",
    "parameter_tying_or_rank_restriction",
    "native_excitation_synthesis",
    "registered_three_to_two_ceo_demotion",
    "dedicated_registered_target_native_circuit",
    "transactional_approximate_demotion",
    "full_ansatz_resource_recount",
    "matched_work_sequential_evaluation",
)


class S4PriorArtAuditError(RuntimeError):
    """Raised when S4 evidence is incomplete or overclaims novelty."""


def _git(*arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _features(*present: str) -> dict[str, bool]:
    unknown = set(present).difference(FEATURES)
    if unknown:
        raise S4PriorArtAuditError(f"unknown feature names: {sorted(unknown)}")
    return {feature: feature in present for feature in FEATURES}


def primary_sources() -> list[dict[str, Any]]:
    """Return the frozen, bounded set of directly inspected primary sources."""
    return [
        {
            "source_id": "ramoa-2025-ceo-adapt",
            "title": (
                "Reducing the resources required by ADAPT-VQE using coupled "
                "exchange operators and improved subroutines"
            ),
            "year": 2025,
            "publication_status": "peer reviewed",
            "identifier": "doi:10.1038/s41534-025-01039-4",
            "url": "https://www.nature.com/articles/s41534-025-01039-4",
            "features": _features(
                "ceo_mvp_or_ovp",
                "parameter_tying_or_rank_restriction",
                "native_excitation_synthesis",
                "full_ansatz_resource_recount",
            ),
            "scope_note": (
                "Defines CEO MVP/OVP blocks and their CNOT-efficient native "
                "circuits. OVP shared-parameter sum/difference families are "
                "direct prior art; the paper does not describe the frozen "
                "13-normal post-checkpoint demotion protocol."
            ),
        },
        {
            "source_id": "vaquero-sabater-2025-pruned-adapt",
            "title": (
                "Pruned-ADAPT-VQE: compacting molecular ansätze by removing "
                "irrelevant operators"
            ),
            "year": 2025,
            "publication_status": "peer reviewed",
            "identifier": "doi:10.1021/acs.jctc.5c00535",
            "url": "https://pubs.acs.org/doi/10.1021/acs.jctc.5c00535",
            "features": _features("post_adapt_operator_pruning"),
            "scope_note": (
                "Removes low-impact ADAPT operators using amplitude, position, "
                "and a dynamic threshold. This is direct generic pruning prior "
                "art, not an internal CEO block rank demotion."
            ),
        },
        {
            "source_id": "sim-2021-pect",
            "title": (
                "Adaptive pruning-based optimization of parameterized quantum "
                "circuits"
            ),
            "year": 2021,
            "publication_status": "peer reviewed",
            "identifier": "doi:10.1088/2058-9565/abe107",
            "url": "https://doi.org/10.1088/2058-9565/abe107",
            "features": _features(
                "post_adapt_operator_pruning",
                "parameter_redundancy_removal",
            ),
            "scope_note": (
                "PECT dynamically prunes and reallocates active parameters in "
                "a fixed variational ansatz. It does not provide CEO-specific "
                "registered target-native rank demotion."
            ),
        },
        {
            "source_id": "funcke-2021-dimensional-expressivity",
            "title": "Dimensional Expressivity Analysis of Parametric Quantum Circuits",
            "year": 2021,
            "publication_status": "peer reviewed",
            "identifier": "doi:10.22331/q-2021-03-29-422",
            "url": "https://quantum-journal.org/papers/q-2021-03-29-422/",
            "features": _features("parameter_redundancy_removal"),
            "scope_note": (
                "Identifies superfluous parameters through expressive "
                "dimension. It establishes broad manifold-compression prior "
                "art, not the CEO-specific finite registry or native circuit."
            ),
        },
        {
            "source_id": "haug-2021-capacity-geometry",
            "title": "Capacity and Quantum Geometry of Parametrized Quantum Circuits",
            "year": 2021,
            "publication_status": "peer reviewed",
            "identifier": "doi:10.1103/PRXQuantum.2.040309",
            "url": (
                "https://journals.aps.org/prxquantum/abstract/"
                "10.1103/PRXQuantum.2.040309"
            ),
            "features": _features("parameter_redundancy_removal"),
            "scope_note": (
                "Uses effective quantum dimension/QFI geometry to prune "
                "redundant circuit parameters. This is generic redundancy "
                "prior art and does not certify physical resource reduction "
                "for a registered CEO target."
            ),
        },
        {
            "source_id": "yordanov-2020-efficient-excitations",
            "title": "Efficient quantum circuits for quantum computational chemistry",
            "year": 2020,
            "publication_status": "peer reviewed",
            "identifier": "doi:10.1103/PhysRevA.102.062612",
            "url": (
                "https://journals.aps.org/pra/abstract/"
                "10.1103/PhysRevA.102.062612"
            ),
            "features": _features("native_excitation_synthesis"),
            "scope_note": (
                "Provides CNOT-efficient qubit and fermionic excitation "
                "circuits. Native excitation synthesis itself is not novel."
            ),
        },
        {
            "source_id": "magoulas-2023-arbitrary-rank",
            "title": (
                "CNOT-Efficient Circuits for Arbitrary Rank Many-Body "
                "Fermionic and Qubit Excitations"
            ),
            "year": 2023,
            "publication_status": "peer reviewed",
            "identifier": "doi:10.1021/acs.jctc.2c01016",
            "url": "https://pubmed.ncbi.nlm.nih.gov/36656643/",
            "features": _features("native_excitation_synthesis"),
            "scope_note": (
                "Extends compact excitation circuits to arbitrary excitation "
                "rank. It is synthesis prior art, but not a tied "
                "three-constituent MVP-CEO target family."
            ),
        },
        {
            "source_id": "zhang-2022-cluster-vqe",
            "title": "Variational quantum eigensolver with reduced circuit complexity",
            "year": 2022,
            "publication_status": "peer reviewed",
            "identifier": "doi:10.1038/s41534-022-00599-z",
            "url": "https://www.nature.com/articles/s41534-022-00599-z",
            "features": _features("full_ansatz_resource_recount"),
            "scope_note": (
                "ClusterVQE reduces width/depth by clustering and Hamiltonian "
                "dressing. It is broad circuit-compression prior art with a "
                "different mechanism and comparison object."
            ),
        },
        {
            "source_id": "vo-2026-plateau-elimination",
            "title": (
                "Reducing quantum resources for ADAPT-VQE via "
                "plateau-operator elimination and correlated mean-field "
                "downfolding"
            ),
            "year": 2026,
            "publication_status": "preprint",
            "identifier": "arXiv:2607.00575",
            "url": "https://arxiv.org/abs/2607.00575",
            "features": _features("post_adapt_operator_pruning"),
            "scope_note": (
                "Eliminates non-contributing pool operators and optionally "
                "restores the pool. It does not report the registered "
                "CEO-internal rank-demotion transition."
            ),
        },
        {
            "source_id": "he-2026-ha-adapt",
            "title": (
                "Hamiltonian-Aware ADAPT Variational Quantum Eigensolver for "
                "Molecular Ground-State Simulation"
            ),
            "year": 2026,
            "publication_status": "preprint",
            "identifier": "arXiv:2606.13118",
            "url": "https://arxiv.org/abs/2606.13118",
            "features": _features("post_adapt_operator_pruning"),
            "scope_note": (
                "Changes ADAPT selection and prunes degraded excitation "
                "operators using Hamiltonian-aware criteria. It is distinct "
                "from post-checkpoint CEO block rank demotion."
            ),
        },
    ]


def build_report() -> dict[str, Any]:
    s3 = json.loads(S3_OUTPUT.read_text(encoding="utf-8"))
    if s3["authorization"]["s4"] is not True:
        raise S4PriorArtAuditError("S3 did not authorize S4")

    sources = primary_sources()
    exact_prior = [
        source["source_id"]
        for source in sources
        if source["features"]["registered_three_to_two_ceo_demotion"]
        or source["features"]["dedicated_registered_target_native_circuit"]
        or source["features"]["transactional_approximate_demotion"]
        or source["features"]["matched_work_sequential_evaluation"]
    ]
    status_counts: dict[str, int] = {}
    for source in sources:
        status = source["publication_status"]
        status_counts[status] = status_counts.get(status, 0) + 1

    report: dict[str, Any] = {
        "schema": "dvg-obs-ceo.pra-path.s4-prior-art-audit.v1",
        "decision": "GO_S5_NOVELTY_SCOPE_DEFENSIBLE",
        "audit_scope": {
            "kind": "bounded primary-source audit",
            "accessed_utc_date": "2026-07-27",
            "databases_and_surfaces": [
                "publisher article pages",
                "Crossref-linked journal records",
                "arXiv",
            ],
            "query_families": [
                "CEO MVP OVP native circuit",
                "parameter tying block rank reduction VQE",
                "post-ADAPT operator pruning",
                "CNOT-efficient excitation synthesis",
                "variational circuit compression",
                "QFI effective dimension parameter pruning",
                "sequential dynamic pruning",
            ],
            "exhaustive_world_literature_claim": False,
            "source_count": len(sources),
            "publication_status_counts": status_counts,
        },
        "sources": sources,
        "novelty_matrix": [
            {
                "feature": "three-to-two CEO family",
                "prior_work": (
                    "CEO MVP/OVP and shared-parameter CEO families exist; no "
                    "source in this bounded audit reports the frozen "
                    "13-normal post-checkpoint registry."
                ),
                "this_work": (
                    "complete finite {-1,0,1}^3/global-sign registry for "
                    "three-constituent MVP-CEO blocks"
                ),
                "evidence": "S3 theorem-by-enumeration and registry audit",
            },
            {
                "feature": "dedicated target-native circuit",
                "prior_work": (
                    "CEO-native and general excitation-native circuits exist"
                ),
                "this_work": (
                    "registered target-family native circuit with independent "
                    "semantic equivalence evidence"
                ),
                "evidence": "historical V6 native synthesis artifacts",
            },
            {
                "feature": "pointwise/statewise evidence",
                "prior_work": (
                    "expressive-dimension and QFI redundancy analyses exist"
                ),
                "this_work": (
                    "separates family embedding, pointwise state agreement, "
                    "native equivalence, stationarity, and resources"
                ),
                "evidence": "historical V6 and V6.1 evidence layers",
            },
            {
                "feature": "transactional approximate demotion",
                "prior_work": (
                    "dynamic and post-ADAPT pruning exists; no exact protocol "
                    "match was identified in the bounded audit"
                ),
                "this_work": (
                    "commit-or-complete-rollback CEO block demotion guarded by "
                    "energy, tangent stationarity, semantics, and resources"
                ),
                "evidence": "historical V6 transaction artifacts and tests",
            },
            {
                "feature": "full-circuit recount",
                "prior_work": "full ansatz resource comparisons are established",
                "this_work": (
                    "independent before/after recount is a certification layer, "
                    "not a standalone novelty claim"
                ),
                "evidence": "historical V6 independent resource audit",
            },
            {
                "feature": "matched-work sequential evaluation",
                "prior_work": (
                    "resource and optimization-work comparisons exist broadly; "
                    "no exact protocol match identified here"
                ),
                "this_work": "planned componentwise work-ledger evaluation",
                "evidence": "not yet generated; S7 and S9 remain prospective",
            },
        ],
        "direct_overlap": [
            "CEO operators, MVP/OVP definitions, and native CEO circuits",
            "shared-parameter CEO sum/difference families",
            "generic parameter/operator pruning",
            "QFI or expressive-dimension redundancy removal",
            "CNOT-efficient excitation synthesis",
            "full-circuit resource comparison",
        ],
        "defensible_distinction": (
            "A synthesis-certified finite registered rank-demotion framework "
            "for three-constituent MVP-CEO blocks, with target-native "
            "resynthesis and orthogonal semantic, optimization, transaction, "
            "and resource evidence."
        ),
        "safe_claim": (
            "a synthesis-certified registered rank demotion not present in "
            "the compared V4.1 implementation"
        ),
        "conditional_claim_after_complete_evidence": (
            "The bounded literature audit did not identify the same finite "
            "registered CEO rank-demotion and certification protocol; any "
            "novelty claim remains limited to this combined formulation."
        ),
        "prohibited_claims": [
            "CEO operators or native CEO circuits are new",
            "parameter pruning is new",
            "QFI-based redundancy removal is new",
            "CNOT-efficient excitation synthesis is new",
            "the search proves absence from all world literature",
            "matched-work superiority before S7/S9 evidence",
            "general performance improvement across molecules",
        ],
        "exact_protocol_matches_in_bounded_audit": exact_prior,
        "authorization": {
            "s5": not exact_prior,
            "performance_execution": False,
        },
        "execution": {"git_commit": _git("rev-parse", "HEAD")},
        "claim_boundary": (
            "This bounded audit supports only a narrow combined-method "
            "distinction. It is not an exhaustive proof of novelty and contains "
            "no new performance result."
        ),
    }
    if exact_prior:
        report["decision"] = "NO_GO_EXACT_PRIOR_ART_MATCH"
    report["report_digest"] = sha256_hex(report)
    return report


def audit_report(report: dict[str, Any]) -> None:
    content = dict(report)
    digest = content.pop("report_digest", None)
    if digest != sha256_hex(content):
        raise S4PriorArtAuditError("S4 report digest mismatch")
    if report["audit_scope"]["exhaustive_world_literature_claim"]:
        raise S4PriorArtAuditError("bounded audit cannot claim exhaustiveness")
    statuses = {source["publication_status"] for source in report["sources"]}
    if not {"peer reviewed", "preprint"}.issubset(statuses):
        raise S4PriorArtAuditError("publication statuses were not separated")
    for source in report["sources"]:
        if set(source["features"]) != set(FEATURES):
            raise S4PriorArtAuditError("source feature schema is incomplete")
        if not source["url"].startswith("https://"):
            raise S4PriorArtAuditError("source lacks a stable HTTPS URL")
        if not source["identifier"]:
            raise S4PriorArtAuditError("source lacks a persistent identifier")
    if report["exact_protocol_matches_in_bounded_audit"]:
        raise S4PriorArtAuditError("exact prior-art match requires NO-GO review")
    if report["authorization"]["performance_execution"]:
        raise S4PriorArtAuditError("S4 cannot authorize performance execution")


def main() -> None:
    if OUTPUT.exists():
        raise S4PriorArtAuditError("refusing to overwrite S4 audit")
    if _git("status", "--porcelain"):
        raise S4PriorArtAuditError("S4 requires a clean worktree")
    report = build_report()
    audit_report(report)
    atomic_write_new_json(OUTPUT, report)


if __name__ == "__main__":
    main()

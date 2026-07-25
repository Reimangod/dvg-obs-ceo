import json

import numpy as np

from dvg_obs_ceo.identity import sha256_hex
from dvg_obs_ceo.v6_rank_adaptive.native_synthesis_pipeline import (
    NS1_OUTPUT,
    NS3_OUTPUT,
    NS4_OUTPUT,
    NS5_OUTPUT,
    NS6_OUTPUT,
    _canonical_normals,
    _parameter_map,
    shortest_parity_walk,
)


def test_discrete_registry_has_all_canonical_signed_normals():
    normals = _canonical_normals()
    assert len(normals) == 13
    for normal in normals:
        matrix = _parameter_map(normal)
        assert np.linalg.matrix_rank(matrix) == 2
        assert np.array_equal(np.asarray(normal) @ matrix, [0, 0])


def test_shortest_walk_is_deterministic_and_bound_complete():
    required = (0, 1, 3, 7, 6, 4)
    forward = shortest_parity_walk(required)
    reverse = shortest_parity_walk(tuple(reversed(required)))
    assert forward == reverse
    assert forward[0] == (1, 2, 4, 1, 2)


def test_committed_ns_artifacts_are_hash_bound_and_resource_first():
    ns1 = json.loads(NS1_OUTPUT.read_text(encoding="utf-8"))
    digest = ns1.pop("report_digest")
    assert digest == sha256_hex(ns1)
    ns3 = json.loads(NS3_OUTPUT.read_text(encoding="utf-8"))
    digest = ns3.pop("report_digest")
    assert digest == sha256_hex(ns3)
    assert ns3["local_primary_eligible_count"] >= 1
    ns4 = json.loads(NS4_OUTPUT.read_text(encoding="utf-8"))
    digest = ns4.pop("report_digest")
    assert digest == sha256_hex(ns4)
    assert all(
        item["maximum_statevector_l2_error_up_to_global_phase"] <= 1e-10
        for item in ns4["certifications"]
        if item["familywise_certified"]
    )
    ns5 = json.loads(NS5_OUTPUT.read_text(encoding="utf-8"))
    digest = ns5.pop("report_digest")
    assert digest == sha256_hex(ns5)
    assert ns5["work"]["energy_evaluations"] == 0
    ns6 = json.loads(NS6_OUTPUT.read_text(encoding="utf-8"))
    digest = ns6.pop("freeze_digest")
    assert digest == sha256_hex(ns6)
    assert ns6["information_firewall"]["candidate_energy_available"] is False
    assert ns6["energy_queue_count"] <= (
        ns6["maximum_families"]
        * len({item["context_id"] for item in ns6["energy_queue"]})
    )

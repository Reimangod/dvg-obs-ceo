import copy
import hashlib

import pytest

from dvg_obs_ceo.identity import (
    MeasurementContextSpec,
    ProblemSpec,
    ScientificIdentityBundle,
    StatePreparationSpec,
)
from dvg_obs_ceo.v6_rank_adaptive.architecture_state import (
    ArchitectureBlock,
    ArchitectureResources,
    ArchitectureState,
    ArchitectureStateError,
    GeneratorSemantic,
    ParameterMapIR,
    ParameterMapRepresentation,
    WorkLedger,
    generator_definition_digest,
)
from dvg_obs_ceo.v6_rank_adaptive.evidence import ResourceVector


DIGEST_A = hashlib.sha256(b"a").hexdigest()
DIGEST_B = hashlib.sha256(b"b").hexdigest()
DIGEST_C = hashlib.sha256(b"c").hexdigest()
EVIDENCE_ID = "v6-evidence-v1:" + hashlib.sha256(b"e").hexdigest()


def generator(label, support=(0, 1, 2, 3), orientation="canonical"):
    digest = hashlib.sha256(label.encode()).hexdigest()
    return GeneratorSemantic(
        generator_id="generator-v1:" + digest,
        operator_digest=digest,
        support_qubits=support,
        normalization="anti-hermitian-qe-v1",
        orientation=orientation,
        symmetry_quantum_numbers=(
            "delta_alpha=0",
            "delta_beta=0",
            "delta_particles=0",
        ),
    )


def block(
    block_label,
    family,
    positions,
    indices,
    coefficient_hex,
    generators,
    parameter_map,
):
    del block_label
    return ArchitectureBlock.create(
        family=family,
        ansatz_positions=positions,
        ansatz_indices=indices,
        coefficient_bytes_hex=coefficient_hex,
        selection_iteration=1,
        generators=generators,
        parameter_map=parameter_map,
        circuit_implementation_id=f"{family.lower()}-circuit-v1",
        native_synthesis_id=f"{family.lower()}-native-v1",
    )


def identity_and_blocks(*, plan="exact-plan-v1", orientation="canonical"):
    coefficients = (0.1, -0.2, 0.3)
    coefficient_hex = StatePreparationSpec.create(
        reference_state=(1, 1, 0, 0),
        generator_definition_digest=DIGEST_A,
        ansatz_block_structure=(("temporary", (0, 1, 2)),),
        ansatz_indices=(0, 1, 2),
        coefficients=coefficients,
        qubit_mapping="jordan-wigner",
        qubit_ordering=(0, 1, 2, 3),
    ).coefficient_bytes_hex
    generators = (
        generator("g0", orientation=orientation),
        generator("g1", orientation=orientation),
        generator("g2", orientation=orientation),
    )
    blocks = (
        block(
            "mvp",
            "MVP",
            (0, 1, 2),
            (10, 11, 12),
            coefficient_hex,
            generators,
            ParameterMapIR.identity(3),
        ),
    )
    prepared = StatePreparationSpec(
        reference_state=(1, 1, 0, 0),
        generator_definition_digest=generator_definition_digest(blocks),
        ansatz_block_structure=(("MVP", (10, 11, 12)),),
        ansatz_indices=(10, 11, 12),
        coefficient_bytes_hex=coefficient_hex,
        orbital_parameter_bytes_hex=(),
        qubit_mapping="jordan-wigner",
        qubit_ordering=(0, 1, 2, 3),
    )
    problem = ProblemSpec(
        DIGEST_A,
        "H2",
        (("H", (0.0, 0.0, 0.0)), ("H", (0.0, 0.0, 1.5))),
        "sto-3g",
        (0, 1),
        (),
        "jordan-wigner-v1",
    )
    measurement = MeasurementContextSpec(
        prepared.state_preparation_id,
        problem.problem_id,
        DIGEST_B,
        plan,
        "none-exact-statevector",
        "exact-statevector-v1",
        DIGEST_C,
    )
    return ScientificIdentityBundle(prepared, problem, measurement), blocks


def architecture(*, plan="exact-plan-v1", orientation="canonical"):
    identity, blocks = identity_and_blocks(
        plan=plan,
        orientation=orientation,
    )
    return ArchitectureState(
        identity=identity,
        blocks=blocks,
        resources=ArchitectureResources(
            vector=ResourceVector(3, 1, 13, 11, 20),
            resource_counter_version="paper-era-v1",
            native_synthesizer_version="mvp-native-v1",
            compiler_configuration="no-global-compilation",
            qubit_order=(0, 1, 2, 3),
            circuit_digest=DIGEST_A,
        ),
        work_ledger=WorkLedger(energy_evaluations=2),
        evidence_ids=(EVIDENCE_ID,),
        transition_registry_digest=DIGEST_A,
        protocol_digest=DIGEST_B,
        environment_digest=DIGEST_C,
        parent_checkpoint_id="checkpoint:test",
        parent_checkpoint_digest=DIGEST_A,
        original_artifact_digest=DIGEST_B,
    )


def test_architecture_state_round_trip_and_digest_are_stable():
    original = architecture()
    value = original.to_dict()
    restored = ArchitectureState.from_dict(value)
    assert restored == original
    assert restored.architecture_state_id == original.architecture_state_id
    assert value["normalized_ir_digest"] in value["architecture_state_id"]


def test_measurement_plan_does_not_change_state_preparation_id():
    first = architecture(plan="plan-v1")
    second = architecture(plan="plan-v2")
    assert (
        first.identity.state.state_preparation_id
        == second.identity.state.state_preparation_id
    )
    assert (
        first.identity.measurement.measurement_context_id
        != second.identity.measurement.measurement_context_id
    )
    assert first.architecture_state_id != second.architecture_state_id


def test_generator_orientation_changes_state_and_architecture_identity():
    first = architecture()
    second = architecture(orientation="reversed")
    assert (
        first.identity.state.state_preparation_id
        != second.identity.state.state_preparation_id
    )
    assert first.architecture_state_id != second.architecture_state_id


def test_tampered_normalized_ir_digest_is_rejected():
    value = architecture().to_dict()
    value["work_ledger"]["energy_evaluations"] += 1
    with pytest.raises(ArchitectureStateError, match="normalized_ir_digest"):
        ArchitectureState.from_dict(value)


def test_block_positions_must_cover_ansatz_without_gaps():
    original = architecture()
    value = original.blocks[0]
    with pytest.raises(ArchitectureStateError, match="positions"):
        ArchitectureState(
            **{
                **original.__dict__,
                "blocks": (
                    ArchitectureBlock.create(
                        family=value.family,
                        ansatz_positions=(0, 1, 3),
                        ansatz_indices=value.ansatz_indices,
                        coefficient_bytes_hex=value.coefficient_bytes_hex,
                        selection_iteration=value.selection_iteration,
                        generators=value.generators,
                        parameter_map=value.parameter_map,
                        circuit_implementation_id=value.circuit_implementation_id,
                        native_synthesis_id=value.native_synthesis_id,
                    ),
                ),
            }
        )


def test_resource_counts_must_match_ir():
    original = architecture()
    with pytest.raises(ArchitectureStateError, match="parameter count"):
        ArchitectureState(
            **{
                **original.__dict__,
                "resources": ArchitectureResources(
                    **{
                        **original.resources.__dict__,
                        "vector": ResourceVector(2, 1, 13, 11, 20),
                    }
                ),
            }
        )


def test_evidence_inventory_must_be_sorted_and_unique():
    original = architecture()
    with pytest.raises(ArchitectureStateError, match="sorted and unique"):
        ArchitectureState(
            **{
                **original.__dict__,
                "evidence_ids": (EVIDENCE_ID, EVIDENCE_ID),
            }
        )


def test_parameter_map_uses_canonical_exact_rationals():
    with pytest.raises(ArchitectureStateError, match="not canonical"):
        ParameterMapIR(
            ParameterMapRepresentation.AFFINE_EXACT,
            2,
            1,
            ("0", "0"),
            (("2/2",), ("-1",)),
            None,
            None,
            1,
        )
    ovp = ParameterMapIR(
        ParameterMapRepresentation.AFFINE_EXACT,
        2,
        1,
        ("0", "0"),
        (("1",), ("-1",)),
        None,
        None,
        1,
    )
    assert ovp.to_dict()["jacobian"] == [["1"], ["-1"]]


def test_registered_analytic_map_cannot_masquerade_as_affine():
    with pytest.raises(ArchitectureStateError, match="masquerade"):
        ParameterMapIR(
            ParameterMapRepresentation.REGISTERED_ANALYTIC_MAP,
            2,
            1,
            ("0", "0"),
            (("1",), ("1",)),
            None,
            "nonlinear-map-v1",
            1,
        )
    analytic = ParameterMapIR(
        ParameterMapRepresentation.REGISTERED_ANALYTIC_MAP,
        2,
        1,
        (),
        (),
        None,
        "nonlinear-map-v1",
        1,
    )
    assert analytic.analytic_map_id == "nonlinear-map-v1"


def test_block_id_detects_semantic_aliasing():
    original = architecture().blocks[0]
    with pytest.raises(ArchitectureStateError, match="block ID"):
        ArchitectureBlock(
            **{
                **original.__dict__,
                "native_synthesis_id": "different-synthesis",
            }
        )


def test_schema_rejects_extra_fields_and_measurement_cost():
    value = architecture().to_dict()
    value["unknown"] = True
    with pytest.raises(ArchitectureStateError, match="schema"):
        ArchitectureState.from_dict(value)
    ledger = architecture().work_ledger.to_dict()
    ledger["paper_measurement_cost"] = 1
    with pytest.raises(ArchitectureStateError, match="undefined"):
        WorkLedger.from_dict(ledger)

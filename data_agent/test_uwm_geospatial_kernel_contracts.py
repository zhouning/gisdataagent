import pytest

from data_agent.uwm.geospatial_kernel.contracts import (
    GEOSPATIAL_KERNEL_SCHEMA,
    MAX_CLAIM_LEVEL,
    build_geospatial_kernel_contract,
)
from data_agent.uwm.geospatial_kernel.validation import validate_geospatial_kernel_contract


def _valid_contract() -> dict:
    return build_geospatial_kernel_contract(
        kernel_version="0.1.0",
        evidence_refs=["evidence_manifest:sha256:test"],
    )


def test_contract_declares_closed_world_geospatial_types_and_claim_boundary():
    contract = _valid_contract()

    validation = validate_geospatial_kernel_contract(contract)

    assert validation == {"valid": True, "errors": []}
    assert contract["schema"] == GEOSPATIAL_KERNEL_SCHEMA
    assert contract["node_types"] == [
        "admin_context",
        "facility",
        "parcel",
        "planning_resource",
        "village_context",
    ]
    assert contract["relation_types"] == [
        "cross_scale_context",
        "functional_compatibility",
        "parcel_adjacent_parcel",
        "parcel_contains_resource",
        "parcel_near_facility",
        "parcel_near_parcel",
        "parcel_within_village",
        "village_within_admin",
    ]
    assert contract["state_times"] == [
        "t0_current",
        "t1_post_change",
        "t2_neighborhood_adaptation",
    ]
    assert contract["support_levels"] == [
        "authoritative_rule",
        "bounded_proxy",
        "deterministic_geometry",
        "learned_calibrated",
        "unavailable",
    ]
    assert contract["effect_levels"] == [
        "geometry_supported_signal",
        "observed_state_change",
        "rule_supported_effect",
        "unavailable_prediction",
        "unresolved_effect",
    ]
    assert contract["claim_boundary"]["max_claim_level"] == MAX_CLAIM_LEVEL
    assert contract["trusted_actor_source"] == "server_authenticated_identity"
    assert contract["empirical_policy_effect_claim"] is False


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("node_types", ["parcel", "unknown_node"], "node_types_mismatch"),
        ("relation_types", ["parcel_adjacent_parcel"], "relation_types_mismatch"),
        ("state_times", ["t0_current", "t1_post_change"], "state_times_mismatch"),
        ("support_levels", ["learned_calibrated"], "support_levels_mismatch"),
        ("effect_levels", ["policy_success_probability"], "effect_levels_mismatch"),
        ("trusted_actor_source", "client_payload", "trusted_actor_source_must_be_server_authenticated_identity"),
    ],
)
def test_contract_rejects_open_ended_or_client_trusted_semantics(field, value, error):
    contract = _valid_contract()
    contract[field] = value

    validation = validate_geospatial_kernel_contract(contract)

    assert not validation["valid"]
    assert error in validation["errors"]


def test_contract_requires_evidence_and_caps_claims():
    contract = _valid_contract()
    contract["evidence_refs"] = []
    contract["claim_boundary"]["max_claim_level"] = "validated_policy_effect"
    contract["empirical_policy_effect_claim"] = True

    validation = validate_geospatial_kernel_contract(contract)

    assert not validation["valid"]
    assert "evidence_refs_missing" in validation["errors"]
    assert "max_claim_level_exceeds_kernel_boundary" in validation["errors"]
    assert "empirical_policy_effect_claim_must_be_false" in validation["errors"]


def test_contract_keeps_current_planned_and_candidate_land_use_distinct():
    contract = _valid_contract()
    assert contract["parcel_land_use_fields"] == [
        "candidate_land_use_class",
        "current_land_use_class",
        "planned_land_use_class",
        "source_land_use_code",
    ]

    contract["parcel_land_use_fields"] = ["land_use_class"]
    validation = validate_geospatial_kernel_contract(contract)

    assert not validation["valid"]
    assert "parcel_land_use_fields_mismatch" in validation["errors"]


def test_contract_does_not_enable_learned_effects_without_calibration_evidence():
    contract = _valid_contract()
    contract["enabled_support_levels"] = [
        "deterministic_geometry",
        "authoritative_rule",
        "bounded_proxy",
        "learned_calibrated",
    ]
    contract["calibration_evidence_refs"] = []

    validation = validate_geospatial_kernel_contract(contract)

    assert not validation["valid"]
    assert "learned_calibrated_requires_calibration_evidence" in validation["errors"]

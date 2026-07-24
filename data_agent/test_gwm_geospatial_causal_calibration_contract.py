from copy import deepcopy

import pytest

from data_agent.test_uwm_geospatial_counterfactual_rollout import (
    _action,
    _dictionary,
    _graph,
    _matrix,
)
from data_agent.uwm.geospatial_kernel import (
    bind_causal_calibration_to_rollout,
    build_scca_causal_calibration_contract,
    validate_causal_calibration_contract,
)
from data_agent.uwm.geospatial_kernel.counterfactual_rollout import (
    run_counterfactual_rollout,
)


def _scca_report(*, coefficient: float = 0.31) -> dict:
    return {
        "schema": "territory_world_model.scca_causal_evidence_report.v1",
        "status": "pass",
        "algorithm": "SCCA",
        "role": "external_spatial_causal_evidence",
        "effect": {
            "coef": coefficient,
            "neighbor_exposure_coef": 0.08,
            "ci_lower": 0.12,
            "ci_upper": 0.50,
            "p_value": 0.02,
        },
        "balance": {
            "status": "available",
            "max_abs_standardized_mean_difference": 0.11,
        },
        "spatial_diagnostics": {
            "status": "available",
            "residual_moran_i": 0.09,
        },
        "credibility": {"evidence_grade": "bounded_support"},
        "evidence_gate": {"status": "pass", "passed": True},
    }


def _contract(*, coefficient: float = 0.31) -> dict:
    return build_scca_causal_calibration_contract(
        estimand={
            "unit": "parcel_and_mapped_neighbors",
            "treatment_action": "land_use_class_change",
            "outcome": "bounded_parcel_and_neighborhood_state",
            "treatment_time": "t1_post_change",
            "horizon": {"steps": 2, "unit": "kernel_stage"},
        },
        spatial_exposure_mapping={
            "direct_target": "intervention_action.parcel_id",
            "relation_types": [
                "parcel_adjacent_parcel",
                "parcel_contains_resource",
            ],
            "neighborhood_hops": 1,
            "mapping_version": "parcel-exposure-v1",
        },
        identification={
            "design": "observational_spatial_context_adjustment",
            "adjustment_set": ["baseline_land_use", "parcel_area", "spatial_context"],
            "overlap": {"status": "diagnosed_not_guaranteed"},
            "consistency": {"status": "assumption_not_empirically_proven"},
            "exchangeability_boundary": {
                "status": "conditional_on_observed_adjustment_set_only"
            },
            "interference_assumption": {
                "status": "sensitivity_only_not_formally_identified"
            },
            "time_varying_confounders": {
                "status": "not_supported",
                "required_future_method": "longitudinal_aipw_or_msm",
            },
        },
        scca_report=_scca_report(coefficient=coefficient),
        diagnostics={
            "balance": {"status": "pass"},
            "overlap": {"status": "review"},
            "placebo": {"status": "pass"},
            "negative_controls": {"status": "not_available"},
            "spatial_residual": {"status": "review"},
            "geographic_holdout": {"status": "not_available"},
            "temporal_placebo": {"status": "not_available"},
            "sensitivity": {"status": "bounded_support"},
        },
        provenance={
            "source_id": "paper6-scca-fixture",
            "source_artifact_hashes": {
                "credibility_report.json": "1" * 64,
            },
        },
    )


def _rollout_kwargs() -> dict:
    graph = _graph()
    return {
        "graph": graph,
        "intervention_action": _action(graph),
        "land_use_dictionary": _dictionary(),
        "transition_matrix": _matrix(),
        "alternative_land_use_class": "commercial",
    }


def test_missing_or_invalid_estimand_fails_closed():
    contract = _contract()
    contract["estimand"].pop("outcome")
    validation = validate_causal_calibration_contract(contract)

    assert validation["valid"] is False
    assert "estimand_outcome_required" in validation["errors"]

    invalid_horizon = _contract()
    invalid_horizon["estimand"]["horizon"] = 0
    validation = validate_causal_calibration_contract(invalid_horizon)
    assert "estimand_horizon_invalid" in validation["errors"]


def test_paper6_scca_bridge_is_diagnostic_only():
    contract = _contract()
    validation = validate_causal_calibration_contract(contract)

    assert validation["valid"] is True
    assert contract["readiness"] == {
        "diagnostic_ready": True,
        "diagnostic_readiness_basis": {
            "source_schema": "territory_world_model.scca_causal_evidence_report.v1",
            "algorithmic_causal_diagnostic_ready": False,
            "source_evidence_gate_passed": True,
            "source_scca_report_passed": True,
        },
        "observed_policy_outcome_ready": False,
        "longitudinal_causal_identification_ready": False,
        "spatiotemporal_interference_identification_ready": False,
        "effect_application_admitted": False,
    }
    assert contract["estimates"]["direct"]["identified"] is False
    assert contract["estimates"]["spillover"]["identified"] is False
    assert contract["claim_boundary"]["empirical_policy_effect_claim"] is False


def test_observed_policy_outcome_false_prevents_effect_application():
    contract = _contract()
    assert contract["readiness"]["observed_policy_outcome_ready"] is False
    assert contract["admission"]["effect_application_admitted"] is False

    tampered = deepcopy(contract)
    tampered["admission"]["effect_application_admitted"] = True
    validation = validate_causal_calibration_contract(tampered)
    assert validation["valid"] is False
    assert "admission_effect_application_admitted_must_be_false" in validation["errors"]

    error_pattern = (
        "causal_calibration_contract_invalid:"
        "admission_effect_application_admitted_must_be_false"
    )
    with pytest.raises(ValueError, match=error_pattern):
        bind_causal_calibration_to_rollout(
            rollout=run_counterfactual_rollout(**_rollout_kwargs()),
            causal_calibration_contract=tampered,
        )


def test_binding_preserves_trajectories_and_existing_deltas():
    kwargs = _rollout_kwargs()
    unbound = run_counterfactual_rollout(**kwargs)
    bound = run_counterfactual_rollout(
        **kwargs,
        causal_calibration_contract=_contract(),
    )

    for field in (
        "baseline",
        "intervention",
        "alternative",
        "direct_state_delta",
        "spillover_state_delta",
    ):
        assert bound[field] == unbound[field]
    attachment = bound["causal_calibration"]
    assert attachment["trajectory_modified"] is False
    assert attachment["effect_application_admitted"] is False
    assert attachment["effect_application_status"] == "blocked_diagnostic_only"
    assert bound["claim_boundary"] == unbound["claim_boundary"]


def test_causal_binding_is_deterministic_and_hash_bound():
    rollout = run_counterfactual_rollout(**_rollout_kwargs())
    first = bind_causal_calibration_to_rollout(
        rollout=rollout,
        causal_calibration_contract=_contract(),
    )
    second = bind_causal_calibration_to_rollout(
        rollout=rollout,
        causal_calibration_contract=_contract(),
    )

    assert first == second
    assert first["causal_calibration"]["contract_digest"] == _contract()[
        "contract_digest"
    ]

    changed = bind_causal_calibration_to_rollout(
        rollout=rollout,
        causal_calibration_contract=_contract(coefficient=0.32),
    )
    assert changed["causal_calibration"]["contract_digest"] != first[
        "causal_calibration"
    ]["contract_digest"]
    assert changed["causal_calibration"]["binding_digest"] != first[
        "causal_calibration"
    ]["binding_digest"]


def test_time_varying_confounders_and_interference_are_explicit():
    contract = _contract()
    identification = contract["identification"]

    assert identification["time_varying_confounders"]["status"] == "not_supported"
    assert (
        identification["interference_assumption"]["status"]
        == "sensitivity_only_not_formally_identified"
    )
    assert contract["spatial_exposure_mapping"]["neighborhood_hops"] == 1
    assert contract["diagnostics"]["temporal_placebo"]["status"] == "not_available"


def test_complete_contract_cannot_validate_general_gwm_or_k0():
    contract = _contract()
    validation = validate_causal_calibration_contract(contract)

    assert validation["valid"] is True
    assert validation["general_geospatial_kernel_validated"] is False
    assert validation["gwm_k0_validated"] is False

    overclaim = deepcopy(contract)
    overclaim["claim_boundary"]["general_geospatial_kernel_validated"] = True
    overclaim["claim_boundary"]["gwm_k0_validated"] = True
    validation = validate_causal_calibration_contract(overclaim)
    assert validation["valid"] is False
    assert (
        "claim_boundary_general_geospatial_kernel_validated_must_be_false"
        in validation["errors"]
    )
    assert "claim_boundary_gwm_k0_validated_must_be_false" in validation["errors"]


def test_provenance_identity_and_artifact_hashes_are_required():
    missing_identity = _contract()
    missing_identity["provenance"]["source_id"] = None
    validation = validate_causal_calibration_contract(missing_identity)
    assert validation["valid"] is False
    assert "provenance_source_id_required" in validation["errors"]

    invalid_hash = _contract()
    invalid_hash["provenance"]["source_artifact_hashes"][
        "credibility_report.json"
    ] = "not-a-sha256"
    validation = validate_causal_calibration_contract(invalid_hash)
    assert (
        "provenance_source_artifact_hash_invalid:credibility_report.json"
        in validation["errors"]
    )


def test_binding_rejects_a_tampered_existing_rollout_digest():
    rollout = run_counterfactual_rollout(**_rollout_kwargs())
    rollout["direct_state_delta"]["to_land_use_class"] = "tampered"

    with pytest.raises(
        ValueError,
        match="causal_calibration_rollout_digest_mismatch",
    ):
        bind_causal_calibration_to_rollout(
            rollout=rollout,
            causal_calibration_contract=_contract(),
        )


def test_no_contract_preserves_existing_counterfactual_output_exactly():
    kwargs = _rollout_kwargs()

    assert run_counterfactual_rollout(**kwargs) == run_counterfactual_rollout(
        **kwargs,
        causal_calibration_contract=None,
    )

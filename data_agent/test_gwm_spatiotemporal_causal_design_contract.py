from copy import deepcopy

import pytest

from data_agent.test_gwm_geospatial_causal_calibration_contract import (
    _contract as _scca_contract,
)
from data_agent.test_gwm_geospatial_causal_calibration_contract import (
    _rollout_kwargs,
)
from data_agent.uwm.geospatial_kernel import (
    LONGITUDINAL_DESIGN_GATES,
    LONGITUDINAL_ESTIMATION_GATES,
    bind_spatiotemporal_design_to_causal_calibration,
    build_spatiotemporal_causal_design_contract,
    validate_causal_calibration_contract,
    validate_spatiotemporal_causal_design_binding,
    validate_spatiotemporal_causal_design_contract,
)
from data_agent.uwm.geospatial_kernel.counterfactual_rollout import (
    run_counterfactual_rollout,
)


def _gate_evidence(*, design_ready: bool, estimation_ready: bool) -> dict:
    evidence = {}
    for gate_name in LONGITUDINAL_DESIGN_GATES:
        evidence[gate_name] = {
            "passed": design_ready,
            "evidence_refs": [f"evidence:design:{gate_name}"]
            if design_ready
            else [],
        }
    for gate_name in LONGITUDINAL_ESTIMATION_GATES:
        evidence[gate_name] = {
            "passed": estimation_ready,
            "evidence_refs": [f"evidence:estimation:{gate_name}"]
            if estimation_ready
            else [],
        }
    return evidence


def _design_contract(
    *,
    design_ready: bool = True,
    estimation_ready: bool = False,
    feedback: str = "present_measured",
    treatment_type: str = "time_varying_treatment",
    time_varying_confounders: list[str] | None = None,
    treatment_affected_confounders: list[str] | None = None,
) -> dict:
    if time_varying_confounders is None:
        time_varying_confounders = [
            "accessibility_t",
            "development_pressure_t",
        ]
    if treatment_affected_confounders is None:
        treatment_affected_confounders = ["development_pressure_t"]
    return build_spatiotemporal_causal_design_contract(
        study={
            "study_id": "gwm-longitudinal-fixture-v1",
            "domain_instance": "TWM_fixture",
            "unit_id_field": "parcel_id",
            "time_field": "observation_time",
            "timezone": "UTC",
            "cadence": "monthly",
            "observation_start": "2022-01-01T00:00:00Z",
            "observation_end": "2025-12-31T00:00:00Z",
        },
        estimand={
            "treatment_strategy": "sustained_land_use_policy_sequence",
            "outcome": "parcel_and_neighbor_state_at_horizon",
            "horizon": {"periods": 12, "unit": "month"},
            "contrast": "always_treat_versus_never_treat",
            "target_population": "eligible_parcels_with_observed_history",
        },
        panel_design={
            "treatment_type": treatment_type,
            "treatment_field": "policy_action_t",
            "outcome_field": "outcome_t_plus_1",
            "baseline_confounders": ["baseline_land_use", "parcel_area"],
            "time_varying_confounders": time_varying_confounders,
            "treatment_affected_confounders": treatment_affected_confounders,
            "treatment_confounder_feedback": feedback,
            "censoring_indicator": "panel_observed_t_plus_1",
            "missingness_strategy": "time_specific_inverse_probability_weights",
        },
        temporal_ordering={
            "confounder_measurement": "before_treatment_at_each_time",
            "treatment_measurement": "after_confounders_before_outcome",
            "outcome_measurement": "after_treatment",
            "lag_definition": "L_t_then_A_t_then_Y_t_plus_1",
            "pre_period_count": 12,
            "post_period_count": 12,
        },
        interference_mapping={
            "direct_exposure": "policy_action_t",
            "neighbor_exposure": "lagged_weighted_neighbor_policy_action_t",
            "relation_types": [
                "parcel_adjacent_parcel",
                "functional_compatibility",
            ],
            "neighborhood_hops": 1,
            "network_time_mode": "lagged_dynamic",
            "mapping_version": "dynamic-parcel-exposure-v1",
            "partial_interference_clusters": {
                "status": "declared",
                "cluster_field": "planning_district_id",
            },
            "exposure_history_window": {"periods": 3, "unit": "month"},
        },
        identification={
            "strategy": "marginal_structural_model_ipw",
            "sequential_exchangeability_boundary": {
                "status": "assumed_given_measured_history_only"
            },
            "positivity_boundary": {
                "status": "must_be_checked_at_every_treatment_time"
            },
            "consistency_boundary": {
                "status": "policy_versions_must_be_well_defined"
            },
            "interference_boundary": {
                "status": "exposure_mapping_and_partial_interference_required"
            },
        },
        gate_evidence=_gate_evidence(
            design_ready=design_ready,
            estimation_ready=estimation_ready,
        ),
        provenance={
            "source_bundle_id": "longitudinal-panel-fixture-v1",
            "source_bundle_schema": "gwm.test.longitudinal_panel.v1",
            "source_bundle_sha256": "2" * 64,
            "source_artifact_hashes": {"panel.parquet": "3" * 64},
        },
    )


def test_incomplete_evidence_is_valid_but_all_readiness_gates_stay_closed():
    contract = _design_contract(design_ready=False, estimation_ready=False)
    validation = validate_spatiotemporal_causal_design_contract(contract)

    assert validation["valid"] is True
    assert validation["longitudinal_design_ready"] is False
    assert validation["spatiotemporal_interference_design_ready"] is False
    assert validation["estimator_execution_ready"] is False
    assert validation["blocking_design_gates"] == list(LONGITUDINAL_DESIGN_GATES)
    assert validation["blocking_estimation_gates"] == list(
        LONGITUDINAL_ESTIMATION_GATES
    )


def test_design_evidence_does_not_substitute_for_estimator_execution():
    contract = _design_contract(design_ready=True, estimation_ready=False)
    validation = validate_spatiotemporal_causal_design_contract(contract)

    assert validation["valid"] is True
    assert validation["longitudinal_design_ready"] is True
    assert validation["spatiotemporal_interference_design_ready"] is True
    assert validation["estimator_execution_ready"] is False
    assert contract["admission"]["design_evidence_admitted"] is True
    assert contract["admission"]["estimator_evidence_admitted"] is False
    assert contract["admission"]["effect_application_admitted"] is False


def test_complete_synthetic_estimation_evidence_still_cannot_apply_effects_or_pass_k0():
    contract = _design_contract(design_ready=True, estimation_ready=True)
    validation = validate_spatiotemporal_causal_design_contract(contract)

    assert validation["valid"] is True
    assert validation["longitudinal_design_ready"] is True
    assert validation["estimator_execution_ready"] is True
    assert validation["observed_policy_outcome_ready"] is True
    assert validation["effect_application_admitted"] is False
    assert validation["general_geospatial_kernel_validated"] is False
    assert validation["gwm_k0_validated"] is False
    assert contract["claim_boundary"]["identified_policy_effect"] is False


def test_unresolved_treatment_confounder_feedback_blocks_design_noncompensatorily():
    contract = _design_contract(
        design_ready=True,
        estimation_ready=True,
        feedback="present_unmeasured",
    )
    validation = validate_spatiotemporal_causal_design_contract(contract)

    assert validation["valid"] is True
    assert validation["longitudinal_design_ready"] is False
    assert validation["estimator_execution_ready"] is False
    assert validation["structural_blockers"] == [
        "treatment_confounder_feedback_not_resolved"
    ]


def test_time_varying_treatment_requires_explicit_time_varying_confounders():
    contract = _design_contract()
    contract["panel_design"]["time_varying_confounders"] = []
    validation = validate_spatiotemporal_causal_design_contract(contract)

    assert validation["valid"] is False
    assert (
        "time_varying_treatment_requires_time_varying_confounders"
        in validation["errors"]
    )


def test_point_intervention_can_declare_no_time_varying_or_affected_confounders():
    contract = _design_contract(
        feedback="absent_by_design",
        treatment_type="point_intervention_with_longitudinal_outcomes",
        time_varying_confounders=[],
        treatment_affected_confounders=[],
    )
    validation = validate_spatiotemporal_causal_design_contract(contract)

    assert validation["valid"] is True
    assert validation["longitudinal_design_ready"] is True


def test_observation_window_must_be_chronologically_ordered():
    contract = _design_contract()
    contract["study"]["observation_start"] = "2026-01-01T00:00:00Z"
    contract["study"]["observation_end"] = "2025-01-01T00:00:00Z"
    validation = validate_spatiotemporal_causal_design_contract(contract)

    assert validation["valid"] is False
    assert "study_observation_window_invalid" in validation["errors"]


def test_design_contract_is_deterministic_and_hash_tampering_is_detected():
    first = _design_contract()
    second = _design_contract()
    assert first == second

    tampered = deepcopy(first)
    tampered["temporal_ordering"]["post_period_count"] = 24
    validation = validate_spatiotemporal_causal_design_contract(tampered)
    assert validation["valid"] is False
    assert "readiness_not_reproducible_from_contract" not in validation["errors"]
    assert "contract_digest_mismatch" in validation["errors"]


def test_longitudinal_design_binding_preserves_scca_fail_closed_boundaries():
    bound = bind_spatiotemporal_design_to_causal_calibration(
        causal_calibration_contract=_scca_contract(),
        spatiotemporal_design_contract=_design_contract(
            design_ready=True,
            estimation_ready=True,
        ),
    )
    validation = validate_causal_calibration_contract(bound)

    assert validation["valid"] is True
    assert bound["readiness"]["longitudinal_design_contract_ready"] is True
    assert bound["readiness"]["longitudinal_estimator_execution_ready"] is True
    assert bound["readiness"]["longitudinal_causal_identification_ready"] is False
    assert bound["readiness"]["observed_policy_outcome_ready"] is False
    assert bound["admission"]["effect_application_admitted"] is False
    assert validate_spatiotemporal_causal_design_binding(
        bound["spatiotemporal_causal_design"]
    ) == {"valid": True, "errors": []}


def test_bound_longitudinal_design_does_not_modify_rollout_trajectories():
    kwargs = _rollout_kwargs()
    baseline = run_counterfactual_rollout(**kwargs)
    causal_contract = bind_spatiotemporal_design_to_causal_calibration(
        causal_calibration_contract=_scca_contract(),
        spatiotemporal_design_contract=_design_contract(
            design_ready=True,
            estimation_ready=True,
        ),
    )
    result = run_counterfactual_rollout(
        **kwargs,
        causal_calibration_contract=causal_contract,
    )

    for field in (
        "baseline",
        "intervention",
        "alternative",
        "direct_state_delta",
        "spillover_state_delta",
    ):
        assert result[field] == baseline[field]
    attached = result["causal_calibration"]["contract"]
    assert attached["spatiotemporal_causal_design"][
        "effect_application_admitted"
    ] is False
    assert result["causal_calibration"]["trajectory_modified"] is False


def test_invalid_longitudinal_design_cannot_bind_to_causal_calibration():
    invalid = _design_contract()
    invalid["panel_design"].pop("treatment_field")

    with pytest.raises(
        ValueError,
        match=(
            "spatiotemporal_causal_design_contract_invalid:"
            "panel_design_treatment_field_required"
        ),
    ):
        bind_spatiotemporal_design_to_causal_calibration(
            causal_calibration_contract=_scca_contract(),
            spatiotemporal_design_contract=invalid,
        )

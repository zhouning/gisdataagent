"""Spatial causal question and estimand contracts for UWM livability actions."""

from __future__ import annotations

from typing import Any


UWM_SPATIAL_CAUSAL_QUESTION_REGISTRY_SCHEMA = (
    "uwm.spatial_causal_question_registry.v1"
)

SUPPORTED_CURRENT_ACTION_ORDER = [
    "increase_green_infrastructure",
    "traffic_emission_control",
    "add_community_service",
]

DEFAULT_REQUIRED_AUTHORITATIVE_TABLES = [
    "policy_project_history",
    "action_constraint_cost_model",
    "observed_outcome_validation_panel",
    "causal_effect_calibration_panel",
    "human_governance_review_log",
]

_QUESTION_TEMPLATES: dict[str, dict[str, Any]] = {
    "increase_green_infrastructure": {
        "question_id": "uwm-cq-green-heat-livability",
        "causal_query": (
            "P(heat_risk, livability | do(increase_green_infrastructure), spatial_context)"
        ),
        "outcomes": {
            "primary_outcome": "heat_risk",
            "secondary_outcomes": [
                "livability",
                "equity",
                "air_pollution_exposure",
            ],
            "expected_direction": {
                "heat_risk": "decrease",
                "livability": "increase",
                "equity": "non_decrease",
            },
        },
        "adjustment_set": {
            "confounders": [
                "baseline_heat_risk",
                "baseline_green_access",
                "building_density",
                "population_density_proxy",
                "impervious_surface_proxy",
                "baseline_service_accessibility",
                "topography",
            ],
            "spatial_confounders": [
                "neighbor_heat_risk",
                "neighbor_green_access",
                "geographic_similarity_cluster",
            ],
            "colliders_to_avoid": [
                "planner_priority_rank",
                "post_action_livability_score",
            ],
        },
        "mechanism_path": {
            "mediators": [
                "green_accessibility_change",
                "surface_cooling_change",
                "neighbor_spillover_cooling",
            ],
            "scm_edges": [
                ["increase_green_infrastructure", "green_accessibility_change"],
                ["green_accessibility_change", "surface_cooling_change"],
                ["surface_cooling_change", "heat_risk"],
                ["heat_risk", "livability"],
                ["neighbor_spillover_cooling", "neighbor_heat_risk"],
            ],
        },
    },
    "traffic_emission_control": {
        "question_id": "uwm-cq-traffic-air-livability",
        "causal_query": (
            "P(air_pollution_exposure, livability | do(traffic_emission_control), spatial_context)"
        ),
        "outcomes": {
            "primary_outcome": "air_pollution_exposure",
            "secondary_outcomes": [
                "livability",
                "heat_risk",
                "equity",
            ],
            "expected_direction": {
                "air_pollution_exposure": "decrease",
                "livability": "increase",
                "equity": "non_decrease",
            },
        },
        "adjustment_set": {
            "confounders": [
                "baseline_air_pollution_exposure",
                "road_density",
                "traffic_activity_proxy",
                "population_density_proxy",
                "building_density",
                "meteorology",
                "topography",
            ],
            "spatial_confounders": [
                "neighbor_air_pollution_exposure",
                "upwind_or_regional_background_proxy",
                "geographic_similarity_cluster",
            ],
            "colliders_to_avoid": [
                "planner_priority_rank",
                "post_action_air_quality_score",
            ],
        },
        "mechanism_path": {
            "mediators": [
                "traffic_emission_intensity_change",
                "road_exposure_change",
                "neighbor_air_spillover_change",
            ],
            "scm_edges": [
                ["traffic_emission_control", "traffic_emission_intensity_change"],
                ["traffic_emission_intensity_change", "air_pollution_exposure"],
                ["meteorology", "air_pollution_exposure"],
                ["air_pollution_exposure", "livability"],
                ["neighbor_air_spillover_change", "neighbor_air_pollution_exposure"],
            ],
        },
    },
    "add_community_service": {
        "question_id": "uwm-cq-service-equity-livability",
        "causal_query": (
            "P(service_accessibility, livability | do(add_community_service), spatial_context)"
        ),
        "outcomes": {
            "primary_outcome": "service_accessibility",
            "secondary_outcomes": [
                "livability",
                "equity",
                "population_served",
            ],
            "expected_direction": {
                "service_accessibility": "increase",
                "livability": "increase",
                "equity": "increase",
            },
        },
        "adjustment_set": {
            "confounders": [
                "baseline_service_accessibility",
                "population_need",
                "population_density_proxy",
                "road_accessibility",
                "existing_service_capacity_proxy",
                "urban_density",
                "land_availability_proxy",
            ],
            "spatial_confounders": [
                "neighbor_service_accessibility",
                "neighbor_population_need",
                "geographic_similarity_cluster",
            ],
            "colliders_to_avoid": [
                "planner_priority_rank",
                "post_action_service_score",
            ],
        },
        "mechanism_path": {
            "mediators": [
                "service_capacity_change",
                "travel_impedance_change",
                "neighbor_service_spillover",
            ],
            "scm_edges": [
                ["add_community_service", "service_capacity_change"],
                ["service_capacity_change", "service_accessibility"],
                ["road_accessibility", "service_accessibility"],
                ["service_accessibility", "livability"],
                ["neighbor_service_spillover", "neighbor_service_accessibility"],
            ],
        },
    },
}


def build_uwm_spatial_causal_question_registry(
    *,
    registry_id: str,
    created_at: str,
    production_action_catalog: dict[str, Any],
    governance_data_contract: dict[str, Any],
    causal_policy_evidence_gate: dict[str, Any],
    data_foundation_evidence_gate: dict[str, Any],
) -> dict[str, Any]:
    """Build claim-safe causal question contracts for current UWM actions."""

    action_contracts = {
        str(contract.get("action_type")): contract
        for contract in production_action_catalog.get("action_type_contracts") or []
        if isinstance(contract, dict)
    }
    bound_action_types = [
        action_type
        for action_type in SUPPORTED_CURRENT_ACTION_ORDER
        if _is_currently_bound(action_contracts.get(action_type) or {})
    ]
    required_tables = _required_table_ids(governance_data_contract)
    ready_table_count = _int(
        (governance_data_contract.get("summary") or {}).get(
            "ready_governance_table_count"
        )
    )
    observed_outcome_ready = bool(
        governance_data_contract.get("observed_outcome_panel_ready")
    )
    causal_calibration_ready = bool(
        governance_data_contract.get("causal_effect_calibration_ready")
    )
    algorithmic_causal_ready = bool(
        causal_policy_evidence_gate.get("algorithmic_causal_diagnostic_ready")
    )
    question_contracts = [
        _question_contract(
            action_type=action_type,
            action_contract=action_contracts.get(action_type) or {},
            required_tables=required_tables,
            algorithmic_causal_ready=algorithmic_causal_ready,
            observed_outcome_ready=observed_outcome_ready,
            causal_calibration_ready=causal_calibration_ready,
        )
        for action_type in bound_action_types
    ]
    identified_count = sum(
        1
        for question in question_contracts
        if (question.get("identification") or {}).get("status") == "identified"
    )
    underidentified_count = sum(
        1
        for question in question_contracts
        if (question.get("identification") or {}).get("status")
        == "underidentified_for_observed_policy_effect"
    )
    action_summary = production_action_catalog.get("summary") or {}
    foundation_scope = data_foundation_evidence_gate.get("data_foundation_scope") or {}
    return {
        "schema": UWM_SPATIAL_CAUSAL_QUESTION_REGISTRY_SCHEMA,
        "registry_id": registry_id,
        "created_at": created_at,
        "experiment_scope": "full_admin_graph",
        "source_artifacts": {
            "production_action_catalog_schema": production_action_catalog.get(
                "schema"
            ),
            "governance_data_contract_schema": governance_data_contract.get(
                "schema"
            ),
            "causal_policy_evidence_gate_schema": causal_policy_evidence_gate.get(
                "schema"
            ),
            "data_foundation_evidence_gate_schema": data_foundation_evidence_gate.get(
                "schema"
            ),
        },
        "registry_ready": True,
        "algorithmic_causal_diagnostic_ready": algorithmic_causal_ready,
        "observed_outcome_panel_ready": observed_outcome_ready,
        "causal_effect_calibration_ready": causal_calibration_ready,
        "planner_governance_binding_ready": False,
        "summary": {
            "production_action_type_count": _int(
                action_summary.get("production_action_type_count")
            ),
            "currently_bound_action_type_count": _int(
                action_summary.get("currently_bound_action_type_count")
            ),
            "currently_bound_feasible_action_count": _int(
                action_summary.get("currently_bound_feasible_action_count")
            ),
            "active_causal_question_count": len(question_contracts),
            "authoritative_required_table_count": len(required_tables),
            "ready_authoritative_table_count": ready_table_count,
            "identified_policy_effect_question_count": identified_count,
            "underidentified_policy_effect_question_count": underidentified_count,
            "manifest_row_count": _int(foundation_scope.get("manifest_row_count")),
        },
        "causal_question_contracts": question_contracts,
        "estimand_registry_policy": {
            "estimand_language_required": True,
            "treat_P_y_given_x_as_policy_effect": False,
            "require_do_query_for_policy_claim": True,
            "require_identification_before_observed_policy_claim": True,
            "require_project_linkage_before_planner_governance_binding": True,
        },
        "supported_claim": (
            "spatial_causal_question_contracts_define_do_queries_and_block_policy_overclaims"
        ),
        "claim_boundary": {
            "max_claim_level": "spatial_causal_question_contract_only",
            "policy_outcome_claim": False,
            "reason": (
                "The registry turns current UWM actions into explicit spatial "
                "causal questions and estimand contracts. Existing data support "
                "algorithmic causal diagnostics and conditional simulation, but "
                "not observed policy-effect identification."
            ),
        },
        "remaining_gates": [
            "authoritative_policy_project_history_required",
            "action_constraint_cost_model_required",
            "observed_policy_outcome_validation_panel_required",
            "causal_effect_calibration_panel_required",
            "human_governance_review_log_required",
        ],
        "limitations": [
            "no_authoritative_policy_project_history_rows",
            "no_observed_post_intervention_outcome_panel",
            "current_do_queries_are_conditional_simulation_contracts",
            "paper6_scca_is_algorithmic_diagnostic_not_uwm_policy_outcome",
        ],
        "production_readiness_claim": False,
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
    }


def validate_uwm_spatial_causal_question_registry(
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Validate claim-safety and minimum causal-contract invariants."""

    errors: list[str] = []
    if payload.get("schema") != UWM_SPATIAL_CAUSAL_QUESTION_REGISTRY_SCHEMA:
        errors.append("schema_mismatch")
    if payload.get("observed_policy_outcome_superiority_claim") is not False:
        errors.append("observed_policy_outcome_superiority_claim_must_be_false")
    if payload.get("empirical_superiority_claim") is not False:
        errors.append("empirical_superiority_claim_must_be_false")
    if payload.get("production_readiness_claim") is not False:
        errors.append("production_readiness_claim_must_be_false")
    observed_outcome_ready = bool(payload.get("observed_outcome_panel_ready"))
    causal_calibration_ready = bool(payload.get("causal_effect_calibration_ready"))
    for question in payload.get("causal_question_contracts") or []:
        if not isinstance(question, dict):
            errors.append("question_contract_must_be_object")
            continue
        if question.get("policy_outcome_claim_allowed") is not False:
            errors.append("question_policy_outcome_claim_must_be_false")
        if not str(question.get("causal_query") or "").startswith("P("):
            errors.append("question_causal_query_required")
        if "do(" not in str(question.get("causal_query") or ""):
            errors.append("question_do_query_required")
        if question.get("required_authoritative_tables") != DEFAULT_REQUIRED_AUTHORITATIVE_TABLES:
            errors.append("question_required_authoritative_tables_mismatch")
        identification = question.get("identification") or {}
        if (
            identification.get("status") == "identified"
            and not (observed_outcome_ready and causal_calibration_ready)
        ):
            errors.append("identified_status_requires_observed_outcome_and_calibration")
        estimand = question.get("estimand_contract") or {}
        if estimand.get("observational_shortcut_allowed") is not False:
            errors.append("observational_shortcut_must_be_false")
    return {"valid": not errors, "errors": errors}


def _question_contract(
    *,
    action_type: str,
    action_contract: dict[str, Any],
    required_tables: list[str],
    algorithmic_causal_ready: bool,
    observed_outcome_ready: bool,
    causal_calibration_ready: bool,
) -> dict[str, Any]:
    template = _QUESTION_TEMPLATES[action_type]
    identified = observed_outcome_ready and causal_calibration_ready
    return {
        "question_id": template["question_id"],
        "query_type": "intervention_effect",
        "action_type": action_type,
        "causal_query": template["causal_query"],
        "treatment": {
            "variable": "policy_action",
            "action_type": action_type,
            "target_unit_type": "admin_unit",
            "current_feasible_action_count": _int(
                action_contract.get("current_feasible_action_count")
            ),
            "current_binding_status": str(
                action_contract.get("current_binding_status")
                or "production_target_unbound"
            ),
        },
        "outcomes": template["outcomes"],
        "adjustment_set": template["adjustment_set"],
        "mechanism_path": template["mechanism_path"],
        "estimand_contract": {
            "target_estimand": "ATT_on_eligible_admin_units",
            "formal_question": (
                "E[Y(do(action)) - Y(do(no_action)) | eligible spatial units, "
                "spatial context, governance constraints]"
            ),
            "unit_of_analysis": "full_admin_graph_admin_unit",
            "time_horizon": "action_rollout_horizon",
            "counterfactual_baseline": "do(no_action_or_static_baseline)",
            "observational_shortcut_allowed": False,
            "requires_backdoor_or_spatial_adjustment_set": True,
            "requires_interference_diagnostics": True,
        },
        "identification": {
            "status": (
                "identified"
                if identified
                else "underidentified_for_observed_policy_effect"
            ),
            "algorithmic_causal_diagnostic_ready": algorithmic_causal_ready,
            "observed_outcome_panel_ready": observed_outcome_ready,
            "causal_effect_calibration_ready": causal_calibration_ready,
            "allowed_current_query_level": (
                "identified_observed_policy_effect"
                if identified
                else "conditional_simulation_with_algorithmic_causal_diagnostic"
            ),
            "blocked_reason": (
                None
                if identified
                else "missing_authoritative_policy_history_outcome_and_causal_calibration"
            ),
        },
        "required_authoritative_tables": list(required_tables),
        "testable_implications": [
            "pre_action_balance_or_overlap_required",
            "placebo_pretrend_or_preperiod_stability_required",
            "negative_control_no_effect_on_unrelated_outcome",
            "spatial_autocorrelation_residual_diagnostic_required",
            "neighbor_or_similarity_spillover_sensitivity_required",
        ],
        "policy_outcome_claim_allowed": False,
        "claim_level": "conditional_simulation_contract",
    }


def _required_table_ids(governance_data_contract: dict[str, Any]) -> list[str]:
    table_ids = [
        str(table.get("table_id"))
        for table in governance_data_contract.get("required_tables") or []
        if isinstance(table, dict) and table.get("table_id")
    ]
    return table_ids or list(DEFAULT_REQUIRED_AUTHORITATIVE_TABLES)


def _is_currently_bound(action_contract: dict[str, Any]) -> bool:
    return (
        action_contract.get("current_binding_status") == "implemented_bounded_support"
        and _int(action_contract.get("current_feasible_action_count")) > 0
    )


def _int(value: Any) -> int:
    try:
        if value is None or value == "":
            return 0
        return int(float(value))
    except (TypeError, ValueError):
        return 0

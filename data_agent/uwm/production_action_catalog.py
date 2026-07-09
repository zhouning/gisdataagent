"""Production action catalog contract for UWM livability planning."""

from __future__ import annotations

from typing import Any

from .production_state_action_space import PRODUCTION_ACTION_FAMILY_SPECS


UWM_PRODUCTION_ACTION_CATALOG_SCHEMA = "uwm.production_action_catalog.v1"

REQUIRED_PARAMETER_FIELDS = [
    "target_geometry",
    "intensity",
    "capacity_change",
    "budget_cost",
    "implementation_time",
    "maintenance_cost",
    "responsible_department",
    "legal_feasibility",
    "land_constraint",
    "population_served",
    "expected_mechanism",
    "uncertainty",
    "evidence_level",
]

REQUIRED_EVIDENCE_LAYERS = [
    "state_variable_support",
    "constraint_cost_model",
    "historical_policy_project_log",
    "observed_outcome_panel",
    "causal_effect_calibration",
    "human_governance_review",
]

FAMILY_PLANNER_EVIDENCE_REQUIREMENTS = {
    "blue_green_heat_mitigation": [
        "green_blue_asset_inventory_required",
        "land_availability_and_maintenance_cost_required",
        "heat_exposure_effect_calibration_required",
    ],
    "air_quality_traffic_emissions": [
        "traffic_flow_and_emission_inventory_required",
        "traffic_control_legal_feasibility_required",
        "air_quality_effect_calibration_required",
    ],
    "community_service_capacity": [
        "authoritative_service_capacity_inventory_required",
        "operation_budget_and_staffing_required",
        "service_access_outcome_calibration_required",
    ],
    "mobility_accessibility": [
        "transit_authoritative_route_and_frequency_required",
        "walking_cycling_network_quality_required",
        "observed_travel_time_or_validated_assignment_required",
    ],
    "urban_renewal_built_environment": [
        "parcel_building_project_inventory_required",
        "renewal_budget_schedule_and_ownership_required",
        "built_environment_outcome_calibration_required",
    ],
    "housing_equity_policy": [
        "housing_supply_and_affordability_inventory_required",
        "vulnerable_population_targeting_required",
        "housing_policy_outcome_calibration_required",
    ],
    "planning_controls": [
        "statutory_planning_control_required",
        "approval_authority_and_legal_basis_required",
        "development_response_outcome_calibration_required",
    ],
    "resilience_emergency": [
        "hazard_exposure_and_emergency_asset_inventory_required",
        "emergency_response_capacity_required",
        "resilience_outcome_calibration_required",
    ],
}

ACTION_SPECIFIC_EVIDENCE_REQUIREMENTS = {
    "bus_route_adjustment": [
        "transit_authoritative_route_and_frequency_required",
    ],
    "bus_frequency_increase": [
        "transit_authoritative_route_and_frequency_required",
    ],
    "new_bus_stop": [
        "transit_authoritative_stop_inventory_required",
    ],
    "floor_area_ratio_control": [
        "statutory_planning_control_required",
    ],
    "land_use_adjustment": [
        "statutory_planning_control_required",
    ],
    "project_approval_condition": [
        "approval_authority_and_legal_basis_required",
    ],
}


def build_uwm_production_action_catalog(
    *,
    catalog_id: str,
    created_at: str,
    production_state_action_space_assessment: dict[str, Any],
    full_admin_action_inventory: dict[str, Any],
) -> dict[str, Any]:
    """Build an extendable production action contract from current UWM evidence."""

    assessment_action_space = (
        production_state_action_space_assessment.get("current_action_space") or {}
    )
    inventory_summary = full_admin_action_inventory.get("summary") or {}
    current_counts = dict(
        inventory_summary.get("action_type_counts")
        or assessment_action_space.get("action_type_counts")
        or {}
    )
    action_type_definitions = dict(
        full_admin_action_inventory.get("action_type_definitions") or {}
    )
    action_type_contracts = _action_type_contracts(
        current_counts=current_counts,
        action_type_definitions=action_type_definitions,
    )
    current_bindings = _current_candidate_bindings(
        full_admin_action_inventory,
        contracts_by_type={
            contract["action_type"]: contract for contract in action_type_contracts
        },
    )
    production_action_type_count = len(action_type_contracts)
    currently_bound_action_types = sorted(
        action_type for action_type, count in current_counts.items() if _int(count) > 0
    )
    currently_bound_feasible_action_count = len(current_bindings)
    return {
        "schema": UWM_PRODUCTION_ACTION_CATALOG_SCHEMA,
        "catalog_id": catalog_id,
        "created_at": created_at,
        "experiment_scope": "full_admin_graph",
        "source_artifacts": {
            "production_state_action_space_assessment_schema": (
                production_state_action_space_assessment.get("schema")
            ),
            "full_admin_action_inventory_schema": full_admin_action_inventory.get(
                "schema"
            ),
        },
        "action_catalog_contract_ready": True,
        "future_authoritative_data_extension_ready": True,
        "current_planner_binding_ready": (
            currently_bound_feasible_action_count
            == _int(inventory_summary.get("available_action_count"))
            and set(currently_bound_action_types)
            == {
                "add_community_service",
                "increase_green_infrastructure",
                "traffic_emission_control",
            }
        ),
        "planner_production_action_ready": False,
        "policy_project_history_ready": False,
        "constraint_cost_model_ready": False,
        "observed_policy_outcome_panel_ready": False,
        "required_parameter_fields": list(REQUIRED_PARAMETER_FIELDS),
        "required_evidence_layers": list(REQUIRED_EVIDENCE_LAYERS),
        "summary": {
            "production_action_family_count": len(PRODUCTION_ACTION_FAMILY_SPECS),
            "production_action_type_count": production_action_type_count,
            "currently_bound_action_type_count": len(currently_bound_action_types),
            "currently_bound_action_types": currently_bound_action_types,
            "currently_bound_feasible_action_count": (
                currently_bound_feasible_action_count
            ),
            "unbound_production_action_type_count": (
                production_action_type_count - len(currently_bound_action_types)
            ),
            "raw_candidate_action_count": _int(
                inventory_summary.get("candidate_action_mask_trace_count")
            ),
            "current_feasible_action_counts": current_counts,
        },
        "action_family_contracts": _action_family_contracts(current_counts),
        "action_type_contracts": action_type_contracts,
        "current_candidate_bindings": current_bindings,
        "future_data_ingestion_contract": {
            "schema_evolution_rule": "versioned_additive_no_rewrite",
            "adapter_slots": [
                "authoritative_state_layer_adapter",
                "planning_constraint_adapter",
                "budget_cost_adapter",
                "policy_project_history_adapter",
                "observed_outcome_panel_adapter",
                "causal_effect_calibration_adapter",
            ],
            "planner_binding_gates": [
                "validate_action_contract_before_planner_binding",
                "require_constraint_cost_model_for_parameterized_action",
                "require_policy_history_or_authorized_scenario_source",
                "require_observed_outcome_or_causal_calibration_for_effect_claim",
                "keep_unbound_actions_out_of_planner_search",
            ],
        },
        "supported_claim": (
            "production_action_catalog_contract_binds_current_full_admin_actions_and_blocks_unverified_targets"
        ),
        "claim_boundary": {
            "max_claim_level": "contract_and_current_bounded_action_binding",
            "reason": (
                "The catalog defines the production action interface and binds "
                "current full-admin Graph-MDP candidates to implemented action "
                "types. It is not a project approval, not a cost model, not a "
                "historical intervention log and not observed outcome evidence."
            ),
        },
        "production_readiness_claim": False,
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
        "limitations": [
            "current_bindings_cover_only_three_abstract_single_unit_action_types",
            "unbound_production_action_types_are_not_allowed_in_planner_search",
            "parameter_cost_constraint_and_observed_outcome_fields_require_authoritative_data",
        ],
    }


def _action_family_contracts(
    current_counts: dict[str, Any],
) -> list[dict[str, Any]]:
    family_contracts = []
    for family in PRODUCTION_ACTION_FAMILY_SPECS:
        required_action_types = list(family["required_action_types"])
        implemented_action_types = [
            action_type
            for action_type in required_action_types
            if _int(current_counts.get(action_type)) > 0
        ]
        family_contracts.append(
            {
                "family_id": family["family_id"],
                "business_role": family["business_role"],
                "required_action_types": required_action_types,
                "currently_bound_action_types": implemented_action_types,
                "unbound_action_types": [
                    action_type
                    for action_type in required_action_types
                    if action_type not in implemented_action_types
                ],
                "required_evidence_for_planner_binding": (
                    FAMILY_PLANNER_EVIDENCE_REQUIREMENTS.get(family["family_id"])
                    or list(REQUIRED_EVIDENCE_LAYERS)
                ),
            }
        )
    return family_contracts


def _action_type_contracts(
    *,
    current_counts: dict[str, Any],
    action_type_definitions: dict[str, Any],
) -> list[dict[str, Any]]:
    contracts = []
    for family in PRODUCTION_ACTION_FAMILY_SPECS:
        family_id = str(family["family_id"])
        for action_type in family["required_action_types"]:
            count = _int(current_counts.get(action_type))
            implemented = count > 0
            definition = action_type_definitions.get(action_type) or {}
            contracts.append(
                {
                    "action_type": action_type,
                    "family_id": family_id,
                    "business_role": family["business_role"],
                    "current_binding_status": (
                        "implemented_bounded_support"
                        if implemented
                        else "production_target_unbound"
                    ),
                    "planner_binding_level": (
                        "bounded_abstract_single_unit"
                        if implemented
                        else "not_bound_to_planner"
                    ),
                    "current_feasible_action_count": count,
                    "required_parameter_fields": list(REQUIRED_PARAMETER_FIELDS),
                    "required_evidence_layers": list(REQUIRED_EVIDENCE_LAYERS),
                    "existing_state_trigger": definition.get("state_trigger"),
                    "expected_primary_effect": definition.get(
                        "expected_primary_effect"
                    ),
                    "missing_evidence_for_planner": (
                        []
                        if implemented
                        else _missing_evidence_for_action_type(family_id, action_type)
                    ),
                    "planner_search_allowed_now": implemented,
                    "historical_policy_log_claim": False,
                    "observed_policy_outcome_claim": False,
                }
            )
    return contracts


def _current_candidate_bindings(
    inventory: dict[str, Any],
    *,
    contracts_by_type: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    bindings = []
    for action in inventory.get("actions") or []:
        if not isinstance(action, dict):
            continue
        action_type = str(action.get("action_type"))
        contract = contracts_by_type.get(action_type) or {}
        bindings.append(
            {
                "source_action_id": str(action.get("action_id")),
                "action_type": action_type,
                "target_unit_id": str(action.get("target_unit_id")),
                "target_geometry_level": "admin_unit",
                "intensity": _float(action.get("intensity"), default=1.0),
                "catalog_binding_status": str(
                    contract.get("current_binding_status")
                    or "production_target_unbound"
                ),
                "planner_binding_level": str(
                    contract.get("planner_binding_level") or "not_bound_to_planner"
                ),
                "evidence_level": "full_admin_graph_mdp_threshold_mask",
            }
        )
    return bindings


def _missing_evidence_for_action_type(
    family_id: str,
    action_type: str,
) -> list[str]:
    requirements = []
    requirements.extend(ACTION_SPECIFIC_EVIDENCE_REQUIREMENTS.get(action_type) or [])
    for item in FAMILY_PLANNER_EVIDENCE_REQUIREMENTS.get(family_id) or []:
        if item not in requirements:
            requirements.append(item)
    for layer in REQUIRED_EVIDENCE_LAYERS:
        if layer not in requirements:
            requirements.append(layer)
    return requirements


def _int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return int(default)
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return round(float(value), 9)
    except (TypeError, ValueError):
        return float(default)

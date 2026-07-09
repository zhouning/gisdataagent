"""Production state/action space gap assessment for UWM livability."""

from __future__ import annotations

from typing import Any


UWM_PRODUCTION_STATE_ACTION_SPACE_ASSESSMENT_SCHEMA = (
    "uwm.production_state_action_space_assessment.v1"
)

CORE_NODE_STATE_VARIABLES = [
    "heat_risk",
    "air_pollution_exposure",
    "service_accessibility",
    "equity",
    "livability",
]

PRODUCTION_ACTION_FAMILY_SPECS = [
    {
        "family_id": "blue_green_heat_mitigation",
        "business_role": "mitigate heat exposure and increase adaptive capacity",
        "implemented_action_types": ["increase_green_infrastructure"],
        "required_action_types": [
            "increase_green_infrastructure",
            "street_tree_canopy",
            "pocket_park",
            "blue_green_corridor",
            "cool_roof_retrofit",
            "permeable_surface",
            "shading_facility",
            "sponge_city_facility",
        ],
    },
    {
        "family_id": "air_quality_traffic_emissions",
        "business_role": "reduce traffic and point-source air pollution exposure",
        "implemented_action_types": ["traffic_emission_control"],
        "required_action_types": [
            "traffic_emission_control",
            "low_emission_zone",
            "freight_restriction",
            "bus_priority",
            "parking_demand_management",
            "road_speed_management",
            "signal_optimization",
            "pollution_source_control",
            "charging_facility_deployment",
        ],
    },
    {
        "family_id": "community_service_capacity",
        "business_role": "improve service accessibility and capacity for underserved units",
        "implemented_action_types": ["add_community_service"],
        "required_action_types": [
            "add_community_service",
            "community_health_service",
            "elderly_care_service",
            "childcare_service",
            "cultural_sports_service",
            "community_canteen",
            "convenience_retail_service",
            "park_service_capacity",
        ],
    },
    {
        "family_id": "mobility_accessibility",
        "business_role": "improve public transport, walking, cycling and barrier-free access",
        "implemented_action_types": [],
        "required_action_types": [
            "new_bus_stop",
            "bus_route_adjustment",
            "bus_frequency_increase",
            "walking_connection",
            "safe_crossing",
            "bike_lane",
            "barrier_free_retrofit",
            "street_microcirculation",
        ],
    },
    {
        "family_id": "urban_renewal_built_environment",
        "business_role": "upgrade old communities, public space and inefficient urban land",
        "implemented_action_types": [],
        "required_action_types": [
            "old_community_retrofit",
            "building_energy_retrofit",
            "public_space_upgrade",
            "street_section_optimization",
            "mixed_use_adjustment",
            "inefficient_land_redevelopment",
            "micro_renewal_project",
        ],
    },
    {
        "family_id": "housing_equity_policy",
        "business_role": "improve housing affordability and vulnerable-group services",
        "implemented_action_types": [],
        "required_action_types": [
            "affordable_housing_supply",
            "rental_housing_supply",
            "community_care_service",
            "elderly_friendly_retrofit",
            "child_friendly_facility",
        ],
    },
    {
        "family_id": "planning_controls",
        "business_role": "encode land-use, development timing, legal and approval constraints",
        "implemented_action_types": [],
        "required_action_types": [
            "land_use_adjustment",
            "floor_area_ratio_control",
            "development_timing_control",
            "heritage_or_redline_protection",
            "urban_renewal_unit_designation",
            "project_approval_condition",
            "defer_or_replace_project",
        ],
    },
    {
        "family_id": "resilience_emergency",
        "business_role": "support climate adaptation, emergency services and risk response",
        "implemented_action_types": [],
        "required_action_types": [
            "cooling_center",
            "emergency_water_supply",
            "extreme_weather_response",
            "flood_resilience_facility",
            "vulnerable_group_alert_service",
        ],
    },
]


def build_uwm_production_state_action_space_assessment(
    *,
    assessment_id: str,
    created_at: str,
    data_foundation_evidence_gate: dict[str, Any],
    full_admin_action_inventory: dict[str, Any],
    full_admin_livability_decision_package: dict[str, Any],
) -> dict[str, Any]:
    """Build a claim-safe assessment of production state/action space gaps."""

    current_scope = _current_implemented_scope(
        data_foundation_evidence_gate,
        full_admin_action_inventory,
        full_admin_livability_decision_package,
    )
    state_layers = _production_state_layers(
        data_foundation_evidence_gate,
        full_admin_livability_decision_package,
        current_scope,
    )
    action_space = _current_action_space(full_admin_action_inventory)
    action_families = _production_action_families()
    implemented_family_count = len(
        [
            family
            for family in action_families
            if family["implemented_action_types"]
        ]
    )
    missing_family_count = len(action_families) - implemented_family_count
    production_action_type_target_count = len(
        {
            action_type
            for family in action_families
            for action_type in family["required_action_types"]
        }
    )
    implemented_action_type_count = max(
        1, _int(action_space.get("implemented_action_type_count"))
    )
    return {
        "schema": UWM_PRODUCTION_STATE_ACTION_SPACE_ASSESSMENT_SCHEMA,
        "assessment_id": assessment_id,
        "created_at": created_at,
        "experiment_scope": "full_admin_graph",
        "current_implemented_scope": current_scope,
        "production_state_layers": state_layers,
        "current_action_space": action_space,
        "production_action_families": action_families,
        "production_action_type_target_count": production_action_type_target_count,
        "implemented_action_family_count": implemented_family_count,
        "missing_action_family_count": missing_family_count,
        "action_space_expansion_factor_vs_current_types": round(
            production_action_type_target_count / implemented_action_type_count,
            6,
        ),
        "production_gap_summary": {
            "state_space_blocking_gap_count": len(
                [
                    layer
                    for layer in state_layers
                    if layer.get("production_blocking_gap") is True
                ]
            ),
            "action_space_blocking_gap_count": missing_family_count,
            "parameterized_action_model_ready": False,
            "constraint_cost_model_ready": False,
            "policy_project_history_ready": False,
            "causal_effect_calibration_ready": False,
        },
        "next_required_artifacts": [
            "production_state_ontology_required",
            "parameterized_action_catalog_required",
            "policy_project_history_schema_required",
            "constraint_and_cost_model_required",
            "causal_effect_calibration_layer_required",
            "observed_intervention_outcome_panel_required",
            "human_review_workflow_required",
        ],
        "supported_claim": (
            "production_state_action_space_gap_assessment_uses_full_admin_real_data_scope"
        ),
        "claim_boundary": {
            "max_claim_level": "gap_analysis_only",
            "reason": (
                "This assessment maps current full-admin UWM evidence to a "
                "production target ontology. It is not a production readiness "
                "claim and not observed policy outcome evidence."
            ),
        },
        "production_readiness_claim": False,
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
    }


def _current_implemented_scope(
    evidence_gate: dict[str, Any],
    inventory: dict[str, Any],
    decision_package: dict[str, Any],
) -> dict[str, Any]:
    slices = evidence_gate.get("evidence_slices") or {}
    local_assets = (slices.get("local_planning_data_foundation") or {}).get(
        "asset_counts"
    ) or {}
    guard = decision_package.get("full_data_guard") or {}
    inventory_summary = inventory.get("summary") or {}
    return {
        "graph_node_count": _int(guard.get("graph_node_count")),
        "graph_edge_count": _int(guard.get("graph_edge_count")),
        "admin_boundary_edge_count": _int(guard.get("admin_boundary_edge_count")),
        "geographic_similarity_edge_count": _int(
            guard.get("geographic_similarity_edge_count")
        ),
        "non_adjacent_similarity_edge_count": _int(
            guard.get("non_adjacent_similarity_edge_count")
        ),
        "available_action_count": _int(
            inventory_summary.get("available_action_count")
        ),
        "transition_count": _int(guard.get("transition_count")),
        "raw_candidate_action_count": _int(
            inventory_summary.get("candidate_action_mask_trace_count")
        ),
        "source_poi_point_count": _asset_count(
            local_assets,
            "gaode_poi_2024",
            "feature_count",
            fallback=guard.get("source_poi_point_count"),
        ),
        "source_road_count": _asset_count(
            local_assets,
            "chongqing_osm_roads_2021",
            "feature_count",
            fallback=guard.get("source_road_count"),
        ),
        "source_building_record_count": _asset_count(
            local_assets,
            "chongqing_central_buildings_2021",
            "feature_count",
        ),
        "source_unicom_commuting_row_count": _asset_count(
            local_assets,
            "chongqing_unicom_commuting_2023_local",
            "row_count",
        ),
        "core_node_state_variables": list(CORE_NODE_STATE_VARIABLES),
    }


def _production_state_layers(
    evidence_gate: dict[str, Any],
    decision_package: dict[str, Any],
    current_scope: dict[str, Any],
) -> list[dict[str, Any]]:
    slices = evidence_gate.get("evidence_slices") or {}
    openaq = slices.get("openaq_observed_temporal_state") or {}
    tap = slices.get("tap_external_temporal_transition") or {}
    service = decision_package.get("service_accessibility_evidence") or {}
    return [
        {
            "layer_id": "spatial_objects",
            "business_role": "multiscale city object graph for governance units, roads, buildings, services and parcels",
            "current_coverage_level": (
                "full_admin_graph_plus_local_assets_not_multiscale_state_graph"
            ),
            "current_evidence_counts": {
                "admin_units": current_scope["graph_node_count"],
                "graph_edges": current_scope["graph_edge_count"],
                "buildings": current_scope["source_building_record_count"],
                "roads": current_scope["source_road_count"],
                "poi_points": current_scope["source_poi_point_count"],
            },
            "implemented_state_variables": list(CORE_NODE_STATE_VARIABLES),
            "missing_for_production": [
                "community_and_block_nodes_required",
                "parcel_and_project_nodes_required",
                "building_road_service_nodes_required",
                "cross_scale_edges_required",
            ],
            "production_blocking_gap": True,
        },
        {
            "layer_id": "environmental_exposure",
            "business_role": "heat, air pollution, noise, traffic exposure and climate stress",
            "current_coverage_level": "observed_temporal_and_gridded_proxy_ready_not_policy_outcome",
            "current_evidence_counts": {
                "openaq_observations": _int(openaq.get("observation_count")),
                "openaq_holdout_count": _int(openaq.get("holdout_count")),
                "tap_holdout_count": _int(tap.get("holdout_count")),
            },
            "implemented_state_variables": [
                "heat_risk",
                "air_pollution_exposure",
            ],
            "missing_for_production": [
                "station_calibrated_full_city_air_quality_panel_required",
                "street_scale_heat_exposure_required",
                "noise_and_traffic_exposure_required",
                "pollution_source_inventory_required",
            ],
            "production_blocking_gap": True,
        },
        {
            "layer_id": "service_accessibility",
            "business_role": "network, capacity and group-specific access to essential services",
            "current_coverage_level": "full_admin_proxy_surface_ready_not_observed_trip_time",
            "current_evidence_counts": {
                "admin_units": _int(service.get("admin_unit_count")),
                "poi_points": _int(service.get("source_poi_point_count")),
                "roads": _int(service.get("source_road_count")),
                "essential_service_points": _int(
                    service.get("total_essential_service_count")
                ),
            },
            "implemented_state_variables": ["service_accessibility"],
            "missing_for_production": [
                "authoritative_service_inventory_required",
                "service_capacity_and_quality_required",
                "observed_or_model_validated_travel_time_required",
                "transit_and_walking_accessibility_required",
            ],
            "production_blocking_gap": True,
        },
        {
            "layer_id": "population_equity",
            "business_role": "population vulnerability, social equity and benefited groups",
            "current_coverage_level": "district_population_and_proxy_downscaling_not_vulnerable_group_authoritative",
            "current_evidence_counts": {
                "unicom_commuting_rows": current_scope[
                    "source_unicom_commuting_row_count"
                ],
            },
            "implemented_state_variables": ["equity"],
            "missing_for_production": [
                "township_or_community_authoritative_population_required",
                "age_income_health_vulnerability_required",
                "group_specific_access_and_exposure_required",
                "distributional_benefit_metrics_required",
            ],
            "production_blocking_gap": True,
        },
        {
            "layer_id": "urban_form_activity",
            "business_role": "built form, land use, roads, development intensity and activity patterns",
            "current_coverage_level": "local_building_road_aoi_activity_assets_not_full_dynamic_activity_state",
            "current_evidence_counts": {
                "buildings": current_scope["source_building_record_count"],
                "roads": current_scope["source_road_count"],
                "commuting_rows": current_scope[
                    "source_unicom_commuting_row_count"
                ],
            },
            "implemented_state_variables": [],
            "missing_for_production": [
                "building_age_height_and_use_required",
                "parcel_development_intensity_required",
                "street_walkability_features_required",
                "spatial_od_geometry_and_activity_time_series_required",
            ],
            "production_blocking_gap": True,
        },
        {
            "layer_id": "governance_constraints",
            "business_role": "legal feasibility, planning controls, budget, project timing and departmental authority",
            "current_coverage_level": "local_planning_samples_only_not_full_constraint_model",
            "current_evidence_counts": {},
            "implemented_state_variables": [],
            "missing_for_production": [
                "legal_feasibility_and_cost_constraints_required",
                "land_ownership_and_planning_control_required",
                "project_pipeline_and_budget_required",
                "department_authority_and_approval_rules_required",
            ],
            "production_blocking_gap": True,
        },
        {
            "layer_id": "temporal_policy_outcomes",
            "business_role": "historical actions, observed outcomes, counterfactual validation and causal effects",
            "current_coverage_level": "simulator_replay_and_holdout_endpoints_not_observed_intervention_outcomes",
            "current_evidence_counts": {
                "simulator_replay_transitions": _int(
                    current_scope.get("transition_count")
                ),
            },
            "implemented_state_variables": [],
            "missing_for_production": [
                "observed_intervention_outcome_panel_required",
                "historical_policy_project_log_required",
                "off_policy_evaluation_dataset_required",
                "causal_effect_calibration_required",
            ],
            "production_blocking_gap": True,
        },
    ]


def _current_action_space(inventory: dict[str, Any]) -> dict[str, Any]:
    summary = inventory.get("summary") or {}
    action_type_counts = dict(summary.get("action_type_counts") or {})
    return {
        "implemented_action_types": list(action_type_counts.keys()),
        "implemented_action_type_count": len(action_type_counts),
        "implemented_feasible_action_count": _int(
            summary.get("available_action_count")
        ),
        "raw_candidate_action_count": _int(
            summary.get("candidate_action_mask_trace_count")
        ),
        "action_type_counts": action_type_counts,
        "mask_reason_counts": dict(summary.get("mask_reason_counts") or {}),
        "thresholds": dict(summary.get("thresholds") or {}),
        "parameterized_action_claim": False,
        "historical_policy_log_claim": False,
    }


def _production_action_families() -> list[dict[str, Any]]:
    families = []
    for spec in PRODUCTION_ACTION_FAMILY_SPECS:
        missing = [
            action_type
            for action_type in spec["required_action_types"]
            if action_type not in spec["implemented_action_types"]
        ]
        families.append(
            {
                "family_id": spec["family_id"],
                "business_role": spec["business_role"],
                "implemented_action_types": list(spec["implemented_action_types"]),
                "required_action_types": list(spec["required_action_types"]),
                "missing_action_types": missing,
                "parameterization_required": True,
                "constraint_cost_evidence_required": True,
                "observed_effect_evidence_required": True,
                "production_blocking_gap": bool(missing),
            }
        )
    return families


def _asset_count(
    asset_counts: dict[str, Any],
    asset_id: str,
    field: str,
    *,
    fallback: Any = None,
) -> int:
    asset = asset_counts.get(asset_id) or {}
    return _int(asset.get(field), default=_int(fallback))


def _int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return int(default)
        return int(value)
    except (TypeError, ValueError):
        return int(default)

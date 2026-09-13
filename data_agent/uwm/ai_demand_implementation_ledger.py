from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from .livability_requirement_registry import build_livability_requirement_registry


IMPLEMENTATION_STATUSES = {
    "production_verified",
    "implemented_evidence_bounded",
    "data_query_only",
    "contract_only",
    "not_implemented",
}

SCENARIO_OVERLAYS = {
    "S1": {
        "implementation_status": "implemented_evidence_bounded",
        "status_basis": "FP/FPP kernel and S6-to-S1 product exist; authoritative profile, population and capacity gaps remain scene dependent.",
        "implemented_outputs": ["traditional_livability_s1_api", "fp_fpp_gap_matrix", "baseline_proposal_snapshot"],
        "evidence_artifacts": ["docs/reports/traditional_livability_s6_s1_fulu_verification_2026-07-11.md"],
        "production_blockers": ["authoritative_fp_fpp_profile_missing", "authoritative_population_or_capacity_missing"],
        "max_supported_claim": "evidence_bounded_facility_gap_assessment",
        "next_actions": ["bind authoritative facility standards and population/capacity tables"],
    },
    "S2": {
        "implementation_status": "production_verified",
        "status_basis": "Real Fulu parcel state, constrained actions, t0-t1-t2 propagation and counterfactual rollout are implemented and verified.",
        "implemented_outputs": ["uwm_livability_s2_kernel", "parcel_action_validation", "counterfactual_rollout", "map_payload"],
        "evidence_artifacts": ["docs/reports/uwm_livability_s2_fulu_verification_2026-07-11.md"],
        "production_blockers": [],
        "max_supported_claim": "bounded_action_conditioned_spatial_scenario",
        "next_actions": ["add locally calibrated intervention-outcome channels before policy-effect claims"],
    },
    "S4": {
        "implementation_status": "implemented_evidence_bounded",
        "status_basis": "Project activity alignment and conflict analysis are implemented; authoritative project and demand tables remain required for customer production claims.",
        "implemented_outputs": ["traditional_livability_s4_project_analysis"],
        "evidence_artifacts": ["docs/reports/traditional_livability_s4_fulu_verification_2026-07-11.md"],
        "production_blockers": ["authoritative_project_program_required", "authoritative_demand_matrix_required"],
        "max_supported_claim": "project_alignment_proxy_diagnostic",
        "next_actions": ["bind authoritative project GFA schedules and demand rules"],
    },
    "S6": {
        "implementation_status": "production_verified",
        "status_basis": "Semantic confirmation, 150 m conflict screening and immutable S1 handoff are implemented and verified on Fulu data.",
        "implemented_outputs": ["s6_semantic_confirmation", "150m_conflict_screening", "immutable_s1_handoff"],
        "evidence_artifacts": ["docs/reports/traditional_livability_s6_s1_fulu_verification_2026-07-11.md"],
        "production_blockers": [],
        "max_supported_claim": "verified_semantic_and_spatial_conflict_workflow",
        "next_actions": ["expand authoritative mappings for additional out-of-taxonomy facility types"],
    },
    "S7": {
        "implementation_status": "implemented_evidence_bounded",
        "status_basis": "Demand-gated candidate ranking is implemented; Fulu authoritative school need is unresolved, so outputs are not site recommendations.",
        "implemented_outputs": ["s1_demand_gate", "conditional_candidate_ranking", "gated_s7_api"],
        "evidence_artifacts": ["docs/reports/traditional_livability_s7_gated_fulu_verification_2026-07-11.md"],
        "production_blockers": ["need_unresolved", "authoritative_site_recommendation_closed"],
        "max_supported_claim": "conditional_candidate_ranking_not_site_recommendation",
        "next_actions": ["bind authoritative positive S1 count gap and facility capacity assumptions"],
    },
}

def _query(output: str, blockers: list[str] | None = None) -> dict[str, Any]:
    return {"implementation_status": "data_query_only", "status_basis": "Reusable data/query components exist, but the complete requirement output and advanced analysis are not implemented.", "implemented_outputs": [output], "evidence_artifacts": [], "production_blockers": list(blockers or []), "max_supported_claim": "descriptive_observed_or_proxy_query", "next_actions": ["build requirement-specific product and verification report"]}


def _bounded(output: str, blockers: list[str], claim: str, artifacts: list[str] | None = None) -> dict[str, Any]:
    return {"implementation_status": "implemented_evidence_bounded", "status_basis": "A requirement-relevant product exists, but evidence or data blockers prevent full customer requirement completion.", "implemented_outputs": [output], "evidence_artifacts": list(artifacts or []), "production_blockers": blockers, "max_supported_claim": claim, "next_actions": ["close listed evidence and data blockers before promoting status"]}


def _contract(output: str, blockers: list[str]) -> dict[str, Any]:
    return {"implementation_status": "contract_only", "status_basis": "The technical route and safety contract are defined, but no verified requirement product exists.", "implemented_outputs": [output], "evidence_artifacts": [], "production_blockers": blockers, "max_supported_claim": "requirement_and_method_contract_only", "next_actions": ["bind authoritative inputs and implement a verified product"]}


def _not_implemented(blocker: str) -> dict[str, Any]:
    return {"implementation_status": "not_implemented", "status_basis": "No requirement-specific verified product exists.", "implemented_outputs": [], "evidence_artifacts": [], "production_blockers": [blocker], "max_supported_claim": "not_implemented", "next_actions": ["design and implement the requirement-specific product"]}

DEMAND_OVERLAYS = {
    "1": _bounded(
        "spatial_scope_admin_unit_registry_product",
        ["source_license_and_official_vintage_unverified", "topology_not_validated", "authoritative_admin_codes_missing", "historical_county_name_crosswalk_missing"],
        "fragile_spatial_scope_admin_unit_registry_and_uwm_identity_readiness",
        ["docs/reports/spatial_scope_registry_chongqing_verification_2026-07-12.md", "data/uwm_public_proxy/chongqing_central/spatial_scope_registry_chongqing/overview.json"],
    ), "2": _bounded(
        "planning_parcel_version_registry_product",
        ["planning_asset_approval_unverified", "effective_period_and_version_identifiers_missing", "predecessor_successor_lineage_missing", "source_license_pending", "uwm_temporal_baseline_gate_closed"],
        "planning_parcel_asset_inventory_version_contract_and_temporal_baseline_readiness",
        ["docs/reports/planning_version_registry_chongqing_verification_2026-07-12.md", "data/uwm_public_proxy/chongqing_central/planning_version_registry_chongqing/overview.json"],
    ), "3": _bounded(
        "parcel_land_use_state_readiness_product",
        ["source_feature_rows_not_materialized", "authoritative_version_baseline_missing", "planned_use_and_approval_join_missing", "successor_observations_and_transition_labels_missing", "traditional_state_and_uwm_transition_gates_closed"],
        "parcel_land_use_schema_audit_state_contract_and_uwm_transition_readiness",
        ["docs/reports/parcel_state_readiness_chongqing_verification_2026-07-13.md", "data/uwm_public_proxy/chongqing_central/parcel_state_readiness_chongqing/overview.json"],
    ),
    "4": _bounded(
        "infrastructure_network_readiness_product",
        ["underground_utility_networks_missing", "capacity_ownership_and_operator_missing", "load_condition_maintenance_and_outage_timeseries_missing", "cross_network_dependencies_missing", "utility_observation_and_cascade_kernel_gates_closed"],
        "visible_infrastructure_inventory_utility_data_contract_and_cascade_kernel_readiness",
        ["docs/reports/infrastructure_network_readiness_chongqing_verification_2026-07-13.md", "data/uwm_public_proxy/chongqing_central/infrastructure_network_readiness_chongqing/overview.json"],
    ),
    "5": _bounded(
        "asset_lifecycle_readiness_product",
        ["authoritative_asset_identity_and_entity_resolution_missing", "ownership_condition_and_lifecycle_observations_missing", "maintenance_failure_replacement_and_dependency_events_missing", "uwm_asset_state_and_lifecycle_kernel_gates_closed"],
        "cross_product_asset_catalog_lifecycle_contract_and_uwm_asset_state_readiness",
        ["docs/reports/asset_lifecycle_readiness_chongqing_verification_2026-07-13.md", "data/uwm_public_proxy/chongqing_central/asset_lifecycle_readiness_chongqing/overview.json"],
    ),
    "6": _bounded(
        "population_demographic_readiness_product",
        ["authoritative_current_population_and_lineage_missing", "gender_age_nationality_citizenship_and_household_structure_missing", "birth_death_migration_and_household_transition_timeseries_missing", "service_demand_and_planning_response_observations_missing", "uwm_population_state_and_dynamics_kernel_gates_closed"],
        "observed_population_evidence_catalog_demographic_contract_and_uwm_population_dynamics_readiness",
        ["docs/reports/population_demographic_readiness_chongqing_verification_2026-07-13.md", "data/uwm_public_proxy/chongqing_central/population_demographic_readiness_chongqing/overview.json"],
    ),
    "7": _bounded("existing_livability_world_model_decision_package", ["24_month_and_five_year_customer_calibration_missing"], "bounded_model_based_livability_decision_support"),
    "8": _bounded(
        "traditional_mobility_accessibility_product",
        [
            "public_transport_missing",
            "road_safety_missing",
            "shaded_routes_missing",
            "universal_accessibility_missing",
            "cycling_routes_missing",
            "parking_pressure_missing",
            "pedestrian_crossings_missing",
        ],
        "administrative_service_accessibility_and_network_proxy_gap_diagnostic",
        ["docs/reports/traditional_mobility_accessibility_chongqing_verification_2026-07-11.md"],
    ),
    "9": _bounded(
        "traditional_public_space_product",
        ["public_access_and_opening_hours_missing", "quality_vitality_and_actual_use_missing", "shade_seating_furniture_missing", "waterfront_accessibility_missing", "safety_and_universal_accessibility_missing", "authoritative_per_capita_standard_missing", "intervention_effect_evidence_missing"],
        "public_space_inventory_distribution_and_relative_evidence_gap",
        ["docs/reports/traditional_public_space_chongqing_verification_2026-07-11.md", "data/uwm_public_proxy/chongqing_central/traditional_public_space_chongqing/overview.json"],
    ),
    "10": _bounded(
        "traditional_safety_comfort_evidence_product",
        ["crash_conflict_observations_missing", "crime_security_observations_missing", "lighting_crossing_data_missing", "shade_corridor_data_missing", "universal_accessibility_assets_missing", "observed_thermal_comfort_missing", "emergency_response_time_missing", "intervention_effect_evidence_missing", "environment_admin_crosswalk_missing"],
        "mobility_environment_context_and_safety_comfort_evidence_readiness",
        ["docs/reports/traditional_safety_comfort_chongqing_verification_2026-07-12.md", "data/uwm_public_proxy/chongqing_central/traditional_safety_comfort_chongqing/overview.json"],
    ),
    "11": _bounded("environmental_kernel_scene_evidence_gate_and_api", ["environmental_action_response_closed", "temperature_and_vegetation_dynamics_unavailable"], "observed_environmental_state_and_calibrated_pm25_temporal_dynamics", ["docs/reports/uwm_environmental_kernel_chongqing_verification_2026-07-11.md"]),
    "12": _bounded(
        "traditional_social_public_service_product",
        ["authoritative_capacity_missing", "authoritative_lifecycle_and_activity_status_missing", "population_capacity_match_missing", "authoritative_service_area_standard_missing", "future_demand_evidence_missing", "township_accessibility_not_joined_to_county_facilities"],
        "social_infrastructure_inventory_and_relative_evidence_gap",
        ["docs/reports/traditional_social_public_service_chongqing_verification_2026-07-11.md", "data/uwm_public_proxy/chongqing_central/traditional_social_public_service_chongqing/overview.json"],
    ),
    "13": _bounded(
        "traditional_housing_community_evidence_product",
        ["housing_unit_inventory_missing", "residential_use_and_floor_area_missing", "price_rent_affordability_missing", "tenure_missing", "household_composition_microdata_missing", "housing_job_observed_proximity_missing", "causal_housing_transition_model_missing"],
        "building_morphology_population_context_and_housing_evidence_readiness",
        ["docs/reports/traditional_housing_community_chongqing_verification_2026-07-12.md", "data/uwm_public_proxy/chongqing_central/traditional_housing_community_chongqing/overview.json"],
    ),
    "14": _bounded(
        "traditional_daily_convenience_business_evidence_product",
        ["business_operation_and_opening_hours_missing", "business_licence_missing", "employment_data_missing", "revenue_transactions_visits_missing", "market_demand_missing", "entrepreneurship_evidence_missing", "causal_activation_effect_missing", "county_facility_to_township_accessibility_exact_id_missing"],
        "daily_service_inventory_accessibility_context_and_business_activity_evidence",
        ["docs/reports/traditional_daily_convenience_chongqing_verification_2026-07-12.md", "data/uwm_public_proxy/chongqing_central/traditional_daily_convenience_chongqing/overview.json"],
    ),
    "15": _bounded(
        "public_feedback_spatial_semantic_readiness_product",
        ["authoritative_privacy_safe_customer_feedback_corpus_missing", "sampling_frame_and_representativeness_missing", "response_resolution_and_longitudinal_outcomes_missing", "feedback_analysis_and_uwm_observation_gates_closed"],
        "public_feedback_data_contract_spatial_semantic_and_uwm_observation_readiness",
        ["docs/reports/public_feedback_readiness_chongqing_verification_2026-07-12.md", "data/uwm_public_proxy/chongqing_central/public_feedback_readiness_chongqing/overview.json"],
    ),
    "16": _bounded(
        "traditional_cultural_heritage_evidence_product",
        ["authoritative_heritage_register_missing", "legal_status_and_level_missing", "opening_operation_and_public_access_missing", "condition_and_restoration_observations_missing", "visitor_and_community_activity_missing", "longitudinal_intervention_outcomes_missing", "facility_inventory_sampling_not_complete"],
        "cultural_place_inventory_candidate_leads_and_heritage_evidence_readiness",
        ["docs/reports/traditional_cultural_heritage_chongqing_verification_2026-07-12.md", "data/uwm_public_proxy/chongqing_central/traditional_cultural_heritage_chongqing/overview.json"],
    ),
    "17": _bounded(
        "digital_asset_smart_district_readiness_product",
        ["district_digital_infrastructure_inventory_missing", "device_operational_timeseries_missing", "digital_infrastructure_uwm_gate_closed"],
        "platform_digital_capability_and_district_smart_infrastructure_evidence_readiness",
        ["docs/reports/digital_readiness_chongqing_verification_2026-07-12.md", "data/uwm_public_proxy/chongqing_central/digital_readiness_chongqing/overview.json"],
    ),
    "18": _bounded(
        "operations_service_quality_readiness_product",
        ["customer_sla_work_order_and_asset_lifecycle_missing", "authoritative_incident_response_and_recovery_timestamps_missing", "operations_uwm_gate_closed"],
        "platform_operations_evidence_and_customer_service_management_readiness",
        ["docs/reports/operations_quality_chongqing_verification_2026-07-12.md", "data/uwm_public_proxy/chongqing_central/operations_quality_chongqing/overview.json"],
    ),
    "19": _bounded(
        "resilience_kernel_foundation",
        ["authoritative_hazard_event_timeseries_missing", "population_and_asset_exposure_missing", "emergency_response_time_missing", "hazard_spatial_propagation_calibration_missing", "recovery_state_timeseries_missing", "intervention_outcome_evidence_missing", "held_out_event_evaluation_missing"],
        "observed_resilience_context_spatial_graph_and_fail_closed_kernel_readiness",
        ["docs/reports/resilience_kernel_chongqing_verification_2026-07-12.md", "data/uwm_public_proxy/chongqing_central/resilience_kernel_chongqing/overview.json"],
    ),
    "20": _bounded(
        "business_licence_activity_readiness_product",
        ["authoritative_ded_licence_and_lifecycle_data_missing", "poi_to_entity_authoritative_crosswalk_missing", "business_lifecycle_uwm_gate_closed"],
        "business_poi_spatial_evidence_and_authoritative_licence_lifecycle_readiness",
        ["docs/reports/business_licence_chongqing_verification_2026-07-12.md", "data/uwm_public_proxy/chongqing_central/business_licence_chongqing/overview.json"],
    ),
    "21": _bounded(
        "traditional_social_public_service_product",
        ["authoritative_capacity_missing", "observed_service_availability_missing", "population_service_match_missing", "authoritative_service_area_standard_missing", "authoritative_service_deficit_unavailable", "township_accessibility_not_joined_to_county_facilities"],
        "government_public_service_inventory_and_relative_evidence_gap",
        ["docs/reports/traditional_social_public_service_chongqing_verification_2026-07-11.md", "data/uwm_public_proxy/chongqing_central/traditional_social_public_service_chongqing/overview.json"],
    ),
    "22": _bounded(
        "development_control_rule_readiness_product",
        ["approved_site_specific_dcr_missing", "authoritative_project_applicability_and_rule_priority_missing", "dcr_execution_gate_closed"],
        "planning_rule_asset_catalog_and_site_specific_dcr_execution_readiness",
        ["docs/reports/development_control_chongqing_verification_2026-07-12.md", "data/uwm_public_proxy/chongqing_central/development_control_chongqing/overview.json"],
    ),
    "23": _bounded(
        "financial_investment_readiness_product",
        ["authoritative_boq_missing", "capital_and_operating_cost_missing", "revenue_and_benefit_evidence_missing", "financing_discount_and_schedule_assumptions_missing", "financial_calculation_and_uwm_handoff_gates_closed"],
        "financial_data_contract_and_deterministic_calculation_readiness",
        ["docs/reports/financial_readiness_chongqing_verification_2026-07-12.md", "data/uwm_public_proxy/chongqing_central/financial_readiness_chongqing/overview.json"],
    ),
    "24": _bounded(
        "cross_domain_impact_evidence_product",
        ["cross_grain_products_reference_only", "housing_culture_economy_resilience_uwm_gates_closed", "authoritative_cost_benefit_and_policy_outcomes_missing"],
        "cross_domain_evidence_compatibility_priority_and_dynamic_channel_readiness",
        ["docs/reports/cross_domain_impact_chongqing_verification_2026-07-12.md", "data/uwm_public_proxy/chongqing_central/cross_domain_impact_chongqing/overview.json"],
    ),
    "25": _bounded(
        "dependency_aware_implementation_roadmap_product",
        ["roadmap_not_approved_program", "budgets_dates_owners_and_policy_effects_unavailable", "kernel_release_tasks_blocked_until_independent_verification"],
        "evidence_dependency_and_verification_gated_implementation_roadmap",
        ["docs/reports/dependency_roadmap_chongqing_verification_2026-07-12.md", "data/uwm_public_proxy/chongqing_central/dependency_roadmap_chongqing/overview.json"],
    ),
}


def build_ai_demand_implementation_ledger(*, repo_root: Path, registry: Mapping[str, Any] | None = None) -> dict[str, Any]:
    registry_payload = deepcopy(dict(registry or build_livability_requirement_registry()))
    scenarios = [_overlay(row, SCENARIO_OVERLAYS[str(row["id"])], repo_root) for row in registry_payload["livability_scenarios"]]
    demands = [_overlay(row, DEMAND_OVERLAYS[str(row["id"])], repo_root) for row in registry_payload["customer_ai_demands"]]
    counts = {status: 0 for status in sorted(IMPLEMENTATION_STATUSES)}
    for row in scenarios + demands:
        counts[row["implementation_status"]] += 1
    return {"schema": "uwm.ai_demand_implementation_ledger.v1", "source_documents": registry_payload["source_documents"], "livability_scenarios": scenarios, "customer_ai_demands": demands, "summary": {"implementation_status_counts": counts, "verified_or_bounded_count": counts["production_verified"] + counts["implemented_evidence_bounded"]}, "claim_boundary": {"registration_is_not_implementation": True, "product_presence_is_not_full_requirement_completion": True, "observed_policy_outcome_superiority_claim": False}}


def _overlay(row: Mapping[str, Any], overlay: Mapping[str, Any], repo_root: Path) -> dict[str, Any]:
    result = deepcopy(dict(row))
    result.update(deepcopy(dict(overlay)))
    result["evidence_artifact_checks"] = [{"path": path, "exists": (repo_root / path).is_file()} for path in result["evidence_artifacts"]]
    if any(not check["exists"] for check in result["evidence_artifact_checks"]):
        result["production_blockers"] = sorted(set(result["production_blockers"] + ["declared_evidence_artifact_missing"]))
    return result

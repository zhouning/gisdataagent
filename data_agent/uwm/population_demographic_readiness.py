from __future__ import annotations

import hashlib
import json
from copy import deepcopy


DEMOGRAPHIC_CHANNELS = (
    "authoritative_current_total_population",
    "sex_gender_structure",
    "age_cohorts",
    "nationality_structure",
    "citizen_non_citizen_structure",
    "household_composition",
    "household_size",
    "births",
    "deaths",
    "in_migration",
    "out_migration",
    "floating_population",
    "employment_student_status",
    "service_demand_cohorts",
)

POPULATION_MECHANISMS = (
    "population_state_materialization",
    "cohort_transition",
    "birth_death_dynamics",
    "migration_dynamics",
    "household_transition",
    "planning_intervention_response",
    "service_demand_propagation",
    "population_growth_forecasting",
    "counterfactual_rollout",
    "uncertainty_calibration",
)


def build_population_demographic_readiness_product(*, evidence_products, source_artifacts):
    products = deepcopy(evidence_products)
    for product in products:
        if not product.get("source_path"):
            raise ValueError("population_evidence_source_required")
        if product.get("evidence_role") in {"population_spatial_proxy", "population_downscaling_proxy"} and product.get("population_status") == "authoritative_current":
            raise ValueError("proxy_cannot_be_authoritative_population")

    channels = {
        name: {
            "status": "unavailable",
            "value": None,
            "record_count": None,
            "production_blockers": ["authoritative_demographic_structure_and_longitudinal_events_missing"],
        }
        for name in DEMOGRAPHIC_CHANNELS
    }
    contracts = {
        "population_observation": {
            "required_fields": ["admin_or_grid_id", "observation_time", "population_count", "population_definition", "spatial_grain", "source_authority", "version", "quality_flags", "provenance"]
        },
        "demographic_structure_observation": {
            "required_fields": ["admin_or_grid_id", "observation_time", "dimension", "category", "population_count", "denominator_definition", "source_authority", "privacy_classification", "provenance"]
        },
        "population_transition_event": {
            "required_fields": ["event_id", "admin_or_grid_id", "event_type", "event_time", "cohort_or_household_class", "count", "origin", "destination", "planning_action_link", "source_authority", "uncertainty", "provenance"]
        },
    }
    gate = {
        "status": "closed",
        "mechanisms": {name: "closed" for name in POPULATION_MECHANISMS},
        "authoritative_population_state_status": "closed",
        "demographic_structure_status": "closed",
        "longitudinal_transition_status": "closed",
        "uwm_population_kernel_status": "closed",
    }
    digest = {"evidence_products": products, "demographic_channels": channels}
    bundle_id = "population-demographic-" + hashlib.sha256(json.dumps(digest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:20]
    return {
        "schema": "uwm.population_demographic_readiness.v1",
        "bundle_id": bundle_id,
        "summary": {
            "evidence_product_count": len(products),
            "authoritative_current_population": None,
            "forecast_population": None,
            "available_demographic_channel_count": 0,
            "materialized_population_state_count": 0,
            "observed_transition_event_count": 0,
            "open_population_mechanism_count": 0,
        },
        "evidence_products": products,
        "demographic_channels": channels,
        "data_contracts": contracts,
        "population_gate": gate,
        "source_artifacts": sorted(map(str, source_artifacts)),
        "claim_boundary": {
            "max_claim_level": "observed_population_evidence_catalog_demographic_contract_and_uwm_population_dynamics_readiness",
            "population_proxy_not_authoritative_population": True,
            "district_total_not_demographic_structure": True,
            "historical_raster_not_current_population": True,
            "downscaling_not_census_enumeration": True,
            "missing_subgroup_not_zero_population": True,
            "single_cross_section_not_growth_trend": True,
            "planning_capacity_not_observed_migration_response": True,
            "dynamics_contract_not_calibrated_forecast": True,
        },
        "fabricated_value_count": 0,
    }

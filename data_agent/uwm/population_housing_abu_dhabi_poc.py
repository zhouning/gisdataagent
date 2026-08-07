"""Build the bounded Abu Dhabi population and housing proxy demo scenario."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .population_housing_optimization import POPULATION_HOUSING_INPUT_SCHEMA
from .population_housing_poc import (
    GROUP_ASSUMPTIONS,
    HOUSING_ASSUMPTIONS,
    _allocate_integer_total,
    _haversine_km,
)

DEFAULT_ABU_DHABI_EVIDENCE_PATH = Path(
    "data/uwm_public_proxy/abu_dhabi_city/"
    "population_housing_evidence_2026_08_01/"
    "abu_dhabi_population_housing_zone_evidence.json"
)
DEFAULT_ABU_DHABI_BOUNDARY_PATH = Path(
    "data/uwm_public_proxy/abu_dhabi_city/"
    "population_housing_evidence_2026_08_01/"
    "abu_dhabi_six_analysis_zones.geojson"
)
ABU_DHABI_ZONE_COST_MULTIPLIERS = (1.18, 1.12, 1.08, 1.04, 0.98, 0.94)


def build_abu_dhabi_population_housing_proxy_scenario(
    *,
    evidence_path: Path = DEFAULT_ABU_DHABI_EVIDENCE_PATH,
    created_at: str,
) -> dict[str, Any]:
    """Create a six-zone Abu Dhabi scenario from public proxy evidence.

    The OSM city boundary, GHSL population and built surface, and Microsoft
    building counts are evidence-backed proxy channels. Analysis partitions,
    household groups, housing capacity, services, travel time, and costs remain
    explicit engineering assumptions.
    """

    evidence = _read_json(evidence_path)
    if evidence.get("schema") != "uwm.population_housing.abu_dhabi_zone_evidence.v1":
        raise ValueError("unexpected Abu Dhabi population/housing evidence schema")
    source_rows = evidence.get("zone_evidence") or []
    if not isinstance(source_rows, list) or len(source_rows) != 6:
        raise ValueError("Abu Dhabi demo requires exactly six analysis-zone rows")

    source_population = sum(float(row["ghsl_population_2020_proxy"]) for row in source_rows)
    if source_population <= 0:
        raise ValueError("Abu Dhabi source population proxy must be positive")

    groups: list[dict[str, Any]] = []
    zones: list[dict[str, Any]] = []
    housing_options: list[dict[str, Any]] = []
    zone_ids = tuple(str(row["zone_id"]) for row in source_rows)

    for zone_index, source in enumerate(source_rows, start=1):
        zone_id = str(source["zone_id"])
        population = float(source["ghsl_population_2020_proxy"])
        zone_group_rows: list[dict[str, Any]] = []
        for assumption in GROUP_ASSUMPTIONS:
            households = max(
                1,
                round(
                    population
                    * float(assumption["population_share"])
                    / float(assumption["persons_per_household"])
                ),
            )
            group = {
                "group_id": f"g-ad-{zone_index:02d}-{assumption['suffix']}",
                "group_name": f"{source['township']}-{assumption['name']}",
                "origin_zone_id": zone_id,
                "households": households,
                "persons_per_household": assumption["persons_per_household"],
                "service_demand_per_household": assumption["service_demand_per_household"],
                "max_commute_minutes": assumption["max_commute_minutes"],
                "max_relocation_share": assumption["max_relocation_share"],
                "eligible_housing_types": list(assumption["eligible_housing_types"]),
                "population_share_assumption": assumption["population_share"],
                "evidence_status": "scenario_assumption_from_ghsl_population_proxy",
            }
            groups.append(group)
            zone_group_rows.append(group)

        household_count = sum(int(group["households"]) for group in zone_group_rows)
        building_count = int(source["microsoft_building_feature_count"])
        built_surface = float(source["ghsl_built_surface_2020_sq_m_proxy"])
        built_surface_per_person = built_surface / max(population, 1.0)
        building_features_per_10k = building_count / max(population / 10_000, 1.0)
        existing_service_ratio = (
            0.65
            + min(built_surface_per_person, 20.0) * 0.002
            + min(building_features_per_10k, 120.0) * 0.00025
        )
        zones.append(
            {
                "zone_id": zone_id,
                "zone_name": f"阿布扎比{source['township']}",
                "county": source["county"],
                "township": source["township"],
                "centroid": source["centroid"],
                "source_area_sq_km": source["area_sq_km"],
                "source_population_proxy": population,
                "source_population_status": "public_fitted_population_proxy",
                "source_building_count": building_count,
                "source_building_status": "public_ml_building_proxy",
                "source_built_surface_sq_m_proxy": built_surface,
                "source_building_height_available_count": int(
                    source["microsoft_building_height_available_count"]
                ),
                "existing_service_capacity": round(
                    household_count * existing_service_ratio, 3
                ),
                "max_service_expansion": round(household_count * 0.20, 3),
                "service_expansion_unit_public_cost": 42.0,
                "service_capacity_evidence_status": (
                    "scenario_assumption_conditioned_on_built_form_proxies"
                ),
            }
        )

        existing_total = round(household_count * 0.93)
        max_new_total = round(household_count * 0.15)
        housing_types = list(HOUSING_ASSUMPTIONS)
        existing_allocations = _allocate_integer_total(
            existing_total,
            [HOUSING_ASSUMPTIONS[name]["existing_share"] for name in housing_types],
        )
        new_allocations = _allocate_integer_total(
            max_new_total,
            [HOUSING_ASSUMPTIONS[name]["new_share"] for name in housing_types],
        )
        multiplier = ABU_DHABI_ZONE_COST_MULTIPLIERS[zone_index - 1]
        for housing_type, existing_units, max_new_units in zip(
            housing_types, existing_allocations, new_allocations, strict=True
        ):
            assumption = HOUSING_ASSUMPTIONS[housing_type]
            housing_options.append(
                {
                    "housing_option_id": f"h-ad-{zone_index:02d}-{housing_type}",
                    "housing_option_name": (
                        f"{source['township']}-{assumption['name']}"
                    ),
                    "zone_id": zone_id,
                    "housing_type": housing_type,
                    "existing_units": existing_units,
                    "max_new_units": max_new_units,
                    "new_unit_public_cost": round(
                        float(assumption["new_unit_public_cost"]) * multiplier, 3
                    ),
                    "activation_public_cost": round(
                        float(assumption["activation_public_cost"]) * multiplier, 3
                    ),
                    "evidence_status": (
                        "scenario_assumption_not_observed_housing_inventory"
                    ),
                }
            )

    zone_by_id = {str(row["zone_id"]): row for row in zones}
    candidate_assignments: list[dict[str, Any]] = []
    for group in groups:
        origin = zone_by_id[str(group["origin_zone_id"])]
        for option in housing_options:
            destination = zone_by_id[str(option["zone_id"])]
            housing_assumption = HOUSING_ASSUMPTIONS[str(option["housing_type"])]
            straight_distance_km = _haversine_km(origin["centroid"], destination["centroid"])
            road_distance_proxy_km = straight_distance_km * 1.28
            relocated = str(origin["zone_id"]) != str(destination["zone_id"])
            commute_minutes = (
                13.0 if not relocated else 12.0 + (road_distance_proxy_km / 34.0) * 60.0
            )
            destination_index = zone_ids.index(str(destination["zone_id"]))
            multiplier = ABU_DHABI_ZONE_COST_MULTIPLIERS[destination_index]
            candidate_assignments.append(
                {
                    "group_id": group["group_id"],
                    "housing_option_id": option["housing_option_id"],
                    "allowed": True,
                    "distance_km": round(road_distance_proxy_km, 3),
                    "commute_minutes": round(commute_minutes, 3),
                    "commute_generalized_cost": round(commute_minutes * 0.48, 3),
                    "resident_housing_cost": round(
                        float(housing_assumption["resident_housing_cost"]) * multiplier,
                        3,
                    ),
                    "public_cost": round(
                        float(housing_assumption["public_cost"]) * multiplier, 3
                    ),
                    "relocation_cost": 38.0 if relocated else 0.0,
                    "evidence_status": (
                        "centroid_distance_with_road_detour_and_cost_scenario_assumption"
                    ),
                }
            )

    total_households = sum(int(group["households"]) for group in groups)
    modeled_people = sum(
        int(group["households"]) * float(group["persons_per_household"]) for group in groups
    )
    return {
        "schema": POPULATION_HOUSING_INPUT_SCHEMA,
        "scenario_id": "abu-dhabi-city-six-analysis-zone-proxy-demo-2026-08-01",
        "created_at": created_at,
        "display": {
            "city_name": "阿布扎比",
            "area_name": "阿布扎比市六分析分区",
            "scenario_name": "阿布扎比人口与住房空间配置优化代理情景",
            "scope_description": (
                "OSM 阿布扎比城市边界内六个人口分位分析分区的聚合代理配置与硬约束审计"
            ),
            "boundary_label": (
                "OSM 阿布扎比城市边界内 GHSL 人口分位分析分区，EPSG:4326"
            ),
            "boundary_kind_label": "人口分位分析分区",
            "map_zoom": 10,
        },
        "planning_horizon_years": 5,
        "cost_unit": "thousand_AED_2026_planning_horizon",
        "zones": zones,
        "population_groups": groups,
        "housing_options": housing_options,
        "candidate_assignments": candidate_assignments,
        "parameters": {
            "total_public_budget": round(total_households * 152.0, 3),
            "max_relocated_households_share": 0.20,
            "allow_unmet_households": False,
            "unmet_household_penalty": 10_000.0,
            "solver_time_limit_seconds": 120.0,
            "solver_mip_relative_gap": 0.001,
            "solver_log": False,
        },
        "source_summary": {
            "selected_zone_count": len(zones),
            "source_population_proxy": round(source_population, 6),
            "modeled_households": total_households,
            "modeled_people_from_household_assumptions": round(modeled_people, 3),
            "population_difference_due_to_household_rounding": round(
                modeled_people - source_population, 3
            ),
            "microsoft_building_footprint_count": sum(
                int(row["microsoft_building_feature_count"]) for row in source_rows
            ),
            "microsoft_building_height_available_count": sum(
                int(row["microsoft_building_height_available_count"])
                for row in source_rows
            ),
        },
        "source_trace": [
            {
                "path": str(evidence_path),
                "role": "阿布扎比六分析分区聚合证据、来源、方法和质量边界",
                "evidence_status": "mixed_public_proxy_evidence",
            },
            *[
                {
                    "path": source.get("local_path")
                    or source.get("local_paths")
                    or source.get("url")
                    or source.get("urls"),
                    "role": source.get("role"),
                    "dataset": source.get("dataset"),
                    "license": source.get("license"),
                    "evidence_status": source.get("evidence_status"),
                }
                for source in evidence.get("sources") or []
            ],
        ],
        "assumptions": [
            "six_analysis_zones_are_population_balanced_model_partitions_not_official_boundaries",
            "population_group_shares_and_household_sizes_are_engineering_assumptions",
            "housing_units_and_new_supply_are_derived_scenario_capacities_not_inventory",
            "service_capacity_is_conditioned_on_built_form_but_remains_an_assumption",
            "travel_time_is_a_centroid_distance_proxy_with_fixed_detour_not_routing",
            "all_costs_are_engineering_assumptions_not_abu_dhabi_fiscal_estimates",
        ],
        "synthetic_flags": [
            {"field_group": "population_total", "status": "fitted_proxy"},
            {"field_group": "population_groups", "status": "scenario_assumption"},
            {"field_group": "housing_capacity", "status": "scenario_assumption"},
            {"field_group": "transport_impedance", "status": "scenario_assumption"},
            {"field_group": "service_capacity", "status": "scenario_assumption"},
            {"field_group": "costs", "status": "scenario_assumption"},
        ],
        "claim_boundary": {
            "max_claim_level": "aggregate_proxy_scenario_optimization_poc",
            "analysis_zones_not_official_boundaries": True,
            "not_person_level_assignment": True,
            "not_authoritative_population": True,
            "not_observed_housing_inventory": True,
            "not_observed_travel_time": True,
            "not_fiscal_estimate": True,
            "not_policy_recommendation": True,
        },
        "limitations": [
            "six_analysis_zones_are_not_official_abu_dhabi_communities_or_planning_zones",
            "ghsl_2020_population_is_a_one_kilometer_public_proxy",
            "ghsl_built_surface_and_ml_buildings_are_not_housing_inventory",
            "ml_building_coverage_and_geometry_quality_vary_spatially",
            "built_form_conditioning_does_not_observe_service_capacity",
            "centroid_distance_with_fixed_detour_is_not_observed_commute_time",
            "assumed_costs_are_not_budget_records",
            "weighted_scenarios_are_not_a_complete_pareto_frontier",
        ],
        "empirical_policy_optimality_claim": False,
    }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object at {path}")
    return payload


__all__ = [
    "DEFAULT_ABU_DHABI_BOUNDARY_PATH",
    "DEFAULT_ABU_DHABI_EVIDENCE_PATH",
    "build_abu_dhabi_population_housing_proxy_scenario",
]

"""Build the bounded Shanghai population and housing proxy demo scenario."""

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

DEFAULT_SHANGHAI_EVIDENCE_PATH = Path(
    "data/uwm_public_proxy/shanghai_pudong/"
    "population_housing_evidence_2026_08_01/"
    "shanghai_population_housing_zone_evidence.json"
)
DEFAULT_SHANGHAI_BOUNDARY_PATH = Path(
    "data/uwm_public_proxy/shanghai_pudong/"
    "population_housing_evidence_2026_08_01/"
    "shanghai_pudong_six_streets.geojson"
)
SHANGHAI_ZONE_COST_MULTIPLIERS = (1.30, 1.18, 1.10, 1.15, 1.05, 0.98)


def build_shanghai_population_housing_proxy_scenario(
    *,
    evidence_path: Path = DEFAULT_SHANGHAI_EVIDENCE_PATH,
    created_at: str,
) -> dict[str, Any]:
    """Create a six-street Pudong scenario from public proxy evidence.

    GHSL population, GHSL built surface, OSM feature counts, administrative
    identity and geometry are evidence-backed proxy channels. Household groups,
    housing inventory/capacity, service capacity, travel time and every cost are
    explicit engineering assumptions.
    """

    evidence = _read_json(evidence_path)
    if evidence.get("schema") != "uwm.population_housing.shanghai_zone_evidence.v1":
        raise ValueError("unexpected Shanghai population/housing evidence schema")
    source_rows = evidence.get("zone_evidence") or []
    if not isinstance(source_rows, list) or len(source_rows) != 6:
        raise ValueError("Shanghai demo requires exactly six zone evidence rows")

    source_population = sum(float(row["ghsl_population_2020_proxy"]) for row in source_rows)
    if not 1_000_000 <= source_population <= 2_000_000:
        raise ValueError(
            f"selected Shanghai proxy population {source_population} is outside the demo scope"
        )

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
                "group_id": f"g-sh-{zone_index:02d}-{assumption['suffix']}",
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
        service_features = int(source["osm_service_point_proxy_count"]) + int(
            source["osm_service_polygon_proxy_count"]
        )
        service_features_per_10k_people = service_features / max(population / 10_000, 1)
        existing_service_ratio = 0.66 + min(service_features_per_10k_people, 20.0) * 0.004
        zones.append(
            {
                "zone_id": zone_id,
                "zone_name": f"{source['county']}{source['township']}",
                "county": source["county"],
                "township": source["township"],
                "centroid": source["centroid"],
                "source_area_sq_km": source["area_sq_km"],
                "source_population_proxy": population,
                "source_population_status": "public_fitted_population_proxy",
                "source_building_count": int(source["osm_building_feature_count"]),
                "source_built_surface_sq_m_proxy": float(
                    source["ghsl_built_surface_2020_sq_m_proxy"]
                ),
                "source_road_feature_count": int(source["osm_road_feature_count"]),
                "source_essential_service_point_count": service_features,
                "existing_service_capacity": round(household_count * existing_service_ratio, 3),
                "max_service_expansion": round(household_count * 0.20, 3),
                "service_expansion_unit_public_cost": 36.0,
                "service_capacity_evidence_status": (
                    "scenario_assumption_conditioned_on_osm_service_feature_proxy"
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
        multiplier = SHANGHAI_ZONE_COST_MULTIPLIERS[zone_index - 1]
        for housing_type, existing_units, max_new_units in zip(
            housing_types, existing_allocations, new_allocations, strict=True
        ):
            assumption = HOUSING_ASSUMPTIONS[housing_type]
            housing_options.append(
                {
                    "housing_option_id": f"h-sh-{zone_index:02d}-{housing_type}",
                    "housing_option_name": (f"{source['township']}-{assumption['name']}"),
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
                    "evidence_status": ("scenario_assumption_not_observed_housing_inventory"),
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
            road_distance_proxy_km = straight_distance_km * 1.22
            relocated = str(origin["zone_id"]) != str(destination["zone_id"])
            commute_minutes = (
                14.0 if not relocated else 12.0 + (road_distance_proxy_km / 24.0) * 60.0
            )
            destination_index = zone_ids.index(str(destination["zone_id"]))
            multiplier = SHANGHAI_ZONE_COST_MULTIPLIERS[destination_index]
            candidate_assignments.append(
                {
                    "group_id": group["group_id"],
                    "housing_option_id": option["housing_option_id"],
                    "allowed": True,
                    "distance_km": round(road_distance_proxy_km, 3),
                    "commute_minutes": round(commute_minutes, 3),
                    "commute_generalized_cost": round(commute_minutes * 0.42, 3),
                    "resident_housing_cost": round(
                        float(housing_assumption["resident_housing_cost"]) * multiplier,
                        3,
                    ),
                    "public_cost": round(float(housing_assumption["public_cost"]) * multiplier, 3),
                    "relocation_cost": 32.0 if relocated else 0.0,
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
        "scenario_id": "shanghai-pudong-six-street-proxy-demo-2026-08-01",
        "created_at": created_at,
        "display": {
            "city_name": "上海",
            "area_name": "浦东新区六街道",
            "scenario_name": "上海人口与住房空间配置优化代理情景",
            "scope_description": "浦东新区六个相邻街道的聚合代理情景配置与硬约束审计",
            "boundary_label": "上海浦东街道级行政区划，EPSG:4326",
            "map_zoom": 12,
        },
        "planning_horizon_years": 5,
        "cost_unit": "thousand_CNY_2026_planning_horizon",
        "zones": zones,
        "population_groups": groups,
        "housing_options": housing_options,
        "candidate_assignments": candidate_assignments,
        "parameters": {
            "total_public_budget": round(total_households * 145.0, 3),
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
            "osm_building_feature_count": sum(
                int(row["osm_building_feature_count"]) for row in source_rows
            ),
            "osm_service_feature_proxy_count": sum(
                int(row["osm_service_point_proxy_count"])
                + int(row["osm_service_polygon_proxy_count"])
                for row in source_rows
            ),
        },
        "source_trace": [
            {
                "path": str(evidence_path),
                "role": "上海六街道聚合证据、来源、方法和质量边界",
                "evidence_status": "mixed_public_proxy_and_local_geometry",
            },
            *[
                {
                    "path": source.get("local_path") or source.get("url"),
                    "role": source.get("role"),
                    "dataset": source.get("dataset"),
                    "license": source.get("license"),
                    "evidence_status": source.get("evidence_status"),
                }
                for source in evidence.get("sources") or []
            ],
        ],
        "assumptions": [
            "population_group_shares_and_household_sizes_are_engineering_assumptions",
            "housing_units_and_new_supply_are_derived_scenario_capacities_not_inventory",
            "service_capacity_is_a_scenario_assumption_conditioned_on_osm_feature_counts",
            "travel_time_is_a_centroid_distance_proxy_with_fixed_detour_not_routing",
            "all_costs_are_engineering_assumptions_not_fiscal_estimates",
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
            "not_person_level_assignment": True,
            "not_authoritative_population": True,
            "not_observed_housing_inventory": True,
            "not_observed_travel_time": True,
            "not_fiscal_estimate": True,
            "not_policy_recommendation": True,
        },
        "limitations": [
            "selected_six_streets_are_not_the_complete_city_or_pudong",
            "ghsl_2020_population_is_a_one_kilometer_public_proxy",
            "ghsl_built_surface_and_osm_buildings_are_not_housing_inventory",
            "osm_feature_count_is_not_service_capacity",
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
    "DEFAULT_SHANGHAI_BOUNDARY_PATH",
    "DEFAULT_SHANGHAI_EVIDENCE_PATH",
    "build_shanghai_population_housing_proxy_scenario",
]

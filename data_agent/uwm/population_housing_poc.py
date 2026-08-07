"""Build a bounded Chongqing proxy scenario for population/housing optimization."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .population_housing_optimization import POPULATION_HOUSING_INPUT_SCHEMA

DEFAULT_HOUSING_EVIDENCE_PATH = Path(
    "data/uwm_public_proxy/chongqing_central/"
    "traditional_housing_community_chongqing/admin_units.json"
)
DEFAULT_ADMIN_GRAPH_PATH = Path(
    "data/uwm_public_proxy/chongqing_central/"
    "admin_spatial_graph_2026_07_05/uwm_admin_spatial_adjacency_graph.json"
)

DEFAULT_ZONE_IDS = (
    "九龙坡区|九龙镇|77",
    "江北区|观音桥街道|653",
    "渝北区|龙溪街道|696",
    "南岸区|南坪镇|299",
    "江北区|大石坝街道|647",
    "南岸区|花园路街道|143",
)

GROUP_ASSUMPTIONS = (
    {
        "suffix": "worker_family",
        "name": "就业家庭组",
        "population_share": 0.55,
        "persons_per_household": 3.2,
        "service_demand_per_household": 0.75,
        "max_commute_minutes": 60.0,
        "max_relocation_share": 0.20,
        "eligible_housing_types": ["standard", "rental"],
    },
    {
        "suffix": "youth_renter",
        "name": "青年租住组",
        "population_share": 0.25,
        "persons_per_household": 1.5,
        "service_demand_per_household": 0.55,
        "max_commute_minutes": 55.0,
        "max_relocation_share": 0.35,
        "eligible_housing_types": ["rental", "standard"],
    },
    {
        "suffix": "senior_household",
        "name": "老年友好住房组",
        "population_share": 0.20,
        "persons_per_household": 2.0,
        "service_demand_per_household": 1.25,
        "max_commute_minutes": 50.0,
        "max_relocation_share": 0.10,
        "eligible_housing_types": ["accessible", "standard"],
    },
)

HOUSING_ASSUMPTIONS = {
    "standard": {
        "name": "普通住房代理",
        "existing_share": 0.65,
        "new_share": 0.35,
        "new_unit_public_cost": 420.0,
        "activation_public_cost": 18_000.0,
        "public_cost": 12.0,
        "resident_housing_cost": 420.0,
    },
    "rental": {
        "name": "保障/市场租赁住房代理",
        "existing_share": 0.23,
        "new_share": 0.45,
        "new_unit_public_cost": 280.0,
        "activation_public_cost": 14_000.0,
        "public_cost": 55.0,
        "resident_housing_cost": 220.0,
    },
    "accessible": {
        "name": "适老无障碍住房代理",
        "existing_share": 0.12,
        "new_share": 0.20,
        "new_unit_public_cost": 360.0,
        "activation_public_cost": 12_000.0,
        "public_cost": 75.0,
        "resident_housing_cost": 180.0,
    },
}

ZONE_COST_MULTIPLIERS = (1.12, 1.20, 1.08, 1.02, 0.94, 0.98)


def build_chongqing_population_housing_proxy_scenario(
    *,
    housing_evidence_path: Path = DEFAULT_HOUSING_EVIDENCE_PATH,
    admin_graph_path: Path = DEFAULT_ADMIN_GRAPH_PATH,
    created_at: str,
    zone_ids: tuple[str, ...] = DEFAULT_ZONE_IDS,
) -> dict[str, Any]:
    """Create a reproducible 1-2 million person engineering scenario.

    Only administrative identity, population proxy, building morphology, service
    point context, and centroids come from UWM evidence. Household composition,
    housing capacities, costs, service capacity, and travel time are explicit
    scenario assumptions and must not be interpreted as observed values.
    """

    housing_payload = _read_json(housing_evidence_path)
    graph_payload = _read_json(admin_graph_path)
    if housing_payload.get("schema") != "traditional_livability.housing_community_admin_units.v1":
        raise ValueError("unexpected housing evidence schema")
    if graph_payload.get("schema") != "uwm.admin_spatial_adjacency_graph.v1":
        raise ValueError("unexpected admin graph schema")

    evidence_by_id = {
        str(row["admin_unit_id"]): row for row in housing_payload.get("admin_units") or []
    }
    node_by_id = {str(row["unit_id"]): row for row in graph_payload.get("nodes") or []}
    missing = [
        zone_id
        for zone_id in zone_ids
        if zone_id not in evidence_by_id or zone_id not in node_by_id
    ]
    if missing:
        raise ValueError(f"selected UWM zones missing from evidence/graph: {missing}")

    source_rows = [evidence_by_id[zone_id] for zone_id in zone_ids]
    source_population = sum(
        float(row["population_proxy_context"]["downscaled_population"])
        for row in source_rows
    )
    if not 1_000_000 <= source_population <= 2_000_000:
        raise ValueError(
            f"selected proxy population {source_population} is outside the 1-2 million PoC scope"
        )

    groups: list[dict[str, Any]] = []
    zones: list[dict[str, Any]] = []
    housing_options: list[dict[str, Any]] = []
    zone_households: dict[str, int] = {}

    for zone_index, (zone_id, source) in enumerate(
        zip(zone_ids, source_rows, strict=True), start=1
    ):
        population = float(source["population_proxy_context"]["downscaled_population"])
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
                "group_id": f"g-{zone_index:02d}-{assumption['suffix']}",
                "group_name": f"{source['township']}-{assumption['name']}",
                "origin_zone_id": zone_id,
                "households": households,
                "persons_per_household": assumption["persons_per_household"],
                "service_demand_per_household": assumption[
                    "service_demand_per_household"
                ],
                "max_commute_minutes": assumption["max_commute_minutes"],
                "max_relocation_share": assumption["max_relocation_share"],
                "eligible_housing_types": list(assumption["eligible_housing_types"]),
                "population_share_assumption": assumption["population_share"],
                "evidence_status": "scenario_assumption_from_fitted_population_proxy",
            }
            groups.append(group)
            zone_group_rows.append(group)

        household_count = sum(int(group["households"]) for group in zone_group_rows)
        zone_households[zone_id] = household_count
        morphology = source["building_morphology_context"]
        essential_service_count = float(morphology.get("essential_service_count") or 0.0)
        existing_service_ratio = 0.69 + min(essential_service_count, 20.0) * 0.002
        node = node_by_id[zone_id]
        zones.append(
            {
                "zone_id": zone_id,
                "zone_name": f"{source['county']}{source['township']}",
                "county": source["county"],
                "township": source["township"],
                "centroid": node["centroid"],
                "source_population_proxy": population,
                "source_population_status": source["population_proxy_context"][
                    "synthetic_status"
                ],
                "source_building_count": int(morphology["building_count"]),
                "source_floor_count_proxy": int(morphology["floor_count_sum"]),
                "source_essential_service_point_count": essential_service_count,
                "existing_service_capacity": round(
                    household_count * existing_service_ratio, 3
                ),
                "max_service_expansion": round(household_count * 0.20, 3),
                "service_expansion_unit_public_cost": 32.0,
                "service_capacity_evidence_status": (
                    "scenario_assumption_conditioned_on_service_point_proxy"
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
        multiplier = ZONE_COST_MULTIPLIERS[zone_index - 1]
        for housing_type, existing_units, max_new_units in zip(
            housing_types, existing_allocations, new_allocations, strict=True
        ):
            assumption = HOUSING_ASSUMPTIONS[housing_type]
            housing_options.append(
                {
                    "housing_option_id": f"h-{zone_index:02d}-{housing_type}",
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

    zone_map = {str(row["zone_id"]): row for row in zones}
    candidate_assignments: list[dict[str, Any]] = []
    for group in groups:
        origin = zone_map[str(group["origin_zone_id"])]
        for option in housing_options:
            destination = zone_map[str(option["zone_id"])]
            housing_assumption = HOUSING_ASSUMPTIONS[str(option["housing_type"])]
            distance_km = _haversine_km(origin["centroid"], destination["centroid"])
            relocated = str(origin["zone_id"]) != str(destination["zone_id"])
            commute_minutes = (
                15.0 if not relocated else 18.0 + (distance_km / 28.0) * 60.0
            )
            destination_index = zone_ids.index(str(destination["zone_id"]))
            multiplier = ZONE_COST_MULTIPLIERS[destination_index]
            candidate_assignments.append(
                {
                    "group_id": group["group_id"],
                    "housing_option_id": option["housing_option_id"],
                    "allowed": True,
                    "distance_km": round(distance_km, 3),
                    "commute_minutes": round(commute_minutes, 3),
                    "commute_generalized_cost": round(commute_minutes * 0.35, 3),
                    "resident_housing_cost": round(
                        float(housing_assumption["resident_housing_cost"])
                        * multiplier,
                        3,
                    ),
                    "public_cost": round(
                        float(housing_assumption["public_cost"]) * multiplier, 3
                    ),
                    "relocation_cost": 28.0 if relocated else 0.0,
                    "evidence_status": (
                        "centroid_distance_and_cost_scenario_assumption"
                    ),
                }
            )

    total_households = sum(int(group["households"]) for group in groups)
    modeled_people = sum(
        int(group["households"]) * float(group["persons_per_household"])
        for group in groups
    )
    return {
        "schema": POPULATION_HOUSING_INPUT_SCHEMA,
        "scenario_id": "chongqing-central-six-zone-proxy-poc-2026-07-31",
        "created_at": created_at,
        "planning_horizon_years": 5,
        "cost_unit": "thousand_CNY_2026_planning_horizon",
        "zones": zones,
        "population_groups": groups,
        "housing_options": housing_options,
        "candidate_assignments": candidate_assignments,
        "parameters": {
            "total_public_budget": round(total_households * 125.0, 3),
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
        },
        "source_trace": [
            {
                "path": str(housing_evidence_path),
                "role": "zone identity, fitted population, building morphology and service points",
                "evidence_status": "mixed_real_and_fitted_proxy",
            },
            {
                "path": str(admin_graph_path),
                "role": "zone centroid and administrative topology context",
                "evidence_status": "derived_real_geometry",
            },
        ],
        "assumptions": [
            "population_group_shares_and_household_sizes_are_engineering_assumptions",
            "housing_units_and_new_supply_are_derived_scenario_capacities_not_inventory",
            "service_capacity_is_a_scenario_assumption_conditioned_on_poi_counts",
            "travel_time_is_a_centroid_distance_proxy_not_observed_network_impedance",
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
            "selected_six_zones_are_not_the_complete_central_city",
            "fitted_population_proxy_not_census_microdata",
            "building_floor_proxy_not_housing_unit_inventory",
            "poi_count_not_service_capacity",
            "centroid_distance_not_observed_commute_time",
            "assumed_costs_not_budget_records",
            "weighted_scenarios_not_complete_pareto_frontier",
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


def _allocate_integer_total(total: int, weights: list[float]) -> list[int]:
    if total < 0 or not weights or any(weight < 0 for weight in weights):
        raise ValueError("invalid integer allocation inputs")
    weight_sum = sum(weights)
    if weight_sum <= 0:
        raise ValueError("integer allocation weights must have positive sum")
    raw = [total * weight / weight_sum for weight in weights]
    allocated = [math.floor(value) for value in raw]
    remainder = total - sum(allocated)
    order = sorted(
        range(len(raw)),
        key=lambda index: (raw[index] - allocated[index], -index),
        reverse=True,
    )
    for index in order[:remainder]:
        allocated[index] += 1
    return allocated


def _haversine_km(origin: dict[str, Any], destination: dict[str, Any]) -> float:
    lon1 = math.radians(float(origin["lon"]))
    lat1 = math.radians(float(origin["lat"]))
    lon2 = math.radians(float(destination["lon"]))
    lat2 = math.radians(float(destination["lat"]))
    delta_lon = lon2 - lon1
    delta_lat = lat2 - lat1
    value = (
        math.sin(delta_lat / 2.0) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2.0) ** 2
    )
    return 6371.0088 * 2.0 * math.asin(min(1.0, math.sqrt(value)))


__all__ = [
    "DEFAULT_ADMIN_GRAPH_PATH",
    "DEFAULT_HOUSING_EVIDENCE_PATH",
    "DEFAULT_ZONE_IDS",
    "build_chongqing_population_housing_proxy_scenario",
]

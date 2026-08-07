"""Deterministic coverage and decision closure for livability requirement S2."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any

from pyproj import CRS, Transformer
from shapely.geometry import mapping, shape
from shapely.ops import transform, unary_union

from .business_rules import facility_criticality, load_business_rules


SCHEMA = "uwm.livability_s2.business_assessment.v1"
SUPPORTED_ACTIONS = {
    "change_land_use",
    "add_facility",
    "remove_facility",
}


def assess_s2_business_impact(
    *,
    parcels: dict[str, Any],
    facilities: dict[str, Any],
    parcel_id: str,
    action_type: str,
    facility_class: str | None,
    facility_id: str | None,
    service_radius_m: float | None,
    radius_evidence_source: str | None,
    critical_facility: bool,
    facility_inventory_complete: bool,
    transition_status: str,
    baseline_graph: dict[str, Any] | None = None,
    intervention_graph: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare coverage from baseline and action-written future graph states."""
    parcel_features = deepcopy(parcels.get("features") or [])
    facility_features = deepcopy(facilities.get("features") or [])
    target = next(
        (feature for feature in parcel_features if str(feature.get("id")) == parcel_id),
        None,
    )
    if target is None:
        raise ValueError("parcel_not_found")

    planning_area_id = str((target.get("properties") or {}).get("planning_area_id") or "")
    distance_crs = (target.get("properties") or {}).get("distance_crs")
    blockers = _input_blockers(
        action_type=action_type,
        facility_class=facility_class,
        facility_id=facility_id,
        service_radius_m=service_radius_m,
        radius_evidence_source=radius_evidence_source,
        distance_crs=distance_crs,
    )
    if action_type in {"add_facility", "remove_facility"} and (
        not isinstance(baseline_graph, dict)
        or not isinstance(intervention_graph, dict)
    ):
        blockers.append("baseline_and_intervention_state_graphs_required")
    if blockers:
        return _unresolved(
            action_type=action_type,
            parcel_id=parcel_id,
            planning_area_id=planning_area_id,
            facility_class=facility_class,
            service_radius_m=service_radius_m,
            radius_evidence_source=radius_evidence_source,
            blockers=blockers,
            facility_inventory_complete=facility_inventory_complete,
        )

    transformer_to_metric = Transformer.from_crs(
        CRS.from_epsg(4326), CRS.from_user_input(distance_crs), always_xy=True
    )
    transformer_to_wgs84 = Transformer.from_crs(
        CRS.from_user_input(distance_crs), CRS.from_epsg(4326), always_xy=True
    )
    demand_units = _demand_units(
        parcel_features,
        planning_area_id=planning_area_id,
        distance_crs=str(distance_crs),
        transformer=transformer_to_metric,
    )
    if not demand_units:
        return _unresolved(
            action_type=action_type,
            parcel_id=parcel_id,
            planning_area_id=planning_area_id,
            facility_class=facility_class,
            service_radius_m=service_radius_m,
            radius_evidence_source=radius_evidence_source,
            blockers=["parcel_demand_units_missing"],
            facility_inventory_complete=facility_inventory_complete,
        )

    selected_facility_class = str(facility_class or "")
    effective_critical, criticality_source = facility_criticality(
        selected_facility_class, critical_facility
    )
    baseline_facilities = _select_graph_facilities(
        facility_features,
        graph=baseline_graph or {},
        planning_area_id=planning_area_id,
        facility_class=selected_facility_class,
        distance_crs=str(distance_crs),
        transformer=transformer_to_metric,
    )
    intervention_facilities = _select_graph_facilities(
        facility_features,
        graph=intervention_graph or {},
        planning_area_id=planning_area_id,
        facility_class=selected_facility_class,
        distance_crs=str(distance_crs),
        transformer=transformer_to_metric,
    )
    action_evidence: dict[str, Any]
    if action_type == "add_facility":
        added_ids = sorted(
            {row["facility_id"] for row in intervention_facilities}
            - {row["facility_id"] for row in baseline_facilities}
        )
        if len(added_ids) != 1:
            return _unresolved(
                action_type=action_type,
                parcel_id=parcel_id,
                planning_area_id=planning_area_id,
                facility_class=selected_facility_class,
                service_radius_m=service_radius_m,
                radius_evidence_source=radius_evidence_source,
                blockers=["facility_add_write_back_not_exactly_one"],
                facility_inventory_complete=facility_inventory_complete,
            )
        action_evidence = {
            "scenario_facility_id": added_ids[0],
            "placement_method": "target_parcel_representative_point",
        }
    else:
        removed_ids = sorted(
            {row["facility_id"] for row in baseline_facilities}
            - {row["facility_id"] for row in intervention_facilities}
        )
        if removed_ids != [str(facility_id or "")]:
            return _unresolved(
                action_type=action_type,
                parcel_id=parcel_id,
                planning_area_id=planning_area_id,
                facility_class=selected_facility_class,
                service_radius_m=service_radius_m,
                radius_evidence_source=radius_evidence_source,
                blockers=["facility_remove_write_back_mismatch"],
                facility_inventory_complete=facility_inventory_complete,
            )
        action_evidence = {"removed_facility_id": removed_ids[0]}

    baseline = _coverage_snapshot(
        facilities=baseline_facilities,
        demand_units=demand_units,
        service_radius_m=float(service_radius_m),
        transformer_to_wgs84=transformer_to_wgs84,
    )
    intervention = _coverage_snapshot(
        facilities=intervention_facilities,
        demand_units=demand_units,
        service_radius_m=float(service_radius_m),
        transformer_to_wgs84=transformer_to_wgs84,
    )
    delta = round(
        intervention["coverage_percent"] - baseline["coverage_percent"], 6
    )
    newly_covered = sorted(
        set(intervention["covered_parcel_ids"]) - set(baseline["covered_parcel_ids"])
    )
    newly_uncovered = sorted(
        set(baseline["covered_parcel_ids"]) - set(intervention["covered_parcel_ids"])
    )
    recommendation, rules = _recommendation(
        action_type=action_type,
        delta=delta,
        critical_facility=effective_critical,
        transition_status=transition_status,
        facility_inventory_complete=facility_inventory_complete,
        radius_evidence_source=str(radius_evidence_source),
    )
    warnings = ["facility_inventory_incomplete"] if not facility_inventory_complete else []
    if radius_evidence_source == "user_scenario_assumption":
        warnings.append("service_radius_is_user_scenario_assumption")
    result = {
        "schema": SCHEMA,
        "assessment_method": "parcel_spatial_coverage_proxy",
        "demand_basis": "parcel_representative_point_equal_weight_proxy",
        "population_coverage_claim": False,
        "statutory_service_radius_claim": radius_evidence_source == "authoritative_profile",
        "action": {
            "action_type": action_type,
            "parcel_id": parcel_id,
            "planning_area_id": planning_area_id,
            "facility_class": selected_facility_class,
            "facility_id": facility_id,
            "critical_facility": effective_critical,
            "criticality_source": criticality_source,
            **action_evidence,
        },
        "parameters": {
            "service_radius_m": float(service_radius_m),
            "radius_evidence_source": radius_evidence_source,
            "distance_crs": str(distance_crs),
        },
        "baseline": baseline,
        "intervention": intervention,
        "coverage_delta_percentage_points": delta,
        "newly_covered_parcel_ids": newly_covered,
        "newly_uncovered_parcel_ids": newly_uncovered,
        "recommendation": recommendation,
        "triggered_rules": rules,
        "blockers": [],
        "completeness_warnings": warnings,
        "evidence_level": (
            "authoritative_static_assessment"
            if facility_inventory_complete
            and radius_evidence_source == "authoritative_profile"
            else "bounded_scenario_proxy"
        ),
        "business_rule_version": load_business_rules()["version"],
        "claim_boundary": (
            "Real parcel geometry and explicit radius are used. The percentage is an "
            "equal-weight parcel spatial coverage proxy, not population coverage, "
            "network accessibility or a planning approval."
        ),
    }
    result["assessment_digest"] = _digest(result)
    return result


def _input_blockers(
    *,
    action_type: str,
    facility_class: str | None,
    facility_id: str | None,
    service_radius_m: float | None,
    radius_evidence_source: str | None,
    distance_crs: Any,
) -> list[str]:
    blockers = []
    if action_type not in SUPPORTED_ACTIONS:
        blockers.append("unsupported_business_action")
    if action_type == "change_land_use":
        blockers.append("facility_action_not_defined_for_land_use_change")
    if action_type in {"add_facility", "remove_facility"} and not facility_class:
        blockers.append("facility_class_required")
    if action_type == "remove_facility" and not facility_id:
        blockers.append("facility_id_required")
    if not isinstance(service_radius_m, (int, float)) or isinstance(service_radius_m, bool) or service_radius_m <= 0:
        blockers.append("positive_service_radius_required")
    if radius_evidence_source not in {"authoritative_profile", "user_scenario_assumption"}:
        blockers.append("radius_evidence_source_required")
    if not distance_crs:
        blockers.append("distance_crs_missing")
    return blockers


def _demand_units(
    parcels: list[dict[str, Any]],
    *,
    planning_area_id: str,
    distance_crs: str,
    transformer: Transformer,
) -> list[dict[str, Any]]:
    demand_units = []
    for feature in parcels:
        properties = feature.get("properties") or {}
        if str(properties.get("planning_area_id") or "") != planning_area_id:
            continue
        if str(properties.get("distance_crs") or "") != distance_crs:
            continue
        geometry = transform(transformer.transform, shape(feature["geometry"]))
        demand_units.append(
            {
                "parcel_id": str(feature.get("id")),
                "metric_geometry": geometry.representative_point(),
            }
        )
    return demand_units


def _select_graph_facilities(
    facilities: list[dict[str, Any]],
    *,
    graph: dict[str, Any],
    planning_area_id: str,
    facility_class: str,
    distance_crs: str,
    transformer: Transformer,
) -> list[dict[str, Any]]:
    features_by_id = {str(feature.get("id")): feature for feature in facilities}
    selected = []
    for node in graph.get("nodes") or []:
        if node.get("node_type") != "facility":
            continue
        facility_id = str(node.get("node_id") or "")
        feature = features_by_id.get(facility_id) or {}
        properties = feature.get("properties") or {}
        matching_areas = {str(value) for value in properties.get("matching_planning_area_ids") or []}
        node_area = str(node.get("planning_area_id") or "")
        belongs = (
            node_area == planning_area_id
            or str(properties.get("planning_area_id") or "") == planning_area_id
            or planning_area_id in matching_areas
        )
        canonical_class = str(
            node.get("canonical_class") or properties.get("canonical_class") or ""
        )
        if not belongs or canonical_class != facility_class:
            continue
        node_distance_crs = str(
            node.get("distance_crs") or properties.get("distance_crs") or ""
        )
        if node_distance_crs != distance_crs:
            continue
        geometry = node.get("display_geometry_wgs84") or feature.get("geometry")
        if not isinstance(geometry, dict):
            continue
        selected.append(
            {
                "facility_id": facility_id,
                "name": node.get("name") or properties.get("name") or "情景新增设施",
                "canonical_class": canonical_class,
                "metric_geometry": transform(transformer.transform, shape(geometry)),
                "source": node.get("scenario_source")
                or properties.get("source_dataset_id")
                or "scenario_action_state_graph",
            }
        )
    return sorted(selected, key=lambda row: row["facility_id"])


def _coverage_snapshot(
    *,
    facilities: list[dict[str, Any]],
    demand_units: list[dict[str, Any]],
    service_radius_m: float,
    transformer_to_wgs84: Transformer,
) -> dict[str, Any]:
    service_areas = [row["metric_geometry"].buffer(service_radius_m) for row in facilities]
    service_union = unary_union(service_areas) if service_areas else None
    covered_ids = [
        row["parcel_id"]
        for row in demand_units
        if service_union is not None and service_union.covers(row["metric_geometry"])
    ]
    total = len(demand_units)
    coverage_percent = round(len(covered_ids) / total * 100.0, 6) if total else 0.0
    return {
        "facility_count": len(facilities),
        "facility_ids": [row["facility_id"] for row in facilities],
        "demand_parcel_count": total,
        "covered_parcel_count": len(covered_ids),
        "uncovered_parcel_count": total - len(covered_ids),
        "coverage_percent": coverage_percent,
        "covered_parcel_ids": sorted(covered_ids),
        "service_areas": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "id": f"service_area:{row['facility_id']}",
                    "geometry": mapping(
                        transform(transformer_to_wgs84.transform, area)
                    ),
                    "properties": {
                        "facility_id": row["facility_id"],
                        "facility_class": row["canonical_class"],
                        "service_radius_m": service_radius_m,
                        "source": row["source"],
                    },
                }
                for row, area in zip(facilities, service_areas)
            ],
        },
    }


def _recommendation(
    *,
    action_type: str,
    delta: float,
    critical_facility: bool,
    transition_status: str,
    facility_inventory_complete: bool,
    radius_evidence_source: str,
) -> tuple[str, list[str]]:
    if action_type == "remove_facility" and critical_facility and delta < 0:
        return "disagree", ["critical_facility_coverage_proxy_decreases"]
    evidence_is_authoritative = (
        facility_inventory_complete and radius_evidence_source == "authoritative_profile"
    )
    if delta >= 0 and transition_status != "unresolved" and evidence_is_authoritative:
        return "agree", ["coverage_not_decreased", "land_use_transition_resolved"]
    rules = ["coverage_not_decreased" if delta >= 0 else "coverage_decreased"]
    if transition_status == "unresolved":
        rules.append("land_use_transition_requires_review")
    if not facility_inventory_complete:
        rules.append("incomplete_facility_inventory_blocks_formal_agreement")
    if radius_evidence_source == "user_scenario_assumption":
        rules.append("scenario_radius_blocks_statutory_claim")
    return "conditional_agree", rules


def _unresolved(
    *,
    action_type: str,
    parcel_id: str,
    planning_area_id: str,
    facility_class: str | None,
    service_radius_m: float | None,
    radius_evidence_source: str | None,
    blockers: list[str],
    facility_inventory_complete: bool,
) -> dict[str, Any]:
    result = {
        "schema": SCHEMA,
        "assessment_method": "parcel_spatial_coverage_proxy",
        "demand_basis": "parcel_representative_point_equal_weight_proxy",
        "population_coverage_claim": False,
        "statutory_service_radius_claim": False,
        "action": {
            "action_type": action_type,
            "parcel_id": parcel_id,
            "planning_area_id": planning_area_id,
            "facility_class": facility_class,
        },
        "parameters": {
            "service_radius_m": service_radius_m,
            "radius_evidence_source": radius_evidence_source,
        },
        "baseline": None,
        "intervention": None,
        "coverage_delta_percentage_points": None,
        "newly_covered_parcel_ids": [],
        "newly_uncovered_parcel_ids": [],
        "recommendation": "evidence_insufficient",
        "triggered_rules": ["required_evidence_missing_fail_closed"],
        "blockers": sorted(set(blockers)),
        "completeness_warnings": (
            [] if facility_inventory_complete else ["facility_inventory_incomplete"]
        ),
        "evidence_level": "insufficient",
        "business_rule_version": load_business_rules()["version"],
        "claim_boundary": "No coverage or approval conclusion is produced without explicit facility action, radius evidence and projected geometry.",
    }
    result["assessment_digest"] = _digest(result)
    return result


def _digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()

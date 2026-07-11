from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from shapely.geometry import mapping, shape
from shapely.ops import unary_union


SCHEMA = "uwm.traditional_livability.s1_fp_assessment.v1"


def _feature_collection(features=None):
    return {"type": "FeatureCollection", "features": list(features or [])}


def _feature(feature_id: str, geometry, properties: Mapping[str, Any]):
    return {
        "type": "Feature",
        "id": feature_id,
        "geometry": mapping(geometry),
        "properties": deepcopy(dict(properties)),
    }


def _compare(value: float, comparator: str, threshold: float) -> bool:
    return {
        ">=": value >= threshold,
        "<=": value <= threshold,
        ">": value > threshold,
        "<": value < threshold,
        "==": value == threshold,
    }[comparator]


def _unresolved(blockers, *, metric=None, warnings=None):
    return {
        "schema": SCHEMA,
        "dimension": "FP",
        "status": "unresolved",
        "observed_value": None,
        "unit": metric.get("unit") if isinstance(metric, Mapping) else None,
        "threshold": metric.get("threshold") if isinstance(metric, Mapping) else None,
        "comparator": metric.get("comparator") if isinstance(metric, Mapping) else None,
        "method": metric.get("spatial_method") if isinstance(metric, Mapping) else None,
        "method_parameters": {},
        "evidence": {},
        "blockers": list(dict.fromkeys(blockers)),
        "completeness_warnings": list(dict.fromkeys(warnings or [])),
        "max_claim_level": "unresolved",
        "geojson": {
            "service_areas": _feature_collection(),
            "covered_demand_units": _feature_collection(),
            "uncovered_demand_units": _feature_collection(),
        },
    }


def evaluate_fp(
    *,
    facilities: list[Mapping[str, Any]],
    demand_units: list[Mapping[str, Any]],
    profile: Mapping[str, Any],
    admin_code: str,
    complete_facility_inventory: bool = True,
) -> dict[str, Any]:
    profile_copy = deepcopy(dict(profile))
    metric = next(
        (deepcopy(dict(row)) for row in profile_copy.get("metrics", []) if isinstance(row, Mapping) and row.get("dimension") == "FP"),
        None,
    )
    if profile_copy.get("status") != "valid" or metric is None:
        return _unresolved(["valid_fp_profile_required"], metric=metric)
    if metric.get("spatial_method") == "network_service_area":
        return _unresolved(["authoritative_network_missing"], metric=metric)
    if metric.get("spatial_method") != "euclidean_service_radius":
        return _unresolved(["fp_spatial_method_not_implemented"], metric=metric)
    radius = metric.get("service_radius_m")
    distance_crs = metric.get("distance_crs")
    if not isinstance(radius, (int, float)) or isinstance(radius, bool) or radius <= 0:
        return _unresolved(["authoritative_service_radius_required"], metric=metric)

    selected_facilities = []
    blockers = []
    for row in deepcopy(facilities):
        if row.get("admin_code") != admin_code or row.get("canonical_class") != profile_copy.get("standard_class_id"):
            continue
        if row.get("metric_crs") != distance_crs:
            blockers.append("facility_metric_crs_mismatch")
            continue
        try:
            selected_facilities.append((row, shape(row["metric_geometry"])))
        except (AttributeError, KeyError, TypeError, ValueError):
            blockers.append("facility_metric_geometry_invalid")
    selected_demand = []
    for row in deepcopy(demand_units):
        if row.get("admin_code") != admin_code:
            continue
        population = row.get("population")
        if not isinstance(population, (int, float)) or isinstance(population, bool) or population < 0:
            blockers.append("demand_population_invalid")
            continue
        if row.get("metric_crs") != distance_crs:
            blockers.append("demand_metric_crs_mismatch")
            continue
        try:
            selected_demand.append((row, shape(row["metric_geometry"])))
        except (AttributeError, KeyError, TypeError, ValueError):
            blockers.append("demand_metric_geometry_invalid")
    if blockers:
        return _unresolved(blockers, metric=metric)
    if not selected_demand:
        return _unresolved(["demand_units_missing"], metric=metric)

    service_geometries = [geometry.buffer(float(radius)) for _, geometry in selected_facilities]
    service_union = unary_union(service_geometries) if service_geometries else None
    total_population = sum(float(row["population"]) for row, _ in selected_demand)
    if total_population <= 0:
        return _unresolved(["total_demand_population_must_be_positive"], metric=metric)
    covered = []
    uncovered = []
    covered_population = 0.0
    for row, geometry in selected_demand:
        is_covered = service_union is not None and service_union.intersects(geometry)
        target = covered if is_covered else uncovered
        target.append((row, geometry))
        if is_covered:
            covered_population += float(row["population"])
    value = round(covered_population / total_population * 100.0, 6)
    threshold = float(metric["threshold"])
    status = "meets" if _compare(value, metric["comparator"], threshold) else "does_not_meet"
    warnings = [] if complete_facility_inventory else ["facility_inventory_incomplete"]
    return {
        "schema": SCHEMA,
        "dimension": "FP",
        "profile_id": profile_copy.get("profile_id"),
        "standard_class_id": profile_copy.get("standard_class_id"),
        "status": status,
        "observed_value": value,
        "unit": metric.get("unit"),
        "threshold": threshold,
        "comparator": metric.get("comparator"),
        "gap_to_threshold": round(value - threshold, 6),
        "method": metric.get("spatial_method"),
        "method_parameters": {"service_radius_m": float(radius), "distance_crs": distance_crs},
        "evidence": {
            "facility_ids": [row.get("facility_id") for row, _ in selected_facilities],
            "covered_demand_unit_ids": [row.get("demand_unit_id") for row, _ in covered],
            "uncovered_demand_unit_ids": [row.get("demand_unit_id") for row, _ in uncovered],
            "covered_population": int(covered_population) if covered_population.is_integer() else covered_population,
            "total_population": int(total_population) if total_population.is_integer() else total_population,
        },
        "blockers": [],
        "completeness_warnings": warnings,
        "max_claim_level": "authoritative_static_assessment" if complete_facility_inventory else "bounded_sample_diagnostic",
        "geojson": {
            "service_areas": _feature_collection(
                _feature(f"service-area:{row.get('facility_id')}", geometry, {"facility_id": row.get("facility_id")})
                for (row, _), geometry in zip(selected_facilities, service_geometries)
            ),
            "covered_demand_units": _feature_collection(
                _feature(f"covered:{row.get('demand_unit_id')}", geometry, row) for row, geometry in covered
            ),
            "uncovered_demand_units": _feature_collection(
                _feature(f"uncovered:{row.get('demand_unit_id')}", geometry, row) for row, geometry in uncovered
            ),
        },
    }

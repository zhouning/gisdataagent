"""Admin-level service accessibility proxy panel from OSM service points."""

from __future__ import annotations

from collections import Counter
from typing import Any

from shapely.geometry import Point, box, shape


UWM_ADMIN_SERVICE_ACCESSIBILITY_PANEL_SCHEMA = "uwm.admin_service_accessibility_panel.v1"


def build_admin_service_accessibility_panel(
    *,
    admin_features: list[dict[str, Any]],
    service_proxy: dict[str, Any],
    panel_id: str,
    created_at: str,
) -> dict[str, Any]:
    """Assign OSM service sample points to admin units intersecting the OSM bbox."""

    bbox_geom = _bbox_geometry(service_proxy.get("requested_bbox") or [])
    service_points = [_service_point(row) for row in service_proxy.get("service_points") or []]
    service_points = [row for row in service_points if row]
    rows = []
    for index, feature in enumerate(admin_features):
        geom = shape(feature.get("geometry"))
        if not geom.intersects(bbox_geom):
            continue
        props = feature.get("properties") or {}
        admin_unit_id = str(props.get("admin_unit_id") or _fallback_admin_unit_id(props, index))
        assigned = [point for point in service_points if geom.covers(point["geometry"])]
        rows.append(_admin_service_row(admin_unit_id, props, assigned))
    units_with_points = len([row for row in rows if row["service_point_count"] > 0])
    limitations = sorted(
        {
            limitation
            for limitation in (service_proxy.get("limitations") or [])
            if isinstance(limitation, str)
        }
        | {
            "bbox_limited_sample_gap_not_true_absence",
            "not_a_network_travel_time_accessibility_surface",
            "admin_service_counts_depend_on_osm_tag_completeness",
        }
    )
    return {
        "schema": UWM_ADMIN_SERVICE_ACCESSIBILITY_PANEL_SCHEMA,
        "version": "0.1",
        "panel_id": panel_id,
        "created_at": created_at,
        "source_dataset_ids": [
            "osm_services_geometry_public_proxy",
            "chongqing_township_admin_units_local",
        ],
        "requested_bbox": service_proxy.get("requested_bbox"),
        "bbox_admin_count": len(rows),
        "admin_units_with_service_points": units_with_points,
        "service_point_count": len(service_points),
        "admin_service_rows": rows,
        "summary": {
            "bbox_admin_count": len(rows),
            "admin_units_with_service_points": units_with_points,
            "admin_units_without_sample_points": len(rows) - units_with_points,
            "essential_service_count": sum(row["essential_service_count"] for row in rows),
        },
        "claim_boundary": {
            "max_claim_level": "bounded_support",
            "reason": "Admin service panel is a bounded OSM bbox sample, not a complete accessibility surface.",
        },
        "limitations": limitations,
        "empirical_superiority_claim": False,
    }


def validate_admin_service_accessibility_panel(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate admin service accessibility panel."""

    errors: list[str] = []
    if not isinstance(payload, dict):
        return {"valid": False, "errors": ["payload must be a JSON object"]}
    if payload.get("schema") != UWM_ADMIN_SERVICE_ACCESSIBILITY_PANEL_SCHEMA:
        errors.append(f"schema must be {UWM_ADMIN_SERVICE_ACCESSIBILITY_PANEL_SCHEMA}")
    for key in [
        "panel_id",
        "source_dataset_ids",
        "bbox_admin_count",
        "service_point_count",
        "admin_service_rows",
        "claim_boundary",
        "limitations",
    ]:
        if key not in payload:
            errors.append(f"{key} is required")
    if payload.get("empirical_superiority_claim") is not False:
        errors.append("empirical_superiority_claim must be false for OSM bbox sample panel")
    claim = payload.get("claim_boundary") or {}
    if not isinstance(claim, dict) or not claim.get("max_claim_level"):
        errors.append("claim_boundary.max_claim_level is required")
    return {"valid": not errors, "errors": errors}


def _admin_service_row(
    admin_unit_id: str,
    props: dict[str, Any],
    assigned_points: list[dict[str, Any]],
) -> dict[str, Any]:
    categories = Counter(point["service_category"] for point in assigned_points)
    service_count = len(assigned_points)
    sample_gap = "no_osm_points_in_bbox_sample" if service_count == 0 else ""
    return {
        "admin_unit_id": admin_unit_id,
        "county": str(props.get("county") or ""),
        "township": str(props.get("township") or ""),
        "service_point_count": service_count,
        "essential_service_count": categories["healthcare"] + categories["education"],
        "healthcare_count": categories["healthcare"],
        "education_count": categories["education"],
        "food_retail_count": categories["food_retail"],
        "finance_count": categories["finance"],
        "mobility_parking_count": categories["mobility_parking"],
        "civic_public_count": categories["civic_public"],
        "recreation_count": categories["recreation"],
        "other_service_count": categories["other_service"],
        "sample_gap_flag": sample_gap,
        "interpretable_as_true_service_absence": False if sample_gap else None,
    }


def _service_point(row: dict[str, Any]) -> dict[str, Any]:
    lat = _float(row.get("latitude"))
    lon = _float(row.get("longitude"))
    if lat is None or lon is None:
        return {}
    return {
        "geometry": Point(lon, lat),
        "service_category": str(row.get("service_category") or "other_service"),
    }


def _bbox_geometry(bbox: list[Any]) -> Any:
    if len(bbox) != 4:
        raise ValueError("requested_bbox must be [lat_min, lon_min, lat_max, lon_max]")
    lat_min, lon_min, lat_max, lon_max = [_float(value) for value in bbox]
    if None in {lat_min, lon_min, lat_max, lon_max}:
        raise ValueError("requested_bbox values must be numeric")
    return box(lon_min, lat_min, lon_max, lat_max)


def _fallback_admin_unit_id(props: dict[str, Any], index: int) -> str:
    county = str(props.get("county") or "")
    township = str(props.get("township") or "")
    return f"{county}|{township}|{index}"


def _float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

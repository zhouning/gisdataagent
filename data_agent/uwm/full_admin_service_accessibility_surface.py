"""Full-admin service accessibility surface from local POI and road assets."""

from __future__ import annotations

import math
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd


UWM_FULL_ADMIN_SERVICE_ACCESSIBILITY_SURFACE_SCHEMA = (
    "uwm.full_admin_service_accessibility_surface.v1"
)

SERVICE_CATEGORIES = [
    "healthcare",
    "education",
    "food_retail",
    "finance",
    "mobility_transport",
    "civic_public",
    "recreation",
    "lodging",
    "other_service",
]

ESSENTIAL_SERVICE_CATEGORIES = {"healthcare", "education"}


def build_full_admin_service_accessibility_surface(
    *,
    admin_units: gpd.GeoDataFrame,
    poi_points: gpd.GeoDataFrame,
    roads: gpd.GeoDataFrame,
    surface_id: str,
    created_at: str,
    source_refs: dict[str, str],
    experiment_scope: str = "full_admin_graph",
    source_feature_counts: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Build a complete admin service surface from full local POI and road layers."""

    admin = _normalise_admin_units(admin_units)
    poi = _normalise_poi_points(poi_points)
    road = _normalise_roads(roads)
    counts = {
        "admin_units": len(admin),
        "poi_points": len(poi),
        "roads": len(road),
    }
    counts.update({key: _int(value) for key, value in (source_feature_counts or {}).items()})

    point_counts = _service_counts_by_admin(admin, poi)
    nearest = _nearest_essential_service_by_admin(admin, poi)
    road_context = _road_context_by_admin(admin, road)

    rows = []
    for admin_row in admin.drop(columns="geometry").to_dict("records"):
        admin_unit_id = str(admin_row["admin_unit_id"])
        services = point_counts.get(admin_unit_id, {})
        roads_for_admin = road_context.get(admin_unit_id, {})
        nearest_for_admin = nearest.get(admin_unit_id, {})
        row = _surface_row(
            admin_row,
            services,
            roads_for_admin,
            nearest_for_admin,
        )
        rows.append(row)

    _score_rows(rows)
    rows.sort(key=lambda item: item["service_accessibility_score"], reverse=True)

    service_missing_count = sum(
        1 for row in rows if row["service_coverage_status"] != "covered_by_full_local_surface"
    )
    supported_claim = (
        "full_admin_service_accessibility_surface_covers_all_admin_units_from_local_poi_and_road_assets"
        if len(rows) == len(admin) and service_missing_count == 0
        else "no_full_admin_service_accessibility_surface_claim_supported"
    )
    return {
        "schema": UWM_FULL_ADMIN_SERVICE_ACCESSIBILITY_SURFACE_SCHEMA,
        "version": "0.1",
        "surface_id": surface_id,
        "created_at": created_at,
        "experiment_scope": experiment_scope,
        "source_dataset_ids": [
            "chongqing_township_admin_units_local",
            "gaode_poi_2024",
            "chongqing_osm_roads_2021",
        ],
        "source_refs": source_refs,
        "source_feature_counts": counts,
        "admin_unit_count": len(rows),
        "total_service_point_count": _int(sum(row["service_point_count"] for row in rows)),
        "total_essential_service_count": _int(
            sum(row["essential_service_count"] for row in rows)
        ),
        "coverage": {
            "surface_type": "full_admin_local_poi_road_accessibility_surface",
            "service_missing_admin_count": service_missing_count,
            "admin_units_with_service_points": sum(
                row["service_point_count"] > 0 for row in rows
            ),
            "admin_units_with_essential_service_points": sum(
                row["essential_service_count"] > 0 for row in rows
            ),
            "admin_units_with_road_context": sum(row["road_segment_count"] > 0 for row in rows),
            "admin_units_with_accessibility_score": sum(
                row["service_accessibility_score"] >= 0.0 for row in rows
            ),
        },
        "admin_service_rows": rows,
        "supported_claim": supported_claim,
        "claim_boundary": {
            "max_claim_level": "bounded_support"
            if supported_claim
            == "full_admin_service_accessibility_surface_covers_all_admin_units_from_local_poi_and_road_assets"
            else "not_for_claim",
            "reason": (
                "Full-admin service accessibility surface uses local POI and OSM road "
                "geometry for complete state coverage; travel time remains a road-speed "
                "proxy, not observed trip-time or policy outcome evidence."
            ),
        },
        "limitations": [
            "gaode_poi_category_completeness_not_authoritative_service_inventory",
            "road_speed_uses_osm_maxspeed_or_class_defaults_not_observed_congestion",
            "nearest_service_travel_time_is_network_proxy_not_measured_trip_time",
            "not_observed_policy_outcome",
            "source_license_and_redistribution_terms_pending",
        ],
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
    }


def validate_full_admin_service_accessibility_surface(
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Validate the full-admin service accessibility surface contract."""

    errors: list[str] = []
    if not isinstance(payload, dict):
        return {"valid": False, "errors": ["payload must be a JSON object"]}
    if payload.get("schema") != UWM_FULL_ADMIN_SERVICE_ACCESSIBILITY_SURFACE_SCHEMA:
        errors.append(
            f"schema must be {UWM_FULL_ADMIN_SERVICE_ACCESSIBILITY_SURFACE_SCHEMA}"
        )
    for key in [
        "surface_id",
        "experiment_scope",
        "source_dataset_ids",
        "source_feature_counts",
        "admin_unit_count",
        "coverage",
        "admin_service_rows",
        "claim_boundary",
        "limitations",
    ]:
        if key not in payload:
            errors.append(f"{key} is required")
    rows = payload.get("admin_service_rows") or []
    if isinstance(rows, list) and _int(payload.get("admin_unit_count")) != len(rows):
        errors.append("admin_unit_count must equal admin_service_rows length")
    coverage = payload.get("coverage") or {}
    if _int(coverage.get("service_missing_admin_count")) != 0:
        errors.append("service_missing_admin_count must be 0 for the full surface")
    if payload.get("observed_policy_outcome_superiority_claim") is not False:
        errors.append("observed_policy_outcome_superiority_claim must be false")
    if payload.get("empirical_superiority_claim") is not False:
        errors.append("empirical_superiority_claim must be false")
    for row in rows if isinstance(rows, list) else []:
        for key in [
            "admin_unit_id",
            "service_point_count",
            "essential_service_count",
            "nearest_essential_service_distance_m",
            "estimated_nearest_essential_travel_time_min",
            "road_segment_count",
            "road_length_km",
            "service_accessibility_score",
            "service_coverage_status",
        ]:
            if key not in row:
                errors.append(f"admin_service_rows[].{key} is required")
                break
    return {"valid": not errors, "errors": errors}


def _normalise_admin_units(admin_units: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    admin = admin_units.copy()
    if admin.crs is None:
        admin = admin.set_crs("EPSG:4326")
    admin = admin.to_crs("EPSG:4326")
    if "admin_unit_id" not in admin.columns:
        admin["admin_unit_id"] = [
            f"{row.get('county', '')}|{row.get('township', '')}|{index}"
            for index, row in admin.reset_index(drop=True).iterrows()
        ]
    for column in ["county", "township"]:
        if column not in admin.columns:
            admin[column] = ""
    admin = admin[["admin_unit_id", "county", "township", "geometry"]].copy()
    admin["admin_unit_id"] = admin["admin_unit_id"].astype(str)
    admin["county"] = admin["county"].astype(str)
    admin["township"] = admin["township"].astype(str)
    return admin.reset_index(drop=True)


def _normalise_poi_points(poi_points: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    poi = poi_points.copy()
    if poi.crs is None:
        poi = poi.set_crs("EPSG:4326")
    poi = poi.to_crs("EPSG:4326")
    if "类型" not in poi.columns:
        poi["类型"] = ""
    poi["service_category"] = poi["类型"].map(_service_category)
    return poi[["service_category", "geometry"]].copy()


def _normalise_roads(roads: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    road = roads.copy()
    if road.crs is None:
        road = road.set_crs("EPSG:4326")
    road = road.to_crs("EPSG:4326")
    if "fclass" not in road.columns:
        road["fclass"] = ""
    if "maxspeed" not in road.columns:
        road["maxspeed"] = 0
    return road[["fclass", "maxspeed", "geometry"]].copy()


def _service_counts_by_admin(
    admin: gpd.GeoDataFrame,
    poi: gpd.GeoDataFrame,
) -> dict[str, dict[str, int]]:
    if len(poi) == 0:
        return {}
    joined = gpd.sjoin(
        poi,
        admin[["admin_unit_id", "geometry"]],
        how="left",
        predicate="within",
    )
    assigned = joined.dropna(subset=["admin_unit_id"])
    if assigned.empty:
        return {}
    grouped = (
        assigned.groupby(["admin_unit_id", "service_category"], observed=True)
        .size()
        .unstack(fill_value=0)
    )
    result: dict[str, dict[str, int]] = {}
    for admin_unit_id, row in grouped.iterrows():
        counts = {category: _int(row.get(category)) for category in SERVICE_CATEGORIES}
        result[str(admin_unit_id)] = counts
    return result


def _nearest_essential_service_by_admin(
    admin: gpd.GeoDataFrame,
    poi: gpd.GeoDataFrame,
) -> dict[str, dict[str, float]]:
    essential = poi[poi["service_category"].isin(ESSENTIAL_SERVICE_CATEGORIES)].copy()
    if essential.empty:
        return {}
    admin_centroids = admin.to_crs("EPSG:3857").copy()
    admin_centroids["geometry"] = admin_centroids.geometry.centroid
    essential = essential.to_crs("EPSG:3857")
    nearest = gpd.sjoin_nearest(
        admin_centroids[["admin_unit_id", "geometry"]],
        essential[["service_category", "geometry"]],
        how="left",
        distance_col="nearest_essential_service_distance_m",
    )
    result = {}
    for _, row in nearest.iterrows():
        result[str(row["admin_unit_id"])] = {
            "nearest_essential_service_distance_m": _float(
                row.get("nearest_essential_service_distance_m")
            ),
        }
    return result


def _road_context_by_admin(
    admin: gpd.GeoDataFrame,
    roads: gpd.GeoDataFrame,
) -> dict[str, dict[str, float]]:
    if roads.empty:
        return {}
    road_projected = roads.to_crs("EPSG:3857").copy()
    roads_with_metrics = road_projected.copy()
    roads_with_metrics["road_length_km"] = road_projected.geometry.length / 1000.0
    roads_with_metrics["speed_kmh"] = [
        _road_speed(row.get("fclass"), row.get("maxspeed"))
        for _, row in roads_with_metrics.iterrows()
    ]
    midpoints = roads_with_metrics.copy()
    midpoints["geometry"] = midpoints.geometry.interpolate(0.5, normalized=True)
    midpoints = midpoints.to_crs("EPSG:4326")
    joined = gpd.sjoin(
        midpoints,
        admin[["admin_unit_id", "geometry"]],
        how="left",
        predicate="within",
    ).dropna(subset=["admin_unit_id"])
    result = {}
    for admin_unit_id, group in joined.groupby("admin_unit_id", observed=True):
        length = float(group["road_length_km"].sum())
        if length > 0.0:
            mean_speed = float(
                np.average(group["speed_kmh"], weights=group["road_length_km"])
            )
        else:
            mean_speed = float(group["speed_kmh"].mean()) if len(group) else 20.0
        result[str(admin_unit_id)] = {
            "road_segment_count": _int(len(group)),
            "road_length_km": round(length, 6),
            "mean_road_speed_kmh": round(mean_speed, 6),
        }
    return result


def _surface_row(
    admin_row: dict[str, Any],
    service_counts: dict[str, int],
    road_context: dict[str, float],
    nearest: dict[str, float],
) -> dict[str, Any]:
    category_counts = {
        category: _int(service_counts.get(category)) for category in SERVICE_CATEGORIES
    }
    service_count = sum(category_counts.values())
    essential_count = sum(
        category_counts[category] for category in ESSENTIAL_SERVICE_CATEGORIES
    )
    road_segment_count = _int(road_context.get("road_segment_count"))
    road_length_km = _float(road_context.get("road_length_km"))
    mean_speed = _float(road_context.get("mean_road_speed_kmh"), default=20.0) or 20.0
    nearest_distance_m = _float(nearest.get("nearest_essential_service_distance_m"))
    travel_time_min = _travel_time_minutes(nearest_distance_m, mean_speed)
    service_void_flag = (
        "zero_poi_in_full_local_poi_surface_not_authoritative_absence"
        if service_count == 0
        else ""
    )
    return {
        "admin_unit_id": str(admin_row.get("admin_unit_id") or ""),
        "county": str(admin_row.get("county") or ""),
        "township": str(admin_row.get("township") or ""),
        "service_point_count": service_count,
        "essential_service_count": essential_count,
        "healthcare_count": category_counts["healthcare"],
        "education_count": category_counts["education"],
        "food_retail_count": category_counts["food_retail"],
        "finance_count": category_counts["finance"],
        "mobility_transport_count": category_counts["mobility_transport"],
        "civic_public_count": category_counts["civic_public"],
        "recreation_count": category_counts["recreation"],
        "lodging_count": category_counts["lodging"],
        "other_service_count": category_counts["other_service"],
        "nearest_essential_service_distance_m": round(nearest_distance_m, 3),
        "estimated_nearest_essential_travel_time_min": round(travel_time_min, 3),
        "road_segment_count": road_segment_count,
        "road_length_km": round(road_length_km, 6),
        "mean_road_speed_kmh": round(mean_speed, 6),
        "service_capacity_proxy": round(
            service_count + 1.5 * essential_count + 0.05 * road_segment_count,
            6,
        ),
        "service_coverage_status": "covered_by_full_local_surface",
        "sample_gap_flag": "",
        "service_void_flag": service_void_flag,
        "interpretable_as_true_service_absence": False,
    }


def _score_rows(rows: list[dict[str, Any]]) -> None:
    capacity = _minmax([_float(row["service_capacity_proxy"]) for row in rows])
    essential = _minmax([_float(row["essential_service_count"]) for row in rows])
    travel = _inverse_minmax(
        [_float(row["estimated_nearest_essential_travel_time_min"]) for row in rows]
    )
    for index, row in enumerate(rows):
        score = 0.55 * capacity[index] + 0.25 * essential[index] + 0.20 * travel[index]
        row["service_accessibility_score"] = round(score, 6)
        row["service_gap_score"] = round(1.0 - score, 6)
        row["score_components"] = {
            "capacity_norm": round(capacity[index], 6),
            "essential_norm": round(essential[index], 6),
            "travel_time_inverse_norm": round(travel[index], 6),
        }


def _service_category(raw_type: Any) -> str:
    text = str(raw_type or "")
    if "医疗" in text or "医院" in text or "诊所" in text or "药房" in text:
        return "healthcare"
    if "科教" in text or "学校" in text or "大学" in text or "幼儿园" in text:
        return "education"
    if "餐饮" in text or "购物" in text or "生活服务" in text:
        return "food_retail"
    if "金融" in text or "银行" in text:
        return "finance"
    if "交通" in text or "公交" in text or "停车" in text:
        return "mobility_transport"
    if "政府" in text or "公共设施" in text or "社会团体" in text:
        return "civic_public"
    if "体育" in text or "休闲" in text or "风景" in text:
        return "recreation"
    if "住宿" in text or "宾馆" in text or "酒店" in text:
        return "lodging"
    return "other_service"


def _road_speed(fclass: Any, maxspeed: Any) -> float:
    explicit = _float(maxspeed)
    if explicit > 0.0:
        return explicit
    defaults = {
        "motorway": 80.0,
        "motorway_link": 50.0,
        "trunk": 60.0,
        "trunk_link": 45.0,
        "primary": 50.0,
        "primary_link": 40.0,
        "secondary": 40.0,
        "secondary_link": 35.0,
        "tertiary": 35.0,
        "tertiary_link": 30.0,
        "residential": 25.0,
        "living_street": 15.0,
        "service": 15.0,
        "footway": 5.0,
        "pedestrian": 5.0,
        "steps": 3.0,
        "path": 5.0,
        "cycleway": 12.0,
    }
    return defaults.get(str(fclass or ""), 20.0)


def _travel_time_minutes(distance_m: float, speed_kmh: float) -> float:
    if distance_m <= 0.0:
        return 0.0
    usable_speed = max(speed_kmh, 3.0)
    detour_factor = 1.35
    return (distance_m * detour_factor / 1000.0) / usable_speed * 60.0


def _minmax(values: list[float]) -> list[float]:
    if not values:
        return []
    low = min(values)
    high = max(values)
    if math.isclose(low, high):
        return [0.0 for _ in values]
    return [(value - low) / (high - low) for value in values]


def _inverse_minmax(values: list[float]) -> list[float]:
    return [1.0 - value for value in _minmax(values)]


def _int(value: Any, default: int = 0) -> int:
    if isinstance(value, str) and not value:
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _float(value: Any, default: float = 0.0) -> float:
    if isinstance(value, str) and not value:
        return default
    try:
        if pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default

"""Map and Chinese presentation helpers for population/housing optimization."""

from __future__ import annotations

import json
from collections import defaultdict
from copy import deepcopy
from pathlib import Path
from typing import Any

MAP_CONTEXT_SCHEMA = "uwm.population_housing_optimization.map_context.v1"
MAP_UPDATE_SCHEMA = "map_update.v1"


def load_population_housing_map_context(
    input_payload: dict[str, Any],
    boundary_path: Path,
) -> dict[str, Any]:
    """Load exact township polygons for the scenario's bounded zone list."""
    try:
        boundary_payload = json.loads(Path(boundary_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("population_housing_boundary_source_unavailable") from error

    source_features = boundary_payload.get("features")
    if not isinstance(source_features, list):
        raise ValueError("population_housing_boundary_features_invalid")

    by_identity: dict[tuple[str, str], dict[str, Any]] = {}
    for feature in source_features:
        if not isinstance(feature, dict):
            continue
        properties = feature.get("properties") or {}
        identity = (str(properties.get("county") or ""), str(properties.get("township") or ""))
        if all(identity) and identity not in by_identity:
            by_identity[identity] = feature

    display = input_payload.get("display") or {}
    boundary_label = str(
        display.get("boundary_label") or "乡镇街道级行政区划，EPSG:4326"
    )
    features: list[dict[str, Any]] = []
    missing: list[str] = []
    centroids: list[tuple[float, float]] = []
    for zone in input_payload.get("zones") or []:
        identity = (str(zone.get("county") or ""), str(zone.get("township") or ""))
        feature = by_identity.get(identity)
        geometry = feature.get("geometry") if feature else None
        if not isinstance(geometry, dict) or geometry.get("type") not in {
            "Polygon",
            "MultiPolygon",
        }:
            missing.append(str(zone.get("zone_id") or "unknown"))
            continue
        copied = deepcopy(feature)
        copied["properties"] = {
            "空间单元": zone.get("zone_name"),
            "区县": zone.get("county"),
            "乡镇街道": zone.get("township"),
            "空间单元标识": zone.get("zone_id"),
            "边界来源": boundary_label,
        }
        features.append(copied)
        centroid = zone.get("centroid") or {}
        centroids.append((float(centroid.get("lat")), float(centroid.get("lon"))))

    if missing:
        raise ValueError("population_housing_boundary_geometry_missing::" + ",".join(missing))
    if not features or not centroids:
        raise ValueError("population_housing_boundary_geometry_empty")

    latitudes = [item[0] for item in centroids]
    longitudes = [item[1] for item in centroids]
    return {
        "schema": MAP_CONTEXT_SCHEMA,
        "ready": True,
        "center": [
            round((min(latitudes) + max(latitudes)) / 2, 8),
            round((min(longitudes) + max(longitudes)) / 2, 8),
        ],
        "zoom": int(display.get("map_zoom") or 11),
        "display": deepcopy(display),
        "boundary_source": {
            "path": str(boundary_path),
            "crs": "EPSG:4326",
            "match_method": "exact_county_and_township",
            "source_feature_count": len(source_features),
            "matched_feature_count": len(features),
            "label": boundary_label,
        },
        "zones": deepcopy(input_payload.get("zones") or []),
        "boundary_geojson": {
            "type": "FeatureCollection",
            "features": features,
        },
        "empirical_policy_optimality_claim": False,
    }


def build_population_housing_map_update(
    map_context: dict[str, Any],
    result: dict[str, Any],
    *,
    title: str = "人口与住房空间配置",
    profile_label: str = "当前方案",
    focus_assignment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one map_update.v1 payload from exact polygons and solver output."""
    zones = map_context.get("zones") or []
    zone_by_id = {str(zone.get("zone_id")): zone for zone in zones}
    assigned_by_zone: defaultdict[str, float] = defaultdict(float)
    for row in result.get("assignments") or []:
        assigned_by_zone[str(row.get("destination_zone_id"))] += float(
            row.get("households") or 0
        )

    new_units_by_zone: defaultdict[str, float] = defaultdict(float)
    for row in result.get("housing_actions") or []:
        new_units_by_zone[str(row.get("zone_id"))] += float(row.get("new_units") or 0)

    service_by_zone: defaultdict[str, float] = defaultdict(float)
    for row in result.get("service_actions") or []:
        service_by_zone[str(row.get("zone_id"))] += float(
            row.get("service_expansion") or 0
        )

    assigned_values = sorted(assigned_by_zone.values())
    lower = assigned_values[len(assigned_values) // 3] if assigned_values else 0
    upper = assigned_values[(len(assigned_values) * 2) // 3] if assigned_values else 0

    boundary_features = []
    included_zone_ids: set[str] | None = None
    if focus_assignment:
        included_zone_ids = {
            str(focus_assignment.get("origin_zone_id")),
            str(focus_assignment.get("destination_zone_id")),
        }
    for feature in (map_context.get("boundary_geojson") or {}).get("features") or []:
        copied = deepcopy(feature)
        properties = copied.setdefault("properties", {})
        zone_id = str(properties.get("空间单元标识") or "")
        if included_zone_ids is not None and zone_id not in included_zone_ids:
            continue
        assigned = assigned_by_zone[zone_id]
        if assigned <= lower:
            band = "较低"
        elif assigned <= upper:
            band = "中等"
        else:
            band = "较高"
        properties.update(
            {
                "方案": profile_label,
                "配置家庭数": round(assigned),
                "新增住房代理套数": round(new_units_by_zone[zone_id]),
                "公共服务扩容代理": round(service_by_zone[zone_id], 2),
                "配置强度": band,
                "证据边界": "聚合代理情景，不是政策建议或个人分配",
            }
        )
        boundary_features.append(copied)

    flow_totals: defaultdict[tuple[str, str], float] = defaultdict(float)
    if focus_assignment:
        flow_rows = [focus_assignment]
    else:
        flow_rows = result.get("assignments") or []
    for row in flow_rows:
        if not row.get("relocated"):
            continue
        key = (str(row.get("origin_zone_id")), str(row.get("destination_zone_id")))
        flow_totals[key] += float(row.get("households") or 0)

    flow_features = []
    for (origin_id, destination_id), households in sorted(flow_totals.items()):
        origin = zone_by_id.get(origin_id) or {}
        destination = zone_by_id.get(destination_id) or {}
        origin_centroid = origin.get("centroid") or {}
        destination_centroid = destination.get("centroid") or {}
        flow_features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [float(origin_centroid.get("lon")), float(origin_centroid.get("lat"))],
                        [
                            float(destination_centroid.get("lon")),
                            float(destination_centroid.get("lat")),
                        ],
                    ],
                },
                "properties": {
                    "方案": profile_label,
                    "起点": origin.get("zone_name") or origin_id,
                    "目标区": destination.get("zone_name") or destination_id,
                    "跨区配置家庭数": round(households),
                    "箭头说明": "箭头由起点指向目标区",
                    "流向含义": "模型聚合配置关系，不是实际搬迁路线或道路路径",
                },
            }
        )

    center = list(map_context.get("center") or [29.55, 106.55])
    zoom = int(map_context.get("zoom") or 11)
    if focus_assignment:
        origin = zone_by_id.get(str(focus_assignment.get("origin_zone_id"))) or {}
        destination = zone_by_id.get(str(focus_assignment.get("destination_zone_id"))) or {}
        points = [origin.get("centroid") or {}, destination.get("centroid") or {}]
        center = [
            round(sum(float(point.get("lat")) for point in points) / 2, 8),
            round(sum(float(point.get("lon")) for point in points) / 2, 8),
        ]
        zoom = 12

    return {
        "schema": MAP_UPDATE_SCHEMA,
        "summary": {
            "title": title,
            "profile": profile_label,
            "status": result.get("status"),
            "zone_count": len(boundary_features),
            "cross_zone_flow_count": len(flow_features),
            "claim_boundary": "aggregate_proxy_scenario_not_policy_advice",
        },
        "center": center,
        "zoom": zoom,
        "layers": [
            {
                "name": f"{profile_label}行政区配置",
                "type": "categorized",
                "category_column": "配置强度",
                "category_labels": {
                    "较低": "配置家庭较低",
                    "中等": "配置家庭中等",
                    "较高": "配置家庭较高",
                },
                "style_map": {
                    "较低": {"fillColor": "#dbeafe", "color": "#1d4ed8"},
                    "中等": {"fillColor": "#86efac", "color": "#15803d"},
                    "较高": {"fillColor": "#fbbf24", "color": "#a16207"},
                },
                "style": {"weight": 1.5, "fillOpacity": 0.58, "opacity": 0.9},
                "geojsonData": {
                    "type": "FeatureCollection",
                    "features": boundary_features,
                },
            },
            {
                "name": f"{profile_label}跨区配置流",
                "type": "line",
                "legend_title": "聚合配置流向",
                "style": {
                    "color": "#dc2626",
                    "weight": 4 if focus_assignment else 3,
                    "opacity": 0.92 if focus_assignment else 0.78,
                    "arrowheads": True,
                    "arrowColor": "#dc2626",
                    "arrowPlacement": 0.78,
                    "arrowSize": 15 if focus_assignment else 12,
                },
                "geojsonData": {
                    "type": "FeatureCollection",
                    "features": flow_features,
                },
            },
        ],
        "metadata": {
            "boundary_match_method": (map_context.get("boundary_source") or {}).get(
                "match_method"
            ),
            "boundary_crs": (map_context.get("boundary_source") or {}).get("crs"),
            "focus_mode": focus_assignment is not None,
            "flow_direction_encoding": "arrow_points_to_destination",
            "empirical_policy_optimality_claim": False,
        },
    }


__all__ = [
    "MAP_CONTEXT_SCHEMA",
    "MAP_UPDATE_SCHEMA",
    "build_population_housing_map_update",
    "load_population_housing_map_context",
]

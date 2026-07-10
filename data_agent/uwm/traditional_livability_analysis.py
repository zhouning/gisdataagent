"""Complete traditional static livability analysis on the prepared UWM scene."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .livability_requirement_registry import (
    build_livability_requirement_registry,
    requirement_coverage_for_route,
)


UWM_TRADITIONAL_LIVABILITY_ANALYSIS_SCHEMA = (
    "uwm.traditional_livability_analysis.v1"
)
UWM_TRADITIONAL_LIVABILITY_MAP_SCHEMA = "uwm.traditional_livability_map.v1"
TRADITIONAL_LIVABILITY_ROUTE = "traditional_livability"

DIMENSION_SPECS = [
    {
        "dimension_id": "public_service_accessibility",
        "label": "公共服务可达性",
        "weight": 0.30,
        "issue_tag": "公共服务可达性短板",
        "indicator_fields": ["service_gap_norm", "essential_service_gap_norm"],
    },
    {
        "dimension_id": "environment_health",
        "label": "环境健康",
        "weight": 0.25,
        "issue_tag": "环境健康短板",
        "indicator_fields": [
            "heat_exposure_norm",
            "tap_scene_pm25_mean_ugm3",
            "gee_cams_pm25_ugm3",
        ],
    },
    {
        "dimension_id": "mobility_connectivity",
        "label": "交通连通性",
        "weight": 0.20,
        "issue_tag": "交通连通性短板",
        "indicator_fields": [
            "osm_road_segment_count",
            "osm_road_length_degrees_proxy",
            "admin_graph_degree",
        ],
    },
    {
        "dimension_id": "population_exposure_equity",
        "label": "人口暴露公平性",
        "weight": 0.15,
        "issue_tag": "人口暴露公平性短板",
        "indicator_fields": ["exposure_priority_score", "ghsl_population_proxy_sum"],
    },
    {
        "dimension_id": "urban_intensity_balance",
        "label": "城市强度平衡",
        "weight": 0.10,
        "issue_tag": "城市强度平衡短板",
        "indicator_fields": ["ghsl_built_surface_proxy_sum", "osm_bbox_area_degrees2"],
    },
]

ACTION_BY_ISSUE = {
    "公共服务可达性短板": "补齐基本公共服务设施",
    "环境健康短板": "开展热暴露与空气质量治理",
    "交通连通性短板": "提升道路与公共交通连接",
    "人口暴露公平性短板": "开展人口暴露与公平性精细化排查",
    "城市强度平衡短板": "校核开发强度与公共空间配置",
    "综合宜居性高风险": "纳入人工复核重点清单",
}


def build_traditional_livability_analysis(
    *,
    analysis_id: str,
    created_at: str,
    multisource_livability_scene: dict[str, Any],
    top_n: int = 8,
) -> dict[str, Any]:
    """Build an indicator-dashboard style livability analysis from one scene."""

    scene_rows = list(multisource_livability_scene.get("admin_unit_states") or [])
    norm = _normalizers(scene_rows)
    ranked_units = _rank_units(scene_rows, norm)
    priority_count = max(1, min(int(top_n), len(ranked_units))) if ranked_units else 0
    priority_rows = ranked_units[:priority_count]
    dimension_summary = _dimension_summary(ranked_units)
    weakest_dimension = min(
        dimension_summary,
        key=lambda row: _float(row.get("mean_score"), default=1.0),
        default={},
    )

    city_score = _mean(
        [_float(row.get("traditional_livability_score")) for row in ranked_units]
    )
    registry = build_livability_requirement_registry()
    requirement_ownership = requirement_coverage_for_route(
        registry,
        TRADITIONAL_LIVABILITY_ROUTE,
    )
    return {
        "schema": UWM_TRADITIONAL_LIVABILITY_ANALYSIS_SCHEMA,
        "analysis_id": analysis_id,
        "created_at": created_at,
        "scene_id": multisource_livability_scene.get("scene_id"),
        "method": {
            "name": "traditional_static_indicator_weighted_analysis",
            "description": "current_state_indicator_aggregation_and_static_priority_ranking",
            "simulator_used": False,
            "planner_used": False,
            "counterfactual_output_available": False,
            "world_model_components_used": [],
        },
        "summary": {
            "city_livability_score": round(city_score, 6),
            "city_need_score": round(1.0 - city_score, 6),
            "grade": _grade(city_score),
            "admin_unit_count": len(ranked_units),
            "priority_unit_count": priority_count,
            "weakest_dimension": weakest_dimension.get("dimension_id"),
            "weakest_dimension_label": weakest_dimension.get("label"),
            "data_source_count": len(multisource_livability_scene.get("data_sources_used") or []),
        },
        "data_basis": {
            "scene_id": multisource_livability_scene.get("scene_id"),
            "scene_schema": multisource_livability_scene.get("schema"),
            "admin_unit_count": len(scene_rows),
            "data_sources_used": list(multisource_livability_scene.get("data_sources_used") or []),
            "source_coverage": dict(multisource_livability_scene.get("source_coverage") or {}),
        },
        "indicator_system": {
            "score_orientation": "higher_traditional_livability_score_is_better",
            "dimensions": [
                {
                    "dimension_id": spec["dimension_id"],
                    "label": spec["label"],
                    "weight": spec["weight"],
                    "indicator_fields": list(spec["indicator_fields"]),
                    "aggregation": "normalized_static_weighted_mean",
                }
                for spec in DIMENSION_SPECS
            ],
        },
        "dimension_summary": dimension_summary,
        "ranked_admin_units": ranked_units,
        "priority_diagnosis": [
            {
                "static_rank": row["static_rank"],
                "admin_unit_id": row["admin_unit_id"],
                "county": row["county"],
                "township": row["township"],
                "traditional_livability_score": row["traditional_livability_score"],
                "static_livability_need_score": row["static_livability_need_score"],
                "issue_tags": list(row["issue_tags"]),
                "recommended_static_actions": list(row["recommended_static_actions"]),
            }
            for row in priority_rows
        ],
        "static_action_plan": _static_action_plan(priority_rows),
        "requirement_ownership": requirement_ownership,
        "method_boundary": {
            "max_claim_level": "traditional_baseline_reference",
            "world_model_transition_claim": False,
            "policy_outcome_claim": False,
            "can_output": [
                "current_state_indicator_summary",
                "static_problem_ranking",
                "static_priority_units",
                "rule_based_static_action_suggestions",
                "current_state_map_layer",
            ],
            "cannot_output": [
                "action_conditioned_future_state",
                "multi_step_policy_sequence",
                "spatial_spillover_effect",
                "risk_adjusted_counterfactual_benefit",
                "empirical_policy_outcome_superiority",
            ],
            "reason": (
                "Traditional analysis consumes the same prepared multisource scene, "
                "but it only aggregates current indicators and ranks present deficits."
            ),
        },
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
    }


def queue_traditional_livability_map(
    *,
    username: str,
    analysis: dict[str, Any],
    admin_units_geojson_path: Path | str,
    upload_root: Path | str | None = None,
) -> dict[str, Any]:
    """Write a static traditional livability GeoJSON layer and queue map update."""

    admin_path = Path(admin_units_geojson_path)
    admin_geojson = json.loads(admin_path.read_text(encoding="utf-8"))
    rows_by_key = {
        _county_township_key(row): row for row in analysis.get("ranked_admin_units") or []
    }
    features = []
    for feature in admin_geojson.get("features") or []:
        props = dict(feature.get("properties") or {})
        row = rows_by_key.get(_county_township_key(props))
        if row is None:
            continue
        enriched = {
            **props,
            "admin_unit_id": row["admin_unit_id"],
            "traditional_livability_score": row["traditional_livability_score"],
            "static_livability_need_score": row["static_livability_need_score"],
            "static_rank": row["static_rank"],
            "static_priority_class": _priority_class(
                row["static_rank"],
                analysis.get("summary", {}).get("priority_unit_count"),
                analysis.get("summary", {}).get("admin_unit_count"),
            ),
            "issue_tags": "、".join(row.get("issue_tags") or []),
        }
        features.append(
            {
                "type": "Feature",
                "properties": enriched,
                "geometry": feature.get("geometry"),
            }
        )

    output_geojson = {
        "type": "FeatureCollection",
        "name": "uwm_traditional_livability_static_layer",
        "features": features,
    }
    upload_dir = _upload_dir(username=username, upload_root=upload_root)
    upload_dir.mkdir(parents=True, exist_ok=True)
    filename = "uwm_traditional_livability_static.geojson"
    (upload_dir / filename).write_text(
        json.dumps(output_geojson, ensure_ascii=False),
        encoding="utf-8",
    )

    center, zoom = _map_view(features)
    map_update = {
        "layers": [
            {
                "name": "城市宜居性分析（传统方法）",
                "type": "categorized",
                "geojson": filename,
                "category_column": "static_priority_class",
                "style_map": {
                    "高优先级": {
                        "color": "#991b1b",
                        "fillColor": "#ef4444",
                        "weight": 1,
                        "fillOpacity": 0.58,
                    },
                    "中优先级": {
                        "color": "#92400e",
                        "fillColor": "#f59e0b",
                        "weight": 1,
                        "fillOpacity": 0.48,
                    },
                    "一般": {
                        "color": "#166534",
                        "fillColor": "#22c55e",
                        "weight": 1,
                        "fillOpacity": 0.36,
                    },
                },
                "category_labels": {
                    "高优先级": "高优先级",
                    "中优先级": "中优先级",
                    "一般": "一般",
                },
                "legend_title": "传统方法静态优先级",
                "tooltip_fields": [
                    "county",
                    "township",
                    "traditional_livability_score",
                    "static_rank",
                    "issue_tags",
                ],
                "visible": True,
            }
        ],
        "center": center,
        "zoom": zoom,
        "layerControl": {"collapsed": False},
    }

    if upload_root is None:
        from ..frontend_api import _pending_lock, pending_map_updates

        with _pending_lock:
            pending_map_updates[username] = map_update

    return {
        "schema": UWM_TRADITIONAL_LIVABILITY_MAP_SCHEMA,
        "status": "queued",
        "scene_id": analysis.get("scene_id"),
        "map_update_queued": True,
        "matched_feature_count": len(features),
        "map_update": map_update,
    }


def _rank_units(
    scene_rows: list[dict[str, Any]],
    normalizers: dict[str, dict[str, float]],
) -> list[dict[str, Any]]:
    rows = []
    for row in scene_rows:
        state = row.get("state_vector") or {}
        need_score = _clamp01(state.get("livability_need_score"))
        dimension_scores = _dimension_scores(state, normalizers)
        issue_tags = _issue_tags(need_score, dimension_scores)
        rows.append(
            {
                "admin_unit_id": row.get("admin_unit_id"),
                "county": row.get("county"),
                "township": row.get("township"),
                "traditional_livability_score": round(1.0 - need_score, 6),
                "static_livability_need_score": round(need_score, 6),
                "dimension_scores": dimension_scores,
                "issue_tags": issue_tags,
                "recommended_static_actions": [
                    ACTION_BY_ISSUE[tag] for tag in issue_tags if tag in ACTION_BY_ISSUE
                ],
                "source_join_trace": dict(row.get("source_join_trace") or {}),
            }
        )
    rows.sort(
        key=lambda item: (
            -_float(item.get("static_livability_need_score")),
            str(item.get("admin_unit_id") or ""),
        )
    )
    for rank, row in enumerate(rows, start=1):
        row["static_rank"] = rank
    return rows


def _dimension_scores(
    state: dict[str, Any],
    normalizers: dict[str, dict[str, float]],
) -> dict[str, float]:
    service_gap = _clamp01(state.get("service_gap_norm"))
    essential_gap = _clamp01(state.get("essential_service_gap_norm"))
    heat = _clamp01(state.get("heat_exposure_norm"))
    tap_pm25 = _norm("tap_scene_pm25_mean_ugm3", state, normalizers)
    cams_pm25 = _norm("gee_cams_pm25_ugm3", state, normalizers)
    road_count = _norm("osm_road_segment_count", state, normalizers)
    road_length = _norm("osm_road_length_degrees_proxy", state, normalizers)
    graph_degree = _norm("admin_graph_degree", state, normalizers)
    exposure = _clamp01(state.get("exposure_priority_score"))
    population = _norm("ghsl_population_proxy_sum", state, normalizers)
    built_surface = _norm("ghsl_built_surface_proxy_sum", state, normalizers)
    bbox_area = _norm("osm_bbox_area_degrees2", state, normalizers)

    built_balance = 1.0 - min(1.0, abs(built_surface - 0.55) / 0.55)
    area_balance = 1.0 - min(1.0, abs(bbox_area - 0.50) / 0.50)

    return {
        "public_service_accessibility": round(
            1.0 - _mean([service_gap, essential_gap]),
            6,
        ),
        "environment_health": round(
            1.0 - _mean([heat, tap_pm25, cams_pm25]),
            6,
        ),
        "mobility_connectivity": round(
            _mean([road_count, road_length, graph_degree]),
            6,
        ),
        "population_exposure_equity": round(
            1.0 - _mean([exposure, population]),
            6,
        ),
        "urban_intensity_balance": round(
            _mean([built_balance, area_balance]),
            6,
        ),
    }


def _dimension_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summary = []
    for spec in DIMENSION_SPECS:
        dimension_id = spec["dimension_id"]
        scores = [
            _float((row.get("dimension_scores") or {}).get(dimension_id))
            for row in rows
        ]
        worst = min(
            rows,
            key=lambda row: _float(
                (row.get("dimension_scores") or {}).get(dimension_id),
                default=1.0,
            ),
            default={},
        )
        summary.append(
            {
                "dimension_id": dimension_id,
                "label": spec["label"],
                "weight": spec["weight"],
                "mean_score": round(_mean(scores), 6),
                "low_score_unit_count": sum(score < 0.4 for score in scores),
                "worst_unit_id": worst.get("admin_unit_id"),
                "worst_unit_label": _unit_label(worst),
            }
        )
    return summary


def _static_action_plan(priority_rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[str]] = {}
    for row in priority_rows:
        for tag in row.get("issue_tags") or []:
            grouped.setdefault(tag, []).append(str(row.get("admin_unit_id")))

    actions = []
    for tag, units in grouped.items():
        action = ACTION_BY_ISSUE.get(tag)
        if not action:
            continue
        actions.append(
            {
                "action_type": tag,
                "action_name": action,
                "target_units": units,
                "basis": "current_indicator_deficit_and_static_priority_rank",
                "future_effect_estimated": False,
            }
        )
    actions.sort(key=lambda item: (-len(item["target_units"]), item["action_type"]))
    return {
        "method": "rule_based_current_deficit_priority",
        "action_count": len(actions),
        "actions": actions,
    }


def _issue_tags(
    need_score: float,
    dimension_scores: dict[str, float],
) -> list[str]:
    tags = []
    if need_score >= 0.75:
        tags.append("综合宜居性高风险")
    for spec in DIMENSION_SPECS:
        dimension_id = spec["dimension_id"]
        if _float(dimension_scores.get(dimension_id), default=1.0) < 0.4:
            tags.append(str(spec["issue_tag"]))
    return tags or ["静态观察"]


def _normalizers(scene_rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    fields = {
        "tap_scene_pm25_mean_ugm3",
        "gee_cams_pm25_ugm3",
        "osm_road_segment_count",
        "osm_road_length_degrees_proxy",
        "admin_graph_degree",
        "ghsl_population_proxy_sum",
        "ghsl_built_surface_proxy_sum",
        "osm_bbox_area_degrees2",
    }
    normalizers = {}
    for field in fields:
        values = [_float((row.get("state_vector") or {}).get(field)) for row in scene_rows]
        normalizers[field] = {"min": min(values, default=0.0), "max": max(values, default=0.0)}
    return normalizers


def _norm(
    field: str,
    state: dict[str, Any],
    normalizers: dict[str, dict[str, float]],
) -> float:
    bounds = normalizers.get(field) or {"min": 0.0, "max": 0.0}
    low = _float(bounds.get("min"))
    high = _float(bounds.get("max"))
    value = _float(state.get(field))
    if math.isclose(high, low):
        return 0.0
    return _clamp01((value - low) / (high - low))


def _priority_class(rank: Any, priority_count: Any, unit_count: Any) -> str:
    rank_value = _int(rank, default=0)
    priority_value = max(1, _int(priority_count, default=0))
    total = max(priority_value, _int(unit_count, default=priority_value))
    if rank_value and rank_value <= priority_value:
        return "高优先级"
    if rank_value and rank_value <= max(priority_value + 1, math.ceil(total * 0.5)):
        return "中优先级"
    return "一般"


def _map_view(features: list[dict[str, Any]]) -> tuple[list[float], int]:
    coords = []
    for feature in features:
        coords.extend(_iter_coords((feature.get("geometry") or {}).get("coordinates")))
    if not coords:
        return [29.56, 106.55], 10
    lon_values = [item[0] for item in coords]
    lat_values = [item[1] for item in coords]
    center = [
        round((min(lat_values) + max(lat_values)) / 2.0, 6),
        round((min(lon_values) + max(lon_values)) / 2.0, 6),
    ]
    lon_span = max(lon_values) - min(lon_values)
    lat_span = max(lat_values) - min(lat_values)
    span = max(lon_span, lat_span)
    zoom = 12 if span < 0.08 else 11 if span < 0.18 else 10
    return center, zoom


def _iter_coords(value: Any) -> list[tuple[float, float]]:
    if not isinstance(value, list):
        return []
    if len(value) >= 2 and all(isinstance(item, (int, float)) for item in value[:2]):
        return [(_float(value[0]), _float(value[1]))]
    coords: list[tuple[float, float]] = []
    for item in value:
        coords.extend(_iter_coords(item))
    return coords


def _upload_dir(*, username: str, upload_root: Path | str | None) -> Path:
    if upload_root is not None:
        return Path(upload_root) / username
    return Path(__file__).resolve().parents[1] / "uploads" / username


def _county_township_key(row: dict[str, Any]) -> tuple[str, str]:
    return (str(row.get("county") or ""), str(row.get("township") or ""))


def _unit_label(row: dict[str, Any]) -> str:
    county = str(row.get("county") or "")
    township = str(row.get("township") or "")
    return f"{county}{township}" if county or township else ""


def _grade(score: float) -> str:
    if score >= 0.80:
        return "A"
    if score >= 0.65:
        return "B"
    if score >= 0.50:
        return "C"
    if score >= 0.35:
        return "D"
    return "E"


def _mean(values: list[float]) -> float:
    finite = [value for value in values if math.isfinite(value)]
    return sum(finite) / len(finite) if finite else 0.0


def _clamp01(value: Any) -> float:
    return max(0.0, min(1.0, _float(value)))


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _float(value: Any, default: float = 0.0) -> float:
    if value in {None, ""}:
        return default
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default

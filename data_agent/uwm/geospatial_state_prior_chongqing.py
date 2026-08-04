"""Chongqing public-proxy adapter for the multi-geometry state-prior benchmark."""

from __future__ import annotations

import math
from collections import defaultdict
from statistics import fmean
from typing import Any

from .geospatial_state_prior_benchmark import (
    UWM_GEOSPATIAL_STATE_PRIOR_DATASET_SCHEMA,
)

SCENE_HOLDOUT_SCHEMA = "uwm.scene_aligned_gridded_air_quality_holdout.v1"
ADMIN_PANEL_SCHEMA = "uwm.admin_livability_target_panel.v1"
ADMIN_GRAPH_SCHEMA = "uwm.admin_spatial_adjacency_graph.v1"

OPENMETEO_DYNAMIC_FEATURES = [
    "temperature_2m_mean_c",
    "precipitation_sum_mm",
    "wind_speed_10m_max_kmh",
    "relative_humidity_2m_mean_percent",
    "openmeteo_pm25_mean_ugm3",
]


def build_chongqing_pm25_state_prior_dataset(
    *,
    scene_aligned_holdout: dict[str, Any],
    admin_livability_panel: dict[str, Any],
    admin_spatial_graph: dict[str, Any],
    dataset_id: str,
    created_at: str,
    evidence_refs: list[str],
    openmeteo_weather_payload: dict[str, Any] | None = None,
    openmeteo_air_quality_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Join TAP/CHAP, admin attributes and graph topology without claim escalation."""

    _require_schema(scene_aligned_holdout, SCENE_HOLDOUT_SCHEMA, "scene_aligned_holdout")
    _require_schema(admin_livability_panel, ADMIN_PANEL_SCHEMA, "admin_livability_panel")
    _require_schema(admin_spatial_graph, ADMIN_GRAPH_SCHEMA, "admin_spatial_graph")

    series_rows = _dict_rows(scene_aligned_holdout, "series_results")
    panel_rows = _dict_rows(admin_livability_panel, "admin_livability_target_rows")
    graph_nodes = _dict_rows(admin_spatial_graph, "nodes")
    panel_by_key = _unique_rows_by_unit_key(panel_rows, "admin_livability_panel")
    graph_by_key = _unique_rows_by_unit_key(graph_nodes, "admin_spatial_graph")
    missing_panel = sorted(
        _unit_key(row) for row in series_rows if _unit_key(row) not in panel_by_key
    )
    missing_graph = sorted(
        _unit_key(row) for row in series_rows if _unit_key(row) not in graph_by_key
    )
    if missing_panel or missing_graph:
        raise ValueError(
            "scene routes are incomplete: "
            f"missing_panel={len(missing_panel)}, missing_graph={len(missing_graph)}"
        )

    if (openmeteo_weather_payload is None) != (openmeteo_air_quality_payload is None):
        raise ValueError("openmeteo weather and air-quality payloads must be provided together")
    dynamic_context_by_date = (
        _openmeteo_daily_context(
            openmeteo_weather_payload,
            openmeteo_air_quality_payload,
        )
        if openmeteo_weather_payload is not None and openmeteo_air_quality_payload is not None
        else {}
    )

    rows: list[dict[str, Any]] = []
    for series in sorted(series_rows, key=_unit_key):
        key = _unit_key(series)
        panel = panel_by_key[key]
        graph_node = graph_by_key[key]
        bbox = graph_node.get("bbox")
        if not isinstance(bbox, list) or len(bbox) != 4:
            raise ValueError(f"admin_spatial_graph node {key!r} requires a four-value bbox")
        x = _required_float(series, "longitude", f"series {key!r}")
        y = _required_float(series, "latitude", f"series {key!r}")
        chap_pm25 = _required_float(series, "chap_pm25_ugm3", f"series {key!r}")
        grid_distance = _required_float(
            series,
            "tap_nearest_grid_distance_degrees",
            f"series {key!r}",
        )
        raster_features = {
            "chap_pm25_ugm3": chap_pm25,
            "tap_grid_distance_degrees": grid_distance,
        }
        admin_features = {
            "exposure_priority_score": _required_float(
                panel, "exposure_priority_score", f"panel {key!r}"
            ),
            "livability_need_score": _required_float(
                panel, "livability_need_score", f"panel {key!r}"
            ),
            "log_service_point_count": math.log1p(
                max(0.0, _required_float(panel, "service_point_count", f"panel {key!r}"))
            ),
            "log_essential_service_count": math.log1p(
                max(
                    0.0,
                    _required_float(panel, "essential_service_count", f"panel {key!r}"),
                )
            ),
        }
        graph_features = {
            "degree": _required_float(graph_node, "degree", f"graph node {key!r}"),
            "bbox_width_degrees": _finite_float(bbox[2]) - _finite_float(bbox[0]),
            "bbox_height_degrees": _finite_float(bbox[3]) - _finite_float(bbox[1]),
        }
        daily_rows = series.get("daily_pm25")
        if not isinstance(daily_rows, list) or not daily_rows:
            raise ValueError(f"series {key!r} requires daily_pm25 observations")
        for daily in daily_rows:
            if not isinstance(daily, dict):
                raise ValueError(f"series {key!r} contains a non-object daily observation")
            date = str(daily.get("date") or "").strip()
            if not date:
                raise ValueError(f"series {key!r} daily observation requires date")
            row = {
                "sample_id": f"{series['admin_unit_id']}|{date}",
                "x": x,
                "y": y,
                "time_id": date,
                "admin_unit_id": str(series["admin_unit_id"]),
                "target": _required_float(daily, "pm25_ugm3", f"daily {key!r}"),
                "raster_features": dict(raster_features),
                "admin_features": dict(admin_features),
                "graph_object_features": dict(graph_features),
            }
            if dynamic_context_by_date:
                if date not in dynamic_context_by_date:
                    raise ValueError(f"Open-Meteo dynamic context is missing date {date}")
                row["dynamic_context_features"] = dict(dynamic_context_by_date[date])
            rows.append(row)

    source_dataset_ids = _unique_strings(
        [
            *(scene_aligned_holdout.get("source_dataset_ids") or []),
            *(admin_livability_panel.get("source_dataset_ids") or []),
            admin_spatial_graph.get("source_dataset_id"),
            *(
                [
                    "openmeteo_weather_historical_point_proxy",
                    "openmeteo_air_quality_historical_point_proxy",
                ]
                if dynamic_context_by_date
                else []
            ),
        ]
    )
    dataset = {
        "schema": UWM_GEOSPATIAL_STATE_PRIOR_DATASET_SCHEMA,
        "dataset_id": str(dataset_id),
        "created_at": str(created_at),
        "source_evidence_kind": "public_proxy",
        "source_dataset_ids": source_dataset_ids,
        "evidence_refs": _unique_strings(evidence_refs),
        "target": {
            "name": "tap_daily_pm25_ugm3",
            "geometry_type": "point",
            "spatial_support": {"support_type": "grid_cell", "resolution": "1km"},
            "temporal_support": dict(scene_aligned_holdout.get("scene_period") or {}),
            "observation_semantics": "observed",
            "source_boundary": "public_gridded_product_not_station_observation",
        },
        "geometry_routes": {
            "raster": {
                "geometry_type": "raster",
                "spatial_support": {"support_type": "grid_cell"},
                "feature_names": ["chap_pm25_ugm3", "tap_grid_distance_degrees"],
            },
            "admin": {
                "geometry_type": "polygon",
                "spatial_support": {"support_type": "admin_unit"},
                "feature_names": [
                    "exposure_priority_score",
                    "livability_need_score",
                    "log_service_point_count",
                    "log_essential_service_count",
                ],
            },
            "graph_object": {
                "geometry_type": "network",
                "spatial_support": {"support_type": "network_node"},
                "feature_names": [
                    "degree",
                    "bbox_width_degrees",
                    "bbox_height_degrees",
                ],
            },
        },
        "rows": rows,
        "adapter_audit": {
            "scene_admin_unit_count": len(series_rows),
            "matched_panel_unit_count": len(series_rows) - len(missing_panel),
            "matched_graph_node_count": len(series_rows) - len(missing_graph),
            "row_count": len(rows),
            "route_join_key": "county_and_township",
            "complete_three_route_join": not missing_panel and not missing_graph,
            "dynamic_context_date_count": len(dynamic_context_by_date),
            "dynamic_context_complete": not dynamic_context_by_date
            or len(dynamic_context_by_date) == len({str(row["time_id"]) for row in rows}),
        },
        "claim_boundary": {
            "max_claim_level": "exploratory_only",
            "reason": (
                "TAP and CHAP are public gridded products; this adapter does not create "
                "station-observed or policy-outcome holdout evidence."
            ),
        },
    }
    if dynamic_context_by_date:
        dataset["dynamic_context"] = {
            "context_type": "contemporaneous_external_public_proxy",
            "temporal_support": dict(scene_aligned_holdout.get("scene_period") or {}),
            "feature_names": list(OPENMETEO_DYNAMIC_FEATURES),
            "source_dataset_ids": [
                "openmeteo_weather_historical_point_proxy",
                "openmeteo_air_quality_historical_point_proxy",
            ],
            "shared_across_spatial_units": True,
            "uses_target_values": False,
        }
    return dataset


def _openmeteo_daily_context(
    weather_payload: dict[str, Any],
    air_quality_payload: dict[str, Any],
) -> dict[str, dict[str, float]]:
    weather_daily = weather_payload.get("daily")
    weather_hourly = weather_payload.get("hourly")
    air_hourly = air_quality_payload.get("hourly")
    if not all(
        isinstance(payload, dict) for payload in (weather_daily, weather_hourly, air_hourly)
    ):
        raise ValueError("Open-Meteo payloads require daily and hourly objects")

    daily_fields = {
        "temperature_2m_mean": "temperature_2m_mean_c",
        "precipitation_sum": "precipitation_sum_mm",
        "wind_speed_10m_max": "wind_speed_10m_max_kmh",
    }
    daily_times = _parallel_values(weather_daily, "time", list(daily_fields))
    result: dict[str, dict[str, float]] = {}
    for index, date_value in enumerate(daily_times):
        date = str(date_value)
        if date in result:
            raise ValueError(f"Open-Meteo weather daily contains duplicate date {date}")
        result[date] = {
            output_name: _finite_float(weather_daily[source_name][index])
            for source_name, output_name in daily_fields.items()
        }

    humidity = _hourly_daily_means(weather_hourly, "relative_humidity_2m")
    pm25 = _hourly_daily_means(air_hourly, "pm2_5")
    if set(result) != set(humidity) or set(result) != set(pm25):
        raise ValueError("Open-Meteo daily weather, humidity and PM2.5 dates must match")
    for date in result:
        result[date]["relative_humidity_2m_mean_percent"] = humidity[date]
        result[date]["openmeteo_pm25_mean_ugm3"] = pm25[date]
    return result


def _parallel_values(
    payload: dict[str, Any],
    time_key: str,
    value_keys: list[str],
) -> list[Any]:
    times = payload.get(time_key)
    if not isinstance(times, list) or not times:
        raise ValueError(f"Open-Meteo {time_key} must be a non-empty list")
    for key in value_keys:
        values = payload.get(key)
        if not isinstance(values, list) or len(values) != len(times):
            raise ValueError(f"Open-Meteo {key} must align with {time_key}")
    return times


def _hourly_daily_means(payload: dict[str, Any], value_key: str) -> dict[str, float]:
    times = _parallel_values(payload, "time", [value_key])
    values_by_date: dict[str, list[float]] = defaultdict(list)
    for timestamp, value in zip(times, payload[value_key], strict=True):
        date = str(timestamp)[:10]
        values_by_date[date].append(_finite_float(value))
    return {date: float(fmean(values)) for date, values in values_by_date.items()}


def _require_schema(payload: Any, expected: str, name: str) -> None:
    if not isinstance(payload, dict) or payload.get("schema") != expected:
        raise ValueError(f"{name}.schema must be {expected}")


def _dict_rows(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    rows = payload.get(key)
    if not isinstance(rows, list) or not rows or any(not isinstance(row, dict) for row in rows):
        raise ValueError(f"{key} must be a non-empty list of objects")
    return rows


def _unique_rows_by_unit_key(
    rows: list[dict[str, Any]],
    source_name: str,
) -> dict[tuple[str, str], dict[str, Any]]:
    indexed: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = _unit_key(row)
        if not all(key):
            raise ValueError(f"{source_name} row requires county and township")
        if key in indexed:
            raise ValueError(f"{source_name} contains duplicate unit key {key!r}")
        indexed[key] = row
    return indexed


def _unit_key(row: dict[str, Any]) -> tuple[str, str]:
    return (
        str(row.get("county") or "").strip(),
        str(row.get("township") or "").strip(),
    )


def _required_float(row: dict[str, Any], key: str, prefix: str) -> float:
    try:
        return _finite_float(row.get(key))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{prefix}.{key} must be a finite number") from exc


def _finite_float(value: Any) -> float:
    if isinstance(value, bool):
        raise TypeError("boolean is not numeric")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("number must be finite")
    return number


def _unique_strings(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    result = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result

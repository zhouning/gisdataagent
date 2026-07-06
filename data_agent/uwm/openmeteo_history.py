"""Persist Open-Meteo historical point proxies for UWM environmental state."""

from __future__ import annotations

import json
from pathlib import Path
from statistics import mean
from typing import Any
from urllib.parse import urlencode


OPENMETEO_HISTORICAL_PROXY_SCHEMA = "uwm.openmeteo_historical_environmental_proxy.v1"

HISTORICAL_WEATHER_DAILY_FIELDS = [
    "temperature_2m_mean",
    "precipitation_sum",
    "wind_speed_10m_max",
]

HISTORICAL_WEATHER_HOURLY_FIELDS = [
    "relative_humidity_2m",
    "surface_pressure",
]

HISTORICAL_AIR_QUALITY_HOURLY_FIELDS = [
    "pm10",
    "pm2_5",
    "carbon_monoxide",
    "nitrogen_dioxide",
    "sulphur_dioxide",
    "ozone",
]


def build_openmeteo_historical_urls(
    *,
    latitude: float,
    longitude: float,
    start_date: str,
    end_date: str,
    timezone: str,
) -> dict[str, str]:
    """Build reproducible Open-Meteo historical weather and air-quality URLs."""

    common = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": start_date,
        "end_date": end_date,
        "timezone": timezone,
    }
    weather_query = urlencode(
        {
            **common,
            "daily": ",".join(HISTORICAL_WEATHER_DAILY_FIELDS),
            "hourly": ",".join(HISTORICAL_WEATHER_HOURLY_FIELDS),
        },
        safe=",/",
    )
    air_query = urlencode(
        {
            **common,
            "hourly": ",".join(HISTORICAL_AIR_QUALITY_HOURLY_FIELDS),
        },
        safe=",/",
    )
    return {
        "weather": f"https://archive-api.open-meteo.com/v1/archive?{weather_query}",
        "air_quality": f"https://air-quality-api.open-meteo.com/v1/air-quality?{air_query}",
    }


def build_openmeteo_historical_environmental_proxy(
    weather_payload: dict[str, Any],
    air_quality_payload: dict[str, Any],
    *,
    requested_location: dict[str, Any],
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
    """Build a bounded, non-holdout historical environmental proxy."""

    weather_hourly = weather_payload.get("hourly") or {}
    weather_daily = weather_payload.get("daily") or {}
    air_hourly = air_quality_payload.get("hourly") or {}
    non_null_counts = _non_null_counts(weather_hourly, weather_daily, air_hourly)
    limitations = [
        "not_station_calibrated_holdout",
        "point_proxy_not_citywide_grid",
        "not_a_replacement_for_era5_or_cams_historical_grids",
        "not_a_replacement_for_local_monitoring_station_observations",
    ]
    if all(non_null_counts.get(field, 0) == 0 for field in HISTORICAL_AIR_QUALITY_HOURLY_FIELDS):
        limitations.append("air_quality_values_missing_for_requested_period")
    return {
        "schema": OPENMETEO_HISTORICAL_PROXY_SCHEMA,
        "source": "Open-Meteo API",
        "source_dataset_ids": [
            "openmeteo_weather_historical_point_proxy",
            "openmeteo_air_quality_historical_point_proxy",
        ],
        "requested_location": requested_location,
        "resolved_locations": {
            "weather": {
                "latitude": _float(weather_payload.get("latitude")),
                "longitude": _float(weather_payload.get("longitude")),
            },
            "air_quality": {
                "latitude": _float(air_quality_payload.get("latitude")),
                "longitude": _float(air_quality_payload.get("longitude")),
            },
        },
        "time_range": {"start_date": start_date, "end_date": end_date},
        "record_counts": {
            "weather_hourly": len(weather_hourly.get("time") or []),
            "weather_daily": len(weather_daily.get("time") or []),
            "air_quality_hourly": len(air_hourly.get("time") or []),
        },
        "non_null_counts": non_null_counts,
        "meteorology_summary": {
            "temperature_2m_mean_avg_c": _rounded_mean(weather_daily.get("temperature_2m_mean")),
            "precipitation_sum_total_mm": _rounded_sum(weather_daily.get("precipitation_sum")),
            "wind_speed_10m_max_kmh": _rounded_max(weather_daily.get("wind_speed_10m_max")),
            "relative_humidity_2m_avg_percent": _rounded_mean(weather_hourly.get("relative_humidity_2m")),
            "surface_pressure_avg_hpa": _rounded_mean(weather_hourly.get("surface_pressure")),
        },
        "air_pollution_summary": {
            "pm10_avg_ugm3": _rounded_mean(air_hourly.get("pm10")),
            "pm25_avg_ugm3": _rounded_mean(air_hourly.get("pm2_5")),
            "co_avg_ugm3": _rounded_mean(air_hourly.get("carbon_monoxide")),
            "no2_avg_ugm3": _rounded_mean(air_hourly.get("nitrogen_dioxide")),
            "so2_avg_ugm3": _rounded_mean(air_hourly.get("sulphur_dioxide")),
            "o3_avg_ugm3": _rounded_mean(air_hourly.get("ozone")),
        },
        "mmfe_target_roles": ["meteorology", "air_pollution_exposure", "simulator_context"],
        "synthetic_flags": [{"dataset_id": "openmeteo_historical_environmental_proxy", "status": "public_proxy"}],
        "claim_boundary": {
            "max_claim_level": "bounded_support",
            "reason": (
                "Open-Meteo historical point proxy is reproducible context for UWM state construction, "
                "but it is not station-calibrated observed holdout evidence."
            ),
        },
        "limitations": limitations,
        "empirical_superiority_claim": False,
    }


def write_openmeteo_historical_snapshot(
    *,
    output_dir: str | Path,
    weather_payload: dict[str, Any],
    air_quality_payload: dict[str, Any],
    requested_location: dict[str, Any],
    start_date: str,
    end_date: str,
    fetched_at: str,
) -> dict[str, Any]:
    """Persist raw historical payloads, normalized proxy and snapshot manifest."""

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    _write_json(output_path / "openmeteo_historical_weather_raw.json", weather_payload)
    _write_json(output_path / "openmeteo_historical_air_quality_raw.json", air_quality_payload)
    proxy = build_openmeteo_historical_environmental_proxy(
        weather_payload,
        air_quality_payload,
        requested_location=requested_location,
        start_date=start_date,
        end_date=end_date,
    )
    _write_json(output_path / "openmeteo_historical_environmental_proxy.json", proxy)
    manifest = {
        "schema": "uwm.public_proxy_snapshot_manifest.v1",
        "dataset_id": "openmeteo_historical_environmental_proxy_snapshot",
        "source_dataset_ids": proxy["source_dataset_ids"],
        "fetched_at": fetched_at,
        "requested_location": requested_location,
        "time_range": proxy["time_range"],
        "files": {
            "weather_raw": "openmeteo_historical_weather_raw.json",
            "air_quality_raw": "openmeteo_historical_air_quality_raw.json",
            "normalized_proxy": "openmeteo_historical_environmental_proxy.json",
        },
        "record_counts": proxy["record_counts"],
        "claim_boundary": proxy["claim_boundary"],
        "limitations": proxy["limitations"],
        "mmfe_target_roles": proxy["mmfe_target_roles"],
        "empirical_superiority_claim": False,
    }
    _write_json(output_path / "snapshot_manifest.json", manifest)
    return manifest


def build_mmfe_state_input_from_openmeteo_historical_proxy(
    proxy: dict[str, Any],
    *,
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Convert an Open-Meteo historical proxy into MMFE UWM state input."""

    from .mmfe_state_input import build_uwm_state_input_from_semantic_product

    if proxy.get("schema") != OPENMETEO_HISTORICAL_PROXY_SCHEMA:
        raise ValueError(f"proxy schema must be {OPENMETEO_HISTORICAL_PROXY_SCHEMA}")
    time_range = proxy.get("time_range") or {}
    start_date = str(time_range.get("start_date") or "unknown_start")
    end_date = str(time_range.get("end_date") or "unknown_end")
    record_counts = proxy.get("record_counts") or {}
    dataset_ids = proxy.get("source_dataset_ids") or []
    weather_dataset_id = _dataset_id(dataset_ids, "weather", "openmeteo_weather_historical_point_proxy")
    air_dataset_id = _dataset_id(dataset_ids, "air_quality", "openmeteo_air_quality_historical_point_proxy")
    payload = build_uwm_state_input_from_semantic_product(
        {
            "product_id": f"mmfe-openmeteo-history-{start_date}-{end_date}",
            "product_type": "semantic_fusion_product",
            "version": "0.1",
            "quality": {"score": 0.54},
        },
        semantic_relations=[
            {
                "semantic_relation_type": "point_has_weather_hourly_record",
                "uwm_usage": "meteorology",
                "relation_count": record_counts.get("weather_hourly", 0),
            },
            {
                "semantic_relation_type": "point_has_weather_daily_record",
                "uwm_usage": "meteorology",
                "relation_count": record_counts.get("weather_daily", 0),
            },
            {
                "semantic_relation_type": "point_has_air_quality_hourly_record",
                "uwm_usage": "air_pollution_exposure",
                "relation_count": record_counts.get("air_quality_hourly", 0),
            },
        ],
        input_contract={
            "spatial_unit": {
                "unit_type": "point_environmental_proxy",
                "crs": "EPSG:4326",
                "location": proxy.get("requested_location") or {},
                "temporal_extent": f"{start_date}/{end_date}",
            },
            "role_bindings": [
                {
                    "role": "openmeteo_weather_hourly_humidity_pressure",
                    "uwm_role": "meteorology",
                    "object_type": "point_timeseries",
                    "source_dataset_id": weather_dataset_id,
                    "synthetic_status": "public_proxy",
                },
                {
                    "role": "openmeteo_weather_daily_temperature_precipitation_wind",
                    "uwm_role": "meteorology",
                    "object_type": "point_timeseries",
                    "source_dataset_id": weather_dataset_id,
                    "synthetic_status": "public_proxy",
                },
                {
                    "role": "openmeteo_air_quality_hourly_pollutants",
                    "uwm_role": "air_pollution_exposure",
                    "object_type": "point_timeseries",
                    "source_dataset_id": air_dataset_id,
                    "synthetic_status": "public_proxy",
                },
            ],
        },
        timestamp=timestamp,
    )
    payload["source_proxy"] = {
        "schema": proxy.get("schema"),
        "time_range": proxy.get("time_range"),
        "record_counts": proxy.get("record_counts"),
        "claim_boundary": proxy.get("claim_boundary"),
        "limitations": proxy.get("limitations") or [],
        "empirical_superiority_claim": False,
    }
    payload["warnings"].append(
        "Open-Meteo historical point proxy is not station-calibrated holdout evidence and must not unlock observed empirical superiority claims"
    )
    return payload


def _rounded_mean(values: Any) -> float | None:
    numbers = _numbers(values)
    return round(mean(numbers), 3) if numbers else None


def _rounded_sum(values: Any) -> float | None:
    numbers = _numbers(values)
    return round(sum(numbers), 3) if numbers else None


def _rounded_max(values: Any) -> float | None:
    numbers = _numbers(values)
    return round(max(numbers), 3) if numbers else None


def _numbers(values: Any) -> list[float]:
    if not isinstance(values, list):
        return []
    return [number for number in (_float(value) for value in values) if number is not None]


def _non_null_counts(
    weather_hourly: dict[str, Any],
    weather_daily: dict[str, Any],
    air_hourly: dict[str, Any],
) -> dict[str, int]:
    fields = {
        field: weather_daily.get(field)
        for field in HISTORICAL_WEATHER_DAILY_FIELDS
    }
    fields.update({field: weather_hourly.get(field) for field in HISTORICAL_WEATHER_HOURLY_FIELDS})
    fields.update({field: air_hourly.get(field) for field in HISTORICAL_AIR_QUALITY_HOURLY_FIELDS})
    return {field: len(_numbers(values)) for field, values in fields.items()}


def _float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _dataset_id(dataset_ids: Any, marker: str, fallback: str) -> str:
    if isinstance(dataset_ids, list):
        for dataset_id in dataset_ids:
            if marker in str(dataset_id):
                return str(dataset_id)
    return fallback

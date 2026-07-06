"""Normalize Open-Meteo current environmental payloads for UWM ingestion."""

from __future__ import annotations

from typing import Any


OPENMETEO_ENVIRONMENTAL_PROXY_SCHEMA = "uwm.openmeteo_environmental_proxy.v1"


def build_openmeteo_environmental_proxy(
    weather_payload: dict[str, Any],
    air_quality_payload: dict[str, Any],
    *,
    requested_location: dict[str, Any],
) -> dict[str, Any]:
    """Build a bounded-support environmental proxy from Open-Meteo payloads."""

    weather_current = weather_payload.get("current") or {}
    air_current = air_quality_payload.get("current") or {}
    return {
        "schema": OPENMETEO_ENVIRONMENTAL_PROXY_SCHEMA,
        "source": "Open-Meteo API",
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
        "source_dataset_ids": [
            "openmeteo_weather_current_proxy",
            "openmeteo_air_quality_current_proxy",
        ],
        "meteorology": {
            "time": weather_current.get("time"),
            "temperature_c": _float(weather_current.get("temperature_2m")),
            "humidity_percent": _float(weather_current.get("relative_humidity_2m")),
            "precipitation_mm": _float(weather_current.get("precipitation")),
            "pressure_hpa": _float(weather_current.get("surface_pressure")),
            "wind_speed_kmh": _float(weather_current.get("wind_speed_10m")),
            "source_units": weather_payload.get("current_units") or {},
        },
        "air_pollution": {
            "time": air_current.get("time"),
            "pm10_ugm3": _float(air_current.get("pm10")),
            "pm25_ugm3": _float(air_current.get("pm2_5")),
            "co_ugm3": _float(air_current.get("carbon_monoxide")),
            "no2_ugm3": _float(air_current.get("nitrogen_dioxide")),
            "so2_ugm3": _float(air_current.get("sulphur_dioxide")),
            "o3_ugm3": _float(air_current.get("ozone")),
            "source_units": air_quality_payload.get("current_units") or {},
        },
        "synthetic_flags": [{"dataset_id": "openmeteo_environmental_proxy", "status": "public_proxy"}],
        "claim_boundary": {
            "max_claim_level": "bounded_support",
            "reason": "Open-Meteo keyless live proxy is useful for UWM smoke/live context but not station-calibrated holdout",
        },
        "limitations": [
            "not_station_calibrated_holdout",
            "not_a_replacement_for_era5_or_cams_historical_grids",
            "must_be_archived_with_query_parameters_before_reproducible_evaluation",
        ],
        "mmfe_target_roles": ["meteorology", "air_pollution_exposure"],
    }


def _float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

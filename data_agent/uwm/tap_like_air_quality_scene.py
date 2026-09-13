"""TAP-like semi-synthetic PM2.5 scene generation for UWM development."""

from __future__ import annotations

from datetime import datetime
from statistics import mean
from typing import Any


TAP_LIKE_PM25_SCENE_SCHEMA = "uwm.tap_like_pm25_scene.v2"
DEFAULT_TAP_LIKE_PM25_BACKEND = "chap_anchored_openmeteo_noaa_openaq_pm25_synthesis_v2"


def build_tap_like_pm25_scene_v2(
    *,
    chap_proxy: dict[str, Any],
    openmeteo_raw: dict[str, Any],
    openaq_raw: dict[str, Any],
    noaa_weather_proxy: dict[str, Any] | None = None,
    gee_zonal_proxy: dict[str, Any] | None = None,
    scene_id: str,
    created_at: str,
) -> dict[str, Any]:
    """Build a CHAP-anchored TAP-like PM2.5 panel for pipeline development.

    This output is deliberately semi-synthetic. It is a development substitute
    while TAP access is pending, not observed TAP data.
    """

    chap = _chap_anchor_index(chap_proxy)
    openmeteo = _openmeteo_hourly_series(openmeteo_raw, chap)
    if not openmeteo:
        raise ValueError("TAP-like PM2.5 scene requires Open-Meteo hourly admin PM2.5 series")
    timestamps = _common_timestamps(openmeteo)
    if not timestamps:
        raise ValueError("TAP-like PM2.5 scene requires at least one common hourly timestamp")

    openaq_pattern = _repeat_to_length(_openaq_pm25_anomaly_pattern(openaq_raw), len(timestamps))
    noaa_pattern = _noaa_weather_adjustment_pattern(noaa_weather_proxy or {}, timestamps)
    gee = _gee_zonal_pm25_index(gee_zonal_proxy or {})

    records = []
    calibration_errors = []
    for admin_unit_id, series in sorted(openmeteo.items()):
        anchor = series["chap_anchor_pm25_ugm3"]
        raw_values = []
        raw_components = []
        openmeteo_mean = mean(series["pm25_by_timestamp"].values())
        gee_pm25 = _match_optional_admin_value(gee, admin_unit_id, series["county"], series["township"])
        gee_static_adjustment = 0.0 if gee_pm25 is None else 0.10 * (gee_pm25 - anchor)
        for index, timestamp in enumerate(timestamps):
            openmeteo_pm25 = series["pm25_by_timestamp"][timestamp]
            openmeteo_anomaly = 0.45 * (openmeteo_pm25 - openmeteo_mean)
            openaq_anomaly = openaq_pattern[index]
            noaa_adjustment = noaa_pattern[index]
            raw_pm25 = anchor + openmeteo_anomaly + openaq_anomaly + noaa_adjustment + gee_static_adjustment
            raw_values.append(max(0.0, raw_pm25))
            raw_components.append(
                {
                    "timestamp": timestamp,
                    "openmeteo_hourly_pm25_ugm3": openmeteo_pm25,
                    "openmeteo_hourly_anomaly_ugm3": openmeteo_anomaly,
                    "openaq_historical_pm25_anomaly_ugm3": openaq_anomaly,
                    "noaa_weather_adjustment_ugm3": noaa_adjustment,
                    "gee_cams_zonal_pm25_ugm3": gee_pm25,
                    "gee_static_adjustment_ugm3": gee_static_adjustment,
                }
            )

        calibrated_values = _anchor_series(raw_values, anchor)
        calibrated_mean = mean(calibrated_values)
        calibration_errors.append(abs(calibrated_mean - anchor))
        for value, component in zip(calibrated_values, raw_components):
            uncertainty = _uncertainty_width(
                openaq_anomaly=component["openaq_historical_pm25_anomaly_ugm3"],
                noaa_adjustment=component["noaa_weather_adjustment_ugm3"],
                gee_pm25=component["gee_cams_zonal_pm25_ugm3"],
            )
            records.append(
                {
                    "timestamp": component["timestamp"],
                    "admin_unit_id": admin_unit_id,
                    "county": series["county"],
                    "township": series["township"],
                    "pm25_ugm3": round(value, 3),
                    "synthetic_status": "semi_synthetic",
                    "quality_status": "tap_like_pm25_scene_not_observed_holdout",
                    "source_components": {
                        "chap_monthly_anchor_pm25_ugm3": round(anchor, 3),
                        "openmeteo_hourly_pm25_ugm3": round(component["openmeteo_hourly_pm25_ugm3"], 3),
                        "openmeteo_hourly_anomaly_ugm3": round(component["openmeteo_hourly_anomaly_ugm3"], 3),
                        "openaq_historical_pm25_anomaly_ugm3": round(
                            component["openaq_historical_pm25_anomaly_ugm3"],
                            3,
                        ),
                        "noaa_weather_adjustment_ugm3": round(component["noaa_weather_adjustment_ugm3"], 3),
                        "gee_cams_zonal_pm25_ugm3": None
                        if component["gee_cams_zonal_pm25_ugm3"] is None
                        else round(component["gee_cams_zonal_pm25_ugm3"], 3),
                        "gee_static_adjustment_ugm3": round(component["gee_static_adjustment_ugm3"], 3),
                    },
                    "uncertainty_interval_ugm3": {
                        "low": round(max(0.0, value - uncertainty), 3),
                        "high": round(value + uncertainty, 3),
                        "width": round(uncertainty * 2.0, 3),
                    },
                    "source_trace": [
                        "CHAP_monthly_anchor",
                        "OpenMeteo_2024_hourly_public_model_proxy",
                        "OpenAQ_historical_temporal_noise",
                        "NOAA_ISD_weather_adjustment",
                        "GEE_CAMS_optional_spatial_context",
                    ],
                }
            )

    values = [record["pm25_ugm3"] for record in records]
    return {
        "schema": TAP_LIKE_PM25_SCENE_SCHEMA,
        "scene_id": scene_id,
        "created_at": created_at,
        "backend": DEFAULT_TAP_LIKE_PM25_BACKEND,
        "synthetic_status": "semi_synthetic",
        "quality_status": "tap_like_pm25_scene_not_observed_holdout",
        "source_dataset_ids": [
            "chap_pm25_monthly_1km_2024_07_proxy",
            "openmeteo_livability_admin_air_quality_proxy",
            "openaq_air_quality_station_observation_proxy",
            "noaa_isd_chongqing_weather_observation_2024_07",
            "gee_livability_admin_zonal_environment_proxy",
        ],
        "synthesis_method": {
            "anchor": "CHAP 2024-07 monthly 1km PM2.5 sampled at admin representative points",
            "hourly_shape": "Open-Meteo 2024-07 admin representative-point hourly PM2.5 anomalies",
            "historical_noise": "OpenAQ observed historical PM2.5 anomaly pattern centered to zero mean",
            "meteorology": "NOAA ISD wind and temperature centered ventilation adjustment",
            "spatial_context": "GEE/CAMS zonal PM2.5 optional static residual context",
            "calibration": "per-admin hourly mean is shifted back to the CHAP monthly anchor",
        },
        "time_range": {"start": timestamps[0], "end": timestamps[-1]},
        "record_counts": {
            "admin_units": len(openmeteo),
            "hours": len(timestamps),
            "records": len(records),
            "openaq_pm25_pattern_points": len(_openaq_pm25_values(openaq_raw)),
            "noaa_weather_pattern_points": len(_weather_rows(noaa_weather_proxy or {})),
        },
        "calibration_summary": {
            "max_abs_chap_anchor_error_ugm3": round(max(calibration_errors), 6) if calibration_errors else None,
            "mean_abs_chap_anchor_error_ugm3": round(mean(calibration_errors), 6) if calibration_errors else None,
            "anchor_policy": "per_admin_hourly_mean_equals_chap_monthly_pm25_anchor",
        },
        "summary": {
            "pm25_ugm3_avg": round(mean(values), 3) if values else None,
            "pm25_ugm3_min": round(min(values), 3) if values else None,
            "pm25_ugm3_max": round(max(values), 3) if values else None,
        },
        "records": records,
        "synthetic_flags": [
            {
                "dataset_id": "tap_like_pm25_scene_v2_2024_07",
                "status": "semi_synthetic",
            }
        ],
        "claim_boundary": {
            "max_claim_level": "exploratory_only",
            "reason": "TAP-like PM2.5 scene is semi-synthetic while TAP account access is pending; it is not observed TAP data.",
        },
        "limitations": [
            "not_tap_data",
            "not_observed_air_quality_holdout",
            "not_policy_intervention_outcome",
            "semi_synthetic_for_pipeline_development_only",
        ],
        "empirical_superiority_claim": False,
    }


def _chap_anchor_index(chap_proxy: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = list(chap_proxy.get("admin_pm25_rows") or chap_proxy.get("records") or [])
    exact = {}
    by_admin_pair = {}
    for row in rows:
        anchor = _float(row.get("pm25_ugm3"))
        admin_unit_id = str(row.get("admin_unit_id") or "")
        county = str(row.get("county") or "")
        township = str(row.get("township") or "")
        if not admin_unit_id or anchor is None:
            continue
        payload = {
            "admin_unit_id": admin_unit_id,
            "county": county,
            "township": township,
            "pm25_ugm3": anchor,
        }
        exact[admin_unit_id] = payload
        by_admin_pair[_admin_pair_key(admin_unit_id, county, township)] = payload
    if not exact:
        raise ValueError("TAP-like PM2.5 scene requires CHAP admin PM2.5 anchors")
    return {"exact": exact, "pair": by_admin_pair}


def _openmeteo_hourly_series(
    openmeteo_raw: dict[str, Any],
    chap: dict[str, dict[str, dict[str, Any]]],
) -> dict[str, dict[str, Any]]:
    series = {}
    for admin_unit_id, payload in openmeteo_raw.items():
        hourly = payload.get("hourly") if isinstance(payload, dict) else None
        if not isinstance(hourly, dict):
            continue
        times = list(hourly.get("time") or [])
        pm25_values = list(hourly.get("pm2_5") or hourly.get("pm25") or [])
        if not times or len(times) != len(pm25_values):
            continue
        anchor = _match_chap_anchor(chap, str(admin_unit_id))
        if anchor is None:
            continue
        pm25_by_timestamp = {}
        for timestamp, value in zip(times, pm25_values):
            pm25 = _float(value)
            if pm25 is not None:
                pm25_by_timestamp[_normalise_timestamp(timestamp)] = pm25
        if pm25_by_timestamp:
            series[str(admin_unit_id)] = {
                "county": anchor["county"],
                "township": anchor["township"],
                "chap_anchor_pm25_ugm3": anchor["pm25_ugm3"],
                "pm25_by_timestamp": pm25_by_timestamp,
            }
    return series


def _match_chap_anchor(
    chap: dict[str, dict[str, dict[str, Any]]],
    admin_unit_id: str,
) -> dict[str, Any] | None:
    exact = chap["exact"].get(admin_unit_id)
    if exact:
        return exact
    return chap["pair"].get(_admin_pair_key(admin_unit_id, "", ""))


def _common_timestamps(openmeteo: dict[str, dict[str, Any]]) -> list[str]:
    timestamp_sets = [set(row["pm25_by_timestamp"]) for row in openmeteo.values()]
    if not timestamp_sets:
        return []
    common = set.intersection(*timestamp_sets)
    return sorted(common)


def _openaq_pm25_values(openaq_raw: dict[str, Any]) -> list[float]:
    values = []
    for payload in openaq_raw.values():
        for row in payload.get("results") or []:
            name = str((row.get("parameter") or {}).get("name") or "").lower().replace(".", "")
            if name not in {"pm25", "pm2_5"}:
                continue
            value = _float(row.get("value"))
            if value is not None:
                values.append(value)
    return values


def _openaq_pm25_anomaly_pattern(openaq_raw: dict[str, Any]) -> list[float]:
    values = _openaq_pm25_values(openaq_raw)
    if not values:
        raise ValueError("TAP-like PM2.5 scene requires historical OpenAQ PM2.5 values")
    center = mean(values)
    return [0.25 * (value - center) for value in values]


def _noaa_weather_adjustment_pattern(
    noaa_weather_proxy: dict[str, Any],
    timestamps: list[str],
) -> list[float]:
    rows = _weather_rows(noaa_weather_proxy)
    if not rows:
        return [0.0 for _ in timestamps]
    grouped = {}
    for row in rows:
        timestamp = _normalise_timestamp(row.get("timestamp_utc"))
        grouped.setdefault(timestamp, []).append(row)
    wind_values = [
        _float(row.get("wind_speed_ms"))
        for row in rows
        if _float(row.get("wind_speed_ms")) is not None
    ]
    temp_values = [
        _float(row.get("air_temperature_c"))
        for row in rows
        if _float(row.get("air_temperature_c")) is not None
    ]
    wind_mean = mean(wind_values) if wind_values else 0.0
    temp_mean = mean(temp_values) if temp_values else 0.0
    adjustments = []
    for timestamp in timestamps:
        bucket = grouped.get(timestamp) or []
        wind = _mean_present([_float(row.get("wind_speed_ms")) for row in bucket], default=wind_mean)
        temp = _mean_present([_float(row.get("air_temperature_c")) for row in bucket], default=temp_mean)
        adjustments.append(-0.25 * (wind - wind_mean) + 0.08 * (temp - temp_mean))
    adjustment_mean = mean(adjustments) if adjustments else 0.0
    return [value - adjustment_mean for value in adjustments]


def _weather_rows(noaa_weather_proxy: dict[str, Any]) -> list[dict[str, Any]]:
    return list(noaa_weather_proxy.get("weather_observation_rows") or [])


def _gee_zonal_pm25_index(gee_zonal_proxy: dict[str, Any]) -> dict[str, dict[str, Any]]:
    index = {}
    for row in gee_zonal_proxy.get("admin_environment_rows") or []:
        admin_unit_id = str(row.get("admin_unit_id") or "")
        pm25 = _float(row.get("cams_pm25_ugm3"))
        if not admin_unit_id or pm25 is None:
            continue
        index[admin_unit_id] = {
            "county": str(row.get("county") or ""),
            "township": str(row.get("township") or ""),
            "pm25_ugm3": pm25,
        }
        index[_admin_pair_key(admin_unit_id, row.get("county"), row.get("township"))] = index[admin_unit_id]
    return index


def _match_optional_admin_value(
    index: dict[str, dict[str, Any]],
    admin_unit_id: str,
    county: str,
    township: str,
) -> float | None:
    row = index.get(admin_unit_id) or index.get(_admin_pair_key(admin_unit_id, county, township))
    if not row:
        return None
    return _float(row.get("pm25_ugm3"))


def _anchor_series(values: list[float], anchor: float) -> list[float]:
    if not values:
        return []
    offset = mean(values) - anchor
    shifted = [max(0.0, value - offset) for value in values]
    second_offset = mean(shifted) - anchor
    return [max(0.0, value - second_offset) for value in shifted]


def _uncertainty_width(
    *,
    openaq_anomaly: float,
    noaa_adjustment: float,
    gee_pm25: float | None,
) -> float:
    width = 3.0 + 0.15 * abs(openaq_anomaly) + 0.20 * abs(noaa_adjustment)
    if gee_pm25 is None:
        width += 1.0
    return width


def _repeat_to_length(values: list[float], length: int) -> list[float]:
    if not values:
        return [0.0 for _ in range(length)]
    return [values[index % len(values)] for index in range(length)]


def _normalise_timestamp(value: Any) -> str:
    text = str(value or "")
    if not text:
        return text
    if text.endswith("Z"):
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    parsed = datetime.fromisoformat(text)
    return parsed.replace(microsecond=0).isoformat() + "Z"


def _admin_pair_key(admin_unit_id: str, county: Any, township: Any) -> str:
    parts = str(admin_unit_id or "").split("|")
    if len(parts) >= 2:
        return f"{parts[0]}|{parts[1]}"
    return f"{str(county or '')}|{str(township or '')}"


def _mean_present(values: list[float | None], *, default: float) -> float:
    present = [value for value in values if value is not None]
    return mean(present) if present else default


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

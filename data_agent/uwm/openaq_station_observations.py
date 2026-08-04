"""OpenAQ v3 station observation proxies for UWM air-quality state."""

from __future__ import annotations

import json
from pathlib import Path
from statistics import mean
from typing import Any
from urllib.parse import urlencode

OPENAQ_STATION_OBSERVATION_PROXY_SCHEMA = "uwm.openaq_station_observation_proxy.v1"
OPENAQ_MAX_RADIUS_M = 25000


def build_openaq_locations_url(
    *,
    latitude: float,
    longitude: float,
    radius_m: int = OPENAQ_MAX_RADIUS_M,
    limit: int = 20,
    page: int | None = None,
) -> str:
    """Build an OpenAQ v3 locations URL without embedding credentials."""

    if radius_m > OPENAQ_MAX_RADIUS_M:
        raise ValueError(f"OpenAQ v3 radius must be <= {OPENAQ_MAX_RADIUS_M} m")
    parameters = {
        "coordinates": f"{latitude},{longitude}",
        "radius": radius_m,
        "limit": limit,
    }
    if page is not None:
        parameters["page"] = page
    query = urlencode(parameters, safe=",")
    return f"https://api.openaq.org/v3/locations?{query}"


def build_openaq_sensor_measurements_url(
    *,
    sensor_id: int,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 100,
    page: int | None = None,
) -> str:
    """Build an OpenAQ v3 sensor measurements URL without embedding credentials."""

    query: dict[str, Any] = {"limit": limit}
    if date_from:
        query["datetime_from"] = date_from
    if date_to:
        query["datetime_to"] = date_to
    if page is not None:
        query["page"] = page
    return f"https://api.openaq.org/v3/sensors/{sensor_id}/measurements?{urlencode(query)}"


def build_openaq_station_observation_proxy(
    *,
    locations_payload: dict[str, Any],
    sensor_measurement_payloads: dict[str, dict[str, Any]],
    requested_location: dict[str, Any],
    scene_time_range: dict[str, Any],
    fetched_at: str,
) -> dict[str, Any]:
    """Normalize OpenAQ station metadata and measurement samples into a UWM proxy."""

    locations = _locations(locations_payload)
    sensors = [sensor for location in locations for sensor in _sensors(location)]
    measurements = [
        measurement
        for payload in sensor_measurement_payloads.values()
        for measurement in _measurements(payload)
    ]
    observed_start, observed_end = _observed_time_range(measurements)
    scene_holdout_ready = _covers_scene_range(observed_start, observed_end, scene_time_range)
    limitations = [
        "openaq_station_coverage_must_be_checked_for_city_representativeness",
        "not_policy_intervention_holdout_by_itself",
    ]
    if not scene_holdout_ready:
        limitations.append("station_observations_not_aligned_to_scene_period")
    return {
        "schema": OPENAQ_STATION_OBSERVATION_PROXY_SCHEMA,
        "source": "OpenAQ v3",
        "source_dataset_ids": ["openaq_air_quality_station_observation_proxy"],
        "requested_location": requested_location,
        "scene_time_range": {
            "start_date": str(scene_time_range.get("start_date") or ""),
            "end_date": str(scene_time_range.get("end_date") or ""),
        },
        "fetched_at": fetched_at,
        "record_counts": {
            "locations": len(locations),
            "sensors": len(sensors),
            "measurements": len(measurements),
        },
        "nearest_station": _nearest_station(locations),
        "observed_time_range": {"start": observed_start, "end": observed_end},
        "air_pollution_summary": _air_pollution_summary(measurements),
        "scene_holdout_ready": scene_holdout_ready,
        "mmfe_target_roles": ["air_pollution_exposure", "evidence_gate", "simulator_context"],
        "synthetic_flags": [
            {"dataset_id": "openaq_air_quality_station_observation_proxy", "status": "public_proxy"}
        ],
        "claim_boundary": {
            "max_claim_level": "bounded_support",
            "reason": (
                "OpenAQ station measurements are real public observations, but this "
                "snapshot must match the UWM scene period and evaluation design before "
                "it can serve as observed holdout."
            ),
        },
        "limitations": limitations,
        "empirical_superiority_claim": False,
    }


def write_openaq_station_snapshot(
    *,
    output_dir: str | Path,
    locations_payload: dict[str, Any],
    sensor_measurement_payloads: dict[str, dict[str, Any]],
    requested_location: dict[str, Any],
    scene_time_range: dict[str, Any],
    fetched_at: str,
) -> dict[str, Any]:
    """Persist OpenAQ raw payloads, normalized proxy and snapshot manifest without secrets."""

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    _write_json(output_path / "openaq_locations_raw.json", locations_payload)
    _write_json(output_path / "openaq_sensor_measurements_raw.json", sensor_measurement_payloads)
    proxy = build_openaq_station_observation_proxy(
        locations_payload=locations_payload,
        sensor_measurement_payloads=sensor_measurement_payloads,
        requested_location=requested_location,
        scene_time_range=scene_time_range,
        fetched_at=fetched_at,
    )
    _write_json(output_path / "openaq_station_observation_proxy.json", proxy)
    manifest = {
        "schema": "uwm.public_proxy_snapshot_manifest.v1",
        "dataset_id": "openaq_station_observation_proxy_snapshot",
        "source_dataset_ids": proxy["source_dataset_ids"],
        "fetched_at": fetched_at,
        "requested_location": requested_location,
        "scene_time_range": proxy["scene_time_range"],
        "files": {
            "locations_raw": "openaq_locations_raw.json",
            "sensor_measurements_raw": "openaq_sensor_measurements_raw.json",
            "normalized_proxy": "openaq_station_observation_proxy.json",
        },
        "record_counts": proxy["record_counts"],
        "observed_time_range": proxy["observed_time_range"],
        "scene_holdout_ready": proxy["scene_holdout_ready"],
        "claim_boundary": proxy["claim_boundary"],
        "limitations": proxy["limitations"],
        "mmfe_target_roles": proxy["mmfe_target_roles"],
        "empirical_superiority_claim": False,
    }
    _write_json(output_path / "snapshot_manifest.json", manifest)
    return manifest


def build_mmfe_state_input_from_openaq_station_proxy(
    proxy: dict[str, Any],
    *,
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Convert an OpenAQ station proxy into the MMFE UWM state-input contract."""

    from .mmfe_state_input import build_uwm_state_input_from_semantic_product

    if proxy.get("schema") != OPENAQ_STATION_OBSERVATION_PROXY_SCHEMA:
        raise ValueError(f"proxy schema must be {OPENAQ_STATION_OBSERVATION_PROXY_SCHEMA}")
    observed = proxy.get("observed_time_range") or {}
    start = str(observed.get("start") or "unknown_start")
    end = str(observed.get("end") or "unknown_end")
    counts = proxy.get("record_counts") or {}
    payload = build_uwm_state_input_from_semantic_product(
        {
            "product_id": f"mmfe-openaq-stations-{start}-{end}",
            "product_type": "semantic_fusion_product",
            "version": "0.1",
            "quality": {"score": 0.56},
        },
        semantic_relations=[
            {
                "semantic_relation_type": "station_has_air_quality_measurement",
                "uwm_usage": "air_pollution_exposure",
                "relation_count": counts.get("measurements", 0),
            },
            {
                "semantic_relation_type": "station_has_air_quality_sensor",
                "uwm_usage": "air_pollution_exposure",
                "relation_count": counts.get("sensors", 0),
            },
        ],
        input_contract={
            "spatial_unit": {
                "unit_type": "station_air_quality_proxy",
                "crs": "EPSG:4326",
                "location": proxy.get("nearest_station") or {},
                "temporal_extent": f"{start}/{end}",
            },
            "role_bindings": [
                {
                    "role": "openaq_station_air_quality_measurements",
                    "uwm_role": "air_pollution_exposure",
                    "object_type": "station_timeseries",
                    "source_dataset_id": "openaq_air_quality_station_observation_proxy",
                    "synthetic_status": "public_proxy",
                    "geometry_type": "point",
                    "spatial_support": {
                        "support_type": "sensor_footprint",
                        "support_id_field": "station_id",
                        "crs": "EPSG:4326",
                    },
                    "temporal_support": {
                        "resolution": "sensor_native",
                        "valid_from": start,
                        "valid_to": end,
                    },
                    "aggregation_semantics": "none",
                    "observation_semantics": "observed",
                }
            ],
        },
        timestamp=timestamp,
    )
    payload["source_proxy"] = {
        "schema": proxy.get("schema"),
        "observed_time_range": proxy.get("observed_time_range"),
        "record_counts": proxy.get("record_counts"),
        "scene_holdout_ready": bool(proxy.get("scene_holdout_ready")),
        "claim_boundary": proxy.get("claim_boundary"),
        "limitations": proxy.get("limitations") or [],
        "empirical_superiority_claim": False,
    }
    payload["warnings"].append(
        "OpenAQ station observations are not aligned to the UWM scene holdout period "
        "unless scene_holdout_ready is true"
    )
    return payload


def _locations(payload: dict[str, Any]) -> list[dict[str, Any]]:
    results = payload.get("results")
    return results if isinstance(results, list) else []


def _sensors(location: dict[str, Any]) -> list[dict[str, Any]]:
    sensors = location.get("sensors")
    return sensors if isinstance(sensors, list) else []


def _measurements(payload: dict[str, Any]) -> list[dict[str, Any]]:
    results = payload.get("results")
    return results if isinstance(results, list) else []


def _nearest_station(locations: list[dict[str, Any]]) -> dict[str, Any]:
    if not locations:
        return {}
    location = sorted(locations, key=lambda row: _float(row.get("distance")) or float("inf"))[0]
    coordinates = location.get("coordinates") or {}
    return {
        "id": location.get("id"),
        "name": location.get("name"),
        "distance_m": _float(location.get("distance")),
        "latitude": _float(coordinates.get("latitude")),
        "longitude": _float(coordinates.get("longitude")),
        "datetime_first_utc": _datetime_string(location.get("datetimeFirst")),
        "datetime_last_utc": _datetime_string(location.get("datetimeLast")),
    }


def _observed_time_range(
    measurements: list[dict[str, Any]],
) -> tuple[str | None, str | None]:
    bounds = [_measurement_datetime_bounds(measurement) for measurement in measurements]
    starts = [start for start, _ in bounds if start]
    ends = [end for _, end in bounds if end]
    starts = [value for value in starts if value]
    ends = [value for value in ends if value]
    return (min(starts) if starts else None, max(ends) if ends else None)


def _covers_scene_range(
    observed_start: str | None, observed_end: str | None, scene_time_range: dict[str, Any]
) -> bool:
    scene_start = str(scene_time_range.get("start_date") or "")
    scene_end = str(scene_time_range.get("end_date") or "")
    if not observed_start or not observed_end or not scene_start or not scene_end:
        return False
    return observed_start[:10] <= scene_start and observed_end[:10] >= scene_end


def _air_pollution_summary(measurements: list[dict[str, Any]]) -> dict[str, float | None]:
    pm25_values = []
    pm10_values = []
    for row in measurements:
        parameter = row.get("parameter") or {}
        name = str(parameter.get("name") or row.get("parameter") or "").lower().replace(".", "")
        value = _float(row.get("value"))
        if value is None:
            continue
        if name in {"pm25", "pm2_5"}:
            pm25_values.append(value)
        if name == "pm10":
            pm10_values.append(value)
    return {
        "pm25_avg_ugm3": _rounded_mean(pm25_values),
        "pm10_avg_ugm3": _rounded_mean(pm10_values),
    }


def _measurement_datetime_bounds(row: dict[str, Any]) -> tuple[str | None, str | None]:
    instant = _datetime_string(row.get("datetime"))
    period = row.get("period") or {}
    if not isinstance(period, dict):
        period = {}
    start = _datetime_string(period.get("datetimeFrom")) or instant
    end = _datetime_string(period.get("datetimeTo")) or instant
    return start, end


def _datetime_string(value: Any) -> str | None:
    if isinstance(value, dict):
        for key in ["utc", "local"]:
            if value.get(key):
                return str(value[key])
    if value:
        return str(value)
    return None


def _rounded_mean(values: Any) -> float | None:
    numbers = [number for number in (_float(value) for value in values) if number is not None]
    return round(mean(numbers), 3) if numbers else None


def _float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

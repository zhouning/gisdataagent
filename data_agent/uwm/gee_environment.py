"""GEE ERA5/CAMS environmental proxies for UWM state construction."""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any


GEE_ENVIRONMENTAL_PROXY_SCHEMA = "uwm.gee_era5_cams_environmental_proxy.v1"

GEE_ENVIRONMENT_ASSETS = {
    "era5": {
        "asset_id": "ECMWF/ERA5/HOURLY",
        "dataset_id": "gee_era5_hourly_chongqing_proxy",
        "role": "meteorology",
    },
    "cams": {
        "asset_id": "ECMWF/CAMS/NRT",
        "dataset_id": "gee_cams_nrt_chongqing_proxy",
        "role": "air_pollution_exposure",
    },
}


def build_gee_environmental_proxy(
    *,
    era5_payload: dict[str, Any],
    cams_payload: dict[str, Any],
    requested_location: dict[str, Any],
    time_range: dict[str, Any],
    fetched_at: str,
) -> dict[str, Any]:
    """Normalize sampled GEE ERA5 and CAMS feature collections into a UWM proxy."""

    era5_rows = [_props(feature) for feature in _features(era5_payload)]
    cams_rows = [_props(feature) for feature in _features(cams_payload)]
    return {
        "schema": GEE_ENVIRONMENTAL_PROXY_SCHEMA,
        "source": "Google Earth Engine",
        "source_dataset_ids": [
            GEE_ENVIRONMENT_ASSETS["era5"]["dataset_id"],
            GEE_ENVIRONMENT_ASSETS["cams"]["dataset_id"],
        ],
        "gee_assets": {
            "era5": GEE_ENVIRONMENT_ASSETS["era5"]["asset_id"],
            "cams": GEE_ENVIRONMENT_ASSETS["cams"]["asset_id"],
        },
        "requested_location": requested_location,
        "time_range": {
            "start_date": str(time_range.get("start_date") or ""),
            "end_date": str(time_range.get("end_date") or ""),
        },
        "fetched_at": fetched_at,
        "record_counts": {
            "era5_hourly": len(era5_rows),
            "cams_hourly": len(cams_rows),
        },
        "meteorology_summary": _meteorology_summary(era5_rows),
        "air_pollution_summary": _air_pollution_summary(cams_rows),
        "mmfe_target_roles": ["meteorology", "air_pollution_exposure", "simulator_context"],
        "synthetic_flags": [
            {"dataset_id": GEE_ENVIRONMENT_ASSETS["era5"]["dataset_id"], "status": "public_proxy"},
            {"dataset_id": GEE_ENVIRONMENT_ASSETS["cams"]["dataset_id"], "status": "public_proxy"},
        ],
        "claim_boundary": {
            "max_claim_level": "bounded_support",
            "reason": (
                "GEE ERA5/CAMS samples provide reproducible environmental context for UWM state "
                "construction, but reanalysis/model fields are not local observed station holdout."
            ),
        },
        "limitations": [
            "gee_reanalysis_or_model_proxy_not_station_holdout",
            "point_proxy_not_citywide_grid",
            "cams_nrt_product_not_policy_intervention_observation",
            "not_a_replacement_for_station_calibrated_holdout",
        ],
        "empirical_superiority_claim": False,
    }


def write_gee_environmental_snapshot(
    *,
    output_dir: str | Path,
    era5_payload: dict[str, Any],
    cams_payload: dict[str, Any],
    requested_location: dict[str, Any],
    time_range: dict[str, Any],
    fetched_at: str,
) -> dict[str, Any]:
    """Persist raw GEE payloads, normalized proxy and snapshot manifest."""

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    _write_json(output_path / "gee_era5_hourly_raw.json", era5_payload)
    _write_json(output_path / "gee_cams_nrt_raw.json", cams_payload)
    proxy = build_gee_environmental_proxy(
        era5_payload=era5_payload,
        cams_payload=cams_payload,
        requested_location=requested_location,
        time_range=time_range,
        fetched_at=fetched_at,
    )
    _write_json(output_path / "gee_era5_cams_environmental_proxy.json", proxy)
    manifest = {
        "schema": "uwm.public_proxy_snapshot_manifest.v1",
        "dataset_id": "gee_era5_cams_environmental_proxy_snapshot",
        "source_dataset_ids": proxy["source_dataset_ids"],
        "gee_assets": proxy["gee_assets"],
        "fetched_at": fetched_at,
        "requested_location": requested_location,
        "time_range": proxy["time_range"],
        "files": {
            "era5_raw": "gee_era5_hourly_raw.json",
            "cams_raw": "gee_cams_nrt_raw.json",
            "normalized_proxy": "gee_era5_cams_environmental_proxy.json",
        },
        "record_counts": proxy["record_counts"],
        "claim_boundary": proxy["claim_boundary"],
        "limitations": proxy["limitations"],
        "mmfe_target_roles": proxy["mmfe_target_roles"],
        "empirical_superiority_claim": False,
    }
    _write_json(output_path / "snapshot_manifest.json", manifest)
    return manifest


def build_mmfe_state_input_from_gee_environmental_proxy(
    proxy: dict[str, Any],
    *,
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Convert a GEE environmental proxy into the MMFE UWM state-input contract."""

    from .mmfe_state_input import build_uwm_state_input_from_semantic_product

    if proxy.get("schema") != GEE_ENVIRONMENTAL_PROXY_SCHEMA:
        raise ValueError(f"proxy schema must be {GEE_ENVIRONMENTAL_PROXY_SCHEMA}")
    time_range = proxy.get("time_range") or {}
    start_date = str(time_range.get("start_date") or "unknown_start")
    end_date = str(time_range.get("end_date") or "unknown_end")
    counts = proxy.get("record_counts") or {}
    payload = build_uwm_state_input_from_semantic_product(
        {
            "product_id": f"mmfe-gee-era5-cams-{start_date}-{end_date}",
            "product_type": "semantic_fusion_product",
            "version": "0.1",
            "quality": {"score": 0.58},
        },
        semantic_relations=[
            {
                "semantic_relation_type": "point_has_era5_hourly_record",
                "uwm_usage": "meteorology",
                "relation_count": counts.get("era5_hourly", 0),
            },
            {
                "semantic_relation_type": "point_has_cams_hourly_record",
                "uwm_usage": "air_pollution_exposure",
                "relation_count": counts.get("cams_hourly", 0),
            },
        ],
        input_contract={
            "spatial_unit": {
                "unit_type": "gee_point_environmental_proxy",
                "crs": "EPSG:4326",
                "location": proxy.get("requested_location") or {},
                "temporal_extent": f"{start_date}/{end_date}",
            },
            "role_bindings": [
                {
                    "role": "gee_era5_hourly_meteorology",
                    "uwm_role": "meteorology",
                    "object_type": "point_timeseries",
                    "source_dataset_id": GEE_ENVIRONMENT_ASSETS["era5"]["dataset_id"],
                    "synthetic_status": "public_proxy",
                },
                {
                    "role": "gee_cams_nrt_air_pollution",
                    "uwm_role": "air_pollution_exposure",
                    "object_type": "point_timeseries",
                    "source_dataset_id": GEE_ENVIRONMENT_ASSETS["cams"]["dataset_id"],
                    "synthetic_status": "public_proxy",
                },
            ],
        },
        timestamp=timestamp,
    )
    payload["source_proxy"] = {
        "schema": proxy.get("schema"),
        "gee_assets": proxy.get("gee_assets"),
        "time_range": proxy.get("time_range"),
        "record_counts": proxy.get("record_counts"),
        "claim_boundary": proxy.get("claim_boundary"),
        "limitations": proxy.get("limitations") or [],
        "empirical_superiority_claim": False,
    }
    payload["warnings"].append(
        "GEE ERA5/CAMS proxy is not observed station holdout evidence and must not unlock empirical superiority claims"
    )
    return payload


def _features(payload: dict[str, Any]) -> list[dict[str, Any]]:
    features = payload.get("features")
    return features if isinstance(features, list) else []


def _props(feature: dict[str, Any]) -> dict[str, Any]:
    props = feature.get("properties")
    return props if isinstance(props, dict) else {}


def _meteorology_summary(rows: list[dict[str, Any]]) -> dict[str, float | None]:
    wind_speeds = []
    for row in rows:
        u = _float(row.get("u_component_of_wind_10m"))
        v = _float(row.get("v_component_of_wind_10m"))
        if u is not None and v is not None:
            wind_speeds.append(math.sqrt(u * u + v * v))
    return {
        "temperature_2m_mean_avg_c": _rounded_mean(_kelvin_to_celsius(row.get("temperature_2m")) for row in rows),
        "surface_pressure_avg_hpa": _rounded_mean(_pa_to_hpa(row.get("surface_pressure")) for row in rows),
        "wind_speed_10m_avg_ms": _rounded_mean(wind_speeds),
        "precipitation_total_mm": _rounded_sum(_metres_to_mm(row.get("total_precipitation")) for row in rows),
    }


def _air_pollution_summary(rows: list[dict[str, Any]]) -> dict[str, float | None]:
    return {
        "cams_pm25_avg_ugm3": _rounded_mean(
            _kgm3_to_ugm3(row.get("particulate_matter_d_less_than_25_um_surface")) for row in rows
        ),
        "cams_aod550_avg": _rounded_mean(row.get("total_aerosol_optical_depth_at_550nm_surface") for row in rows),
    }


def _kelvin_to_celsius(value: Any) -> float | None:
    number = _float(value)
    return number - 273.15 if number is not None else None


def _pa_to_hpa(value: Any) -> float | None:
    number = _float(value)
    return number / 100.0 if number is not None else None


def _metres_to_mm(value: Any) -> float | None:
    number = _float(value)
    return number * 1000.0 if number is not None else None


def _kgm3_to_ugm3(value: Any) -> float | None:
    number = _float(value)
    return number * 1_000_000_000.0 if number is not None else None


def _rounded_mean(values: Any) -> float | None:
    numbers = _numbers(values)
    return round(mean(numbers), 3) if numbers else None


def _rounded_sum(values: Any) -> float | None:
    numbers = _numbers(values)
    return round(sum(numbers), 3) if numbers else None


def _numbers(values: Any) -> list[float]:
    return [number for number in (_float(value) for value in values) if number is not None]


def _float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def utc_now_iso() -> str:
    """Return a stable UTC timestamp string for scripts."""

    return datetime.now(timezone.utc).isoformat()

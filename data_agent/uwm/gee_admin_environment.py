"""GEE ERA5/CAMS administrative representative-point proxies for UWM."""

from __future__ import annotations

import json
import math
from pathlib import Path
from statistics import mean
from typing import Any


GEE_ADMIN_ENVIRONMENT_PROXY_SCHEMA = "uwm.gee_admin_environment_proxy.v1"
GEE_ADMIN_ENVIRONMENT_DATASET_ID = "gee_admin_environment_chongqing_proxy"


def build_gee_admin_environment_proxy(
    *,
    sampled_payload: dict[str, Any],
    requested_admin_source: dict[str, Any],
    time_range: dict[str, Any],
    fetched_at: str,
) -> dict[str, Any]:
    """Normalize GEE admin representative-point samples into a spatial proxy."""

    admin_feature_count = _safe_int(requested_admin_source.get("feature_count"), default=0)
    rows = [_normalise_row(feature.get("properties") or {}) for feature in _features(sampled_payload)]
    rows = [row for row in rows if row]
    sampled_admin_count = len(rows)
    return {
        "schema": GEE_ADMIN_ENVIRONMENT_PROXY_SCHEMA,
        "source": "Google Earth Engine",
        "source_dataset_ids": [GEE_ADMIN_ENVIRONMENT_DATASET_ID],
        "source_assets": {
            "era5": "ECMWF/ERA5/HOURLY",
            "cams": "ECMWF/CAMS/NRT",
            "admin_units": requested_admin_source.get("dataset_id"),
        },
        "time_range": {
            "start_date": str(time_range.get("start_date") or ""),
            "end_date": str(time_range.get("end_date") or ""),
        },
        "fetched_at": fetched_at,
        "admin_feature_count": admin_feature_count,
        "sampled_admin_count": sampled_admin_count,
        "coverage": {
            "sampled_admin_share": round(sampled_admin_count / admin_feature_count, 6)
            if admin_feature_count
            else 0.0,
            "sampling_geometry": "admin_representative_point",
        },
        "admin_environment_rows": rows,
        "summary": _summary(rows),
        "mmfe_target_roles": ["meteorology", "air_pollution_exposure", "admin_environment_context"],
        "synthetic_flags": [{"dataset_id": GEE_ADMIN_ENVIRONMENT_DATASET_ID, "status": "public_proxy"}],
        "claim_boundary": {
            "max_claim_level": "bounded_support",
            "reason": (
                "GEE ERA5/CAMS representative-point samples provide spatial environmental context, "
                "but they are not polygon zonal means and not observed station holdout."
            ),
        },
        "limitations": [
            "representative_point_not_zonal_mean",
            "gee_reanalysis_or_model_proxy_not_station_holdout",
            "admin_geometry_vintage_license_crosswalk_pending",
            "not_policy_intervention_holdout",
        ],
        "empirical_superiority_claim": False,
    }


def write_gee_admin_environment_snapshot(
    *,
    output_dir: str | Path,
    sampled_payload: dict[str, Any],
    requested_admin_source: dict[str, Any],
    time_range: dict[str, Any],
    fetched_at: str,
) -> dict[str, Any]:
    """Persist raw admin samples, normalized proxy and manifest."""

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    _write_json(output_path / "gee_admin_environment_samples_raw.json", sampled_payload)
    proxy = build_gee_admin_environment_proxy(
        sampled_payload=sampled_payload,
        requested_admin_source=requested_admin_source,
        time_range=time_range,
        fetched_at=fetched_at,
    )
    _write_json(output_path / "gee_admin_environment_proxy.json", proxy)
    manifest = {
        "schema": "uwm.public_proxy_snapshot_manifest.v1",
        "dataset_id": "gee_admin_environment_proxy_snapshot",
        "source_dataset_ids": proxy["source_dataset_ids"],
        "source_assets": proxy["source_assets"],
        "fetched_at": fetched_at,
        "time_range": proxy["time_range"],
        "files": {
            "raw_samples": "gee_admin_environment_samples_raw.json",
            "normalized_proxy": "gee_admin_environment_proxy.json",
        },
        "record_counts": {
            "admin_features": proxy["admin_feature_count"],
            "sampled_admin_units": proxy["sampled_admin_count"],
        },
        "coverage": proxy["coverage"],
        "claim_boundary": proxy["claim_boundary"],
        "limitations": proxy["limitations"],
        "mmfe_target_roles": proxy["mmfe_target_roles"],
        "empirical_superiority_claim": False,
    }
    _write_json(output_path / "snapshot_manifest.json", manifest)
    return manifest


def build_mmfe_state_input_from_gee_admin_environment_proxy(
    proxy: dict[str, Any],
    *,
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Convert GEE admin environment proxy into MMFE UWM state input."""

    from .mmfe_state_input import build_uwm_state_input_from_semantic_product

    if proxy.get("schema") != GEE_ADMIN_ENVIRONMENT_PROXY_SCHEMA:
        raise ValueError(f"proxy schema must be {GEE_ADMIN_ENVIRONMENT_PROXY_SCHEMA}")
    time_range = proxy.get("time_range") or {}
    start_date = str(time_range.get("start_date") or "unknown_start")
    end_date = str(time_range.get("end_date") or "unknown_end")
    sampled_count = _safe_int(proxy.get("sampled_admin_count"), default=0)
    payload = build_uwm_state_input_from_semantic_product(
        {
            "product_id": f"mmfe-gee-admin-environment-{start_date}-{end_date}",
            "product_type": "semantic_fusion_product",
            "version": "0.1",
            "quality": {"score": 0.57},
        },
        semantic_relations=[
            {
                "semantic_relation_type": "admin_unit_has_environment_representative_point",
                "uwm_usage": "meteorology",
                "relation_count": sampled_count,
            },
            {
                "semantic_relation_type": "admin_unit_has_air_pollution_representative_point",
                "uwm_usage": "air_pollution_exposure",
                "relation_count": sampled_count,
            },
        ],
        input_contract={
            "spatial_unit": {
                "unit_type": "admin_representative_point_environment_proxy",
                "crs": "EPSG:4326",
                "temporal_extent": f"{start_date}/{end_date}",
                "admin_feature_count": proxy.get("admin_feature_count"),
            },
            "role_bindings": [
                {
                    "role": "gee_admin_representative_point_meteorology",
                    "uwm_role": "meteorology",
                    "object_type": "admin_point_timeseries_summary",
                    "source_dataset_id": GEE_ADMIN_ENVIRONMENT_DATASET_ID,
                    "synthetic_status": "public_proxy",
                },
                {
                    "role": "gee_admin_representative_point_air_pollution",
                    "uwm_role": "air_pollution_exposure",
                    "object_type": "admin_point_timeseries_summary",
                    "source_dataset_id": GEE_ADMIN_ENVIRONMENT_DATASET_ID,
                    "synthetic_status": "public_proxy",
                },
            ],
        },
        timestamp=timestamp,
    )
    payload["source_proxy"] = {
        "schema": proxy.get("schema"),
        "time_range": proxy.get("time_range"),
        "record_counts": {
            "admin_features": proxy.get("admin_feature_count"),
            "sampled_admin_units": proxy.get("sampled_admin_count"),
        },
        "coverage": proxy.get("coverage"),
        "claim_boundary": proxy.get("claim_boundary"),
        "limitations": proxy.get("limitations") or [],
        "empirical_superiority_claim": False,
    }
    payload["warnings"].append(
        "GEE admin environment proxy uses representative point samples, not polygon zonal mean or observed station holdout"
    )
    return payload


def _normalise_row(props: dict[str, Any]) -> dict[str, Any]:
    admin_id = str(props.get("admin_id") or "").strip()
    if not admin_id:
        return {}
    u = _safe_float(props.get("u_component_of_wind_10m"))
    v = _safe_float(props.get("v_component_of_wind_10m"))
    wind = math.sqrt(u * u + v * v) if u is not None and v is not None else None
    return {
        "admin_id": admin_id,
        "county": str(props.get("county") or ""),
        "township": str(props.get("township") or ""),
        "longitude": _safe_float(props.get("longitude")),
        "latitude": _safe_float(props.get("latitude")),
        "temperature_2m_mean_c": _round(_kelvin_to_celsius(props.get("temperature_2m"))),
        "surface_pressure_hpa": _round(_pa_to_hpa(props.get("surface_pressure"))),
        "wind_speed_10m_ms": _round(wind),
        "precipitation_total_mm": _round(_metres_to_mm(props.get("total_precipitation_sum"))),
        "cams_pm25_ugm3": _round(_kgm3_to_ugm3(props.get("particulate_matter_d_less_than_25_um_surface"))),
        "cams_aod550": _round(props.get("total_aerosol_optical_depth_at_550nm_surface")),
    }


def _summary(rows: list[dict[str, Any]]) -> dict[str, float | int | None]:
    return {
        "admin_count": len(rows),
        "temperature_2m_mean_c_avg": _rounded_mean(row.get("temperature_2m_mean_c") for row in rows),
        "precipitation_total_mm_avg": _rounded_mean(row.get("precipitation_total_mm") for row in rows),
        "cams_pm25_ugm3_avg": _rounded_mean(row.get("cams_pm25_ugm3") for row in rows),
        "cams_pm25_ugm3_max": _rounded_max(row.get("cams_pm25_ugm3") for row in rows),
    }


def _features(payload: dict[str, Any]) -> list[dict[str, Any]]:
    features = payload.get("features")
    return features if isinstance(features, list) else []


def _kelvin_to_celsius(value: Any) -> float | None:
    number = _safe_float(value)
    return number - 273.15 if number is not None else None


def _pa_to_hpa(value: Any) -> float | None:
    number = _safe_float(value)
    return number / 100.0 if number is not None else None


def _metres_to_mm(value: Any) -> float | None:
    number = _safe_float(value)
    return number * 1000.0 if number is not None else None


def _kgm3_to_ugm3(value: Any) -> float | None:
    number = _safe_float(value)
    return number * 1_000_000_000.0 if number is not None else None


def _rounded_mean(values: Any) -> float | None:
    numbers = [number for number in (_safe_float(value) for value in values) if number is not None]
    return round(mean(numbers), 3) if numbers else None


def _rounded_max(values: Any) -> float | None:
    numbers = [number for number in (_safe_float(value) for value in values) if number is not None]
    return round(max(numbers), 3) if numbers else None


def _round(value: Any) -> float | None:
    number = _safe_float(value)
    return round(number, 3) if number is not None else None


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any, *, default: int) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

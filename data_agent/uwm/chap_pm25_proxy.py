"""CHAP PM2.5 gridded proxy alignment for UWM."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

import h5py
import numpy as np
from shapely.geometry import shape


CHAP_PM25_ADMIN_PROXY_SCHEMA = "uwm.chap_pm25_admin_proxy.v1"
SOURCE_DATASET_ID = "chap_pm25_monthly_1km_2024_07_proxy"


def build_chap_pm25_admin_proxy(
    *,
    nc_path: str | Path,
    admin_geojson: dict[str, Any],
    selected_admin_ids: set[str] | None = None,
    fetched_at: str | None = None,
) -> dict[str, Any]:
    """Sample CHAP monthly 1 km PM2.5 at admin representative points."""

    fetched_at = fetched_at or _utc_now()
    grid = _read_chap_grid(nc_path)
    selected_admin_ids = {str(value) for value in selected_admin_ids} if selected_admin_ids else None
    admin_features = _selected_admin_features(admin_geojson, selected_admin_ids)
    rows = [_sample_admin_feature(feature, grid, index) for index, feature in enumerate(admin_features)]
    valid_values = [row["pm25_ugm3"] for row in rows if row.get("pm25_ugm3") is not None]

    return {
        "schema": CHAP_PM25_ADMIN_PROXY_SCHEMA,
        "source": "ChinaHighAirPollutants / ChinaHighPM2.5",
        "source_dataset_ids": [SOURCE_DATASET_ID],
        "source_ref": "https://doi.org/10.5281/zenodo.10472665",
        "source_file": str(Path(nc_path)),
        "time_range": {"month": "2024-07", "temporal_resolution": "monthly"},
        "fetched_at": fetched_at,
        "grid_metadata": {
            "pm25_shape": list(grid["pm25"].shape),
            "lat_count": int(grid["lat"].shape[0]),
            "lon_count": int(grid["lon"].shape[0]),
            "lat_min": _round(float(np.nanmin(grid["lat"]))),
            "lat_max": _round(float(np.nanmax(grid["lat"]))),
            "lon_min": _round(float(np.nanmin(grid["lon"]))),
            "lon_max": _round(float(np.nanmax(grid["lon"]))),
            "units": grid["units"],
            "scale_factor": grid["scale_factor"],
            "add_offset": grid["add_offset"],
            "fill_value": grid["fill_value"],
        },
        "record_counts": {
            "requested_admin_units": len(admin_features),
            "sampled_admin_units": len(rows),
            "valid_pm25_admin_units": len(valid_values),
            "missing_pm25_admin_units": len(rows) - len(valid_values),
        },
        "coverage": {
            "sampling_geometry": "admin_representative_point_nearest_grid_cell",
            "grid_resolution": "1 km monthly",
            "valid_pm25_share": _round(len(valid_values) / len(rows)) if rows else 0.0,
        },
        "admin_pm25_rows": rows,
        "summary": {
            "pm25_avg_ugm3": _rounded_mean(valid_values),
            "pm25_min_ugm3": _rounded_min(valid_values),
            "pm25_max_ugm3": _rounded_max(valid_values),
        },
        "synthetic_flags": [{"dataset_id": SOURCE_DATASET_ID, "status": "public_proxy"}],
        "claim_boundary": {
            "max_claim_level": "bounded_support",
            "reason": (
                "CHAP PM2.5 is an openly released AI-fused gridded product using monitoring, "
                "remote sensing, reanalysis and model inputs; it improves scene air-pollution "
                "coverage but is not an observed station or policy-intervention holdout."
            ),
        },
        "limitations": [
            "ai_fused_gridded_product_not_station_observation",
            "monthly_mean_not_hourly_scene_state",
            "representative_point_nearest_grid_cell_not_polygon_zonal_mean",
            "not_policy_intervention_outcome",
        ],
        "empirical_superiority_claim": False,
    }


def write_chap_pm25_admin_proxy_snapshot(
    *,
    nc_path: str | Path,
    admin_geojson: dict[str, Any],
    output_dir: str | Path,
    selected_admin_ids: set[str] | None = None,
    fetched_at: str | None = None,
) -> dict[str, Any]:
    """Write CHAP PM2.5 UWM proxy and snapshot manifest."""

    proxy = build_chap_pm25_admin_proxy(
        nc_path=nc_path,
        admin_geojson=admin_geojson,
        selected_admin_ids=selected_admin_ids,
        fetched_at=fetched_at,
    )
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    _write_json(output / "chap_pm25_admin_proxy.json", proxy)
    manifest = {
        "schema": "uwm.public_proxy_snapshot_manifest.v1",
        "dataset_id": "chap_pm25_monthly_1km_2024_07_proxy_snapshot",
        "source_dataset_ids": proxy["source_dataset_ids"],
        "source_ref": proxy["source_ref"],
        "source_file": str(Path(nc_path)),
        "fetched_at": proxy["fetched_at"],
        "time_range": proxy["time_range"],
        "files": {
            "raw_netcdf": Path(nc_path).name,
            "normalized_proxy": "chap_pm25_admin_proxy.json",
        },
        "grid_metadata": proxy["grid_metadata"],
        "record_counts": proxy["record_counts"],
        "coverage": proxy["coverage"],
        "summary": proxy["summary"],
        "claim_boundary": proxy["claim_boundary"],
        "limitations": proxy["limitations"],
        "empirical_superiority_claim": False,
    }
    _write_json(output / "snapshot_manifest.json", manifest)
    return manifest


def _read_chap_grid(nc_path: str | Path) -> dict[str, Any]:
    with h5py.File(nc_path, "r") as handle:
        pm25 = handle["PM2.5"]
        return {
            "pm25": pm25[:],
            "lat": handle["lat"][:],
            "lon": handle["lon"][:],
            "fill_value": _scalar_attr(pm25.attrs.get("_FillValue"), default=65535),
            "scale_factor": _scalar_attr(pm25.attrs.get("scale_factor"), default=1.0),
            "add_offset": _scalar_attr(pm25.attrs.get("add_offset"), default=0.0),
            "units": _decode_attr(pm25.attrs.get("units"), default="ug/m3"),
        }


def _selected_admin_features(
    admin_geojson: dict[str, Any],
    selected_admin_ids: set[str] | None,
) -> list[dict[str, Any]]:
    features = []
    for index, feature in enumerate(admin_geojson.get("features") or []):
        props = feature.get("properties") or {}
        admin_unit_id = str(props.get("admin_unit_id") or _fallback_admin_unit_id(props, index))
        if selected_admin_ids is not None and admin_unit_id not in selected_admin_ids:
            continue
        features.append(feature)
    return features


def _sample_admin_feature(feature: dict[str, Any], grid: dict[str, Any], index: int) -> dict[str, Any]:
    props = feature.get("properties") or {}
    admin_unit_id = str(props.get("admin_unit_id") or _fallback_admin_unit_id(props, index))
    point = shape(feature.get("geometry")).representative_point()
    lat_index = int(np.abs(grid["lat"] - float(point.y)).argmin())
    lon_index = int(np.abs(grid["lon"] - float(point.x)).argmin())
    raw_value = grid["pm25"][lat_index, lon_index]
    value = _scaled_value(
        raw_value,
        fill_value=grid["fill_value"],
        scale_factor=grid["scale_factor"],
        add_offset=grid["add_offset"],
    )
    return {
        "admin_unit_id": admin_unit_id,
        "county": str(props.get("county") or ""),
        "township": str(props.get("township") or ""),
        "longitude": _round(float(point.x)),
        "latitude": _round(float(point.y)),
        "nearest_grid_longitude": _round(float(grid["lon"][lon_index])),
        "nearest_grid_latitude": _round(float(grid["lat"][lat_index])),
        "grid_row": lat_index,
        "grid_col": lon_index,
        "pm25_ugm3": _round(value),
        "raw_pm25_value": int(raw_value),
    }


def _scaled_value(
    value: Any,
    *,
    fill_value: float | int,
    scale_factor: float,
    add_offset: float,
) -> float | None:
    number = float(value)
    if number == float(fill_value):
        return None
    return number * scale_factor + add_offset


def _fallback_admin_unit_id(props: dict[str, Any], index: int) -> str:
    return f"{str(props.get('county') or '')}|{str(props.get('township') or '')}|{index}"


def _scalar_attr(value: Any, *, default: float) -> float:
    if value is None:
        return float(default)
    if isinstance(value, np.ndarray):
        return float(value.reshape(-1)[0])
    if isinstance(value, (list, tuple)):
        return float(value[0])
    return float(value)


def _decode_attr(value: Any, *, default: str) -> str:
    if value is None:
        return default
    if isinstance(value, np.ndarray):
        value = value.reshape(-1)[0]
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if hasattr(value, "decode"):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _rounded_mean(values: list[float]) -> float | None:
    return _round(mean(values)) if values else None


def _rounded_min(values: list[float]) -> float | None:
    return _round(min(values)) if values else None


def _rounded_max(values: list[float]) -> float | None:
    return _round(max(values)) if values else None


def _round(value: Any) -> float | None:
    if value is None:
        return None
    return round(float(value), 6)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

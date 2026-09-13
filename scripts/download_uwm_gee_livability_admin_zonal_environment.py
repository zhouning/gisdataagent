"""Download GEE ERA5/CAMS zonal proxy for UWM livability candidate admin units."""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import ee
from shapely.geometry import shape


REPO_ROOT = Path(__file__).resolve().parents[1]
ADMIN_GEOJSON = REPO_ROOT / "data/uwm_public_proxy/chongqing_central/admin_units/chongqing_township_admin_units.geojson"
LIVABILITY_PANEL = (
    REPO_ROOT
    / "data/uwm_public_proxy/chongqing_central/admin_livability_target_2024_07_2026_07_05/uwm_admin_livability_target_panel.json"
)
OUTPUT_DIR = (
    REPO_ROOT
    / "data/uwm_public_proxy/chongqing_central/gee_livability_admin_zonal_environment_2024_07_01_07"
)


def main() -> None:
    start_date = "2024-07-01"
    end_date_exclusive = "2024-07-08"
    ee.Initialize()
    panel = _load_json(LIVABILITY_PANEL)
    selected_ids = {str(row.get("admin_unit_id")) for row in panel.get("admin_livability_target_rows") or []}
    admin_features = _selected_admin_features(_load_json(ADMIN_GEOJSON), selected_ids)
    image = _build_environment_image(start_date, end_date_exclusive)
    raw = image.reduceRegions(
        collection=ee.FeatureCollection(admin_features),
        reducer=ee.Reducer.mean(),
        scale=40000,
        tileScale=4,
    ).getInfo()
    raw["source_assets"] = {
        "era5": "ECMWF/ERA5/HOURLY",
        "cams": "ECMWF/CAMS/NRT",
        "admin_units": str(ADMIN_GEOJSON.relative_to(REPO_ROOT)),
        "livability_panel": str(LIVABILITY_PANEL.relative_to(REPO_ROOT)),
    }
    fetched_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    proxy = _normalise_proxy(
        raw,
        requested_admin_count=len(selected_ids),
        start_date=start_date,
        end_date="2024-07-07",
        fetched_at=fetched_at,
    )
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _write_json(OUTPUT_DIR / "gee_livability_admin_zonal_environment_raw.json", raw)
    _write_json(OUTPUT_DIR / "gee_livability_admin_zonal_environment_proxy.json", proxy)
    _write_json(
        OUTPUT_DIR / "snapshot_manifest.json",
        {
            "schema": "uwm.public_proxy_snapshot_manifest.v1",
            "dataset_id": "gee_livability_admin_zonal_environment_proxy_snapshot",
            "source_dataset_ids": proxy["source_dataset_ids"],
            "source_assets": raw["source_assets"],
            "fetched_at": fetched_at,
            "time_range": proxy["time_range"],
            "files": {
                "raw": "gee_livability_admin_zonal_environment_raw.json",
                "normalized_proxy": "gee_livability_admin_zonal_environment_proxy.json",
            },
            "record_counts": proxy["record_counts"],
            "coverage": proxy["coverage"],
            "claim_boundary": proxy["claim_boundary"],
            "limitations": proxy["limitations"],
            "empirical_superiority_claim": False,
        },
    )
    print(
        json.dumps(
            {
                "output_dir": str(OUTPUT_DIR.relative_to(REPO_ROOT)),
                "record_counts": proxy["record_counts"],
                "coverage": proxy["coverage"],
                "summary": proxy["summary"],
                "claim_boundary": proxy["claim_boundary"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _selected_admin_features(admin_geojson: dict[str, Any], selected_ids: set[str]) -> list[ee.Feature]:
    features = []
    for index, feature in enumerate(admin_geojson.get("features") or []):
        props = feature.get("properties") or {}
        admin_unit_id = str(props.get("admin_unit_id") or _fallback_admin_unit_id(props, index))
        if admin_unit_id not in selected_ids:
            continue
        geom = shape(feature.get("geometry"))
        simplified = geom.simplify(0.002, preserve_topology=True)
        point = geom.representative_point()
        features.append(
            ee.Feature(
                ee.Geometry(simplified.__geo_interface__),
                {
                    "admin_unit_id": admin_unit_id,
                    "county": str(props.get("county") or ""),
                    "township": str(props.get("township") or ""),
                    "longitude": float(point.x),
                    "latitude": float(point.y),
                },
            )
        )
    return features


def _build_environment_image(start_date: str, end_date: str) -> Any:
    era5 = ee.ImageCollection("ECMWF/ERA5/HOURLY").filterDate(start_date, end_date)
    era5_mean = era5.select(
        [
            "temperature_2m",
            "surface_pressure",
            "u_component_of_wind_10m",
            "v_component_of_wind_10m",
        ]
    ).mean()
    era5_precip = era5.select("total_precipitation").sum().rename("total_precipitation_sum")
    cams_mean = (
        ee.ImageCollection("ECMWF/CAMS/NRT")
        .filterDate(start_date, end_date)
        .select(
            [
                "particulate_matter_d_less_than_25_um_surface",
                "total_aerosol_optical_depth_at_550nm_surface",
            ]
        )
        .mean()
    )
    return era5_mean.addBands(era5_precip).addBands(cams_mean)


def _normalise_proxy(
    raw: dict[str, Any],
    *,
    requested_admin_count: int,
    start_date: str,
    end_date: str,
    fetched_at: str,
) -> dict[str, Any]:
    rows = [_normalise_row(feature.get("properties") or {}) for feature in raw.get("features") or []]
    rows = [row for row in rows if row]
    return {
        "schema": "uwm.gee_livability_admin_zonal_environment_proxy.v1",
        "source": "Google Earth Engine",
        "source_dataset_ids": ["gee_livability_admin_zonal_environment_proxy"],
        "source_assets": raw.get("source_assets") or {},
        "time_range": {"start_date": start_date, "end_date": end_date},
        "fetched_at": fetched_at,
        "record_counts": {
            "requested_admin_units": requested_admin_count,
            "zonal_admin_units": len(rows),
        },
        "coverage": {
            "zonal_admin_share": round(len(rows) / requested_admin_count, 6) if requested_admin_count else 0.0,
            "sampling_geometry": "simplified_admin_polygon_zonal_mean",
        },
        "admin_environment_rows": rows,
        "summary": _summary(rows),
        "synthetic_flags": [
            {"dataset_id": "gee_livability_admin_zonal_environment_proxy", "status": "public_proxy"}
        ],
        "claim_boundary": {
            "max_claim_level": "bounded_support",
            "reason": "ERA5/CAMS zonal means over simplified admin polygons improve scene context but remain model proxies rather than observed holdout.",
        },
        "limitations": [
            "gee_reanalysis_or_model_proxy_not_station_holdout",
            "simplified_admin_polygon_zonal_mean",
            "coarse_era5_cams_resolution_relative_to_township_polygons",
            "not_policy_intervention_holdout",
        ],
        "empirical_superiority_claim": False,
    }


def _normalise_row(props: dict[str, Any]) -> dict[str, Any]:
    u = _safe_float(props.get("u_component_of_wind_10m"))
    v = _safe_float(props.get("v_component_of_wind_10m"))
    wind = math.sqrt(u * u + v * v) if u is not None and v is not None else None
    return {
        "admin_unit_id": str(props.get("admin_unit_id") or ""),
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


def _fallback_admin_unit_id(props: dict[str, Any], index: int) -> str:
    return f"{str(props.get('county') or '')}|{str(props.get('township') or '')}|{index}"


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
    return round(sum(numbers) / len(numbers), 3) if numbers else None


def _rounded_max(values: Any) -> float | None:
    numbers = [number for number in (_safe_float(value) for value in values) if number is not None]
    return round(max(numbers), 3) if numbers else None


def _round(value: Any) -> float | None:
    number = _safe_float(value)
    return round(number, 3) if number is not None else None


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


if __name__ == "__main__":
    main()

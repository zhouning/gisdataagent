"""Download GEE ERA5/CAMS representative-point samples for Chongqing admin units."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import ee
import geopandas as gpd

from data_agent.uwm.gee_admin_environment import (
    build_mmfe_state_input_from_gee_admin_environment_proxy,
    write_gee_admin_environment_snapshot,
)


ADMIN_SOURCE_DATASET_ID = "chongqing_township_admin_units_local"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--admin-geojson",
        default="data/uwm_public_proxy/chongqing_central/admin_units/chongqing_township_admin_units.geojson",
    )
    parser.add_argument("--start-date", default="2024-07-01")
    parser.add_argument("--end-date-exclusive", default="2024-07-08")
    parser.add_argument(
        "--output-dir",
        default="data/uwm_public_proxy/chongqing_central/gee_admin_environment_2024_07_01_07",
    )
    args = parser.parse_args()

    ee.Initialize()
    admin_points, feature_count = _load_admin_representative_points(Path(args.admin_geojson))
    sample_image = _build_environment_image(args.start_date, args.end_date_exclusive)
    sampled_payload = sample_image.reduceRegions(
        collection=ee.FeatureCollection(admin_points),
        reducer=ee.Reducer.first(),
        scale=40000,
    ).getInfo()
    sampled_payload["source_assets"] = {
        "era5": "ECMWF/ERA5/HOURLY",
        "cams": "ECMWF/CAMS/NRT",
        "admin_units": args.admin_geojson,
    }
    fetched_at = datetime.now(timezone.utc).isoformat()
    output_dir = Path(args.output_dir)
    manifest = write_gee_admin_environment_snapshot(
        output_dir=output_dir,
        sampled_payload=sampled_payload,
        requested_admin_source={
            "dataset_id": ADMIN_SOURCE_DATASET_ID,
            "feature_count": feature_count,
            "source_path": args.admin_geojson,
        },
        time_range={
            "start_date": args.start_date,
            "end_date": _inclusive_end_date(args.end_date_exclusive),
        },
        fetched_at=fetched_at,
    )
    proxy = json.loads((output_dir / "gee_admin_environment_proxy.json").read_text(encoding="utf-8"))
    state_input = build_mmfe_state_input_from_gee_admin_environment_proxy(proxy, timestamp=fetched_at)
    _write_json(output_dir / "mmfe_uwm_state_input_gee_admin_environment.json", state_input)
    print(
        json.dumps(
            {
                "output_dir": str(output_dir),
                "record_counts": manifest["record_counts"],
                "coverage": manifest["coverage"],
                "claim_boundary": manifest["claim_boundary"],
            },
            ensure_ascii=False,
        )
    )


def _load_admin_representative_points(path: Path) -> tuple[list[ee.Feature], int]:
    gdf = gpd.read_file(path)
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")
    gdf = gdf.to_crs("EPSG:4326")
    features = []
    for index, row in gdf.iterrows():
        point = row.geometry.representative_point()
        admin_id = f"cq-admin-{index:04d}"
        properties = {
            "admin_id": admin_id,
            "province": _string(row.get("province")),
            "city": _string(row.get("city")),
            "county": _string(row.get("county")),
            "township": _string(row.get("township")),
            "city_county": _string(row.get("city_county")),
            "province_county": _string(row.get("province_county")),
            "longitude": float(point.x),
            "latitude": float(point.y),
        }
        features.append(ee.Feature(ee.Geometry.Point([float(point.x), float(point.y)]), properties))
    return features, len(gdf)


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


def _inclusive_end_date(end_date_exclusive: str) -> str:
    date = datetime.fromisoformat(end_date_exclusive)
    return date.fromordinal(date.toordinal() - 1).date().isoformat()


def _string(value: Any) -> str:
    return "" if value is None else str(value)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

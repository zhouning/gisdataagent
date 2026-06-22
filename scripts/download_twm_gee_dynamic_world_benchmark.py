#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
import zipfile
from pathlib import Path
from typing import Any

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


DEFAULT_OUTPUT_DIR = REPO_ROOT / "data/twm_public_landcover/gee_dynamic_world"
DEFAULT_MANIFEST = DEFAULT_OUTPUT_DIR / "twm_dynamic_world_manifest.json"
DEFAULT_STATUS = REPO_ROOT / "docs/reports/twm_gee_dynamic_world_download_status_2026-06-22.json"
NODATA_VALUE = -32768

DYNAMIC_WORLD_CLASSES = [
    {"value": 0, "label": "water"},
    {"value": 1, "label": "trees"},
    {"value": 2, "label": "grass"},
    {"value": 3, "label": "flooded_vegetation"},
    {"value": 4, "label": "crops"},
    {"value": 5, "label": "shrub_and_scrub"},
    {"value": 6, "label": "built"},
    {"value": 7, "label": "bare"},
    {"value": 8, "label": "snow_and_ice"},
]

DEFAULT_REGIONS = [
    {"region_id": "beijing_core", "bbox": [116.32, 39.84, 116.48, 40.00]},
    {"region_id": "tianjin_core", "bbox": [117.12, 39.05, 117.28, 39.21]},
    {"region_id": "shanghai_pudong", "bbox": [121.45, 31.16, 121.61, 31.32]},
    {"region_id": "suzhou_core", "bbox": [120.52, 31.22, 120.68, 31.38]},
    {"region_id": "hangzhou_core", "bbox": [120.08, 30.20, 120.24, 30.36]},
    {"region_id": "ningbo_core", "bbox": [121.47, 29.80, 121.63, 29.96]},
    {"region_id": "nanjing_core", "bbox": [118.70, 31.96, 118.86, 32.12]},
    {"region_id": "hefei_core", "bbox": [117.20, 31.76, 117.36, 31.92]},
    {"region_id": "wuhan_core", "bbox": [114.22, 30.50, 114.38, 30.66]},
    {"region_id": "changsha_core", "bbox": [112.86, 28.14, 113.02, 28.30]},
    {"region_id": "zhengzhou_core", "bbox": [113.56, 34.68, 113.72, 34.84]},
    {"region_id": "xian_core", "bbox": [108.86, 34.18, 109.02, 34.34]},
    {"region_id": "chengdu_core", "bbox": [104.00, 30.58, 104.16, 30.74]},
    {"region_id": "chongqing_core", "bbox": [106.46, 29.48, 106.62, 29.64]},
    {"region_id": "guangzhou_core", "bbox": [113.18, 23.06, 113.34, 23.22]},
    {"region_id": "shenzhen_core", "bbox": [113.98, 22.48, 114.14, 22.64]},
    {"region_id": "dongguan_core", "bbox": [113.68, 22.86, 113.84, 23.02]},
    {"region_id": "foshan_core", "bbox": [113.04, 22.94, 113.20, 23.10]},
    {"region_id": "xiamen_core", "bbox": [118.02, 24.40, 118.18, 24.56]},
    {"region_id": "fuzhou_core", "bbox": [119.22, 26.00, 119.38, 26.16]},
]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download a real multi-region multi-year Dynamic World land-cover benchmark from Google Earth Engine for TWM."
    )
    parser.add_argument("--project", default="", help="Earth Engine enabled Google Cloud project id. Can also use GEE_PROJECT.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--manifest-output", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--status-output", type=Path, default=DEFAULT_STATUS)
    parser.add_argument("--regions-json", type=Path, default=None, help="Optional JSON list of {region_id,bbox}.")
    parser.add_argument("--regions-from-shapefile", type=Path, default=None, help="Optional township/admin polygon shapefile used to build benchmark regions.")
    parser.add_argument("--shapefile-city-field", default="市")
    parser.add_argument("--shapefile-county-field", default="县")
    parser.add_argument("--shapefile-town-field", default="乡")
    parser.add_argument("--shapefile-cities", default="", help="Comma-separated city names to sample from the shapefile.")
    parser.add_argument("--max-regions-per-city", type=int, default=1)
    parser.add_argument("--max-admin-area-km2", type=float, default=260.0)
    parser.add_argument("--min-admin-area-km2", type=float, default=8.0)
    parser.add_argument("--years", default="2017,2018,2019,2020,2021,2022,2023")
    parser.add_argument("--scale", type=int, default=100, help="Export scale in meters. Default 100m keeps the first benchmark compact.")
    parser.add_argument("--crs", default="EPSG:3857")
    parser.add_argument("--include-drivers", action="store_true", help="Also export static driver layers: SRTM elevation/slope and VIIRS nightlight mean.")
    parser.add_argument("--driver-years", default="2017,2018,2019,2020,2021,2022,2023", help="Years used for temporal driver composites such as VIIRS nightlight.")
    parser.add_argument("--limit-regions", type=int, default=0)
    parser.add_argument("--sleep", type=float, default=0.4, help="Delay between GEE download requests.")
    parser.add_argument("--dry-run", action="store_true", help="Only write a plan/status file; do not call Earth Engine.")
    args = parser.parse_args()

    years = [int(item.strip()) for item in args.years.split(",") if item.strip()]
    regions = load_regions(
        args.regions_json,
        shapefile_path=args.regions_from_shapefile,
        city_field=args.shapefile_city_field,
        county_field=args.shapefile_county_field,
        town_field=args.shapefile_town_field,
        city_names=[item.strip() for item in args.shapefile_cities.split(",") if item.strip()],
        max_regions_per_city=args.max_regions_per_city,
        min_area_km2=args.min_admin_area_km2,
        max_area_km2=args.max_admin_area_km2,
    )
    if args.limit_regions > 0:
        regions = regions[: args.limit_regions]
    report = download_dynamic_world_benchmark(
        project=args.project,
        output_dir=args.output_dir,
        manifest_output=args.manifest_output,
        years=years,
        driver_years=[int(item.strip()) for item in args.driver_years.split(",") if item.strip()],
        regions=regions,
        scale=args.scale,
        crs=args.crs,
        include_drivers=args.include_drivers,
        sleep_seconds=args.sleep,
        dry_run=args.dry_run,
    )
    args.status_output.parent.mkdir(parents=True, exist_ok=True)
    args.status_output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "status_output": str(args.status_output)}, ensure_ascii=False))


def load_regions(
    path: Path | None,
    *,
    shapefile_path: Path | None,
    city_field: str,
    county_field: str,
    town_field: str,
    city_names: list[str],
    max_regions_per_city: int,
    min_area_km2: float,
    max_area_km2: float,
) -> list[dict[str, Any]]:
    if path is not None and shapefile_path is not None:
        raise ValueError("Use either --regions-json or --regions-from-shapefile, not both.")
    if shapefile_path is not None:
        return load_regions_from_shapefile(
            shapefile_path,
            city_field=city_field,
            county_field=county_field,
            town_field=town_field,
            city_names=city_names,
            max_regions_per_city=max_regions_per_city,
            min_area_km2=min_area_km2,
            max_area_km2=max_area_km2,
        )
    if path is None:
        return list(DEFAULT_REGIONS)
    payload = json.loads(path.expanduser().read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload = payload.get("regions") or []
    regions = []
    for item in payload:
        region_id = str(item["region_id"])
        bbox = [float(value) for value in item["bbox"]]
        if len(bbox) != 4:
            raise ValueError(f"{region_id} bbox must contain four values.")
        regions.append({"region_id": region_id, "bbox": bbox})
    return regions


def load_regions_from_shapefile(
    path: Path,
    *,
    city_field: str,
    county_field: str,
    town_field: str,
    city_names: list[str],
    max_regions_per_city: int,
    min_area_km2: float,
    max_area_km2: float,
) -> list[dict[str, Any]]:
    import geopandas as gpd
    from shapely.geometry import mapping

    gdf = gpd.read_file(path.expanduser())
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")
    gdf = gdf.to_crs("EPSG:4326")
    if city_names:
        gdf = gdf[gdf[city_field].astype(str).isin(city_names)].copy()
    if gdf.empty:
        raise ValueError("No shapefile features matched the requested city filter.")
    area_gdf = gdf.to_crs("EPSG:6933")
    gdf["area_km2"] = area_gdf.geometry.area.astype(float) / 1_000_000.0
    gdf = gdf[(gdf["area_km2"] >= min_area_km2) & (gdf["area_km2"] <= max_area_km2)].copy()
    if gdf.empty:
        raise ValueError("No shapefile features passed the area filters.")
    regions: list[dict[str, Any]] = []
    for city, part in gdf.groupby(city_field, sort=True):
        selected = part.sort_values(["area_km2", county_field, town_field], ascending=[False, True, True]).head(max(1, max_regions_per_city))
        for _, row in selected.iterrows():
            bounds = [float(value) for value in row.geometry.bounds]
            region_id = admin_region_id(str(city), str(row.get(county_field, "")), str(row.get(town_field, "")))
            regions.append(
                {
                    "region_id": region_id,
                    "bbox": bounds,
                    "geometry": mapping(row.geometry),
                    "admin": {
                        "city": str(city),
                        "county": str(row.get(county_field, "")),
                        "town": str(row.get(town_field, "")),
                        "area_km2": round(float(row["area_km2"]), 4),
                        "source_path": str(path.expanduser()),
                    },
                }
            )
    return regions


def admin_region_id(city: str, county: str, town: str) -> str:
    import re

    raw = "_".join(part for part in [city, county, town] if part)
    raw = re.sub(r"\s+", "_", raw)
    raw = re.sub(r"[^\w\u4e00-\u9fff]+", "_", raw)
    return raw.strip("_").lower()


def download_dynamic_world_benchmark(
    *,
    project: str,
    output_dir: Path,
    manifest_output: Path,
    years: list[int],
    driver_years: list[int],
    regions: list[dict[str, Any]],
    scale: int,
    crs: str,
    include_drivers: bool,
    sleep_seconds: float,
    dry_run: bool,
) -> dict[str, Any]:
    output_dir = output_dir.expanduser().resolve()
    manifest_output = manifest_output.expanduser().resolve()
    project = project or read_project_from_env()
    plan = {
        "schema": "territory_world_model.gee_dynamic_world_download_status.v1",
        "status": "planned" if dry_run else "running",
        "source": {
            "provider": "Google Earth Engine",
            "collection": "GOOGLE/DYNAMICWORLD/V1",
            "label_band": "label",
            "annual_reducer": "mode",
            "scale_m": scale,
            "crs": crs,
            "include_drivers": include_drivers,
            "driver_years": driver_years,
        },
        "project": project,
        "region_count": len(regions),
        "years": years,
        "expected_raster_count": len(regions) * len(years),
        "output_dir": str(output_dir),
        "manifest_output": str(manifest_output),
        "regions": regions,
        "downloads": [],
        "blocked_reason": "",
    }
    if dry_run:
        return plan
    if not project:
        plan["status"] = "blocked"
        plan["blocked_reason"] = "missing_earth_engine_enabled_project_id"
        return plan

    ee = initialize_earth_engine(project)
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_regions: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for region in regions:
        region_id = region["region_id"]
        bbox = [float(value) for value in region["bbox"]]
        region_dir = output_dir / region_id
        region_dir.mkdir(parents=True, exist_ok=True)
        raster_stack: list[dict[str, Any]] = []
        driver_layers: list[dict[str, Any]] = []
        for year in years:
            out_path = region_dir / f"{region_id}_dynamic_world_{year}_{scale}m.tif"
            try:
                if not out_path.exists():
                    download_one_year(
                        ee=ee,
                        bbox=bbox,
                        geometry=region.get("geometry"),
                        year=year,
                        output_path=out_path,
                        scale=scale,
                        crs=crs,
                        name=f"{region_id}_{year}",
                    )
                    time.sleep(max(0.0, sleep_seconds))
                raster_stack.append({"year": year, "path": str(out_path.relative_to(manifest_output.parent)), "nodata": NODATA_VALUE})
                plan["downloads"].append({"region_id": region_id, "year": year, "status": "downloaded", "path": str(out_path)})
            except Exception as exc:  # noqa: BLE001
                failure = {"region_id": region_id, "year": year, "status": "failed", "error": f"{type(exc).__name__}: {exc}"}
                failures.append(failure)
                plan["downloads"].append(failure)
        if include_drivers:
            try:
                driver_layers = download_driver_layers(
                    ee=ee,
                    bbox=bbox,
                    geometry=region.get("geometry"),
                    output_dir=region_dir,
                    manifest_base=manifest_output.parent,
                    scale=scale,
                    crs=crs,
                    name_prefix=region_id,
                    driver_years=driver_years,
                    sleep_seconds=sleep_seconds,
                )
                for driver in driver_layers:
                    plan["downloads"].append(
                        {
                            "region_id": region_id,
                            "driver": driver["name"],
                            "status": "downloaded",
                            "path": str((manifest_output.parent / driver["path"]).resolve()),
                        }
                    )
            except Exception as exc:  # noqa: BLE001
                failure = {"region_id": region_id, "driver": "driver_layers", "status": "failed", "error": f"{type(exc).__name__}: {exc}"}
                failures.append(failure)
                plan["downloads"].append(failure)
        if len(raster_stack) >= 3:
            manifest_regions.append(
                {
                    "region_id": region_id,
                    "bbox": bbox,
                    "geometry": region.get("geometry"),
                    "admin": region.get("admin"),
                    "cell_area_ha": float(scale * scale) / 10000.0,
                    "nodata": NODATA_VALUE,
                    "raster_stack": raster_stack,
                    "driver_layers": driver_layers,
                }
            )
    manifest = build_manifest(
        years=years,
        regions=manifest_regions,
        scale=scale,
        crs=crs,
        project=project,
        include_drivers=include_drivers,
        driver_years=driver_years,
    )
    manifest_output.parent.mkdir(parents=True, exist_ok=True)
    manifest_output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    plan["status"] = "pass" if len(manifest_regions) == len(regions) and not failures else "partial" if manifest_regions else "blocked"
    plan["downloaded_region_count"] = len(manifest_regions)
    plan["downloaded_raster_count"] = sum(len(region["raster_stack"]) for region in manifest_regions)
    plan["downloaded_driver_count"] = sum(len(region.get("driver_layers") or []) for region in manifest_regions)
    plan["failed_count"] = len(failures)
    plan["failures"] = failures
    return plan


def read_project_from_env() -> str:
    import os

    return os.environ.get("GEE_PROJECT", "") or os.environ.get("GOOGLE_CLOUD_PROJECT", "")


def initialize_earth_engine(project: str):
    import ee

    ee.Initialize(project=project)
    return ee


def download_one_year(
    *,
    ee: Any,
    bbox: list[float],
    geometry: dict[str, Any] | None,
    year: int,
    output_path: Path,
    scale: int,
    crs: str,
    name: str,
) -> None:
    geom = ee.Geometry(geometry, proj="EPSG:4326", geodesic=False) if geometry else ee.Geometry.Rectangle(bbox, proj="EPSG:4326", geodesic=False)
    start = f"{year}-01-01"
    end = f"{year + 1}-01-01"
    collection = ee.ImageCollection("GOOGLE/DYNAMICWORLD/V1").filterDate(start, end).filterBounds(geom)
    image_count = int(collection.size().getInfo())
    if image_count <= 0:
        raise RuntimeError(f"No Dynamic World images for {name} in {year}.")
    label = collection.select("label").mode().rename("landcover").clip(geom).unmask(NODATA_VALUE).toInt16()
    url = label.getDownloadURL(
        {
            "name": name,
            "region": geom,
            "scale": scale,
            "crs": crs,
            "format": "GEO_TIFF",
        }
    )
    response = requests.get(url, timeout=180)
    response.raise_for_status()
    write_download_response(response.content, output_path)


def download_driver_layers(
    *,
    ee: Any,
    bbox: list[float],
    geometry: dict[str, Any] | None,
    output_dir: Path,
    manifest_base: Path,
    scale: int,
    crs: str,
    name_prefix: str,
    driver_years: list[int],
    sleep_seconds: float,
) -> list[dict[str, Any]]:
    geom = ee.Geometry(geometry, proj="EPSG:4326", geodesic=False) if geometry else ee.Geometry.Rectangle(bbox, proj="EPSG:4326", geodesic=False)
    terrain = ee.Image("USGS/SRTMGL1_003").select("elevation").clip(geom).unmask(NODATA_VALUE).toFloat()
    slope = ee.Terrain.slope(terrain).rename("slope").clip(geom).unmask(NODATA_VALUE).toFloat()
    first_year = min(driver_years)
    last_year = max(driver_years)
    nightlight = (
        ee.ImageCollection("NOAA/VIIRS/DNB/MONTHLY_V1/VCMSLCFG")
        .filterDate(f"{first_year}-01-01", f"{last_year + 1}-01-01")
        .select("avg_rad")
        .mean()
        .rename("nightlight_mean")
        .clip(geom)
        .unmask(NODATA_VALUE)
        .toFloat()
    )
    specs = [
        {"name": "srtm_elevation", "image": terrain},
        {"name": "srtm_slope", "image": slope},
        {"name": "viirs_nightlight_mean", "image": nightlight},
    ]
    outputs: list[dict[str, Any]] = []
    for spec in specs:
        out_path = output_dir / f"{name_prefix}_{spec['name']}_{scale}m.tif"
        if not out_path.exists():
            download_image(
                ee=ee,
                image=spec["image"],
                geom=geom,
                output_path=out_path,
                scale=scale,
                crs=crs,
                name=f"{name_prefix}_{spec['name']}",
            )
            time.sleep(max(0.0, sleep_seconds))
        outputs.append({"name": spec["name"], "path": str(out_path.relative_to(manifest_base)), "nodata": NODATA_VALUE})
    return outputs


def download_image(
    *,
    ee: Any,
    image: Any,
    geom: Any,
    output_path: Path,
    scale: int,
    crs: str,
    name: str,
) -> None:
    url = image.getDownloadURL(
        {
            "name": name,
            "region": geom,
            "scale": scale,
            "crs": crs,
            "format": "GEO_TIFF",
        }
    )
    response = requests.get(url, timeout=180)
    response.raise_for_status()
    write_download_response(response.content, output_path)


def write_download_response(content: bytes, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if zipfile.is_zipfile(io_bytes(content)):
        tmp_zip = output_path.with_suffix(".zip")
        tmp_zip.write_bytes(content)
        with zipfile.ZipFile(tmp_zip) as zf:
            tif_names = [name for name in zf.namelist() if name.lower().endswith((".tif", ".tiff"))]
            if not tif_names:
                raise RuntimeError("Earth Engine response zip did not contain a GeoTIFF.")
            with zf.open(tif_names[0]) as src:
                output_path.write_bytes(src.read())
        tmp_zip.unlink(missing_ok=True)
    else:
        output_path.write_bytes(content)
    sanitize_geotiff_nodata(output_path)


def sanitize_geotiff_nodata(output_path: Path) -> None:
    import numpy as np
    import rasterio

    with rasterio.open(output_path) as src:
        profile = src.profile.copy()
        arr = src.read(1)
    if np.issubdtype(arr.dtype, np.floating):
        data = arr.astype(np.float32, copy=True)
        invalid = (~np.isfinite(data)) | (data < -1.0e20)
        data[invalid] = float(NODATA_VALUE)
        profile.update(dtype="float32", nodata=float(NODATA_VALUE))
    else:
        data = arr.astype(np.int16, copy=True)
        profile.update(dtype="int16", nodata=int(NODATA_VALUE))
    with rasterio.open(output_path, "w", **profile) as dst:
        dst.write(data, 1)


def io_bytes(content: bytes):
    import io

    return io.BytesIO(content)


def build_manifest(
    *,
    years: list[int],
    regions: list[dict[str, Any]],
    scale: int,
    crs: str,
    project: str,
    include_drivers: bool,
    driver_years: list[int],
) -> dict[str, Any]:
    return {
        "schema": "territory_world_model.public_landcover_manifest.v1",
        "dataset_id": f"gee_dynamic_world_annual_{scale}m_{min(years)}_{max(years)}",
        "source": {
            "provider": "Google Earth Engine",
            "collection": "GOOGLE/DYNAMICWORLD/V1",
            "label_band": "label",
            "annual_reducer": "mode",
            "project": project,
            "scale_m": scale,
            "crs": crs,
            "include_drivers": include_drivers,
            "driver_layers": [
                "srtm_elevation",
                "srtm_slope",
                "viirs_nightlight_mean",
            ]
            if include_drivers
            else [],
            "driver_years": driver_years if include_drivers else [],
            "notes": [
                "Dynamic World labels are annual mode composites over each region/year.",
                "This compact benchmark exports at the configured scale for fast multi-region TWM validation.",
                f"Masked pixels outside the export geometry use nodata={NODATA_VALUE}.",
                "Driver layers are static or period-composite covariates clipped to the same administrative geometry when enabled.",
            ],
        },
        "cell_area_ha": float(scale * scale) / 10000.0,
        "classes": DYNAMIC_WORLD_CLASSES,
        "years": years,
        "regions": regions,
    }


if __name__ == "__main__":
    main()

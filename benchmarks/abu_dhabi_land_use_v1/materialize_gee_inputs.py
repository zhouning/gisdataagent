#!/usr/bin/env python3
"""Materialize Earth Engine inputs on the frozen Abu Dhabi benchmark grid."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import tempfile
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
import requests
from affine import Affine

HERE = Path(__file__).resolve().parent
DEFAULT_BOUNDARY = HERE / "source/abu_dhabi_city_osm_r4479763.geojson"
DEFAULT_GRID_PROFILE = HERE / "grid_profile.json"
DEFAULT_CITY_MASK = HERE / "artifacts/abu_dhabi_city_100m_mask.tif"
DEFAULT_OUTPUT = HERE / "artifacts/gee"
DEFAULT_MANIFEST = HERE / "gee_input_manifest.json"
DEFAULT_YEARS = tuple(range(2017, 2025))
NODATA_FLOAT = -32768.0
ALPHAEARTH_COLLECTION = "GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL"
DYNAMIC_WORLD_COLLECTION = "GOOGLE/DYNAMICWORLD/V1"
DYNAMIC_WORLD_PROBABILITY_BANDS = (
    "water",
    "trees",
    "grass",
    "flooded_vegetation",
    "crops",
    "shrub_and_scrub",
    "built",
    "bare",
    "snow_and_ice",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_geometry(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    features = payload.get("features") or []
    if len(features) != 1:
        raise ValueError("boundary_must_contain_one_feature")
    return features[0]["geometry"]


def expected_grid(profile_path: Path) -> dict[str, Any]:
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    return {
        "crs": str(profile["crs"]),
        "width": int(profile["width"]),
        "height": int(profile["height"]),
        "transform": Affine.from_gdal(*profile["transform_gdal"]),
        "bounds": [float(value) for value in profile["bounds"]],
        "resolution_m": int(profile["resolution_m"]),
    }


def validate_raster(path: Path, grid: dict[str, Any], *, band_count: int) -> None:
    with rasterio.open(path) as dataset:
        if dataset.crs is None or dataset.crs.to_string() != grid["crs"]:
            raise ValueError(f"raster_crs_mismatch:{path}:{dataset.crs}")
        if dataset.width != grid["width"] or dataset.height != grid["height"]:
            raise ValueError(f"raster_shape_mismatch:{path}:{dataset.shape}")
        if dataset.count != band_count:
            raise ValueError(f"raster_band_count_mismatch:{path}:{dataset.count}")
        if not dataset.transform.almost_equals(grid["transform"], precision=1e-9):
            raise ValueError(f"raster_transform_mismatch:{path}:{dataset.transform}")


def _write_download(content: bytes, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".gee-download-", dir=output_path.parent) as name:
        temp_root = Path(name)
        downloaded = temp_root / "download"
        if zipfile.is_zipfile(io.BytesIO(content)):
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                names = [
                    item
                    for item in archive.namelist()
                    if item.lower().endswith((".tif", ".tiff"))
                ]
                if len(names) != 1:
                    raise RuntimeError(f"expected_one_geotiff_in_archive:{len(names)}")
                downloaded.write_bytes(archive.read(names[0]))
        else:
            downloaded.write_bytes(content)
        os.replace(downloaded, output_path)


def download_image(
    image: Any,
    *,
    output_path: Path,
    grid: dict[str, Any],
    name: str,
    band_count: int,
) -> None:
    if output_path.is_file():
        validate_raster(output_path, grid, band_count=band_count)
        return
    transform = grid["transform"]
    url = image.getDownloadURL(
        {
            "name": name,
            "crs": grid["crs"],
            "crs_transform": [
                transform.a,
                transform.b,
                transform.c,
                transform.d,
                transform.e,
                transform.f,
            ],
            "dimensions": [grid["width"], grid["height"]],
            "format": "GEO_TIFF",
            "filePerBand": False,
        }
    )
    response = requests.get(url, timeout=300)
    response.raise_for_status()
    _write_download(response.content, output_path)
    validate_raster(output_path, grid, band_count=band_count)


def _rewrite_raster(
    path: Path,
    *,
    dtype: str,
    nodata: float | int,
    descriptions: tuple[str, ...],
    city_mask: np.ndarray,
) -> None:
    with rasterio.open(path) as source:
        data = source.read()
        profile = source.profile.copy()
    if dtype == "uint8":
        normalized = data.astype(np.uint8, copy=False)
    else:
        normalized = data.astype(np.float32, copy=False)
        normalized[~np.isfinite(normalized)] = float(nodata)
    if city_mask.shape != normalized.shape[1:]:
        raise ValueError(f"city_mask_shape_mismatch:{path}:{city_mask.shape}")
    normalized[:, ~city_mask] = nodata
    profile.update(
        dtype=dtype,
        nodata=nodata,
        compress="deflate",
        tiled=True,
        blockxsize=256,
        blockysize=256,
    )
    temp_path = path.with_suffix(f".rewrite.{os.getpid()}.tif")
    with rasterio.open(temp_path, "w", **profile) as target:
        target.write(normalized)
        for index, description in enumerate(descriptions, start=1):
            target.set_band_description(index, description)
    os.replace(temp_path, path)


def dynamic_world_images(ee: Any, geometry: Any, year: int) -> tuple[Any, Any, int]:
    collection = (
        ee.ImageCollection(DYNAMIC_WORLD_COLLECTION)
        .filterDate(f"{year}-01-01", f"{year + 1}-01-01")
        .filterBounds(geometry)
    )
    image_count = int(collection.size().getInfo())
    if image_count <= 0:
        raise RuntimeError(f"dynamic_world_empty:{year}")
    label = collection.select("label").mode()
    canonical = (
        label.remap(
            list(range(9)),
            [1, 2, 3, 4, 3, 3, 5, 6, 0],
            0,
        )
        .rename("land_cover")
        .clip(geometry)
        .unmask(0)
        .toUint8()
    )
    mean_probabilities = collection.select(list(DYNAMIC_WORLD_PROBABILITY_BANDS)).mean()
    confidence = mean_probabilities.reduce(ee.Reducer.max()).rename("mean_top_probability")
    observation_count = collection.select("label").count().rename("observation_count")
    quality = (
        confidence.addBands(observation_count)
        .clip(geometry)
        .unmask(NODATA_FLOAT)
        .toFloat()
    )
    return canonical, quality, image_count


def materialize_dynamic_world(
    ee: Any,
    geometry: Any,
    *,
    years: tuple[int, ...],
    output_root: Path,
    grid: dict[str, Any],
    city_mask: np.ndarray,
) -> list[dict[str, Any]]:
    records = []
    for year in years:
        state_path = output_root / "land_cover" / f"land_cover_{year}_100m.tif"
        quality_path = output_root / "land_cover" / f"land_cover_quality_{year}_100m.tif"
        state, quality, image_count = dynamic_world_images(ee, geometry, year)
        download_image(
            state,
            output_path=state_path,
            grid=grid,
            name=f"abu_dhabi_land_cover_{year}",
            band_count=1,
        )
        _rewrite_raster(
            state_path,
            dtype="uint8",
            nodata=0,
            descriptions=("canonical_land_cover",),
            city_mask=city_mask,
        )
        download_image(
            quality,
            output_path=quality_path,
            grid=grid,
            name=f"abu_dhabi_land_cover_quality_{year}",
            band_count=2,
        )
        _rewrite_raster(
            quality_path,
            dtype="float32",
            nodata=NODATA_FLOAT,
            descriptions=("mean_top_probability", "observation_count"),
            city_mask=city_mask,
        )
        records.extend(
            [
                artifact(state_path, role="annual_land_cover", year=year, image_count=image_count),
                artifact(quality_path, role="annual_land_cover_quality", year=year),
            ]
        )
        print(f"dynamic_world:{year}:complete", flush=True)
    return records


def materialize_viirs(
    ee: Any,
    geometry: Any,
    *,
    years: tuple[int, ...],
    output_root: Path,
    grid: dict[str, Any],
    city_mask: np.ndarray,
) -> list[dict[str, Any]]:
    records = []
    for year in years:
        collection = (
            ee.ImageCollection("NOAA/VIIRS/DNB/MONTHLY_V1/VCMSLCFG")
            .filterDate(f"{year}-01-01", f"{year + 1}-01-01")
            .filterBounds(geometry)
            .select("avg_rad")
        )
        image_count = int(collection.size().getInfo())
        if image_count <= 0:
            raise RuntimeError(f"viirs_empty:{year}")
        image = (
            collection.mean()
            .rename("annual_mean_radiance")
            .clip(geometry)
            .unmask(NODATA_FLOAT)
            .toFloat()
        )
        path = output_root / "viirs" / f"viirs_{year}_100m.tif"
        download_image(
            image,
            output_path=path,
            grid=grid,
            name=f"abu_dhabi_viirs_{year}",
            band_count=1,
        )
        _rewrite_raster(
            path,
            dtype="float32",
            nodata=NODATA_FLOAT,
            descriptions=("annual_mean_radiance",),
            city_mask=city_mask,
        )
        records.append(artifact(path, role="annual_viirs", year=year, image_count=image_count))
        print(f"viirs:{year}:complete", flush=True)
    return records


def materialize_terrain(
    ee: Any,
    geometry: Any,
    *,
    output_root: Path,
    grid: dict[str, Any],
    city_mask: np.ndarray,
) -> list[dict[str, Any]]:
    dem = (
        ee.ImageCollection("COPERNICUS/DEM/GLO30_2024_1")
        .select("DEM")
        .mosaic()
        .rename("elevation")
    )
    slope = ee.Terrain.slope(dem).rename("slope")
    image = dem.addBands(slope).clip(geometry).unmask(NODATA_FLOAT).toFloat()
    path = output_root / "terrain" / "copernicus_dem_2024_1_slope_100m.tif"
    download_image(
        image,
        output_path=path,
        grid=grid,
        name="abu_dhabi_copernicus_dem_slope",
        band_count=2,
    )
    _rewrite_raster(
        path,
        dtype="float32",
        nodata=NODATA_FLOAT,
        descriptions=("elevation", "slope"),
        city_mask=city_mask,
    )
    _derive_local_slope(path, city_mask=city_mask, resolution_m=grid["resolution_m"])
    print("terrain:complete", flush=True)
    return [artifact(path, role="static_terrain")]


def _derive_local_slope(
    path: Path,
    *,
    city_mask: np.ndarray,
    resolution_m: int,
) -> None:
    with rasterio.open(path) as source:
        data = source.read().astype(np.float32)
        profile = source.profile.copy()
    elevation = data[0]
    fill_value = float(np.median(elevation[city_mask]))
    working = elevation.copy()
    working[~city_mask] = fill_value
    gradient_y, gradient_x = np.gradient(working, float(resolution_m))
    slope = np.degrees(np.arctan(np.hypot(gradient_x, gradient_y))).astype(np.float32)
    slope[~city_mask] = NODATA_FLOAT
    data[1] = slope
    temp_path = path.with_suffix(f".slope.{os.getpid()}.tif")
    with rasterio.open(temp_path, "w", **profile) as target:
        target.write(data)
        target.set_band_description(1, "elevation")
        target.set_band_description(2, "slope")
        target.update_tags(2, derivation="local_finite_difference_on_canonical_100m_dem")
    os.replace(temp_path, path)


def materialize_constraints(
    ee: Any,
    geometry: Any,
    *,
    output_root: Path,
    grid: dict[str, Any],
    city_mask: np.ndarray,
) -> list[dict[str, Any]]:
    worldcover = ee.ImageCollection("ESA/WorldCover/v200").first().select("Map")
    water = worldcover.eq(80).rename("permanent_water")
    ecological = worldcover.eq(90).Or(worldcover.eq(95)).rename("wetland_or_mangrove")
    constraints = (
        water.addBands(ecological)
        .reduceResolution(reducer=ee.Reducer.max(), maxPixels=1024)
        .clip(geometry)
        .unmask(0)
        .toUint8()
    )
    path = output_root / "constraints" / "esa_worldcover_2021_water_ecological_100m.tif"
    download_image(
        constraints,
        output_path=path,
        grid=grid,
        name="abu_dhabi_esa_worldcover_2021_constraints",
        band_count=2,
    )
    _rewrite_raster(
        path,
        dtype="uint8",
        nodata=0,
        descriptions=("permanent_water", "wetland_or_mangrove"),
        city_mask=city_mask,
    )
    print("constraints:complete", flush=True)
    return [artifact(path, role="static_ecological_constraints", year=2021)]


def materialize_alphaearth(
    ee: Any,
    geometry: Any,
    *,
    city_mask_path: Path,
    years: tuple[int, ...],
    output_root: Path,
    grid: dict[str, Any],
    chunk_size: int,
) -> list[dict[str, Any]]:
    with rasterio.open(city_mask_path) as mask_dataset:
        city_mask = mask_dataset.read(1).astype(bool)
    bands = tuple(f"A{index:02d}" for index in range(64))
    records = []
    for year in years:
        collection = (
            ee.ImageCollection(ALPHAEARTH_COLLECTION)
            .filterDate(f"{year}-01-01", f"{year + 1}-01-01")
            .filterBounds(geometry)
        )
        image_count = int(collection.size().getInfo())
        if image_count <= 0:
            raise RuntimeError(f"alphaearth_empty:{year}")
        first_projection = ee.Image(collection.first()).select("A00").projection()
        image = (
            collection.mosaic()
            .select(list(bands))
            .setDefaultProjection(first_projection)
        )
        chunk_paths = []
        for start in range(0, len(bands), chunk_size):
            chunk_bands = bands[start : start + chunk_size]
            chunk = (
                image.select(list(chunk_bands))
                .reduceResolution(reducer=ee.Reducer.mean(), maxPixels=1024)
                .clip(geometry)
                .unmask(NODATA_FLOAT)
                .toFloat()
            )
            path = (
                output_root
                / "alphaearth/chunks"
                / f"alphaearth_{year}_{start:02d}_{start + len(chunk_bands) - 1:02d}_100m.tif"
            )
            download_image(
                chunk,
                output_path=path,
                grid=grid,
                name=f"abu_dhabi_alphaearth_{year}_{start:02d}",
                band_count=len(chunk_bands),
            )
            _rewrite_raster(
                path,
                dtype="float32",
                nodata=NODATA_FLOAT,
                descriptions=chunk_bands,
                city_mask=city_mask,
            )
            chunk_paths.append(path)
            print(
                f"alphaearth:{year}:bands_{start:02d}_"
                f"{start + len(chunk_bands) - 1:02d}",
                flush=True,
            )
        final_path = output_root / "alphaearth" / f"alphaearth_{year}_100m.tif"
        merge_alphaearth_chunks(
            chunk_paths,
            output_path=final_path,
            city_mask=city_mask,
            descriptions=bands,
            grid=grid,
        )
        records.append(
            artifact(
                final_path,
                role="annual_alphaearth_embedding",
                year=year,
                image_count=image_count,
            )
        )
        print(f"alphaearth:{year}:complete", flush=True)
    return records


def merge_alphaearth_chunks(
    chunk_paths: list[Path],
    *,
    output_path: Path,
    city_mask: np.ndarray,
    descriptions: tuple[str, ...],
    grid: dict[str, Any],
) -> None:
    if output_path.is_file():
        validate_raster(output_path, grid, band_count=len(descriptions))
        return
    arrays = []
    profile = None
    for path in chunk_paths:
        with rasterio.open(path) as dataset:
            arrays.append(dataset.read().astype(np.float32, copy=False))
            profile = dataset.profile.copy()
    data = np.concatenate(arrays, axis=0)
    valid = city_mask & np.all(np.isfinite(data) & (data != NODATA_FLOAT), axis=0)
    norm = np.sqrt(np.sum(np.square(data, dtype=np.float64), axis=0))
    valid &= norm > 1e-8
    data[:, valid] /= norm[valid].astype(np.float32)
    data[:, ~valid] = NODATA_FLOAT
    assert profile is not None
    profile.update(
        count=len(descriptions),
        dtype="float32",
        nodata=NODATA_FLOAT,
        compress="deflate",
        tiled=True,
        blockxsize=256,
        blockysize=256,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_suffix(f".partial.{os.getpid()}.tif")
    with rasterio.open(temp_path, "w", **profile) as target:
        target.write(data)
        for index, description in enumerate(descriptions, start=1):
            target.set_band_description(index, description)
    os.replace(temp_path, output_path)
    validate_raster(output_path, grid, band_count=len(descriptions))


def artifact(path: Path, *, role: str, **metadata: Any) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(HERE)),
        "role": role,
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        **metadata,
    }


def materialize(
    *,
    project: str,
    products: tuple[str, ...],
    years: tuple[int, ...],
    boundary_path: Path,
    grid_profile_path: Path,
    city_mask_path: Path,
    output_root: Path,
    manifest_path: Path,
    alphaearth_chunk_size: int,
) -> dict[str, Any]:
    import ee

    ee.Initialize(project=project)
    grid = expected_grid(grid_profile_path)
    validate_raster(city_mask_path, grid, band_count=1)
    with rasterio.open(city_mask_path) as mask_dataset:
        city_mask = mask_dataset.read(1).astype(bool)
    geometry = ee.Geometry(load_geometry(boundary_path), proj="EPSG:4326", geodesic=False)
    started = time.perf_counter()
    records: list[dict[str, Any]] = []
    if "landcover" in products:
        records.extend(
            materialize_dynamic_world(
                ee,
                geometry,
                years=years,
                output_root=output_root,
                grid=grid,
                city_mask=city_mask,
            )
        )
    if "viirs" in products:
        records.extend(
            materialize_viirs(
                ee,
                geometry,
                years=years,
                output_root=output_root,
                grid=grid,
                city_mask=city_mask,
            )
        )
    if "terrain" in products:
        records.extend(
            materialize_terrain(
                ee,
                geometry,
                output_root=output_root,
                grid=grid,
                city_mask=city_mask,
            )
        )
    if "constraints" in products:
        records.extend(
            materialize_constraints(
                ee,
                geometry,
                output_root=output_root,
                grid=grid,
                city_mask=city_mask,
            )
        )
    if "alphaearth" in products:
        records.extend(
            materialize_alphaearth(
                ee,
                geometry,
                city_mask_path=city_mask_path,
                years=years,
                output_root=output_root,
                grid=grid,
                chunk_size=alphaearth_chunk_size,
            )
        )
    previous_artifacts: list[dict[str, Any]] = []
    previous_products: list[str] = []
    previous_years: list[int] = []
    if manifest_path.is_file():
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        if previous.get("schema") == "gwm.abu_dhabi_gee_input_manifest.v1":
            replaced_roles = {str(row["role"]) for row in records}
            previous_artifacts = [
                row
                for row in previous.get("artifacts") or []
                if str(row.get("role")) not in replaced_roles
            ]
            previous_products = [str(value) for value in previous.get("products") or []]
            previous_years = [int(value) for value in previous.get("years") or []]
    merged_artifacts = {
        str(row["path"]): row for row in [*previous_artifacts, *records]
    }
    manifest = {
        "schema": "gwm.abu_dhabi_gee_input_manifest.v1",
        "benchmark_id": "abu-dhabi-land-use-v1",
        "created_at": datetime.now(UTC).isoformat(),
        "status": "complete",
        "earth_engine_project": project,
        "products": sorted(set(previous_products) | set(products)),
        "years": sorted(set(previous_years) | set(years)),
        "grid_profile_sha256": sha256_file(grid_profile_path),
        "sources": {
            "land_cover": {
                "collection": DYNAMIC_WORLD_COLLECTION,
                "annual_reducer": "mode_of_scene_argmax_label",
                "canonical_crosswalk": [1, 2, 3, 4, 3, 3, 5, 6, 0],
            },
            "alphaearth": {
                "collection": ALPHAEARTH_COLLECTION,
                "aggregation": "100m_spatial_mean_then_local_l2_normalization",
                "dimension": 64,
            },
            "viirs": {
                "collection": "NOAA/VIIRS/DNB/MONTHLY_V1/VCMSLCFG",
                "band": "avg_rad",
                "annual_reducer": "mean",
            },
            "terrain": {
                "collection": "COPERNICUS/DEM/GLO30_2024_1",
                "bands": ["DEM", "locally_derived_slope"],
                "slope_derivation": "finite_difference_on_canonical_100m_dem",
            },
            "constraints": {
                "collection": "ESA/WorldCover/v200",
                "source_year": 2021,
                "source_classes": {
                    "permanent_water": [80],
                    "wetland_or_mangrove": [90, 95]
                },
                "aggregation": "100m_any_source_pixel",
            },
        },
        "artifacts": sorted(merged_artifacts.values(), key=lambda row: str(row["path"])),
        "wall_time_seconds": time.perf_counter() - started,
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default="ee-zn19860115")
    parser.add_argument(
        "--products",
        default="landcover,viirs,terrain,constraints,alphaearth",
        help="Comma-separated landcover,viirs,terrain,constraints,alphaearth",
    )
    parser.add_argument("--years", default=",".join(str(year) for year in DEFAULT_YEARS))
    parser.add_argument("--boundary", type=Path, default=DEFAULT_BOUNDARY)
    parser.add_argument("--grid-profile", type=Path, default=DEFAULT_GRID_PROFILE)
    parser.add_argument("--city-mask", type=Path, default=DEFAULT_CITY_MASK)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--alphaearth-chunk-size", type=int, default=8)
    args = parser.parse_args()
    allowed = {"landcover", "viirs", "terrain", "constraints", "alphaearth"}
    products = tuple(item.strip() for item in args.products.split(",") if item.strip())
    unknown = set(products) - allowed
    if unknown:
        raise ValueError(f"unknown_products:{sorted(unknown)}")
    years = tuple(int(item) for item in args.years.split(",") if item.strip())
    if any(year not in DEFAULT_YEARS for year in years):
        raise ValueError("years_must_be_within_2017_2024")
    if args.alphaearth_chunk_size <= 0 or 64 % args.alphaearth_chunk_size != 0:
        raise ValueError("alphaearth_chunk_size_must_divide_64")
    manifest = materialize(
        project=args.project,
        products=products,
        years=years,
        boundary_path=args.boundary,
        grid_profile_path=args.grid_profile,
        city_mask_path=args.city_mask,
        output_root=args.output,
        manifest_path=args.manifest,
        alphaearth_chunk_size=args.alphaearth_chunk_size,
    )
    print(json.dumps({"status": manifest["status"], "artifact_count": len(manifest["artifacts"])}))


if __name__ == "__main__":
    main()

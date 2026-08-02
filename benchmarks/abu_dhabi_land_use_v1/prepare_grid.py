#!/usr/bin/env python3
"""Create the canonical 100 m Abu Dhabi city raster grid and mask."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import rasterize
from rasterio.transform import from_origin

HERE = Path(__file__).resolve().parent
DEFAULT_BOUNDARY = HERE / "source/abu_dhabi_city_osm_r4479763.geojson"
DEFAULT_MASK = HERE / "artifacts/abu_dhabi_city_100m_mask.tif"
DEFAULT_PROFILE = HERE / "grid_profile.json"
CRS = "EPSG:32640"
RESOLUTION_M = 100


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def aligned_bounds(
    bounds: tuple[float, float, float, float], resolution: int
) -> tuple[float, float, float, float]:
    min_x, min_y, max_x, max_y = bounds
    return (
        math.floor(min_x / resolution) * resolution,
        math.floor(min_y / resolution) * resolution,
        math.ceil(max_x / resolution) * resolution,
        math.ceil(max_y / resolution) * resolution,
    )


def build_grid(
    *,
    boundary_path: Path = DEFAULT_BOUNDARY,
    mask_path: Path = DEFAULT_MASK,
    profile_path: Path = DEFAULT_PROFILE,
    resolution_m: int = RESOLUTION_M,
) -> dict[str, Any]:
    boundary = gpd.read_file(boundary_path)
    if boundary.empty:
        raise ValueError("boundary_is_empty")
    if boundary.crs is None:
        raise ValueError("boundary_crs_missing")
    boundary = boundary.to_crs(CRS)
    geometry = boundary.geometry.union_all()
    if geometry.is_empty or not geometry.is_valid:
        raise ValueError("boundary_geometry_invalid")
    min_x, min_y, max_x, max_y = aligned_bounds(geometry.bounds, resolution_m)
    width = int(round((max_x - min_x) / resolution_m))
    height = int(round((max_y - min_y) / resolution_m))
    transform = from_origin(min_x, max_y, resolution_m, resolution_m)
    mask = rasterize(
        [(geometry, 1)],
        out_shape=(height, width),
        transform=transform,
        fill=0,
        all_touched=False,
        dtype=np.uint8,
    )
    if not mask.any():
        raise ValueError("canonical_grid_has_no_city_pixels")
    mask_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        mask_path,
        "w",
        driver="GTiff",
        width=width,
        height=height,
        count=1,
        dtype="uint8",
        crs=CRS,
        transform=transform,
        nodata=0,
        compress="deflate",
        tiled=True,
    ) as dataset:
        dataset.write(mask, 1)
        dataset.set_band_description(1, "abu_dhabi_city_mask")
    valid_pixels = int(mask.sum())
    profile = {
        "schema": "gwm.canonical_grid_profile.v1",
        "benchmark_id": "abu-dhabi-land-use-v1",
        "crs": CRS,
        "resolution_m": resolution_m,
        "bounds": [min_x, min_y, max_x, max_y],
        "transform_gdal": list(transform.to_gdal()),
        "width": width,
        "height": height,
        "total_pixel_count": int(width * height),
        "valid_city_pixel_count": valid_pixels,
        "boundary_area_km2": float(geometry.area / 1_000_000.0),
        "rasterized_city_area_km2": float(valid_pixels * resolution_m * resolution_m / 1_000_000.0),
        "pixel_inclusion": "center_within_city_polygon",
        "boundary_artifact": {
            "path": str(boundary_path.relative_to(HERE)),
            "sha256": sha256_file(boundary_path),
        },
        "mask_artifact": {
            "path": str(mask_path.relative_to(HERE)),
            "size_bytes": mask_path.stat().st_size,
            "sha256": sha256_file(mask_path),
        },
    }
    profile_path.write_text(
        json.dumps(profile, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return profile


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--boundary", type=Path, default=DEFAULT_BOUNDARY)
    parser.add_argument("--mask", type=Path, default=DEFAULT_MASK)
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--resolution", type=int, default=RESOLUTION_M)
    args = parser.parse_args()
    profile = build_grid(
        boundary_path=args.boundary,
        mask_path=args.mask,
        profile_path=args.profile,
        resolution_m=args.resolution,
    )
    print(json.dumps(profile, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

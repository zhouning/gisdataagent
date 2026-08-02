#!/usr/bin/env python3
"""Fallback OSM materialization from a versioned Geofabrik GCC PBF snapshot."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import rasterio
import requests
from materialize_osm_inputs import _write_raster, load_grid, sha256_file
from rasterio.features import rasterize
from scipy.ndimage import distance_transform_edt
from shapely.ops import unary_union

HERE = Path(__file__).resolve().parent
DEFAULT_GRID_PROFILE = HERE / "grid_profile.json"
DEFAULT_CITY_MASK = HERE / "artifacts/abu_dhabi_city_100m_mask.tif"
DEFAULT_PBF = HERE / "artifacts/osm/gcc-states-260731.osm.pbf"
DEFAULT_OUTPUT_ROOT = HERE / "artifacts/osm"
DEFAULT_MANIFEST = HERE / "osm_input_manifest.json"
GEOFABRIK_URL = "https://download.geofabrik.de/asia/gcc-states-260731.osm.pbf"
BBOX = (54.2971553, 24.2810331, 54.7659108, 24.6018540)
MAJOR_HIGHWAYS = {"motorway", "trunk", "primary", "secondary"}


def download_pbf(*, url: str, path: Path, proxy: str | None) -> None:
    if path.is_file():
        return
    proxies = {"http": proxy, "https": proxy} if proxy else None
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f".partial.{os.getpid()}.pbf")
    with requests.get(url, proxies=proxies, stream=True, timeout=(30, 600)) as response:
        response.raise_for_status()
        with temp_path.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=4 * 1024 * 1024):
                if chunk:
                    handle.write(chunk)
    os.replace(temp_path, path)


def _nonempty(frame: gpd.GeoDataFrame, column: str) -> np.ndarray:
    if column not in frame.columns:
        return np.zeros(len(frame), dtype=bool)
    values = frame[column].fillna("").astype(str)
    return (~values.isin({"", "None", "nan"})).to_numpy()


def _equals(frame: gpd.GeoDataFrame, column: str, value: str) -> np.ndarray:
    if column not in frame.columns:
        return np.zeros(len(frame), dtype=bool)
    return (frame[column].fillna("").astype(str) == value).to_numpy()


def _other_tag(frame: gpd.GeoDataFrame, key: str, value: str | None = None) -> np.ndarray:
    if "other_tags" not in frame.columns:
        return np.zeros(len(frame), dtype=bool)
    needle = f'"{key}"=>"' if value is None else f'"{key}"=>"{value}"'
    return (
        frame["other_tags"].fillna("").astype(str).str.contains(needle, regex=False).to_numpy()
    )


def _geometries(frame: gpd.GeoDataFrame, mask: np.ndarray, crs: str) -> list[Any]:
    selected = frame.loc[mask, ["geometry"]].copy()
    if selected.empty:
        return []
    selected = selected[selected.geometry.notna() & ~selected.geometry.is_empty]
    if selected.empty:
        return []
    return list(selected.to_crs(crs).geometry)


def read_features(pbf_path: Path, target_crs: str) -> dict[str, list[Any]]:
    lines = gpd.read_file(pbf_path, layer="lines", bbox=BBOX)
    polygons = gpd.read_file(pbf_path, layer="multipolygons", bbox=BBOX)
    points = gpd.read_file(pbf_path, layer="points", bbox=BBOX)

    highway_mask = _nonempty(lines, "highway")
    highway_values = lines.get("highway", "").fillna("").astype(str)
    major_mask = highway_values.isin(MAJOR_HIGHWAYS).to_numpy()
    protected_polygon_mask = (
        _equals(polygons, "boundary", "protected_area")
        | _equals(polygons, "leisure", "nature_reserve")
        | _other_tag(polygons, "boundary", "protected_area")
        | _other_tag(polygons, "leisure", "nature_reserve")
    )
    infrastructure_line_mask = (
        _other_tag(lines, "aeroway")
        | _other_tag(lines, "harbour", "yes")
        | _other_tag(lines, "landuse", "port")
        | _other_tag(lines, "industrial", "port")
    )
    infrastructure_polygon_mask = (
        _nonempty(polygons, "aeroway")
        | _equals(polygons, "landuse", "port")
        | _other_tag(polygons, "aeroway")
        | _other_tag(polygons, "harbour", "yes")
        | _other_tag(polygons, "landuse", "port")
        | _other_tag(polygons, "industrial", "port")
    )
    infrastructure_point_mask = (
        _other_tag(points, "aeroway")
        | _other_tag(points, "harbour", "yes")
        | _other_tag(points, "landuse", "port")
        | _other_tag(points, "industrial", "port")
    )
    return {
        "roads": _geometries(lines, highway_mask, target_crs),
        "major_roads": _geometries(lines, major_mask, target_crs),
        "protected": _geometries(polygons, protected_polygon_mask, target_crs),
        "infrastructure_lines": _geometries(lines, infrastructure_line_mask, target_crs),
        "infrastructure_polygons": _geometries(
            polygons, infrastructure_polygon_mask, target_crs
        ),
        "infrastructure_points": _geometries(points, infrastructure_point_mask, target_crs),
        "source_counts": {
            "bbox_lines": len(lines),
            "bbox_multipolygons": len(polygons),
            "bbox_points": len(points),
            "highway_features": int(highway_mask.sum()),
            "major_highway_features": int(major_mask.sum()),
            "protected_features": int(protected_polygon_mask.sum()),
            "infrastructure_line_features": int(infrastructure_line_mask.sum()),
            "infrastructure_polygon_features": int(infrastructure_polygon_mask.sum()),
            "infrastructure_point_features": int(infrastructure_point_mask.sum()),
        },
    }


def materialize(
    *,
    pbf_path: Path,
    url: str,
    proxy: str | None,
    grid_profile_path: Path,
    city_mask_path: Path,
    output_root: Path,
    manifest_path: Path,
) -> dict[str, Any]:
    download_pbf(url=url, path=pbf_path, proxy=proxy)
    grid = load_grid(grid_profile_path)
    with rasterio.open(city_mask_path) as dataset:
        city = dataset.read(1).astype(bool)
    features = read_features(pbf_path, grid["crs"])
    shape = (grid["height"], grid["width"])
    road_mask = rasterize(
        [(geometry, 1) for geometry in features["roads"]],
        out_shape=shape,
        transform=grid["transform"],
        all_touched=True,
        dtype=np.uint8,
    ).astype(bool)
    major_mask = rasterize(
        [(geometry, 1) for geometry in features["major_roads"]],
        out_shape=shape,
        transform=grid["transform"],
        all_touched=True,
        dtype=np.uint8,
    ).astype(bool)
    if not road_mask.any() or not major_mask.any():
        raise RuntimeError("geofabrik_road_raster_is_empty")
    road_data = np.stack(
        [
            distance_transform_edt(~road_mask, sampling=grid["resolution_m"]),
            distance_transform_edt(~major_mask, sampling=grid["resolution_m"]),
        ]
    ).astype(np.float32)
    road_data[:, ~city] = -32768.0
    road_path = output_root / "road_accessibility_100m.tif"
    _write_raster(
        road_path,
        road_data,
        grid=grid,
        dtype="float32",
        nodata=-32768.0,
        descriptions=("distance_to_any_road_m", "distance_to_major_road_m"),
    )

    protected_areas = [geometry.buffer(100) for geometry in features["protected"]]
    infrastructure_areas = [
        *[geometry.buffer(150) for geometry in features["infrastructure_lines"]],
        *[geometry.buffer(100) for geometry in features["infrastructure_polygons"]],
        *[geometry.buffer(300) for geometry in features["infrastructure_points"]],
    ]
    constraints = np.zeros((2, *shape), dtype=np.uint8)
    if protected_areas:
        constraints[0] = rasterize(
            [(unary_union(protected_areas), 1)],
            out_shape=shape,
            transform=grid["transform"],
            all_touched=True,
            dtype=np.uint8,
        )
    if infrastructure_areas:
        constraints[1] = rasterize(
            [(unary_union(infrastructure_areas), 1)],
            out_shape=shape,
            transform=grid["transform"],
            all_touched=True,
            dtype=np.uint8,
        )
    constraints[:, ~city] = 0
    constraint_path = output_root / "osm_public_proxy_constraints_100m.tif"
    _write_raster(
        constraint_path,
        constraints,
        grid=grid,
        dtype="uint8",
        nodata=0,
        descriptions=("osm_protected_area_proxy", "osm_airport_port_proxy"),
    )
    artifacts = []
    for path, role in (
        (pbf_path, "geofabrik_gcc_pbf_snapshot"),
        (road_path, "road_accessibility"),
        (constraint_path, "public_proxy_constraints"),
    ):
        artifacts.append(
            {
                "path": str(path.relative_to(HERE)),
                "role": role,
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    report = {
        "schema": "gwm.abu_dhabi_osm_input_manifest.v1",
        "benchmark_id": "abu-dhabi-land-use-v1",
        "created_at": datetime.now(UTC).isoformat(),
        "status": "complete",
        "source": {
            "provider": "Geofabrik OpenStreetMap GCC extract",
            "snapshot_date": "2026-07-31",
            "url": url,
            "licence": "OpenStreetMap contributors, ODbL 1.0",
            "bbox_wgs84": list(BBOX),
        },
        "source_counts": features["source_counts"],
        "raster_counts": {
            "road_pixels": int((road_mask & city).sum()),
            "major_road_pixels": int((major_mask & city).sum()),
            "protected_proxy_pixels": int(constraints[0].sum()),
            "airport_port_proxy_pixels": int(constraints[1].sum()),
        },
        "constraint_warning": (
            "OSM protected/airport/port geometry is a public-data proxy, not an "
            "authoritative Abu Dhabi statutory planning layer."
        ),
        "artifacts": artifacts,
    }
    manifest_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pbf", type=Path, default=DEFAULT_PBF)
    parser.add_argument("--url", default=GEOFABRIK_URL)
    parser.add_argument("--proxy", default="")
    parser.add_argument("--grid-profile", type=Path, default=DEFAULT_GRID_PROFILE)
    parser.add_argument("--city-mask", type=Path, default=DEFAULT_CITY_MASK)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()
    report = materialize(
        pbf_path=args.pbf,
        url=args.url,
        proxy=args.proxy or None,
        grid_profile_path=args.grid_profile,
        city_mask_path=args.city_mask,
        output_root=args.output_root,
        manifest_path=args.manifest,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "source_counts": report["source_counts"],
                "raster_counts": report["raster_counts"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

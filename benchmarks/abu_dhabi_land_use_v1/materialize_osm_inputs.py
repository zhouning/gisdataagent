#!/usr/bin/env python3
"""Materialize OSM road accessibility and public proxy constraint layers."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import rasterio
import requests
from rasterio.features import rasterize
from scipy.ndimage import distance_transform_edt
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import polygonize, unary_union

HERE = Path(__file__).resolve().parent
DEFAULT_GRID_PROFILE = HERE / "grid_profile.json"
DEFAULT_CITY_MASK = HERE / "artifacts/abu_dhabi_city_100m_mask.tif"
DEFAULT_RAW = HERE / "artifacts/osm/overpass_city_features.json"
DEFAULT_OUTPUT_ROOT = HERE / "artifacts/osm"
DEFAULT_MANIFEST = HERE / "osm_input_manifest.json"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OSM_BBOX = "24.2810331,54.2971553,24.6018540,54.7659108"


def build_queries() -> dict[str, str]:
    south, west, north, east = (24.2810331, 54.2971553, 24.6018540, 54.7659108)
    queries = {}
    tile_count = 4
    for row in range(tile_count):
        tile_south = south + (north - south) * row / tile_count
        tile_north = south + (north - south) * (row + 1) / tile_count
        for column in range(tile_count):
            tile_west = west + (east - west) * column / tile_count
            tile_east = west + (east - west) * (column + 1) / tile_count
            bbox = f"{tile_south},{tile_west},{tile_north},{tile_east}"
            queries[f"roads_r{row}_c{column}"] = f"""[out:json][timeout:120];
way["highway"]({bbox});
out tags geom;
"""
    queries["constraints"] = f"""[out:json][timeout:180];
(
  nwr["aeroway"]({OSM_BBOX});
  nwr["boundary"="protected_area"]({OSM_BBOX});
  nwr["leisure"="nature_reserve"]({OSM_BBOX});
  nwr["harbour"="yes"]({OSM_BBOX});
  nwr["landuse"="port"]({OSM_BBOX});
  nwr["industrial"="port"]({OSM_BBOX});
);
out tags geom;
"""
    return queries


QUERIES = build_queries()
MAJOR_HIGHWAYS = {"motorway", "trunk", "primary", "secondary"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_grid(path: Path) -> dict[str, Any]:
    profile = json.loads(path.read_text(encoding="utf-8"))
    return {
        "crs": str(profile["crs"]),
        "width": int(profile["width"]),
        "height": int(profile["height"]),
        "transform": rasterio.Affine.from_gdal(*profile["transform_gdal"]),
        "resolution_m": int(profile["resolution_m"]),
    }


def fetch_overpass(
    *,
    raw_path: Path,
    endpoint: str,
    proxy: str | None,
) -> dict[str, Any]:
    if raw_path.is_file():
        return json.loads(raw_path.read_text(encoding="utf-8"))
    proxies = {"http": proxy, "https": proxy} if proxy else None
    by_key: dict[tuple[str, int], dict[str, Any]] = {}
    query_reports = []
    for query_name, query in QUERIES.items():
        part_path = raw_path.with_name(f"{raw_path.stem}_{query_name}.json")
        if part_path.is_file():
            part = json.loads(part_path.read_text(encoding="utf-8"))
        else:
            response = requests.post(
                endpoint,
                data={"data": query},
                headers={"User-Agent": "gisdataagent-abu-dhabi-benchmark/1.0"},
                proxies=proxies,
                timeout=240,
            )
            response.raise_for_status()
            part = response.json()
            if part.get("remark"):
                raise RuntimeError(f"overpass_error:{query_name}:{part['remark']}")
            part_path.parent.mkdir(parents=True, exist_ok=True)
            part_path.write_text(
                json.dumps(part, ensure_ascii=False, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
        elements = part.get("elements") or []
        query_reports.append({"name": query_name, "element_count": len(elements)})
        for element in elements:
            by_key[(str(element["type"]), int(element["id"]))] = element
    payload = {
        "version": 0.6,
        "generator": "merged_split_overpass_queries",
        "query_reports": query_reports,
        "elements": list(by_key.values()),
    }
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return payload


def _coordinates(rows: list[dict[str, Any]]) -> list[tuple[float, float]]:
    return [(float(row["lon"]), float(row["lat"])) for row in rows]


def element_geometries(element: dict[str, Any]) -> list[Any]:
    if element.get("type") == "node" and "lon" in element and "lat" in element:
        return [Point(float(element["lon"]), float(element["lat"]))]
    rows = element.get("geometry") or []
    if rows:
        coordinates = _coordinates(rows)
        if len(coordinates) >= 4 and coordinates[0] == coordinates[-1]:
            polygon = Polygon(coordinates)
            return [polygon] if polygon.is_valid else []
        return [LineString(coordinates)] if len(coordinates) >= 2 else []
    member_lines = []
    for member in element.get("members") or []:
        member_rows = member.get("geometry") or []
        coordinates = _coordinates(member_rows)
        if len(coordinates) >= 2:
            member_lines.append(LineString(coordinates))
    polygons = list(polygonize(member_lines))
    return polygons or member_lines


def _project(geometries: list[Any], target_crs: str) -> list[Any]:
    if not geometries:
        return []
    series = gpd.GeoSeries(geometries, crs="EPSG:4326").to_crs(target_crs)
    return [geometry for geometry in series if not geometry.is_empty]


def _is_protected(tags: dict[str, str]) -> bool:
    return tags.get("boundary") == "protected_area" or tags.get("leisure") == "nature_reserve"


def _is_infrastructure(tags: dict[str, str]) -> bool:
    return bool(
        tags.get("aeroway")
        or tags.get("harbour") == "yes"
        or tags.get("landuse") == "port"
        or tags.get("industrial") == "port"
    )


def _write_raster(
    path: Path,
    data: np.ndarray,
    *,
    grid: dict[str, Any],
    dtype: str,
    nodata: float | int,
    descriptions: tuple[str, ...],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    profile = {
        "driver": "GTiff",
        "width": grid["width"],
        "height": grid["height"],
        "count": len(descriptions),
        "dtype": dtype,
        "crs": grid["crs"],
        "transform": grid["transform"],
        "nodata": nodata,
        "compress": "deflate",
        "tiled": True,
        "blockxsize": 256,
        "blockysize": 256,
    }
    temp_path = path.with_suffix(f".partial.{os.getpid()}.tif")
    with rasterio.open(temp_path, "w", **profile) as dataset:
        dataset.write(data.astype(dtype, copy=False))
        for index, description in enumerate(descriptions, start=1):
            dataset.set_band_description(index, description)
    os.replace(temp_path, path)


def materialize(
    *,
    grid_profile_path: Path,
    city_mask_path: Path,
    raw_path: Path,
    output_root: Path,
    manifest_path: Path,
    endpoint: str,
    proxy: str | None,
) -> dict[str, Any]:
    grid = load_grid(grid_profile_path)
    with rasterio.open(city_mask_path) as dataset:
        city = dataset.read(1).astype(bool)
    payload = fetch_overpass(raw_path=raw_path, endpoint=endpoint, proxy=proxy)
    roads = []
    major_roads = []
    protected = []
    infrastructure = []
    element_counts = {
        "total": 0,
        "highway": 0,
        "major_highway": 0,
        "protected": 0,
        "infrastructure": 0,
    }
    for element in payload.get("elements") or []:
        tags = {str(key): str(value) for key, value in (element.get("tags") or {}).items()}
        geometries = element_geometries(element)
        if not geometries:
            continue
        element_counts["total"] += 1
        if tags.get("highway"):
            roads.extend(geometries)
            element_counts["highway"] += 1
            if tags["highway"] in MAJOR_HIGHWAYS:
                major_roads.extend(geometries)
                element_counts["major_highway"] += 1
        if _is_protected(tags):
            protected.extend(geometries)
            element_counts["protected"] += 1
        if _is_infrastructure(tags):
            infrastructure.extend(geometries)
            element_counts["infrastructure"] += 1

    roads_projected = _project(roads, grid["crs"])
    major_projected = _project(major_roads, grid["crs"])
    protected_projected = _project(protected, grid["crs"])
    infrastructure_projected = _project(infrastructure, grid["crs"])
    shape = (grid["height"], grid["width"])
    road_mask = rasterize(
        [(geometry, 1) for geometry in roads_projected],
        out_shape=shape,
        transform=grid["transform"],
        all_touched=True,
        dtype=np.uint8,
    ).astype(bool)
    major_mask = rasterize(
        [(geometry, 1) for geometry in major_projected],
        out_shape=shape,
        transform=grid["transform"],
        all_touched=True,
        dtype=np.uint8,
    ).astype(bool)
    if not road_mask.any() or not major_mask.any():
        raise RuntimeError("osm_road_raster_is_empty")
    road_distance = distance_transform_edt(~road_mask, sampling=grid["resolution_m"])
    major_distance = distance_transform_edt(~major_mask, sampling=grid["resolution_m"])
    road_data = np.stack([road_distance, major_distance]).astype(np.float32)
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

    protected_polygons = [
        geometry if geometry.geom_type in {"Polygon", "MultiPolygon"} else geometry.buffer(100)
        for geometry in protected_projected
    ]
    infrastructure_areas = []
    for geometry in infrastructure_projected:
        if geometry.geom_type in {"Polygon", "MultiPolygon"}:
            infrastructure_areas.append(geometry.buffer(100))
        elif geometry.geom_type == "Point":
            infrastructure_areas.append(geometry.buffer(300))
        else:
            infrastructure_areas.append(geometry.buffer(150))
    protected_union = unary_union(protected_polygons) if protected_polygons else None
    infrastructure_union = unary_union(infrastructure_areas) if infrastructure_areas else None
    constraint_data = np.zeros((2, *shape), dtype=np.uint8)
    if protected_union is not None and not protected_union.is_empty:
        constraint_data[0] = rasterize(
            [(protected_union, 1)],
            out_shape=shape,
            transform=grid["transform"],
            all_touched=True,
            dtype=np.uint8,
        )
    if infrastructure_union is not None and not infrastructure_union.is_empty:
        constraint_data[1] = rasterize(
            [(infrastructure_union, 1)],
            out_shape=shape,
            transform=grid["transform"],
            all_touched=True,
            dtype=np.uint8,
        )
    constraint_data[:, ~city] = 0
    constraint_path = output_root / "osm_public_proxy_constraints_100m.tif"
    _write_raster(
        constraint_path,
        constraint_data,
        grid=grid,
        dtype="uint8",
        nodata=0,
        descriptions=("osm_protected_area_proxy", "osm_airport_port_proxy"),
    )
    artifacts = []
    for path, role in (
        (raw_path, "raw_overpass_response"),
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
            "provider": "OpenStreetMap via Overpass API",
            "endpoint": endpoint,
            "query_bbox_wgs84_south_west_north_east": [
                24.2810331,
                54.2971553,
                24.6018540,
                54.7659108,
            ],
            "licence": "OpenStreetMap contributors, ODbL 1.0",
            "queries": QUERIES,
        },
        "element_counts": element_counts,
        "raster_counts": {
            "road_pixels": int((road_mask & city).sum()),
            "major_road_pixels": int((major_mask & city).sum()),
            "protected_proxy_pixels": int(constraint_data[0].sum()),
            "airport_port_proxy_pixels": int(constraint_data[1].sum()),
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
    parser.add_argument("--grid-profile", type=Path, default=DEFAULT_GRID_PROFILE)
    parser.add_argument("--city-mask", type=Path, default=DEFAULT_CITY_MASK)
    parser.add_argument("--raw", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--endpoint", default=OVERPASS_URL)
    parser.add_argument("--proxy", default="")
    args = parser.parse_args()
    report = materialize(
        grid_profile_path=args.grid_profile,
        city_mask_path=args.city_mask,
        raw_path=args.raw,
        output_root=args.output_root,
        manifest_path=args.manifest,
        endpoint=args.endpoint,
        proxy=args.proxy or None,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "element_counts": report["element_counts"],
                "raster_counts": report["raster_counts"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

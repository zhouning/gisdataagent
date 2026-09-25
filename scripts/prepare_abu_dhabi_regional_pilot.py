#!/usr/bin/env python3
"""Build a bounded Abu Dhabi regional hydro input package.

The customer export contains three regions with different levels of attribute
completeness.  This utility materializes a model-ready pilot package for a
named region, preserving static outfall/pump attributes and clipping the
registered DTM to the region plus a configurable hydraulic buffer.
"""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import geopandas as gpd
import rasterio
from rasterio.mask import mask
from shapely.geometry import mapping
from shapely.ops import unary_union
from shapely.validation import make_valid


REGION_FILES = {
    "Musaffah_00": {
        "swmm": "Mussafah_00.inp",
        "catchment": "Catchment.shp",
        "conduit": "conduit.shp",
        "manholes": "Manholes.shp",
        "outfalls": "Outfall.shp",
        "pumps": "Pumps.shp",
        "wetwell": "Wetwell.shp",
        "ponds": "POnds.shp",
    },
    "Shaliela": {
        "swmm": "Shaliela.inp",
        "catchment": "Catchment.shp",
        "conduit": "Conduit.shp",
        "manholes": "Manhole.shp",
        "inlets": "Inlets.shp",
        "outfalls": "Outfalls.shp",
        "pumps": "Pumps.shp",
        "wetwell": "Wetwell.shp",
        "ponds": "ponds.shp",
    },
    "RB3": {
        "swmm": None,
        "catchment": "Catchment.shp",
        "conduit": "Conduit.shp",
        "inlets": "Inlets.shp",
        "manholes": "Manhole.shp",
        "outfall": "Outfall.shp",
        "pumps": "Pumps.shp",
        "wetwell": "Wetwell.shp",
        "ponds": "POnds.shp",
    },
}


def _safe_geometry(geometry: Any) -> Any:
    if geometry is None or geometry.is_empty:
        return None
    if not geometry.is_valid:
        geometry = make_valid(geometry)
    return None if geometry is None or geometry.is_empty else geometry


def _write_geojson(source: Path, target: Path, *, source_crs: str = "EPSG:32640") -> dict[str, Any]:
    if not source.exists():
        return {"status": "missing", "path": str(source), "feature_count": 0}
    frame = gpd.read_file(source)
    if frame.crs is None:
        frame = frame.set_crs(source_crs, allow_override=True)
    frame = frame.to_crs("EPSG:4326")
    frame = frame[frame.geometry.notna()].copy()
    frame["geometry"] = frame.geometry.map(_safe_geometry)
    frame = frame[frame.geometry.notna() & ~frame.geometry.is_empty].copy()
    target.parent.mkdir(parents=True, exist_ok=True)
    frame.to_file(target, driver="GeoJSON", index=False)
    return {
        "status": "ready",
        "source": source.name,
        "feature_count": int(len(frame)),
        "attribute_columns": [str(column) for column in frame.columns if column != "geometry"],
        "attribute_status": "complete" if source.with_suffix(".dbf").exists() else "geometry_only",
    }


def _clip_dtm(dtm: Path, region_geom: Any, target: Path, buffer_m: float) -> dict[str, Any]:
    target.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(dtm) as dataset:
        projected = gpd.GeoSeries([region_geom], crs="EPSG:4326").to_crs(dataset.crs).iloc[0]
        projected = projected.buffer(buffer_m)
        image, transform = mask(dataset, [mapping(projected)], crop=True, nodata=dataset.nodata)
        profile = dataset.profile.copy()
        profile.update(
            driver="GTiff",
            height=image.shape[1],
            width=image.shape[2],
            transform=transform,
            compress="DEFLATE",
            tiled=True,
            BIGTIFF="IF_SAFER",
        )
        with rasterio.open(target, "w", **profile) as output:
            output.write(image)
        bounds = rasterio.transform.array_bounds(image.shape[1], image.shape[2], transform)
        return {
            "status": "ready",
            "source": dtm.name,
            "crs": str(dataset.crs),
            "resolution_m": float(abs(dataset.transform.a)),
            "width": int(image.shape[2]),
            "height": int(image.shape[1]),
            "bounds": [float(value) for value in bounds],
            "buffer_m": buffer_m,
        }


def build_package(archive: Path, dtm: Path, output: Path, region: str, buffer_m: float) -> dict[str, Any]:
    if region not in REGION_FILES:
        raise ValueError(f"unsupported region: {region}")
    spec = REGION_FILES[region]
    with tempfile.TemporaryDirectory(prefix="abu-dhabi-regional-pilot-") as temporary:
        extracted = Path(temporary)
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(extracted)
        root = extracted / "Hydraulic Model Data Export"
        region_root = root / region
        package = output / region.lower()
        if package.exists():
            shutil.rmtree(package)
        package.mkdir(parents=True)

        catchment_path = region_root / spec["catchment"]
        catchments = gpd.read_file(catchment_path)
        if catchments.crs is None:
            catchments = catchments.set_crs("EPSG:32640", allow_override=True)
        catchments = catchments.to_crs("EPSG:4326")
        geometries = [_safe_geometry(value) for value in catchments.geometry]
        geometries = [value for value in geometries if value is not None]
        if not geometries:
            raise ValueError(f"region has no valid catchment geometry: {region}")
        region_geom = unary_union(geometries)

        assets: dict[str, Any] = {}
        swmm_name = spec.get("swmm")
        if swmm_name and (root / "SWMM_Export" / swmm_name).exists():
            target = package / "network" / swmm_name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / "SWMM_Export" / swmm_name, target)
            assets["network"] = {"status": "ready", "source": swmm_name}
        else:
            assets["network"] = {"status": "missing", "source": swmm_name}

        assets["terrain"] = _clip_dtm(
            dtm,
            region_geom,
            package / "terrain" / f"AUH_DTM_10m_{region.lower()}.tif",
            buffer_m,
        )

        for key in ("catchment", "conduit", "inlets", "manholes", "outfalls", "outfall", "pumps", "wetwell", "ponds"):
            filename = spec.get(key)
            if not filename:
                continue
            source = region_root / filename
            if not source.exists():
                assets[key] = {"status": "missing", "source": filename}
                continue
            target_name = f"{region.lower()}_{key if key != 'outfall' else 'outfalls'}.geojson"
            assets[key] = _write_geojson(source, package / "network" / target_name)

        manifest = {
            "schema": "gwm.abu_dhabi_flood.regional_pilot_manifest.v1",
            "region": region,
            "source_archive": archive.name,
            "source_crs": "EPSG:32640",
            "output_crs": "EPSG:4326",
            "pilot_status": "recommended" if region == "Musaffah_00" else "candidate",
            "engineering_admission": "diagnostic_only",
            "dynamic_tide_available": False,
            "scada_available": False,
            "catchment_count": int(len(catchments)),
            "region_bbox_wgs84": [float(value) for value in region_geom.bounds],
            "assets": assets,
        }
        (package / "region_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument("dtm", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--region", choices=sorted(REGION_FILES), default="Musaffah_00")
    parser.add_argument("--buffer-m", type=float, default=500.0)
    args = parser.parse_args()
    print(json.dumps(build_package(args.archive, args.dtm, args.output, args.region, args.buffer_m), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

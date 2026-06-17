#!/usr/bin/env python3
"""Fetch real public imagery for a TWM test-data package.

The script intentionally avoids heavyweight STAC SDK dependencies. It queries a
STAC /search endpoint, reads Cloud-Optimized GeoTIFF assets through rasterio,
clips/resamples them to the package AOI, writes local GeoTIFF products, and
optionally registers them in the package evidence table.
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import requests
import rasterio
from rasterio import windows
from rasterio.enums import Resampling
from rasterio.warp import reproject, transform_bounds
from rasterio.transform import from_bounds


DEFAULT_DATA_DIR = Path("data_agent/test_data/twm_bishan_multi_admin_eval")
DEFAULT_STAC_ENDPOINT = "https://earth-search.aws.element84.com/v1"
DEFAULT_COLLECTION = "sentinel-2-l2a"
DEFAULT_DATETIME = "2025-01-01/2025-12-31"
DEFAULT_PROJECT_CRS = "EPSG:32648"

REFLECTANCE_ASSETS = {
    "blue": {"band_name": "B02", "resolution_m": 10},
    "green": {"band_name": "B03", "resolution_m": 10},
    "red": {"band_name": "B04", "resolution_m": 10},
    "nir": {"band_name": "B08", "resolution_m": 10},
    "swir16": {"band_name": "B11", "resolution_m": 20},
    "swir22": {"band_name": "B12", "resolution_m": 20},
}
CORE_ASSETS = ["blue", "green", "red", "nir"]
FULL_ASSETS = ["blue", "green", "red", "nir", "swir16", "swir22"]
SCL_CLOUD_CLASSES = {0, 1, 3, 8, 9, 10, 11}
NODATA_FLOAT = -9999.0
LOCAL_PRODUCT_SPECS = {
    "sentinel2_l2a_reflectance_stack": {
        "filename": "sentinel2_l2a_reflectance_stack.tif",
        "product_id": "REAL-S2-L2A-REFLECTANCE",
        "type": "reflectance_stack",
    },
    "sentinel2_l2a_rgb": {
        "filename": "sentinel2_l2a_rgb.tif",
        "product_id": "REAL-S2-L2A-RGB",
        "type": "visual_rgb",
    },
    "sentinel2_l2a_ndvi": {
        "filename": "sentinel2_l2a_ndvi.tif",
        "product_id": "REAL-S2-L2A-NDVI",
        "type": "spectral_index",
        "formula": "NDVI=(NIR-Red)/(NIR+Red)",
    },
    "sentinel2_l2a_scl": {
        "filename": "sentinel2_l2a_scl.tif",
        "product_id": "REAL-S2-L2A-SCL",
        "type": "scene_classification",
    },
}


def _normalise_datetime(value: str) -> str:
    if "/" not in value:
        raise ValueError("datetime must be an interval, for example 2025-01-01/2025-12-31")
    start, end = value.split("/", 1)

    def normalise_part(text: str, is_end: bool) -> str:
        text = text.strip()
        if len(text) == 10 and text[4] == "-" and text[7] == "-":
            return f"{text}T{'23:59:59' if is_end else '00:00:00'}Z"
        if text.endswith("Z"):
            return text
        if "T" in text:
            return f"{text}Z"
        return text

    return f"{normalise_part(start, False)}/{normalise_part(end, True)}"


def _bbox_overlap_area(a: list[float], b: list[float]) -> float:
    minx = max(a[0], b[0])
    miny = max(a[1], b[1])
    maxx = min(a[2], b[2])
    maxy = min(a[3], b[3])
    if maxx <= minx or maxy <= miny:
        return 0.0
    return (maxx - minx) * (maxy - miny)


def _load_aoi(data_dir: Path, project_crs: str, padding_m: float) -> dict[str, Any]:
    parcels_path = data_dir / "parcel_current.geojson"
    if not parcels_path.exists():
        raise FileNotFoundError(f"missing AOI source: {parcels_path}")
    parcels = gpd.read_file(parcels_path)
    if parcels.crs is None:
        raise ValueError(f"{parcels_path} has no CRS")
    parcels_wgs84 = parcels.to_crs("EPSG:4326")
    parcels_projected = parcels.to_crs(project_crs)
    minx, miny, maxx, maxy = parcels_projected.total_bounds
    minx -= padding_m
    miny -= padding_m
    maxx += padding_m
    maxy += padding_m
    projected_bounds = [float(minx), float(miny), float(maxx), float(maxy)]
    padded = gpd.GeoSeries(
        [parcels_projected.geometry.union_all().envelope.buffer(padding_m).envelope],
        crs=project_crs,
    ).to_crs("EPSG:4326")
    wgs84_bounds = [float(v) for v in padded.total_bounds]
    return {
        "parcels_path": str(parcels_path),
        "bbox_wgs84": wgs84_bounds,
        "bbox_projected": projected_bounds,
        "parcel_bounds_wgs84": [float(v) for v in parcels_wgs84.total_bounds],
        "feature_count": int(len(parcels)),
    }


def _query_stac(
    *,
    endpoint: str,
    collection: str,
    bbox: list[float],
    datetime_range: str,
    cloud_cover_max: float,
    limit: int,
) -> list[dict[str, Any]]:
    search_url = endpoint.rstrip("/") + "/search"
    body: dict[str, Any] = {
        "collections": [collection],
        "bbox": bbox,
        "datetime": _normalise_datetime(datetime_range),
        "limit": min(max(limit, 1), 100),
        "query": {"eo:cloud_cover": {"lt": cloud_cover_max}},
    }
    resp = requests.post(search_url, json=body, timeout=60)
    resp.raise_for_status()
    payload = resp.json()
    return payload.get("features", [])


def _select_item_group(features: list[dict[str, Any]], bbox: list[float]) -> dict[str, Any]:
    if not features:
        raise ValueError("STAC search returned no items")
    bbox_area = max((bbox[2] - bbox[0]) * (bbox[3] - bbox[1]), 1e-12)
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in features:
        dt = item.get("properties", {}).get("datetime", "")
        date = dt[:10] if dt else "unknown"
        groups.setdefault(date, []).append(item)

    candidates = []
    for date, items in groups.items():
        overlap = sum(_bbox_overlap_area(bbox, item.get("bbox", bbox)) for item in items)
        coverage_ratio = min(1.0, overlap / bbox_area)
        clouds = [
            float(item.get("properties", {}).get("eo:cloud_cover", 100.0) or 100.0)
            for item in items
        ]
        avg_cloud = sum(clouds) / len(clouds)
        candidates.append(
            {
                "date": date,
                "items": items,
                "coverage_ratio_estimate": round(coverage_ratio, 6),
                "avg_cloud_cover": round(avg_cloud, 6),
            }
        )
    candidates.sort(
        key=lambda x: (
            x["coverage_ratio_estimate"] >= 0.95,
            x["coverage_ratio_estimate"],
            -x["avg_cloud_cover"],
            x["date"],
        ),
        reverse=True,
    )
    selected = candidates[0]
    selected["items"] = sorted(
        selected["items"],
        key=lambda item: float(item.get("properties", {}).get("eo:cloud_cover", 100.0) or 100.0),
    )
    return selected


def _target_grid(projected_bounds: list[float], resolution_m: float) -> dict[str, Any]:
    minx, miny, maxx, maxy = projected_bounds
    width = max(1, int(math.ceil((maxx - minx) / resolution_m)))
    height = max(1, int(math.ceil((maxy - miny) / resolution_m)))
    transform = from_bounds(minx, miny, maxx, maxy, width, height)
    return {"width": width, "height": height, "transform": transform}


def _asset_scale_offset(item: dict[str, Any], asset_name: str) -> tuple[float, float]:
    asset = item.get("assets", {}).get(asset_name, {})
    bands = asset.get("raster:bands") or []
    if not bands:
        return 1.0, 0.0
    band = bands[0]
    return float(band.get("scale", 1.0) or 1.0), float(band.get("offset", 0.0) or 0.0)


def _read_asset_mosaic(
    items: list[dict[str, Any]],
    asset_name: str,
    *,
    project_crs: str,
    transform: Any,
    width: int,
    height: int,
    projected_bounds: list[float],
    resampling: Resampling,
    reflectance: bool,
    target_resolution_m: float,
) -> tuple[np.ndarray, list[dict[str, Any]]]:
    out = np.full((height, width), NODATA_FLOAT, dtype="float32")
    sources = []
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", AWS_NO_SIGN_REQUEST="YES"):
        for item in items:
            asset = item.get("assets", {}).get(asset_name)
            if not asset:
                continue
            href = asset.get("href")
            if not href:
                continue
            scale, offset = _asset_scale_offset(item, asset_name)
            try:
                with rasterio.open(href) as src:
                    src_nodata = src.nodata if src.nodata is not None else 0
                    source_bounds = transform_bounds(
                        project_crs,
                        src.crs,
                        projected_bounds[0],
                        projected_bounds[1],
                        projected_bounds[2],
                        projected_bounds[3],
                        densify_pts=21,
                    )
                    window = windows.from_bounds(*source_bounds, transform=src.transform)
                    window = window.round_offsets().round_lengths()
                    full = windows.Window(0, 0, src.width, src.height)
                    window = windows.intersection(window, full)
                    if window.width <= 0 or window.height <= 0:
                        continue
                    src_xres = abs(float(src.transform.a)) if src.transform else target_resolution_m
                    src_yres = abs(float(src.transform.e)) if src.transform else target_resolution_m
                    x_factor = max(float(target_resolution_m) / max(src_xres, 1e-9), 1.0)
                    y_factor = max(float(target_resolution_m) / max(src_yres, 1e-9), 1.0)
                    out_width = max(1, int(math.ceil(window.width / x_factor)))
                    out_height = max(1, int(math.ceil(window.height / y_factor)))
                    src_data = src.read(
                        1,
                        window=window,
                        out_shape=(out_height, out_width),
                        out_dtype="float32",
                        masked=False,
                        resampling=resampling,
                    )
                    src_window_transform = src.window_transform(window)
                    src_transform = src_window_transform * src_window_transform.scale(
                        window.width / out_width,
                        window.height / out_height,
                    )
                    raw = np.full((height, width), NODATA_FLOAT, dtype="float32")
                    reproject(
                        source=src_data,
                        destination=raw,
                        src_transform=src_transform,
                        src_crs=src.crs,
                        src_nodata=src_nodata,
                        dst_transform=transform,
                        dst_crs=project_crs,
                        dst_nodata=NODATA_FLOAT,
                        resampling=resampling,
                    )
                valid = np.isfinite(raw) & (raw != NODATA_FLOAT) & (raw != src_nodata)
                data = np.full_like(raw, NODATA_FLOAT, dtype="float32")
                if reflectance:
                    data[valid] = raw[valid] * scale + offset
                else:
                    data[valid] = raw[valid]
                fill = valid & ((out == NODATA_FLOAT) | ~np.isfinite(out))
                out[fill] = data[fill]
                sources.append(
                    {
                        "item_id": item.get("id"),
                        "datetime": item.get("properties", {}).get("datetime", ""),
                        "asset": asset_name,
                        "href": href,
                        "scale": scale,
                        "offset": offset,
                    }
                )
            except Exception as exc:
                sources.append(
                    {
                        "item_id": item.get("id"),
                        "asset": asset_name,
                        "href": href,
                        "error": str(exc)[:300],
                    }
                )
    return out, sources


def _stats(array: np.ndarray, nodata: float = NODATA_FLOAT) -> dict[str, Any]:
    valid = array[np.isfinite(array) & (array != nodata)]
    if valid.size == 0:
        return {"valid_pixels": 0, "min": None, "mean": None, "max": None}
    return {
        "valid_pixels": int(valid.size),
        "min": round(float(valid.min()), 6),
        "mean": round(float(valid.mean()), 6),
        "max": round(float(valid.max()), 6),
    }


def _band_order_from_descriptions(descriptions: list[str], band_count: int) -> list[str]:
    mapping = {
        "B02": "blue",
        "BLUE": "blue",
        "B03": "green",
        "GREEN": "green",
        "B04": "red",
        "RED": "red",
        "B08": "nir",
        "NIR": "nir",
        "B11": "swir16",
        "SWIR16": "swir16",
        "SWIR1": "swir16",
        "B12": "swir22",
        "SWIR22": "swir22",
        "SWIR2": "swir22",
    }
    order = []
    for desc in descriptions:
        text = (desc or "").upper()
        matched = ""
        for token, name in mapping.items():
            if token in text:
                matched = name
                break
        if matched:
            order.append(matched)
    if len(order) == band_count:
        return order
    if band_count == 4:
        return CORE_ASSETS.copy()
    if band_count == 6:
        return FULL_ASSETS.copy()
    return [f"band_{i}" for i in range(1, band_count + 1)]


def _product_stats_from_raster(path: Path, product_type: str, band_order: list[str]) -> Any:
    with rasterio.open(path) as src:
        nodata = src.nodata if src.nodata is not None else NODATA_FLOAT
        if product_type == "visual_rgb":
            names = ["red", "green", "blue"]
            return {
                names[i] if i < len(names) else f"band_{i + 1}": _stats(src.read(i + 1), nodata)
                for i in range(src.count)
            }
        if product_type == "reflectance_stack":
            return {
                band_order[i] if i < len(band_order) else f"band_{i + 1}": _stats(
                    src.read(i + 1), nodata
                )
                for i in range(src.count)
            }
        if src.count == 1:
            return _stats(src.read(1), nodata)
        return {f"band_{i}": _stats(src.read(i), nodata) for i in range(1, src.count + 1)}


def _reconstruct_products_from_local_files(data_dir: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    """Rebuild product metadata when local GeoTIFFs exist but manifest products were lost."""

    imagery_dir = data_dir / "real_imagery"
    products: dict[str, Any] = {}
    target_grid: dict[str, Any] = {}
    source_records: dict[str, list[dict[str, Any]]] = {}
    observed_date = manifest.get("stac", {}).get("selected_date") or ""

    for name, spec in LOCAL_PRODUCT_SPECS.items():
        path = imagery_dir / spec["filename"]
        if not path.exists():
            continue
        with rasterio.open(path) as src:
            descriptions = [d or "" for d in src.descriptions]
            band_order = (
                _band_order_from_descriptions(descriptions, src.count)
                if spec["type"] == "reflectance_stack"
                else []
            )
            if not target_grid:
                xres = abs(float(src.transform.a)) if src.transform else None
                yres = abs(float(src.transform.e)) if src.transform else None
                target_grid = {
                    "crs": str(src.crs),
                    "resolution_m": round(float(((xres or 0.0) + (yres or 0.0)) / 2), 6)
                    if xres and yres
                    else None,
                    "product_set": "full" if src.count >= 6 else "core",
                    "width": int(src.width),
                    "height": int(src.height),
                    "transform": [round(float(v), 9) for v in tuple(src.transform)[:6]],
                    "reconstructed_from_local_files": True,
                }
        product = {
            "product_id": spec["product_id"],
            "path": str(path),
            "relative_path": str(path.relative_to(data_dir)),
            "type": spec["type"],
            "stats": _product_stats_from_raster(path, spec["type"], band_order),
        }
        if band_order:
            product["band_order"] = band_order
        if spec.get("formula"):
            product["formula"] = spec["formula"]
        if spec["type"] == "scene_classification":
            product["masked_classes"] = sorted(SCL_CLOUD_CLASSES)
        products[name] = product
        source_records[name] = [
            {
                "item_id": "LOCAL-REGISTERED-SENTINEL2-L2A",
                "datetime": observed_date,
                "asset": name,
                "href": str(path),
                "source_registration_only": True,
            }
        ]

    if not products:
        return {}

    manifest.setdefault("source_type", "observed_remote_sensing")
    manifest["synthetic"] = False
    manifest["not_for_production"] = False
    manifest["products"] = products
    manifest.setdefault("sources", source_records)
    if not manifest.get("sources"):
        manifest["sources"] = source_records
    if target_grid and not manifest.get("target_grid"):
        manifest["target_grid"] = target_grid
    stac = manifest.setdefault("stac", {})
    stac.setdefault("collection", DEFAULT_COLLECTION)
    stac.setdefault("selected_date", observed_date)
    if not stac.get("selected_items"):
        stac["selected_items"] = [
            {
                "id": "LOCAL-REGISTERED-SENTINEL2-L2A",
                "datetime": observed_date,
                "source_registration_only": True,
                "note": "Product metadata reconstructed from existing local GeoTIFF files.",
            }
        ]
    manifest.setdefault("processing_history", []).append(
        {
            "time": datetime.now(timezone.utc).isoformat(),
            "step": "reconstruct_products_from_local_files",
            "note": "Recovered real imagery product metadata from local GeoTIFF files.",
        }
    )
    return products


def _write_raster(
    path: Path,
    arrays: list[np.ndarray],
    *,
    project_crs: str,
    transform: Any,
    dtype: str,
    nodata: float | int,
    descriptions: list[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    profile = {
        "driver": "GTiff",
        "height": arrays[0].shape[0],
        "width": arrays[0].shape[1],
        "count": len(arrays),
        "dtype": dtype,
        "crs": project_crs,
        "transform": transform,
        "nodata": nodata,
        "compress": "deflate",
        "tiled": True,
        "blockxsize": 256,
        "blockysize": 256,
    }
    with rasterio.open(path, "w", **profile) as dst:
        for i, array in enumerate(arrays, start=1):
            dst.write(array.astype(dtype), i)
            if i <= len(descriptions):
                dst.set_band_description(i, descriptions[i - 1])


def _safe_index(numerator: np.ndarray, denominator: np.ndarray, valid_mask: np.ndarray) -> np.ndarray:
    out = np.full(numerator.shape, NODATA_FLOAT, dtype="float32")
    denom = denominator
    valid = valid_mask & np.isfinite(denom) & (np.abs(denom) > 1e-6)
    values = np.full(numerator.shape, np.nan, dtype="float32")
    values[valid] = numerator[valid] / denom[valid]
    valid &= np.isfinite(values) & (values >= -1.0) & (values <= 1.0)
    out[valid] = values[valid]
    return out


def _rgb_uint8(red: np.ndarray, green: np.ndarray, blue: np.ndarray, valid_mask: np.ndarray) -> np.ndarray:
    rgb = []
    for band in [red, green, blue]:
        scaled = np.zeros(band.shape, dtype="uint8")
        values = band[valid_mask & np.isfinite(band)]
        if values.size:
            lo, hi = np.percentile(values, [2, 98])
            if hi <= lo:
                hi = lo + 1e-6
            stretched = np.clip((band - lo) / (hi - lo), 0.0, 1.0)
            scaled[valid_mask] = np.round(stretched[valid_mask] * 255).astype("uint8")
        rgb.append(scaled)
    return np.stack(rgb)


def _update_evidence_table(data_dir: Path, products: dict[str, Any], observed_date: str) -> None:
    path = data_dir / "tables" / "multimodal_evidence_index.csv"
    if not path.exists():
        return
    df = pd.read_csv(path)
    if "evidence_type" in df.columns:
        df = df[df["evidence_type"].astype(str) != "observed_remote_sensing"].copy()
    rows = []
    for i, product in enumerate(products.values()):
        rows.append(
            {
                "evidence_id": f"EVD-REAL-{i:06d}",
                "evidence_type": "observed_remote_sensing",
                "evidence_uri": product.get("relative_path", product.get("path", "")),
                "linked_object_id": product.get("product_id", ""),
                "linked_object_type": "raster_product",
                "observed_date": observed_date,
                "confidence": 0.9,
                "synthetic": False,
                "not_for_production": False,
            }
        )
    df = pd.concat([df, pd.DataFrame(rows)], ignore_index=True)
    df.to_csv(path, index=False)


def _update_dataset_manifest(data_dir: Path, manifest_path: Path, product_count: int) -> None:
    path = data_dir / "dataset_manifest.json"
    if not path.exists():
        return
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["real_imagery"] = {
        "path": str(manifest_path),
        "product_count": product_count,
        "priority": "preferred_over_synthetic_raster_fixture",
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _refresh_products_from_local_stack(args: argparse.Namespace) -> dict[str, Any]:
    data_dir = Path(args.data_dir)
    manifest_path = data_dir / "real_imagery_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"missing real imagery manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    products = manifest.get("products", {})
    if not products:
        products = _reconstruct_products_from_local_files(data_dir, manifest)
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
    stack_info = products.get("sentinel2_l2a_reflectance_stack", {})
    stack_path = data_dir / stack_info.get("relative_path", stack_info.get("path", ""))
    if not stack_path.exists() and stack_info.get("path"):
        stack_path = Path(stack_info["path"])
    if not stack_path.exists():
        raise FileNotFoundError(f"missing reflectance stack: {stack_path}")

    with rasterio.open(stack_path) as src:
        descriptions = [d or "" for d in src.descriptions]
        band_order = stack_info.get("band_order") or []
        if not band_order:
            band_order = [
                "blue" if "B02" in descriptions[0] else descriptions[0],
                "green" if len(descriptions) > 1 and "B03" in descriptions[1] else descriptions[1],
                "red" if len(descriptions) > 2 and "B04" in descriptions[2] else descriptions[2],
                "nir" if len(descriptions) > 3 and "B08" in descriptions[3] else descriptions[3],
            ]
        arrays = {
            name: src.read(i + 1).astype("float32")
            for i, name in enumerate(band_order)
            if i < src.count
        }
        profile_crs = str(src.crs)
        transform = src.transform
        src_nodata = src.nodata if src.nodata is not None else NODATA_FLOAT

    required = {"blue", "green", "red", "nir"}
    missing = sorted(required - set(arrays))
    if missing:
        raise ValueError(f"reflectance stack is missing required bands: {missing}")

    valid = np.ones(arrays["red"].shape, dtype=bool)
    for name in ["blue", "green", "red", "nir"]:
        valid &= np.isfinite(arrays[name]) & (arrays[name] != src_nodata) & (arrays[name] != NODATA_FLOAT)

    scl_info = products.get("sentinel2_l2a_scl", {})
    scl_path = data_dir / scl_info.get("relative_path", scl_info.get("path", ""))
    if not scl_path.exists() and scl_info.get("path"):
        scl_path = Path(scl_info["path"])
    if scl_path.exists() and not args.no_scl_mask:
        with rasterio.open(scl_path) as scl_src:
            scl = scl_src.read(1)
        valid &= ~np.isin(scl.astype("uint8"), list(SCL_CLOUD_CLASSES))

    ndvi = _safe_index(arrays["nir"] - arrays["red"], arrays["nir"] + arrays["red"], valid)
    rgb = _rgb_uint8(arrays["red"], arrays["green"], arrays["blue"], valid)
    out_dir = stack_path.parent

    rgb_path = out_dir / "sentinel2_l2a_rgb.tif"
    _write_raster(
        rgb_path,
        [rgb[0], rgb[1], rgb[2]],
        project_crs=profile_crs,
        transform=transform,
        dtype="uint8",
        nodata=0,
        descriptions=["red", "green", "blue"],
    )
    products["sentinel2_l2a_rgb"] = {
        "product_id": "REAL-S2-L2A-RGB",
        "path": str(rgb_path),
        "relative_path": str(rgb_path.relative_to(data_dir)),
        "type": "visual_rgb",
        "stats": {"red": _stats(rgb[0], 0), "green": _stats(rgb[1], 0), "blue": _stats(rgb[2], 0)},
    }

    ndvi_path = out_dir / "sentinel2_l2a_ndvi.tif"
    _write_raster(
        ndvi_path,
        [ndvi],
        project_crs=profile_crs,
        transform=transform,
        dtype="float32",
        nodata=NODATA_FLOAT,
        descriptions=["NDVI=(NIR-Red)/(NIR+Red)"],
    )
    products["sentinel2_l2a_ndvi"] = {
        "product_id": "REAL-S2-L2A-NDVI",
        "path": str(ndvi_path),
        "relative_path": str(ndvi_path.relative_to(data_dir)),
        "type": "spectral_index",
        "formula": "NDVI=(NIR-Red)/(NIR+Red)",
        "stats": _stats(ndvi),
    }

    manifest["products"] = products
    manifest.setdefault("processing_history", []).append(
        {
            "time": datetime.now(timezone.utc).isoformat(),
            "step": "refresh_products_from_local_stack",
            "note": "Regenerated RGB and NDVI from local reflectance stack without remote reads.",
        }
    )
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    if not args.no_update_evidence:
        observed_date = manifest.get("stac", {}).get("selected_date", "")
        _update_evidence_table(data_dir, products, observed_date)
        _update_dataset_manifest(data_dir, manifest_path, len(products))

    return {
        "status": "success",
        "mode": "refresh-local",
        "manifest": str(manifest_path),
        "products": {
            "sentinel2_l2a_rgb": products["sentinel2_l2a_rgb"]["relative_path"],
            "sentinel2_l2a_ndvi": products["sentinel2_l2a_ndvi"]["relative_path"],
        },
        "ndvi_stats": products["sentinel2_l2a_ndvi"]["stats"],
    }


def fetch_real_imagery(args: argparse.Namespace) -> dict[str, Any]:
    if args.refresh_local:
        return _refresh_products_from_local_stack(args)

    data_dir = Path(args.data_dir)
    out_dir = Path(args.output_dir) if args.output_dir else data_dir / "real_imagery"
    aoi = _load_aoi(data_dir, args.project_crs, args.padding_m)
    features = _query_stac(
        endpoint=args.stac_endpoint,
        collection=args.collection,
        bbox=aoi["bbox_wgs84"],
        datetime_range=args.datetime,
        cloud_cover_max=args.cloud_cover_max,
        limit=args.limit,
    )
    selected = _select_item_group(features, aoi["bbox_wgs84"])
    if args.dry_run:
        return {
            "status": "dry_run",
            "data_dir": str(data_dir),
            "aoi": aoi,
            "matched_items": len(features),
            "selected_date": selected["date"],
            "coverage_ratio_estimate": selected["coverage_ratio_estimate"],
            "avg_cloud_cover": selected["avg_cloud_cover"],
            "selected_items": [
                {
                    "id": item.get("id"),
                    "datetime": item.get("properties", {}).get("datetime", ""),
                    "cloud_cover": item.get("properties", {}).get("eo:cloud_cover"),
                    "grid": item.get("properties", {}).get("grid:code"),
                    "assets": sorted(item.get("assets", {}).keys()),
                }
                for item in selected["items"]
            ],
        }

    grid = _target_grid(aoi["bbox_projected"], args.resolution_m)
    asset_names = FULL_ASSETS if args.product_set == "full" else CORE_ASSETS
    arrays: dict[str, np.ndarray] = {}
    source_records: dict[str, list[dict[str, Any]]] = {}
    for asset_name in asset_names:
        arr, records = _read_asset_mosaic(
            selected["items"],
            asset_name,
            project_crs=args.project_crs,
            transform=grid["transform"],
            width=grid["width"],
            height=grid["height"],
            projected_bounds=aoi["bbox_projected"],
            resampling=Resampling.bilinear,
            reflectance=True,
            target_resolution_m=args.resolution_m,
        )
        arrays[asset_name] = arr
        source_records[asset_name] = records

    scl, scl_records = _read_asset_mosaic(
        selected["items"],
        "scl",
        project_crs=args.project_crs,
        transform=grid["transform"],
        width=grid["width"],
        height=grid["height"],
        projected_bounds=aoi["bbox_projected"],
        resampling=Resampling.nearest,
        reflectance=False,
        target_resolution_m=args.resolution_m,
    )
    source_records["scl"] = scl_records

    valid = np.ones((grid["height"], grid["width"]), dtype=bool)
    for name in ["blue", "green", "red", "nir"]:
        valid &= np.isfinite(arrays[name]) & (arrays[name] != NODATA_FLOAT)
    if not args.no_scl_mask and np.any(scl != NODATA_FLOAT):
        scl_uint = np.where(scl == NODATA_FLOAT, 0, np.round(scl).astype("uint8"))
        valid &= ~np.isin(scl_uint, list(SCL_CLOUD_CLASSES))

    ndvi = _safe_index(arrays["nir"] - arrays["red"], arrays["nir"] + arrays["red"], valid)
    rgb = _rgb_uint8(arrays["red"], arrays["green"], arrays["blue"], valid)

    out_dir.mkdir(parents=True, exist_ok=True)
    products: dict[str, Any] = {}

    stack_path = out_dir / "sentinel2_l2a_reflectance_stack.tif"
    stack_order = asset_names
    _write_raster(
        stack_path,
        [arrays[name] for name in stack_order],
        project_crs=args.project_crs,
        transform=grid["transform"],
        dtype="float32",
        nodata=NODATA_FLOAT,
        descriptions=[REFLECTANCE_ASSETS[name]["band_name"] for name in stack_order],
    )
    products["sentinel2_l2a_reflectance_stack"] = {
        "product_id": "REAL-S2-L2A-REFLECTANCE",
        "path": str(stack_path),
        "relative_path": str(stack_path.relative_to(data_dir)),
        "type": "reflectance_stack",
        "band_order": stack_order,
        "stats": {name: _stats(arrays[name]) for name in stack_order},
    }

    rgb_path = out_dir / "sentinel2_l2a_rgb.tif"
    _write_raster(
        rgb_path,
        [rgb[0], rgb[1], rgb[2]],
        project_crs=args.project_crs,
        transform=grid["transform"],
        dtype="uint8",
        nodata=0,
        descriptions=["red", "green", "blue"],
    )
    products["sentinel2_l2a_rgb"] = {
        "product_id": "REAL-S2-L2A-RGB",
        "path": str(rgb_path),
        "relative_path": str(rgb_path.relative_to(data_dir)),
        "type": "visual_rgb",
        "stats": {"red": _stats(rgb[0], 0), "green": _stats(rgb[1], 0), "blue": _stats(rgb[2], 0)},
    }

    index_specs = {
        "sentinel2_l2a_ndvi": ("REAL-S2-L2A-NDVI", ndvi, "NDVI=(NIR-Red)/(NIR+Red)"),
    }
    if args.product_set == "full":
        ndwi = _safe_index(arrays["green"] - arrays["nir"], arrays["green"] + arrays["nir"], valid)
        ndbi = _safe_index(arrays["swir16"] - arrays["nir"], arrays["swir16"] + arrays["nir"], valid)
        index_specs["sentinel2_l2a_ndwi"] = (
            "REAL-S2-L2A-NDWI",
            ndwi,
            "NDWI=(Green-NIR)/(Green+NIR)",
        )
        index_specs["sentinel2_l2a_ndbi"] = (
            "REAL-S2-L2A-NDBI",
            ndbi,
            "NDBI=(SWIR1-NIR)/(SWIR1+NIR)",
        )
    for name, (product_id, array, desc) in index_specs.items():
        path = out_dir / f"{name}.tif"
        _write_raster(
            path,
            [array],
            project_crs=args.project_crs,
            transform=grid["transform"],
            dtype="float32",
            nodata=NODATA_FLOAT,
            descriptions=[desc],
        )
        products[name] = {
            "product_id": product_id,
            "path": str(path),
            "relative_path": str(path.relative_to(data_dir)),
            "type": "spectral_index",
            "formula": desc,
            "stats": _stats(array),
        }

    scl_path = out_dir / "sentinel2_l2a_scl.tif"
    scl_out = np.where(scl == NODATA_FLOAT, 0, np.round(scl)).astype("uint8")
    _write_raster(
        scl_path,
        [scl_out],
        project_crs=args.project_crs,
        transform=grid["transform"],
        dtype="uint8",
        nodata=0,
        descriptions=["Sentinel-2 scene classification layer, resampled to target grid"],
    )
    products["sentinel2_l2a_scl"] = {
        "product_id": "REAL-S2-L2A-SCL",
        "path": str(scl_path),
        "relative_path": str(scl_path.relative_to(data_dir)),
        "type": "scene_classification",
        "stats": _stats(scl_out, 0),
        "masked_classes": sorted(SCL_CLOUD_CLASSES),
    }

    observed_date = selected["date"]
    manifest = {
        "dataset_id": data_dir.name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_type": "observed_remote_sensing",
        "synthetic": False,
        "not_for_production": False,
        "stac": {
            "endpoint": args.stac_endpoint,
            "collection": args.collection,
            "datetime": _normalise_datetime(args.datetime),
            "cloud_cover_max": args.cloud_cover_max,
            "matched_items": len(features),
            "selected_date": selected["date"],
            "coverage_ratio_estimate": selected["coverage_ratio_estimate"],
            "avg_cloud_cover": selected["avg_cloud_cover"],
            "selected_items": [
                {
                    "id": item.get("id"),
                    "datetime": item.get("properties", {}).get("datetime", ""),
                    "cloud_cover": item.get("properties", {}).get("eo:cloud_cover"),
                    "grid": item.get("properties", {}).get("grid:code"),
                    "bbox": item.get("bbox"),
                }
                for item in selected["items"]
            ],
        },
        "aoi": aoi,
        "target_grid": {
            "crs": args.project_crs,
            "resolution_m": args.resolution_m,
            "product_set": args.product_set,
            "width": grid["width"],
            "height": grid["height"],
            "transform": [round(float(v), 9) for v in tuple(grid["transform"])[:6]],
        },
        "masking": {
            "scl_mask_applied": not args.no_scl_mask,
            "scl_masked_classes": sorted(SCL_CLOUD_CLASSES),
        },
        "products": products,
        "sources": source_records,
        "synthetic_fallback": str(data_dir / "raster_manifest.json"),
        "known_limitations": [
            "Sentinel-2 10m imagery is useful for regional evidence and spectral indices, but not parcel-boundary-grade legal proof.",
            "SCL cloud/shadow masking is used as an engineering QA mask; manual visual review is still required for critical cases.",
        ],
    }
    manifest_path = data_dir / "real_imagery_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    if not args.no_update_evidence:
        _update_evidence_table(data_dir, products, observed_date)
        _update_dataset_manifest(data_dir, manifest_path, len(products))

    return {
        "status": "success",
        "data_dir": str(data_dir),
        "manifest": str(manifest_path),
        "selected_date": selected["date"],
        "coverage_ratio_estimate": selected["coverage_ratio_estimate"],
        "avg_cloud_cover": selected["avg_cloud_cover"],
        "products": {name: info["relative_path"] for name, info in products.items()},
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--stac-endpoint", default=DEFAULT_STAC_ENDPOINT)
    parser.add_argument("--collection", default=DEFAULT_COLLECTION)
    parser.add_argument("--datetime", default=DEFAULT_DATETIME)
    parser.add_argument("--cloud-cover-max", type=float, default=20.0)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--project-crs", default=DEFAULT_PROJECT_CRS)
    parser.add_argument("--resolution-m", type=float, default=20.0)
    parser.add_argument("--product-set", choices=["core", "full"], default="core")
    parser.add_argument("--padding-m", type=float, default=120.0)
    parser.add_argument("--no-scl-mask", action="store_true")
    parser.add_argument("--no-update-evidence", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--refresh-local", action="store_true",
                        help="Regenerate RGB/NDVI from an existing local reflectance stack without remote reads")
    return parser.parse_args()


def main() -> None:
    result = fetch_real_imagery(parse_args())
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()

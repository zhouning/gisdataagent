"""Read-only AAM L1/L2 native 1D/2D result viewer.

The native model files remain in the external delivery directory.  These
endpoints expose only authenticated metadata and a bounded GeoJSON preview so
the browser can inspect the result without downloading multi-gigabyte SWMM
OUT/SWW files into the map.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route

from .helpers import _get_user_from_request, _set_user_context


_AAM_DIR = Path(os.environ.get(
    "ABU_DHABI_AAM_RESULTS_DIR",
    "/Users/zhouning/Downloads/阿布扎比/AAM_L1_L2_100m_60mm1h_20261016",
))
_AAM_SCENARIOS = {
    "L1": ("L1", "L1 · 排水管网 + DTM", "只使用 AAM 行政区、排水管网和 5 m DTM"),
    "L2": ("L2", "L2 · 排水管网 + DTM + 1 个蓄水池", "在 L1 基础上加入 1 个蓄水池信息"),
}
_MAX_PREVIEW_FEATURES = 24000


def _authorized(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return None, JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    return user, None


def _scenario_dir(key: str) -> Path | None:
    entry = _AAM_SCENARIOS.get(str(key or "").upper())
    if not entry:
        return None
    root = _AAM_DIR / "results" / entry[0]
    return root if root.is_dir() else None


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _native_asset_url(key: str, name: str) -> str:
    return f"/api/abu-dhabi/flood/aam/assets/{quote(key, safe='')}/{quote(name, safe='')}"


def _map_overlays() -> dict:
    manifest = _read_json(_AAM_DIR / 'prepared' / 'map_assets' / 'manifest.json')
    if not manifest:
        return {}
    hotspot_geojson = _read_json(_AAM_DIR / 'prepared' / 'map_assets' / 'aam_hotspots.geojson')
    points = [
        feature['geometry']['coordinates']
        for feature in hotspot_geojson.get('features', [])
        if feature.get('geometry', {}).get('type') == 'Point'
    ]
    focus_center = [
        (min(point[1] for point in points) + max(point[1] for point in points)) / 2,
        (min(point[0] for point in points) + max(point[0] for point in points)) / 2,
    ] if points else None
    connection_gap = _read_json(_AAM_DIR / 'prepared' / 'map_assets' / 'aam_connection_gap.geojson')
    return {
        'pipelines': {
            **manifest.get('pipelines', {}),
            'download_url': '/api/abu-dhabi/flood/aam/pipelines',
        },
        'hotspots': {
            **manifest.get('hotspots', {}),
            'geojson_url': '/api/abu-dhabi/flood/aam/hotspots',
            'focus_center': focus_center,
        },
        **({'connection_gap': {
            **connection_gap.get('metadata', {}),
            'geojson_url': '/api/abu-dhabi/flood/aam/connection-gap',
        }} if connection_gap.get('features') else {}),
    }


@lru_cache(maxsize=1)
def _aam_grid_metadata() -> dict:
    try:
        import numpy as np

        with np.load(_AAM_DIR / "prepared" / "grid.npz", allow_pickle=True) as grid:
            x = np.asarray(grid["x"], dtype=float)
            y = np.asarray(grid["y"], dtype=float)
            mask = np.asarray(grid["land_mask"], dtype=bool)
        return {
            "crs": "EPSG:32640",
            "display_crs": "EPSG:4326",
            "grid_spacing_m": 100,
            "grid_columns": int(len(x) - 1),
            "grid_rows": int(len(y) - 1),
            "active_cells": int(mask.sum()),
            "bounds_native": [float(x.min()), float(y.min()), float(x.max()), float(y.max())],
        }
    except (OSError, KeyError, ValueError, ImportError):
        return {"crs": "EPSG:32640", "display_crs": "EPSG:4326", "grid_spacing_m": 100}


def _scenario_summary(key: str) -> dict:
    key = str(key or "").upper()
    entry = _AAM_SCENARIOS.get(key)
    root = _scenario_dir(key)
    if not entry or root is None:
        return {}
    receipt = _read_json(root / "run_receipt.json")
    config = _read_json(_AAM_DIR / "prepared" / "configuration.json")
    ready = receipt.get("status") in {"completed", "completed_quality_failed"}
    duration = float(receipt.get("duration_seconds", 0) or 0)
    step = float(receipt.get("output_seconds", 300) or 300)
    periods = int(round(duration / step)) + 1 if duration and step else 0
    result_fields = {
        k: receipt.get(k)
        for k in (
            "maximum_depth_m",
            "maximum_depth_envelope_area_ge_0_15m_km2",
            "maximum_velocity_mps",
            "rainfall_volume_m3",
            "surface_to_network_volume_m3",
            "network_to_surface_volume_m3",
            "network_final_volume_m3",
            "pond_final_volume_m3",
            "swmm_routing_error_percent",
            "network_residual_percent_of_captured_water",
            "swmm_nonconverging_steps_percent",
            "whole_system_residual_percent_of_rain",
        )
        if k in receipt
    }
    result = {
        "key": entry[0],
        "label": entry[1],
        "description": entry[2],
        "status": receipt.get("status", "missing"),
        "ready": ready,
        "solver": receipt.get("solver", "EPA SWMM 5.2.4 + ANUGA 2D"),
        "engineering_admitted": False,
        "quality_passed": bool(receipt.get("quality_passed", False)),
        "claim_boundary": receipt.get("interpretation", "uncalibrated diagnostic; not engineering-admitted"),
        "run_id": f"aam-{key.lower()}-100m-60mm-20261016",
        "domain": {
            "name": "AAM 全行政区",
            "crs": config.get("crs", "EPSG:32640"),
            "grid_spacing_m": receipt.get("grid_spacing_m", config.get("grid_spacing_m", 100)),
            "active_cells": receipt.get("active_cells", config.get("active_cells")),
            "triangle_count": receipt.get("triangle_count"),
            "native_node_count": receipt.get("native_node_count"),
        },
        "forcing": {
            "rainfall_total_mm": config.get("rainfall", {}).get("total_depth_mm", 60),
            "rainfall_duration_minutes": float(config.get("rainfall", {}).get("rain_duration_seconds", 3600)) / 60,
            "recession_minutes": float(config.get("rainfall", {}).get("recession_seconds", 14400)) / 60,
        },
        "results": result_fields,
        "quality_gates": {
            "quality_passed": bool(receipt.get("quality_passed", False)),
            "swmm_routing_error_percent": receipt.get("swmm_routing_error_percent"),
            "swmm_nonconverging_steps_percent": receipt.get("swmm_nonconverging_steps_percent"),
        },
        "manifest": {
            "available": ready and periods > 0,
            "period_count": periods,
            "elapsed_minutes": [i * step / 60 for i in range(periods)],
            "time_values": [f"{i * step / 60:.0f} min" for i in range(periods)],
            "endpoint": f"/api/abu-dhabi/flood/aam/{key}/frame",
        },
        "assets": {
            "maximum_depth": f"/api/abu-dhabi/flood/aam/{key}/maximum-depth",
            "native_1d_out": _native_asset_url(key, f"AAM_{key}_1D.out"),
            "native_1d_report": _native_asset_url(key, f"AAM_{key}_1D.rpt"),
            "native_2d_sww": _native_asset_url(key, f"AAM_{key}_2D.sww"),
            "native_input_inp": _native_asset_url(key, f"AAM_{key}_1D.inp"),
            "run_receipt": _native_asset_url(key, "run_receipt.json"),
        },
    }
    return result


def _sample_indices(values, *, threshold: float = 0.05, limit: int = _MAX_PREVIEW_FEATURES):
    """Keep a bounded, deterministic preview while preserving the deepest cells."""
    import numpy as np

    candidates = np.flatnonzero(np.asarray(values) >= threshold)
    if len(candidates) <= limit:
        return candidates
    top_count = limit // 2
    top = candidates[np.argpartition(np.asarray(values)[candidates], -top_count)[-top_count:]]
    stride = max(1, int(np.ceil(len(candidates) / (limit - top_count))))
    spread = candidates[::stride]
    return np.unique(np.concatenate([top, spread]))[:limit]


def _frame_geojson(key: str, time_index: int | None, *, maximum: bool = False) -> dict:
    import numpy as np
    from pyproj import Transformer

    root = _scenario_dir(key)
    if root is None:
        return {}
    cells_path = root / "cell_results.npz"
    with np.load(cells_path, allow_pickle=True) as cells:
        x = np.asarray(cells["x"], dtype=float)
        y = np.asarray(cells["y"], dtype=float)
        active = np.asarray(cells["active_cells"], dtype=np.int64)
        if maximum:
            values = np.asarray(cells["maximum_depth_m"], dtype=float)
            elapsed = None
        else:
            frames = np.load(root / "depth_frames.npy", mmap_mode="r")
            if time_index is None or time_index < 0 or time_index >= len(frames):
                raise IndexError
            values = np.asarray(frames[time_index], dtype=float)
            elapsed = int(time_index * 5)
    selected = _sample_indices(values)
    transform = Transformer.from_crs(32640, 4326, always_xy=True)
    columns = len(x) - 1
    features = []
    for local_index in selected:
        cell = int(active[int(local_index)])
        row, col = divmod(cell, columns)
        corners = [
            (x[col], y[row]),
            (x[col + 1], y[row]),
            (x[col + 1], y[row + 1]),
            (x[col], y[row + 1]),
            (x[col], y[row]),
        ]
        ring = [list(transform.transform(px, py)) for px, py in corners]
        property_name = "maximum_depth_m" if maximum else "depth_m"
        properties = {
            "cell_id": cell,
            property_name: float(values[int(local_index)]),
            "cell_size_m": 100,
        }
        if elapsed is not None:
            properties["time_minutes"] = elapsed
        features.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [ring]}, "properties": properties})
    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "scenario": key,
            "time_index": time_index,
            "time_minutes": elapsed,
            "preview_threshold_m": 0.05,
            "preview_feature_count": len(features),
            "native_active_cell_count": len(active),
            "preview_is_bounded": len(features) < int((values >= 0.05).sum()),
            "native_result": True,
            "note": "地图为受限 GeoJSON 预览；原生完整二维结果保留为 .sww。",
        },
    }


@lru_cache(maxsize=2)
def _maximum_depth_cached(key: str) -> dict:
    return _frame_geojson(key, None, maximum=True)


@lru_cache(maxsize=4)
def _boundary_geojson() -> dict:
    try:
        import geopandas as gpd

        path = _AAM_DIR / "prepared" / "aam_boundary.gpkg"
        frame = gpd.read_file(path).to_crs(4326)
        return json.loads(frame.to_json())
    except Exception:
        return {"type": "FeatureCollection", "features": []}


@lru_cache(maxsize=2)
def _pond_geojson() -> dict:
    try:
        import geopandas as gpd

        path = _AAM_DIR / "prepared" / "aam_pond.gpkg"
        frame = gpd.read_file(path).to_crs(4326)
        return json.loads(frame.to_json())
    except Exception:
        return {"type": "FeatureCollection", "features": []}


async def get_aam_scenarios(request: Request) -> JSONResponse:
    _, error = _authorized(request)
    if error:
        return error
    rows = [_scenario_summary(key) for key in _AAM_SCENARIOS]
    return JSONResponse({
        "schema": "gwm.abu_dhabi_flood.aam.native_l1_l2.v1",
        "domain": "AAM 全行政区",
        "resolution_m": 100,
        "scenarios": rows,
        "boundary": "/api/abu-dhabi/flood/aam/boundary",
        "pond": "/api/abu-dhabi/flood/aam/pond",
        "map_overlays": _map_overlays(),
        "comparison": {"same_surface_result": bool(rows and all(r.get("results", {}).get("maximum_depth_m") == rows[0].get("results", {}).get("maximum_depth_m") for r in rows))},
    }, headers={"Cache-Control": "no-store"})


async def get_aam_frame(request: Request) -> JSONResponse:
    _, error = _authorized(request)
    if error:
        return error
    key = str(request.path_params.get("scenario") or "").upper()
    summary = _scenario_summary(key)
    if not summary.get("ready"):
        return JSONResponse({"error": "scenario_not_complete"}, status_code=503)
    try:
        index = int(request.query_params.get("time_index", "0"))
        payload = _frame_geojson(key, index)
    except (ValueError, IndexError):
        return JSONResponse({"error": "time_index_out_of_range"}, status_code=416)
    return JSONResponse(payload, headers={"Cache-Control": "private, max-age=30"})


async def get_aam_maximum_depth(request: Request) -> JSONResponse:
    _, error = _authorized(request)
    if error:
        return error
    key = str(request.path_params.get("scenario") or "").upper()
    if not _scenario_summary(key).get("ready"):
        return JSONResponse({"error": "scenario_not_complete"}, status_code=503)
    try:
        payload = _maximum_depth_cached(key)
    except (OSError, KeyError, ValueError):
        return JSONResponse({"error": "maximum_depth_unreadable"}, status_code=503)
    return JSONResponse(payload, headers={"Cache-Control": "private, max-age=60"})


async def get_aam_boundary(request: Request) -> JSONResponse:
    _, error = _authorized(request)
    if error:
        return error
    return JSONResponse(_boundary_geojson(), headers={"Cache-Control": "private, max-age=3600"})


async def get_aam_pond(request: Request) -> JSONResponse:
    _, error = _authorized(request)
    if error:
        return error
    return JSONResponse(_pond_geojson(), headers={"Cache-Control": "private, max-age=3600"})


async def get_aam_hotspots(request: Request):
    _, error = _authorized(request)
    if error:
        return error
    path = _AAM_DIR / 'prepared' / 'map_assets' / 'aam_hotspots.geojson'
    if not path.is_file():
        return JSONResponse({'error': 'aam_hotspots_not_prepared'}, status_code=404)
    return FileResponse(path, media_type='application/geo+json', headers={'Cache-Control': 'private, max-age=3600'})


async def get_aam_pipelines(request: Request):
    _, error = _authorized(request)
    if error:
        return error
    path = _AAM_DIR / 'prepared' / 'map_assets' / 'aam_drainage.fgb'
    if not path.is_file():
        return JSONResponse({'error': 'aam_pipelines_not_prepared'}, status_code=404)
    return FileResponse(path, filename=path.name, media_type='application/flatgeobuf', headers={'Cache-Control': 'private, max-age=3600'})


async def get_aam_connection_gap(request: Request):
    _, error = _authorized(request)
    if error:
        return error
    path = _AAM_DIR / 'prepared' / 'map_assets' / 'aam_connection_gap.geojson'
    if not path.is_file():
        return JSONResponse({'error': 'aam_connection_gap_not_prepared'}, status_code=404)
    return FileResponse(path, media_type='application/geo+json', headers={'Cache-Control': 'private, no-cache'})


async def get_aam_asset(request: Request):
    _, error = _authorized(request)
    if error:
        return error
    key = str(request.path_params.get("scenario") or "").upper()
    name = Path(str(request.path_params.get("name") or "")).name
    root = _scenario_dir(key)
    allowed = {f"AAM_{key}_1D.out", f"AAM_{key}_1D.rpt", f"AAM_{key}_1D.inp", f"AAM_{key}_2D.sww", "run_receipt.json"}
    if root is None or name not in allowed:
        return JSONResponse({"error": "asset_not_found"}, status_code=404)
    path = root / name
    if not path.is_file():
        return JSONResponse({"error": "asset_not_found"}, status_code=404)
    return FileResponse(path, filename=name, headers={"Cache-Control": "private, max-age=300"})


def get_aam_routes() -> list[Route]:
    return [
        Route("/api/abu-dhabi/flood/aam/scenarios", endpoint=get_aam_scenarios, methods=["GET"]),
        Route("/api/abu-dhabi/flood/aam/boundary", endpoint=get_aam_boundary, methods=["GET"]),
        Route("/api/abu-dhabi/flood/aam/pond", endpoint=get_aam_pond, methods=["GET"]),
        Route("/api/abu-dhabi/flood/aam/hotspots", endpoint=get_aam_hotspots, methods=["GET"]),
        Route("/api/abu-dhabi/flood/aam/pipelines", endpoint=get_aam_pipelines, methods=["GET"]),
        Route("/api/abu-dhabi/flood/aam/connection-gap", endpoint=get_aam_connection_gap, methods=["GET"]),
        Route("/api/abu-dhabi/flood/aam/{scenario}/frame", endpoint=get_aam_frame, methods=["GET"]),
        Route("/api/abu-dhabi/flood/aam/{scenario}/maximum-depth", endpoint=get_aam_maximum_depth, methods=["GET"]),
        Route("/api/abu-dhabi/flood/aam/assets/{scenario}/{name}", endpoint=get_aam_asset, methods=["GET"]),
    ]

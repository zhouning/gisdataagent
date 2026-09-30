"""Read-only Mussafah_00 L1/L2/L2+ gap review workspace.

The underlying delivery is deliberately exposed as a review package.  It is
not presented as an admitted engineering result: the source package carries
``engineering_admitted=false`` and the page keeps that status visible.
"""

from __future__ import annotations

import csv
import io
import json
import mimetypes
import os
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote, urlencode

from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, Response
from starlette.routing import Route

from .helpers import _get_user_from_request, _set_user_context


_DELIVERY_DIR = Path(
    "/Users/zhouning/Downloads/阿布扎比/flood/解决方案_20260924/下一阶段推进_20260925/"
    "Mussafah00_Gap优化交付_20260926"
)
_OLD_5M_DIR = Path(
    "/Users/zhouning/Downloads/阿布扎比/flood/解决方案_20260924/局部试点_20260925/"
    "Mussafah_00_three_defense_lines_5m"
)
_FORMAL_DIR = Path(
    "/Users/zhouning/Downloads/阿布扎比/flood/解决方案_20260924/下一阶段推进_20260925/"
    "正式场景编译_20260926"
)
_REAL_COUPLED_DIR = Path("/Users/zhouning/.tmp/mussafah00_coupled/real_runs")
# Deployment data remains external to Git. Preserve the installed defaults
# while allowing another checkout to mount the same result packages.
_DELIVERY_DIR = Path(os.environ.get("ABU_DHABI_MUSSAFAH_DELIVERY_DIR", str(_DELIVERY_DIR)))
_OLD_5M_DIR = Path(os.environ.get("ABU_DHABI_MUSSAFAH_OLD_5M_DIR", str(_OLD_5M_DIR)))
_FORMAL_DIR = Path(os.environ.get("ABU_DHABI_MUSSAFAH_FORMAL_DIR", str(_FORMAL_DIR)))
_REAL_COUPLED_DIR = Path(os.environ.get("ABU_DHABI_MUSSAFAH_REAL_COUPLED_DIR", str(_REAL_COUPLED_DIR)))
_TERRAIN_ASSET_DIR = Path(__file__).resolve().parents[1] / "static/abu_dhabi_flood/mussafah00_terrain"
_TERRAIN_GRID = Path(os.environ.get("ABU_DHABI_MUSSAFAH_TERRAIN_GRID", str(_TERRAIN_ASSET_DIR / "mussafah00_5m_grid.npz")))
_TERRAIN_IMAGE = _TERRAIN_ASSET_DIR / "mussafah00_5m_terrain_rgb.png"
_TERRAIN_META = _TERRAIN_ASSET_DIR / "mussafah00_5m_terrain.json"
_CATCHMENT_ASSET_DIR = Path(__file__).resolve().parents[1] / "static/abu_dhabi_flood/mussafah00_catchment"
_MUSSAFAH00_CATCHMENT_BOUNDARY = _CATCHMENT_ASSET_DIR / "Mussafah00_formal_boundary_20260927_wgs84.geojson"
_MUSSAFAH00_CATCHMENT_BOUNDARY_SOURCE = _CATCHMENT_ASSET_DIR / "Mussafah00_formal_boundary_20260927.geojson"
_REAL_SCENARIOS = {
    "L1": ("L1", "L1 · 既有永久基础设施", "MUSSAFAH_SOURCE_MODEL_L1_PROXY"),
    "L2": ("L2", "L2 · 当前已有中间 / 临时措施", "MUSSAFAH_SOURCE_MODEL_L2_PROXY"),
    "PARSONS": ("PARSONS", "L2+（A）· Parsons PO-2", "MUSSAFAH_L2PLUS_A_PARSONS_REPORT_PO2"),
    "L2AB": ("L2AB", "L2+（A+B）· Parsons + 六座地下箱涵", "five_state/L2plusAplusB"),
    "L2B6": ("L2B6", "L2+（B）· 六座地下箱涵", "five_state/L2plusB"),
    "B1": ("B1", "L2+（B1）· 自主方案：150 mm 出水管", "B1"),
    "B2": ("B2", "L2+（B2）· 自主方案：300 mm 出水管", "B2"),
}

_REAL_COMPARISON_BASIS = {
    "L1": "参考状态",
    "L2": "L1 → L2：现状 L2 措施增量",
    "PARSONS": "L2 → Parsons：Parsons PO-2 增量",
    "L2AB": "Parsons → Parsons + 六座地下箱涵：箱涵增量",
    "L2B6": "L2 → 六座地下箱涵：自主箱涵增量",
    "B1": "L2 → 自主塘 B1：150 mm 出水管",
    "B2": "L2 → 自主塘 B2：300 mm 出水管",
}
_DELIVERY_PREFIX = "delivery"
_OLD_5M_PREFIX = "old5m"
_FORMAL_PREFIX = "formal"
_ALLOWED_SUFFIXES = {
    ".asc",
    ".csv",
    ".docx",
    ".geojson",
    ".inp",
    ".json",
    ".md",
    ".npy",
    ".npz",
    ".out",
    ".png",
    ".rpt",
    ".tif",
    ".sww",
}
_MAX_ASSET_BYTES = 50 * 1024 * 1024


def _authorized(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return None, JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    return user, None


def _safe_relative_path(value: str) -> Path | None:
    """Return a normalised relative path, rejecting traversal and empty paths."""

    candidate = Path(value)
    if not value or candidate.is_absolute() or ".." in candidate.parts:
        return None
    if any(part in ("", ".") for part in candidate.parts):
        return None
    return candidate


def _asset_path(asset_name: str) -> Path | None:
    """Resolve an allow-listed asset name to one of the two read-only roots."""

    relative = _safe_relative_path(asset_name)
    if relative is None or not relative.parts:
        return None
    prefix = relative.parts[0]
    rest = Path(*relative.parts[1:])
    if not rest or rest.suffix.lower() not in _ALLOWED_SUFFIXES:
        return None
    if prefix == _DELIVERY_PREFIX:
        root = _DELIVERY_DIR
    elif prefix == _OLD_5M_PREFIX:
        root = _OLD_5M_DIR
    elif prefix == _FORMAL_PREFIX:
        root = _FORMAL_DIR
    elif prefix == "catchment":
        root = _CATCHMENT_ASSET_DIR
    elif prefix == "real2d":
        root = _REAL_COUPLED_DIR
    else:
        return None
    resolved = (root / rest).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        return None
    size_limit = 8 * 1024**3 if resolved.suffix in {".sww", ".out"} else _MAX_ASSET_BYTES
    if not resolved.is_file() or resolved.stat().st_size > size_limit:
        return None
    return resolved


def _asset_url(prefix: str, path: Path) -> str:
    root = (
        _DELIVERY_DIR
        if prefix == _DELIVERY_PREFIX
        else _OLD_5M_DIR
        if prefix == _OLD_5M_PREFIX
        else _FORMAL_DIR
        if prefix == _FORMAL_PREFIX
        else _CATCHMENT_ASSET_DIR
        if prefix == "catchment"
        else _REAL_COUPLED_DIR
    )
    relative = path.resolve().relative_to(root.resolve()).as_posix()
    return "/api/abu-dhabi/flood/mussafah00-gap/assets/" + quote(
        f"{prefix}/{relative}", safe="/"
    )


def _terrain_metadata() -> dict:
    if not _TERRAIN_META.is_file():
        return {}
    try:
        value = json.loads(_TERRAIN_META.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


@lru_cache(maxsize=1)
def _terrain_grid_arrays():
    """Load the real 5 m model grid once for the internal terrain service."""
    if not _TERRAIN_GRID.is_file():
        return None
    try:
        import numpy as np

        grid = np.load(_TERRAIN_GRID)
        x = np.asarray(grid["x"], dtype=float)
        y = np.asarray(grid["y"], dtype=float)
        values = np.asarray(grid["values"], dtype=float)
        x_order = np.argsort(x)
        y_order = np.argsort(y)
        return x[x_order], y[y_order], values[np.ix_(y_order, x_order)]
    except (OSError, KeyError, ValueError, ImportError):
        return None


def _terrain_export_url() -> str | None:
    metadata = _terrain_metadata()
    bounds = metadata.get("bounds")
    width = metadata.get("width")
    height = metadata.get("height")
    if not isinstance(bounds, list) or len(bounds) != 4 or not width or not height:
        return None
    query = urlencode({
        "source": "customer_dtm_5m",
        "bbox": ",".join(str(float(value)) for value in bounds),
        "width": int(width),
        "height": int(height),
    })
    return f"/api/abu-dhabi/flood/mussafah00-gap/terrain/export?{query}"


def _terrain_tile_url() -> str:
    return "/api/abu-dhabi/flood/mussafah00-gap/terrain/tiles/{z}/{x}/{y}.png"


def _terrain_service_metadata() -> dict:
    metadata = _terrain_metadata()
    export_url = _terrain_export_url()
    bounds = metadata.get("bounds")
    return {
        "schema": "gwm.abu_dhabi_flood.terrain_service.v1",
        "service_type": "terrain-rgb-tile-service",
        "provider": "customer_dtm_5m",
        "source": "Mussafah_00 coupled model grid / L2B6 preparation",
        "crs": metadata.get("crs", "EPSG:4326"),
        "vertical_reference": "model DTM vertical reference; source datum not supplied in the delivery package",
        "bounds": bounds,
        "resolution_m": metadata.get("resolution_m"),
        "elevation_min_m": metadata.get("elevation_min_m"),
        "elevation_max_m": metadata.get("elevation_max_m"),
        "elevation_decoder": metadata.get("elevation_decoder"),
        "width": metadata.get("width"),
        "height": metadata.get("height"),
        "tile_size": 256,
        "min_zoom": 10,
        "max_zoom": 17,
        "engineering_admitted": False,
        "image_url": _terrain_export_url() if _TERRAIN_IMAGE.is_file() else None,
        "export_url": export_url,
        "tile_url": _terrain_tile_url(),
        "sources": [
            {
                "id": "customer_dtm_5m",
                "label": "客户 5 m DTM（模型实际输入）",
                "status": "active",
                "service": _terrain_tile_url(),
                "vertical_reference": "model DTM vertical reference; datum confirmation pending",
            },
            {
                "id": "arcgis_world_elevation_3d",
                "label": "ArcGIS WorldElevation3D Terrain（公开回退）",
                "status": "registered_fallback",
                "service": "https://elevation3d.arcgis.com/arcgis/rest/services/WorldElevation3D/Terrain3D/ImageServer",
                "crs": "EPSG:3857",
                "vertical_reference": "orthometric metres",
                "note": "公开 ArcGIS 服务可作为背景/回退；不能替代客户 5 m DTM 的水动力输入。",
            },
        ],
    }


def _encode_terrain_rgb(values):
    """Encode metres as Terrain-RGB-compatible 24-bit centimetre values."""
    import numpy as np

    metadata = _terrain_metadata()
    offset = float(metadata.get("elevation_decoder", {}).get("offset", 0.0))
    encoded = np.rint((values - offset) / 0.01).clip(0, 16_777_215).astype(np.uint32)
    return np.stack([(encoded >> 16) & 255, (encoded >> 8) & 255, encoded & 255], axis=-1).astype(np.uint8)


def _render_terrain_export(bbox: list[float], width: int, height: int) -> bytes | None:
    arrays = _terrain_grid_arrays()
    if arrays is None:
        return None
    try:
        import numpy as np
        from PIL import Image
        from pyproj import Transformer

        x, y, values = arrays
        transform = Transformer.from_crs("EPSG:4326", "EPSG:32640", always_xy=True)
        west, south, east, north = bbox
        x0, y0 = transform.transform(west, south)
        x1, y1 = transform.transform(east, north)
        lo_x, hi_x = sorted((x0, x1))
        lo_y, hi_y = sorted((y0, y1))
        if hi_x < float(x[0]) or lo_x > float(x[-1]) or hi_y < float(y[0]) or lo_y > float(y[-1]):
            return None
        sample_x = np.linspace(lo_x, hi_x, width)
        # Image row 0 is north; the source grid rows are south -> north.
        sample_y = np.linspace(hi_y, lo_y, height)
        xi = np.clip(np.searchsorted(x, sample_x, side="left"), 0, len(x) - 1)
        yi = np.clip(np.searchsorted(y, sample_y, side="left"), 0, len(y) - 1)
        raster = values[np.ix_(yi, xi)]
        image = Image.fromarray(_encode_terrain_rgb(raster), mode="RGB")
        output = io.BytesIO()
        image.save(output, format="PNG", optimize=True)
        return output.getvalue()
    except (ImportError, OSError, ValueError):
        return None


def _xyz_tile_bbox(z: int, x: int, y: int) -> list[float]:
    import math

    n = 2 ** z
    west = x / n * 360.0 - 180.0
    east = (x + 1) / n * 360.0 - 180.0
    north = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * y / n))))
    south = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * (y + 1) / n))))
    return [west, south, east, north]


@lru_cache(maxsize=256)
def _render_terrain_tile(z: int, x: int, y: int) -> bytes | None:
    return _render_terrain_export(_xyz_tile_bbox(z, x, y), 256, 256)


def _asset_catalog() -> list[dict]:
    """Build a small, deterministic catalogue from the two delivered roots."""

    items: list[dict] = []
    roots = ((_DELIVERY_PREFIX, _DELIVERY_DIR), (_OLD_5M_PREFIX, _OLD_5M_DIR), (_FORMAL_PREFIX, _FORMAL_DIR), ("real2d", _REAL_COUPLED_DIR))
    for prefix, root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in _ALLOWED_SUFFIXES:
                continue
            try:
                size = path.stat().st_size
                path.relative_to(root)
            except OSError:
                continue
            if size > _MAX_ASSET_BYTES:
                continue
            relative = path.relative_to(root).as_posix()
            label = relative
            if prefix == _DELIVERY_PREFIX:
                label = f"交付包 / {relative}"
            elif prefix == _OLD_5M_PREFIX:
                label = f"旧版 5 m 试点 / {relative}"
            elif prefix == _FORMAL_PREFIX:
                label = f"实际 SWMM 场景 / {relative}"
            else:
                label = f"真实 SWMM–ANUGA 二维耦合 / {relative}"
            items.append(
                {
                    "asset": f"{prefix}/{relative}",
                    "label": label,
                    "size_bytes": size,
                    "suffix": path.suffix.lower(),
                    "url": _asset_url(prefix, path),
                }
            )
    return items


def _read_gap_rows() -> list[dict]:
    path = _DELIVERY_DIR / "Mussafah00_gap_matrix_20260927.csv"
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _read_json(name: str) -> dict:
    path = _DELIVERY_DIR / name
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _read_old5m_json(name: str) -> dict:
    path = _OLD_5M_DIR / name
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _idealized_5m_result() -> dict:
    """Expose the completed local 5 m four-state run as a review result.

    The source receipt contains four raw pilot runs.  The page maps those runs
    to the business states explicitly: L1 and current L2 both use the
    no-current-pond baseline, while Parsons and the locally designed pond use
    their respective completed 5 m runs.
    """
    raw = _read_old5m_json("defense_line_comparison.json")
    if not raw.get("states"):
        return {"status": "not_available", "engineering_admitted": False, "states": [], "candidates": {}}
    mapping = [
        ("L1", "L1 · 既有永久基础设施", "S0_L1_existing", "L1 基线；SWMM 溢流源项进入局部 5 m 二维路由"),
        ("L2", "L2 · 当前已有中间 / 临时措施", "S0_L1_existing", "现状 pond=0；因此采用同一 L1 基线，不把规划塘误当现状塘"),
        ("L2PLUS_A", "L2+（A）· Parsons PO-2", "S2_parsons_PO2", "复现 Parsons PO-2 / STO-PO3 候选塘的局部 5 m 二维地表试验"),
        ("L2PLUS_B", "L2+（B）· 自主 OPT-01", "S2_optimized_local", "自主倒金字塔候选塘 OPT-01 的局部 5 m 二维地表试验"),
    ]
    states = []
    for key, label, source_id, interpretation in mapping:
        source = raw.get("states", {}).get(source_id) or {}
        outputs = source.get("outputs") or {}
        hotspot_depths = source.get("hotspot_depths") or {}
        raster = outputs.get("maximum_depth_raster")
        raster_path = Path(raster) if raster else None
        state = {
            "key": key,
            "label": label,
            "source_scenario": source_id,
            "defense_line": "L1" if key == "L1" else "L2" if key == "L2" else "L2+",
            "interpretation": interpretation,
            "status": source.get("status", "completed_idealized_5m_surface_routing"),
            "engineering_admitted": False,
            "solver": source.get("solver", "ANUGA 2D shallow-water surface routing"),
            "mesh": source.get("mesh", {}),
            "forcing": source.get("forcing", {}),
            "outputs": {
                "maximum_depth_m": outputs.get("maximum_depth_m"),
                "maximum_inundated_area_m2": outputs.get("maximum_inundated_area_m2"),
                "area_ge_0_15m_m2": outputs.get("area_ge_0_15m_m2"),
                "area_ge_0_30m_m2": outputs.get("area_ge_0_30m_m2"),
                "area_ge_0_50m_m2": outputs.get("area_ge_0_50m_m2"),
                "maximum_surface_water_volume_m3": outputs.get("maximum_surface_water_volume_m3"),
                "maximum_surface_water_volume_time_hours": outputs.get("maximum_surface_water_volume_time_hours"),
            },
            "hotspot_depths": hotspot_depths,
            "raster_url": _asset_url(_OLD_5M_PREFIX, raster_path) if raster_path and raster_path.is_file() else None,
        }
        states.append(state)
    candidates = raw.get("candidates") or {}
    return {
        "status": raw.get("status", "completed_idealized_5m_surface_routing"),
        "engineering_admitted": False,
        "resolution_m": raw.get("resolution_m", 5.0),
        "domain": raw.get("domain", {}),
        "states": states,
        "candidates": candidates,
        "comparison_rows": raw.get("comparison_rows", []),
        "interpretation": raw.get("interpretation", ""),
        "baseline_revision": raw.get("baseline_revision", ""),
        "data_conflicts": raw.get("data_conflicts", []),
        "report_url": _asset_url(_OLD_5M_PREFIX, _OLD_5M_DIR / "Mussafah_00_四状态防线对比试点报告.md"),
    }


def _actual_swmm_result() -> dict:
    """Use exactly the audited comparison exposed by the browser workspace."""
    path = _FORMAL_DIR / "actual_review_v2" / "comparison.json"
    if not path.is_file():
        return {"status": "actual_results_not_available", "states": []}
    result = json.loads(path.read_text(encoding="utf-8"))
    states = []
    for source in result["states"]:
        state = dict(source)
        state["assets"] = {
            f"{suffix}_url": _asset_url(_FORMAL_PREFIX, _FORMAL_DIR / source["source_dir"] / f"Mussafah_00.{suffix}")
            for suffix in ("inp", "rpt", "out")
        }
        states.append(state)
    return {
        "status": result["status"], "solver": result["solver"],
        "engineering_admitted": False, "states": states,
        "autonomous_candidate": result["candidate"],
        "autonomous_state": next(s for s in states if s["key"] == "B1"),
        "comparison_rule": "Same external inflow, boundaries, 48 h time window and solver settings; verified input hash.",
        "quality_note": "Nonconverging steps exceed the 1% diagnostic threshold. Not an engineering-admitted result.",
    }


def _bootstrap_payload() -> dict:
    preflight = _read_json("Mussafah00_coupling_preflight_20260927.json")
    pond_audit = _read_json("Mussafah00_pond_source_audit_20260927.json")
    synthetic = _read_json("Mussafah00_synthetic_coupling_test_20260927.json")
    return {
        "schema": "gwm.abu_dhabi_flood.mussafah00_gap_workspace.v1",
        "title": "Mussafah_00 L1 / L2 / L2+ Gap 分析工作台",
        "updated": "2026-09-27",
        "status": "actual_swmm_1d_completed_2d_pending",
        "engineering_admitted": False,
        "notice": "主结果已替换为真实 EPA SWMM 5.2.4 一维运行；二维双向交换和工程准入仍单独标注为待完成。",
        "boundary": {
            "label": "Mussafah_00",
            "database_id": 40,
            "crs": "EPSG:32640",
            "geometry_area_ha": 147.83849835069304,
            "attribute_area_ha": 148.76,
            "difference_ha": 0.92150164930696,
            "geojson_url": _asset_url(
                _DELIVERY_PREFIX,
                _DELIVERY_DIR / "Mussafah00_formal_boundary_20260927.geojson",
            ),
        },
        "state_definitions": [
            {
                "key": "L1",
                "label": "L1",
                "name": "既有永久基础设施",
                "definition": "Existing permanent stormwater assets and infrastructure",
                "current": "L1 proxy：一维诊断可用，工程准入未通过",
            },
            {
                "key": "L2",
                "label": "L2",
                "name": "中间 / 临时措施",
                "definition": "Temporary or intermediate mitigation measures prepared pre-event",
                "current": "正式边界内 stormwater_drainage.pond=0，待客户冻结",
            },
            {
                "key": "L2PLUS_A",
                "label": "L2+（A）",
                "name": "Parsons 规划方案",
                "definition": "Parsons planned pond and associated PMP5/W-4 connection",
                "current": "STO-PO3 / PMP5 链的一维增量诊断",
            },
            {
                "key": "L2PLUS_B",
                "label": "L2+（B）",
                "name": "自主规划方案",
                "definition": "System-generated legal candidate pond and connection alternatives",
                "current": "已完成真实 Makani 地块 167073 的实际 SWMM 一维场景；二维交换和成本准入仍未完成",
            },
        ],
        "scenario_cards": [
            {
                "key": "L1",
                "title": "L1 · 既有永久基础设施基线",
                "role": "Existing / Permanent Infrastructure",
                "objects": ["既有雨水管网", "永久出水口", "客户确认后的永久泵站"],
                "mechanism": "雨水通过既有管线、节点、泵站和出水口排放，不新增调蓄塘。",
                "why": "作为所有方案的共同基线，回答‘不增加规划措施时会发生什么’。",
                "evidence": "L1 proxy 一维诊断；永久泵的 as-built、运行和 H-Q 仍需客户确认。",
                "status": "diagnostic_baseline",
            },
            {
                "key": "L2",
                "title": "L2 · 当前已有中间 / 临时措施",
                "role": "Intermediate / Temporary Measures",
                "objects": ["正式边界内 stormwater_drainage.pond = 0 条"],
                "mechanism": "当前没有已冻结的 Mussafah_00 现状 pond 可加入模型；其他 L2 类型暂因缺少权威数据未纳入。",
                "why": "避免把规划模型对象误当成现状资产，保证 L1→L2 的差异可解释。",
                "evidence": "正式 Mussafah_00 多边形与 stormwater_drainage.pond 空间相交查询；客户冻结仍待完成。",
                "status": "provisional_zero_ponds",
            },
            {
                "key": "L2PLUS_A",
                "title": "L2+（A）· Parsons PO-2 / STO-PO3 方案",
                "role": "Parsons planned pond and associated pump connection",
                "objects": ["STO-PO3（Parsons 报告 PO-2）", "PMP5", "W-4 湿井", "管线 1235", "PMP5_Junction"],
                "mechanism": "W-4 通过 PMP5 抽送至 PMP5_Junction，再经管线 1235 进入 STO-PO3；STO-PO3 作为一维 Storage 拥有库容。模型控制为水深达到约 1.4 m 时停泵，低于该值时启泵。",
                "why": "这是 Mussafah_00 当前能够从 Parsons 报告和模型包中对应出来的最小规划闭环，用于先验证‘规划塘 + 泵 + 管线’的增量效果。",
                "evidence": "Mussafah_00.inp、Parsons Mussafah 报告、pond topology audit；STO-PO3 仍缺批准 stage-area-volume 曲线、二维入水/溢流和泵 H-Q。",
                "status": "one_dimensional_diagnostic_only",
            },
            {
                "key": "L2PLUS_B",
                "title": "L2+（B）· 自主候选塘与连接组合",
                "role": "System-generated legal candidate ponds and connection alternatives",
                "objects": ["合法可用地块候选塘", "重力沟渠 / 管线", "固定或应急泵", "溢流与排空设施"],
                "mechanism": "先按土地利用、道路、建筑、地下管线、地形、距热点和汇水路径筛选地块，再生成 3:1 边坡、深度、库容和连接组合，最后用一二维耦合模型和成本函数排序。",
                "why": "用于回答‘在哪里新建塘，才能以最低全寿命成本获得最大减灾效果’；它不是把一个任意低洼地直接挖深。",
                "evidence": "Makani udm_plot 167073、建筑/道路空间核查、utility overlap=0、实际 SWMM 场景回执；土地许可、二维交换和成本仍未冻结。",
                "status": "actual_swmm_1d_completed_2d_pending",
            },
        ],
        "scenario_logic": {
            "comparison_rule": "所有状态使用同一评价边界、同一降雨/尾水/初始状态和同一指标；只改变已登记的措施对象。",
            "dtm_rule": "L1 和 Parsons 当前一维 Storage 方案不把同一库容重复刻入 DTM；只有确认采用二维地形洼地或混合 1D–2D 方案时才修改 DTM，并由唯一水量所有者负责库容。",
            "engineering_gate": "真实双向交换、批准塘体曲线、泵 H-Q/控制、土地和地下管线约束完成前，只发布诊断结果，不发布正式工程收益或成本排名。",
        },
        "implementation_matrix": [
            {
                "state": "L1",
                "engineering_level": "既有永久设施",
                "object_set": "既有雨水管网、永久出水口、已确认永久泵站",
                "one_d_representation": "SWMM 节点 / 管段 / 泵 / 出水口",
                "two_d_representation": "客户 5 m DTM 的地表径流诊断；不新增塘体洼地",
                "dtm_action": "不修改 DTM",
                "water_owner": "既有管网节点和出水边界",
                "current_result": "L1 proxy：一维诊断可运行",
            },
            {
                "state": "L2",
                "engineering_level": "现状中间 / 临时措施",
                "object_set": "正式 Mussafah_00 内已冻结的 pond；当前查询为 0 条",
                "one_d_representation": "若 pond 已接入：Storage / inlet / outlet / pump；当前没有可加入的 pond 对象",
                "two_d_representation": "只有明确作为地表洼地运行时才进入 2D；当前未准入",
                "dtm_action": "保持不变，避免把规划塘误算成现状资产",
                "water_owner": "当前仍由 L1 管网系统负责",
                "current_result": "L2 proxy 暂按 L1；等待客户冻结现状 L2 清单",
            },
            {
                "state": "L2+（A）",
                "engineering_level": "Parsons 规划增量",
                "object_set": "STO-PO3（PO-2）、W-4、PMP5、PMP5_Junction、管线 1235",
                "one_d_representation": "W-4 → PMP5 → Junction → conduit 1235 → STO-PO3 Storage",
                "two_d_representation": "当前没有正式二维入水、溢流或回流交换",
                "dtm_action": "当前不修改 DTM；STO-PO3 是一维 Storage 的唯一库容所有者",
                "water_owner": "STO-PO3 Storage（规划库容）",
                "current_result": "一维诊断：节点溢流 4,233→3,446 m³；不能解释为正式二维积水收益",
            },
            {
                "state": "L2+（B）",
                "engineering_level": "自主候选塘规划",
                "object_set": "合法地块 + 倒金字塔塘体 + 入水设施 + 排空 / 溢流 + 必要时泵站",
                "one_d_representation": "按连接方式选择 Storage、Orifice / Weir、Conduit、Pump",
                "two_d_representation": "推荐混合 1D–2D：地表水经 inlet 进入塘体，超标经 spillway 回到安全路径",
                "dtm_action": "只有批准采用二维开挖洼地时才刻入 DTM；不能与 Storage 重复计容",
                "water_owner": "明确指定为 1D Storage 或 2D 洼地中的一个，不能重复拥有库容",
                "current_result": "实际 SWMM 已完成：167073 地块；二维交换和成本排名待完成",
            },
        ],
        "l2plus_design": {
            "parsons": {
                "name": "L2+（A）· Parsons PO-2 / STO-PO3 泵送调蓄闭环",
                "type": "混合设施方案：当前按 1D Storage + 1D 泵 / 管线诊断，后续才接入 2D 地表交换",
                "hydraulic_chain": ["W-4 湿井", "PMP5", "PMP5_Junction", "管线 1235", "STO-PO3"],
                "flow_path": "W-4 → PMP5 → PMP5_Junction → 管线 1235 → STO-PO3",
                "control_logic": "STO-PO3 水深达到约 1.4 m 时停止 PMP5，低于该阈值时启动；正式泵 H-Q 和控制曲线尚未批准。",
                "dtm_and_exchange": "当前不修改 DTM，不把同一库容重复刻入 2D；缺少真实地表入水口、溢流口和双向交换定律。",
                "why": "这是现有 Parsons 文件和 Mussafah_00 模型包中能够逐对象对应的最小闭环，连接关系可追溯，适合先验证增量逻辑。",
                "limitations": ["STO-PO3 的 900 / 1120.1 / 1200 / 2380 m³ 来源值冲突", "没有批准 stage-area-volume 曲线", "模型泵当前缺少批准 H-Q，不能发布正式工程收益"],
            },
            "autonomous": {
                "name": "L2+（B）· 重力优先、泵送兜底的合法地块候选塘",
                "type": "推荐的自主方案模板：倒金字塔塘体 + 重力入水优先 + 泵站兜底 + 安全溢流 / 排空",
                "geometry": "实际场景采用 Makani 167073 地块：深度 1.0 m、塘顶面积 2,500 m²、边坡 3H:1V；按 21 点 stage-area 曲线计算容积 2,212.015 m³。",
                "candidate_variants": [
                    {
                        "id": "B1",
                        "name": "重力直入塘",
                        "when": "地块高程高于汇水路径且重力水头足够",
                        "model": "2D 地表入水 + 1D Storage / spillway；不设置常态泵",
                        "priority": "优先，运行成本和故障点最低",
                    },
                    {
                        "id": "B2",
                        "name": "泵送入塘",
                        "when": "地势平坦、逆坡或重力管线过长，重力无法保证入塘",
                        "model": "1D Storage + Pump + Conduit；必要时接 2D inlet / overflow",
                        "priority": "次选，需比较泵 CAPEX、OPEX 和可靠性",
                    },
                    {
                        "id": "B3",
                        "name": "串联分散塘",
                        "when": "单一地块无法覆盖多个积水路径或单塘风险集中",
                        "model": "多个 Storage / 2D 洼地通过受控管渠串联，设置分级溢流",
                        "priority": "用于土地受限或需要分散风险的情形",
                    },
                ],
                "screening_constraints": ["排除高速公路、道路主体、建筑物、居民用地和已知地下管线冲突区", "保留安全退界、施工可达性、土地权属和许可可行性", "以历史积水点、汇水区、地形低点和入水距离作为效果候选排序因素", "连接必须校核管径、坡度、泵扬程、溢流路径和尾水边界"],
                "objective": "在满足安全、土地、连接和容量约束的前提下，最大化历史积水风险下降与调蓄体积收益，并最小化土方、管渠、泵站、用地和运维的全寿命成本；最终以 Pareto 前沿供领导选择。",
                "why": "该方案把‘在哪里挖塘’与‘水如何进去、如何排空、超标后往哪里走’作为一个整体优化，避免只按距离选地块而得到无法发挥作用的孤立水坑。",
                "status": "地块 167073 两个修正方案 B1/B2 已完成实际 SWMM；数值质量尚未通过",
            },
        },
        "publication_matrix": [
            {
                "result": "边界、对象清单与方案定义",
                "now": "可以发布",
                "basis": "正式 Mussafah_00 边界、模型包、Parsons 对象追溯和当前 pond 查询",
                "freeze_required": "客户确认版本、对象角色和边界口径",
            },
            {
                "result": "L1 / L2 一维现状诊断",
                "now": "可以作为 review-only proxy 展示",
                "basis": "当前一维模型运行结果；L2 pond 当前为 0 条的临时口径",
                "freeze_required": "L2 现状设施清单、管网工程语义、泵站和边界条件",
            },
            {
                "result": "Parsons L2+（A）一维增量",
                "now": "可以作为诊断证据展示",
                "basis": "STO-PO3 + PMP5 + W-4 + 管线 1235 的可追溯闭环",
                "freeze_required": "批准塘体曲线、泵 H-Q / 控制、入水 / 溢流交换和双向回执",
            },
            {
                "result": "二维积水面积、最大深度、退水时间和历史点消失率",
                "now": "主结果采用实际 SWMM 一维；二维指标待完成",
                "basis": "四个状态均有 EPA SWMM 5.2.4 实际运行回执；未声明二维积水收益",
                "freeze_required": "5 m DTM / 路缘 / 建筑阻水、源项、交换定律、历史观测和质量门",
            },
            {
                "result": "自主 L2+（B）最优地块、Pareto 排名和成本",
                "now": "可发布真实地块 167073 的实际 SWMM 结果；不能发布正式成本排名",
                "basis": "Makani 地块属性、建筑/道路核查、utility overlap=0 和实际 SWMM 回执",
                "freeze_required": "土地许可、冲突核查、塘体曲线、连接水力、CAPEX / OPEX 和多情景结果",
            },
        ],
        "actual_swmm_result": _actual_swmm_result(),
        "ideal_5m_result": _idealized_5m_result(),
        "metrics": [
            {"state": state["label"], **state["outputs"]}
            for state in _actual_swmm_result().get("states", [])
        ],
        "scope": {
            "formal_boundary_area_ha": 147.83849835069304,
            "database_area_ha": 148.76,
            "current_l2_pond_count": 0,
            "parsons_candidate_pond_count": 1,
            "cross_boundary_objects": {"manhole": 13, "conduit": 9, "outfall": 2},
            "historical_hotspots_total": 506,
            "historical_hotspots_in_network_extent": 9,
            "historical_hotspots_in_5m_window": 3,
            "sto_po3": {
                "status": "L2+（A）Parsons candidate",
                "capacity_sources_m3": [900, 1120.1, 1200, 2380],
                "approved_stage_area_volume_curve": False,
            },
        },
        "preflight": {
            "status": preflight.get("status", "implementation_ready_data_blocked"),
            "engineering_admitted": False,
            "checks": preflight.get("checks", []),
            "coupling_window_seconds": preflight.get("scope", {}).get(
                "coupling_window_seconds", 300
            ),
        },
        "synthetic_coupling_test": {
            "status": synthetic.get("status", "synthetic_contract_test_passed"),
            "mass_balance_pass": synthetic.get("checks", {}).get("mass_balance_pass", True),
            "engineering_admitted": False,
        },
        "pond_audit": pond_audit,
        "gaps": _read_gap_rows(),
        "assets": _asset_catalog(),
    }


async def get_mussafah00_gap_bootstrap(request: Request) -> JSONResponse:
    _, error = _authorized(request)
    if error:
        return error
    return JSONResponse(
        _bootstrap_payload(),
        headers={"Cache-Control": "private, max-age=60"},
    )


async def get_mussafah00_gap_asset(request: Request):
    _, error = _authorized(request)
    if error:
        return error
    asset_name = str(request.path_params.get("filename") or "")
    path = _asset_path(asset_name)
    if path is None:
        return JSONResponse({"error": "asset_not_found"}, status_code=404)
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if path.suffix.lower() in {".geojson", ".json", ".csv", ".md", ".asc"}:
        media_type = {
            ".geojson": "application/geo+json",
            ".json": "application/json",
            ".csv": "text/csv; charset=utf-8",
            ".md": "text/markdown; charset=utf-8",
            ".asc": "text/plain; charset=utf-8",
        }.get(path.suffix.lower(), media_type)
    return FileResponse(path, media_type=media_type, filename=path.name)


def _workspace_html() -> str:
    return (Path(__file__).resolve().parents[1] / "static" / "mussafah_gap.html").read_text(encoding="utf-8")


async def get_mussafah00_review_result(request: Request) -> JSONResponse:
    _, error = _authorized(request)
    if error:
        return error
    path = _FORMAL_DIR / "actual_review_v2" / "comparison.json"
    if not path.is_file():
        return JSONResponse({"error": "actual_results_not_available"}, status_code=503)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return JSONResponse({"error": "actual_results_unreadable"}, status_code=503)
    return JSONResponse(data, headers={"Cache-Control": "no-store"})


async def get_mussafah00_gap_workspace(request: Request) -> HTMLResponse | JSONResponse:
    _, error = _authorized(request)
    if error:
        return error
    return HTMLResponse(_workspace_html(), headers={"Cache-Control": "no-store"})


def _real_scenario_dir(scenario: str) -> Path | None:
    entry = _REAL_SCENARIOS.get(str(scenario or "").upper())
    if entry is None:
        return None
    return _REAL_COUPLED_DIR / entry[0]


def _real_scenario_summary(scenario: str) -> dict:
    key = str(scenario or "").upper()
    entry = _REAL_SCENARIOS.get(key)
    root = _real_scenario_dir(key)
    if entry is None or root is None:
        return {}
    summary_path = root / "delivery_summary.json"
    receipt_path = root / "bidirectional_coupling_receipt.json"
    manifest_path = root / "temporal_snapshots" / "manifest.json"
    summary: dict = {}
    if summary_path.is_file():
        try:
            value = json.loads(summary_path.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                summary = value
        except (OSError, ValueError):
            summary = {}
    receipt: dict = {}
    if receipt_path.is_file():
        try:
            value = json.loads(receipt_path.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                receipt = value
        except (OSError, ValueError):
            receipt = {}
    manifest: dict = {}
    if manifest_path.is_file():
        try:
            value = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                manifest = value
        except (OSError, ValueError):
            manifest = {}
    terrain = _terrain_metadata()
    result = {
        "key": entry[0],
        "label": entry[1],
        "status": summary.get("status") or "queued",
        "solver": summary.get("solver", "EPA SWMM 5.2.4 + ANUGA 2D"),
        "engineering_admitted": False,
        "run_id": summary.get("run_id", f"mussafah00-{key.lower()}-real-48h"),
        "domain": summary.get("domain", {}),
        "results": summary.get("results", {}),
        "coupling": summary.get("coupling", summary.get("coupling_summary", {})),
        "quality_gates": summary.get("quality_gates", {}),
        "model_configuration": summary.get("model_configuration", {}),
        "claim_boundary": summary.get("claim_boundary", "真实二维诊断运行；未校准、未工程准入。"),
        "comparison_basis": _REAL_COMPARISON_BASIS.get(key, "L2 基线"),
        "manifest": {
            "available": bool(manifest.get("snapshots")),
            "period_count": len(manifest.get("snapshots") or []),
            "elapsed_minutes": [float(row.get("time_minutes", 0.0)) for row in (manifest.get("snapshots") or [])],
            "time_values": [f"{float(row.get('time_minutes', 0.0)):.0f} min" for row in (manifest.get("snapshots") or [])],
            "endpoint": f"/api/abu-dhabi/flood/mussafah00/{key}/frame",
        },
        "assets": {
            # The formal Mussafah_00 assessment boundary is the catchment used
            # to define the 5 m coupled model domain.  The served copy is
            # reprojected to WGS84 for deck.gl; the original EPSG:32640 asset
            # remains available as a provenance/audit reference.
            "catchment_boundary": _asset_url("catchment", _MUSSAFAH00_CATCHMENT_BOUNDARY) if _MUSSAFAH00_CATCHMENT_BOUNDARY.is_file() else None,
            "catchment_boundary_source": _asset_url("catchment", _MUSSAFAH00_CATCHMENT_BOUNDARY_SOURCE) if _MUSSAFAH00_CATCHMENT_BOUNDARY_SOURCE.is_file() else None,
            "maximum_depth": _asset_url("real2d", root / "maximum_depth_wgs84.geojson") if (root / "maximum_depth_wgs84.geojson").is_file() else None,
            "delivery_summary": _asset_url("real2d", summary_path) if summary_path.is_file() else None,
            "coupling_receipt": _asset_url("real2d", receipt_path) if receipt_path.is_file() else None,
            "native_sww": _asset_url("real2d", root / "mussafah00_coupled.sww") if (root / "mussafah00_coupled.sww").is_file() else None,
            "configuration": _asset_url("real2d", root / "configuration.json") if (root / "configuration.json").is_file() else None,
            "infrastructure": _asset_url("real2d", root / "infrastructure.geojson") if (root / "infrastructure.geojson").is_file() else None,
            "hotspots_506": _asset_url("real2d", _REAL_COUPLED_DIR / "hotspots_506.geojson") if (_REAL_COUPLED_DIR / "hotspots_506.geojson").is_file() else None,
            # The map consumes the authenticated bounded terrain service.  The
            # raw PNG remains available as a compatibility asset in
            # ``terrain_image`` for downloads and audit comparison.
            "terrain": _terrain_tile_url() if _TERRAIN_IMAGE.is_file() else None,
            "terrain_export": _terrain_export_url() if _TERRAIN_IMAGE.is_file() else None,
            "terrain_image": _terrain_export_url() if _TERRAIN_IMAGE.is_file() else None,
            "terrain_service": "/api/abu-dhabi/flood/mussafah00-gap/terrain/service",
            "terrain_bounds": terrain.get("bounds"),
            "terrain_decoder": terrain.get("elevation_decoder"),
            "terrain_resolution_m": terrain.get("resolution_m"),
        },
    }
    progress_path = root / "progress.json"
    if progress_path.is_file():
        try:
            result["progress"] = json.loads(progress_path.read_text())
            if not summary:
                result["status"] = result["progress"].get("status", "queued")
        except (OSError, ValueError):
            pass
    result["ready"] = bool(summary and manifest.get("snapshots") and receipt.get("status") == "completed")
    if result["ready"]:
        expected = round(float(summary.get("domain", {}).get("simulation_duration_hours", 0)) * 12)
        result["ready"] = len(manifest["snapshots"]) == expected and expected > 0
    hydrograph = root / "hydrograph.json"
    if result["ready"] and hydrograph.is_file():
        try:
            hydro = json.loads(hydrograph.read_text())
            result["manifest"]["peak_time_index"] = max(range(len(hydro)), key=lambda i: hydro[i]["inundated_area_ge_0_01m2"])
            result["manifest"]["first_wet_time_index"] = next((i for i, row in enumerate(hydro) if row["inundated_area_ge_0_01m2"] > 0), 0)
            result["hydrograph"] = hydro
        except (OSError, ValueError, KeyError):
            pass
    if receipt:
        result["receipt_status"] = receipt.get("status")
        result["receipt_quality_passed"] = receipt.get("quality_passed")
        result["receipt_window_count"] = len(receipt.get("windows") or [])
        result["quality_failed_windows"] = [
            int(row.get("window_index", -1))
            for row in (receipt.get("windows") or [])
            if row.get("quality_passed") is False
        ]
    return result


def _read_real_comparison() -> dict:
    """Compute deltas only from completed native coupled deliveries."""
    rows = []
    for key in _REAL_SCENARIOS:
        value = _real_scenario_summary(key)
        if value.get("ready"):
            results = value.get("results") or {}
            rows.append({
                "key": key,
                "label": value.get("label"),
                "maximum_depth_m": results.get("maximum_depth_m"),
                "maximum_depth_envelope_area_ge_0_01m2": results.get("maximum_depth_envelope_area_ge_0_01m2"),
                "peak_simultaneous_inundated_area_m2": (results.get("peak_simultaneous_inundated_area_m2") or {}).get("0.01"),
                "final_inundated_area_ge_0_01m2": results.get("final_inundated_area_ge_0_01m2"),
                "total_swmm_to_anuga_m3": (value.get("coupling") or {}).get("total_swmm_to_anuga_m3"),
                "total_anuga_to_swmm_m3": (value.get("coupling") or {}).get("total_anuga_to_swmm_m3"),
            })
    baseline = next((row for row in rows if row["key"] == "L1"), None)
    previous_by_key = {
        "L2": "L1",
        "PARSONS": "L2",
        "L2AB": "PARSONS",
        "L2B6": "L2",
        "B1": "L2",
        "B2": "L2",
    }
    by_key = {row["key"]: row for row in rows}
    for row in rows:
        row["delta_vs_l1"] = {
            key: (None if baseline is None or row.get(key) is None or baseline.get(key) is None else row[key] - baseline[key])
            for key in ("maximum_depth_m", "maximum_depth_envelope_area_ge_0_01m2", "peak_simultaneous_inundated_area_m2", "final_inundated_area_ge_0_01m2")
        }
        previous = by_key.get(previous_by_key.get(row["key"], ""))
        row["previous_key"] = previous["key"] if previous else None
        row["delta_vs_previous"] = {
            key: (None if previous is None or row.get(key) is None or previous.get(key) is None else row[key] - previous[key])
            for key in ("maximum_depth_m", "maximum_depth_envelope_area_ge_0_01m2", "peak_simultaneous_inundated_area_m2", "final_inundated_area_ge_0_01m2")
        }
    return {"baseline": "L1", "rows": rows, "all_states_complete": len(rows) == len(_REAL_SCENARIOS)}


async def get_mussafah00_difference(request: Request) -> JSONResponse:
    _, error = _authorized(request)
    if error:
        return error
    import numpy as np
    from pyproj import Transformer

    selected = str(request.path_params.get("scenario") or "").upper()
    baseline = str(request.query_params.get("baseline", "L2")).upper()
    roots = [_real_scenario_dir(key) for key in (baseline, selected)]
    if any(root is None for root in roots):
        return JSONResponse({"error": "scenario_not_found"}, status_code=404)
    if not all(_real_scenario_summary(key).get("ready") for key in (baseline, selected)):
        return JSONResponse({"error": "comparison_not_complete"}, status_code=503)
    try:
        index = int(request.query_params["time_index"]) if "time_index" in request.query_params else None
    except ValueError:
        return JSONResponse({"error": "time_index_invalid"}, status_code=400)
    arrays = []
    supports = []
    for root in roots:
        with np.load(root / "cell_results.npz") as cells:
            x, y = cells["x"], cells["y"]
            active = cells["active_cells"]
            data = np.zeros((len(x)-1)*(len(y)-1))
            support = np.zeros(data.shape, dtype=bool)
            support[active] = cells["assessment_mask"]
            if index is None:
                data[active] = cells["maximum_depth_m"]
            else:
                frames = np.load(root / "depth_frames.npy", mmap_mode="r")
                if index < 0 or index >= len(frames):
                    return JSONResponse({"error": "time_index_out_of_range"}, status_code=416)
                data[active] = frames[index]
            arrays.append(data)
            supports.append(support)
    before, after = arrays
    reduction = before-after
    active = supports[0] & supports[1]
    transform = Transformer.from_crs(32640, 4326, always_xy=True)
    features = []
    for cell in np.flatnonzero(active & (np.abs(reduction) >= 0.001)):
        row, col = divmod(int(cell), len(x)-1)
        corners = [(x[col],y[row]),(x[col+1],y[row]),(x[col+1],y[row+1]),(x[col],y[row+1]),(x[col],y[row])]
        features.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[list(transform.transform(*p)) for p in corners]]},
                         "properties": {"cell_id": int(cell), "baseline_depth_m": float(before[cell]), "scenario_depth_m": float(after[cell]),
                                        "reduction_m": float(reduction[cell]), "time_minutes": (index+1)*5 if index is not None else None}})
    return JSONResponse({"type": "FeatureCollection", "features": features,
                         "metadata": {"baseline": baseline, "scenario": selected, "positive_means": "depth_reduction",
                                      "comparison": "same-time depths" if index is not None else "difference of per-cell maxima; peaks need not occur simultaneously"}},
                        headers={"Cache-Control": "private, max-age=30"})


async def get_mussafah00_real_scenarios(request: Request) -> JSONResponse:
    _, error = _authorized(request)
    if error:
        return error
    return JSONResponse(
        {
            "schema": "gwm.abu_dhabi_flood.mussafah00.real_coupled_scenarios.v1",
            "domain": "Mussafah_00",
            "resolution_m": 5,
            "scenarios": [_real_scenario_summary(key) for key in _REAL_SCENARIOS],
            "comparison": _read_real_comparison(),
        },
        headers={"Cache-Control": "no-store"},
    )


async def get_mussafah00_terrain_service(request: Request) -> JSONResponse:
    """Return the authenticated DEM service contract used by the 3D map."""
    _, error = _authorized(request)
    if error:
        return error
    return JSONResponse(_terrain_service_metadata(), headers={"Cache-Control": "no-store"})


async def get_mussafah00_terrain_export(request: Request) -> Response:
    """Export a bounded Terrain-RGB image from the actual 5 m model DTM.

    This is intentionally a small ImageServer-like endpoint rather than a
    browser-only static file.  The map can request the full Mussafah extent,
    while diagnostics can request a smaller bbox without changing the model.
    """
    _, error = _authorized(request)
    if error:
        return error
    source = str(request.query_params.get("source", "customer_dtm_5m"))
    if source != "customer_dtm_5m":
        return JSONResponse(
            {"error": "terrain_source_not_available", "source": source,
             "fallback": "arcgis_world_elevation_3d"},
            status_code=400,
        )
    metadata = _terrain_metadata()
    raw_bbox = request.query_params.get("bbox")
    if raw_bbox:
        try:
            bbox = [float(value) for value in raw_bbox.split(",")]
            if len(bbox) != 4:
                raise ValueError
        except ValueError:
            return JSONResponse({"error": "bbox_invalid"}, status_code=400)
    else:
        bbox = [float(value) for value in metadata.get("bounds", [])]
    try:
        width = max(32, min(2048, int(request.query_params.get("width", metadata.get("width", 512)))))
        height = max(32, min(2048, int(request.query_params.get("height", metadata.get("height", 512)))))
    except ValueError:
        return JSONResponse({"error": "image_size_invalid"}, status_code=400)
    payload = _render_terrain_export(bbox, width, height)
    if payload is None:
        return JSONResponse({"error": "terrain_export_failed"}, status_code=503)
    decoder = json.dumps(metadata.get("elevation_decoder", {}), separators=(",", ":"))
    return Response(
        content=payload,
        media_type="image/png",
        headers={
            "Cache-Control": "private, max-age=3600",
            "Content-Disposition": "inline; filename=mussafah00_5m_terrain_rgb.png",
            "X-Terrain-CRS": str(metadata.get("crs", "EPSG:4326")),
            "X-Terrain-Resolution-M": str(metadata.get("resolution_m", 5)),
            "X-Terrain-Decoder": decoder,
        },
    )


async def get_mussafah00_terrain_tile(request: Request) -> Response:
    """Serve one authenticated XYZ Terrain-RGB tile from the model DTM."""
    _, error = _authorized(request)
    if error:
        return error
    try:
        z = int(request.path_params["z"])
        x = int(request.path_params["x"])
        y = int(request.path_params["y"])
        n = 2 ** z
        if z < 0 or z > 18 or x < 0 or x >= n or y < 0 or y >= n:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return JSONResponse({"error": "tile_coordinates_invalid"}, status_code=400)
    payload = _render_terrain_tile(z, x, y)
    if payload is None:
        return Response(status_code=204, headers={"Cache-Control": "private, max-age=3600"})
    return Response(
        content=payload,
        media_type="image/png",
        headers={
            "Cache-Control": "private, max-age=3600",
            "Content-Disposition": f"inline; filename=terrain-{z}-{x}-{y}.png",
            "X-Terrain-CRS": "EPSG:4326",
            "X-Terrain-Resolution-M": "5",
        },
    )


async def get_mussafah00_real_scenario_summary(request: Request) -> JSONResponse:
    _, error = _authorized(request)
    if error:
        return error
    scenario = str(request.path_params.get("scenario") or "").upper()
    value = _real_scenario_summary(scenario)
    if not value:
        return JSONResponse({"error": "scenario_not_found"}, status_code=404)
    return JSONResponse(value, headers={"Cache-Control": "no-store"})


async def get_mussafah00_real_scenario_frame(request: Request) -> JSONResponse:
    _, error = _authorized(request)
    if error:
        return error
    scenario = str(request.path_params.get("scenario") or "").upper()
    root = _real_scenario_dir(scenario)
    summary = _real_scenario_summary(scenario)
    if root is None or not summary:
        return JSONResponse({"error": "scenario_not_found"}, status_code=404)
    if not summary.get("ready"):
        return JSONResponse({"error": "scenario_not_complete", "status": summary.get("status")}, status_code=503)
    try:
        index = int(request.query_params.get("time_index", "0"))
    except ValueError:
        return JSONResponse({"error": "time_index_invalid"}, status_code=400)
    manifest_path = root / "temporal_snapshots" / "manifest.json"
    if not manifest_path.is_file():
        return JSONResponse({"error": "timeline_not_available"}, status_code=503)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        rows = manifest.get("snapshots") or []
        if index < 0 or index >= len(rows):
            return JSONResponse({"error": "time_index_out_of_range"}, status_code=416)
        relative = Path(str(rows[index].get("path") or ""))
        path = (root / relative).resolve()
        path.relative_to(root.resolve())
        if not path.is_file():
            return JSONResponse({"error": "frame_not_available"}, status_code=503)
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError):
        return JSONResponse({"error": "frame_unreadable"}, status_code=503)
    return JSONResponse(payload, headers={"Cache-Control": "private, max-age=30"})


async def get_mussafah00_real_scenario_maximum_depth(request: Request) -> JSONResponse:
    _, error = _authorized(request)
    if error:
        return error
    scenario = str(request.path_params.get("scenario") or "").upper()
    root = _real_scenario_dir(scenario)
    if root is None or not (root / "maximum_depth_wgs84.geojson").is_file():
        return JSONResponse({"error": "maximum_depth_not_available"}, status_code=503)
    try:
        payload = json.loads((root / "maximum_depth_wgs84.geojson").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return JSONResponse({"error": "maximum_depth_unreadable"}, status_code=503)
    return JSONResponse(payload, headers={"Cache-Control": "private, max-age=60"})


def get_mussafah00_gap_routes() -> list[Route]:
    return [
        Route("/api/abu-dhabi/flood/mussafah00/{scenario}/difference", endpoint=get_mussafah00_difference, methods=["GET"]),
        Route("/api/abu-dhabi/flood/mussafah00/scenarios", endpoint=get_mussafah00_real_scenarios, methods=["GET"]),
        Route("/api/abu-dhabi/flood/mussafah00-gap/terrain/service", endpoint=get_mussafah00_terrain_service, methods=["GET"]),
        Route("/api/abu-dhabi/flood/mussafah00-gap/terrain/export", endpoint=get_mussafah00_terrain_export, methods=["GET"]),
        Route("/api/abu-dhabi/flood/mussafah00-gap/terrain/tiles/{z:int}/{x:int}/{y:int}.png", endpoint=get_mussafah00_terrain_tile, methods=["GET"]),
        Route("/api/abu-dhabi/flood/mussafah00/{scenario}/summary", endpoint=get_mussafah00_real_scenario_summary, methods=["GET"]),
        Route("/api/abu-dhabi/flood/mussafah00/{scenario}/frames", endpoint=get_mussafah00_real_scenario_summary, methods=["GET"]),
        Route("/api/abu-dhabi/flood/mussafah00/{scenario}/frame", endpoint=get_mussafah00_real_scenario_frame, methods=["GET"]),
        Route("/api/abu-dhabi/flood/mussafah00/{scenario}/maximum-depth", endpoint=get_mussafah00_real_scenario_maximum_depth, methods=["GET"]),
        Route("/api/abu-dhabi/flood/mussafah00-gap/review", endpoint=get_mussafah00_review_result, methods=["GET"]),
        # Browser-facing page paths.  These are intentionally outside /api;
        # the page calls the authenticated JSON/assets endpoints internally.
        Route(
            "/mussafah00-gap",
            endpoint=get_mussafah00_gap_workspace,
            methods=["GET"],
        ),
        Route(
            "/abu-dhabi/flood/mussafah00-gap",
            endpoint=get_mussafah00_gap_workspace,
            methods=["GET"],
        ),
        Route(
            "/api/abu-dhabi/flood/mussafah00-gap",
            endpoint=get_mussafah00_gap_workspace,
            methods=["GET"],
        ),
        Route(
            "/api/abu-dhabi/flood/mussafah00-gap/bootstrap",
            endpoint=get_mussafah00_gap_bootstrap,
            methods=["GET"],
        ),
        Route(
            "/api/abu-dhabi/flood/mussafah00-gap/assets/{filename:path}",
            endpoint=get_mussafah00_gap_asset,
            methods=["GET"],
        ),
    ]

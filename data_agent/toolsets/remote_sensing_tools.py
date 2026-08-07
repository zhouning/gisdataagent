"""Remote sensing toolset: raster analysis, data download, spectral indices, STAC discovery."""
import asyncio
import json
import os
import re

import yaml
from google.adk.tools import FunctionTool
from google.adk.tools.base_toolset import BaseToolset

from ..remote_sensing import (
    describe_raster,
    calculate_ndvi,
    raster_band_math,
    classify_raster,
    visualize_raster,
    download_lulc,
    download_dem,
)
from ..spectral_indices import (
    calculate_spectral_index,
    list_spectral_indices,
    recommend_indices,
    assess_cloud_cover,
)

_STANDARDS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "standards")
_DEFAULT_STAC_ENDPOINT = "https://earth-search.aws.element84.com/v1"
_STAC_TIMEOUT_ENV = "GIS_AGENT_STAC_TIMEOUT_SECONDS"
_STAC_PROXY_ENV = "GIS_AGENT_STAC_PROXY_URL"
_DATE_ONLY_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ---------------------------------------------------------------------------
# Experience pool + satellite preset + STAC tool functions
# ---------------------------------------------------------------------------

def _load_satellite_presets() -> list[dict]:
    path = os.path.join(_STANDARDS_DIR, "satellite_presets.yaml")
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("presets", [])


def _find_preset(preset_name: str) -> dict | None:
    name = (preset_name or "").strip()
    if not name:
        return None
    for preset in _load_satellite_presets():
        if preset.get("name") == name:
            return preset
    return None


def _parse_bbox(bbox) -> list[float] | None:
    if bbox in (None, ""):
        return None
    if isinstance(bbox, str):
        values = [v.strip() for v in bbox.split(",") if v.strip()]
    else:
        values = list(bbox)
    parsed = [float(v) for v in values]
    if len(parsed) != 4:
        raise ValueError("bbox must contain four values: west,south,east,north")
    west, south, east, north = parsed
    if west >= east or south >= north:
        raise ValueError("bbox must be ordered west,south,east,north")
    return parsed


def _run_async(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(asyncio.run, coro)
        return future.result()


def _positive_float(value) -> float | None:
    if value in (None, ""):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _build_stac_client_config(timeout_seconds: float = 0.0, proxy_url: str = "") -> dict:
    config: dict = {}
    timeout = _positive_float(timeout_seconds) or _positive_float(os.getenv(_STAC_TIMEOUT_ENV, ""))
    if timeout is not None:
        config["timeout_seconds"] = int(timeout) if timeout.is_integer() else timeout

    proxy = (proxy_url or os.getenv(_STAC_PROXY_ENV, "")).strip()
    if proxy:
        config["proxy_url"] = proxy
    return config


def _normalize_stac_datetime(value: str) -> str:
    """Expand date-only STAC intervals to RFC3339 timestamps."""

    normalized = (value or "").strip()
    if not normalized:
        return ""
    if "/" not in normalized:
        return (
            f"{normalized}T00:00:00Z"
            if _DATE_ONLY_PATTERN.fullmatch(normalized)
            else normalized
        )
    start, end = normalized.split("/", 1)
    if _DATE_ONLY_PATTERN.fullmatch(start):
        start = f"{start}T00:00:00Z"
    if _DATE_ONLY_PATTERN.fullmatch(end):
        end = f"{end}T23:59:59Z"
    return f"{start}/{end}"


def search_rs_experience(query: str) -> str:
    """搜索遥感分析经验库，获取推荐指数、参数和常见陷阱。

    Args:
        query: 搜索关键词 (如 "植被监测", "水体检测", "火灾评估")
    Returns:
        JSON: 匹配的经验案例列表
    """
    try:
        pool_path = os.path.join(_STANDARDS_DIR, "rs_experience_pool.yaml")
        with open(pool_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        query_lower = query.lower()
        matches = []
        for case in data.get("cases", []):
            tags = [t.lower() for t in case.get("tags", [])]
            title_lower = case.get("title", "").lower()
            scenario_lower = case.get("scenario", "").lower()
            score = sum(1 for t in tags if t in query_lower)
            score += sum(1 for word in query_lower.split() if word in title_lower or word in scenario_lower)
            if score > 0:
                matches.append({**case, "_relevance": score})

        matches.sort(key=lambda x: x["_relevance"], reverse=True)
        for m in matches:
            m.pop("_relevance", None)

        return json.dumps({"status": "success", "matches": matches[:3]}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)


def list_satellite_presets() -> str:
    """列出所有预置的卫星数据源 (Sentinel-2, Landsat, SAR, DEM)。

    Returns:
        JSON: 预置源列表，含名称、分辨率、重访周期、波段
    """
    try:
        presets = []
        for p in _load_satellite_presets():
            presets.append({
                "name": p["name"],
                "display_name": p.get("display_name", p["name"]),
                "resolution_m": p.get("resolution_m"),
                "revisit_days": p.get("revisit_days"),
                "source_type": p.get("source_type"),
                "endpoint_url": p.get("endpoint_url"),
                "collection": p.get("collection"),
                "default_cloud_cover": p.get("default_cloud_cover"),
                "bands": list(p.get("bands", {}).keys()),
                "description": p.get("description", ""),
            })
        return json.dumps({"status": "success", "presets": presets}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)


def stac_search(
    bbox: str = "",
    datetime: str = "",
    cloud_cover: float = -1.0,
    collection: str = "",
    limit: int = 20,
    endpoint_url: str = "",
    preset_name: str = "",
    timeout_seconds: float = 0.0,
    proxy_url: str = "",
) -> str:
    """Search a STAC API for satellite imagery items.

    Args:
        bbox: Spatial extent as "west,south,east,north" in EPSG:4326.
        datetime: STAC datetime range, e.g. "2024-01-01/2024-12-31".
        cloud_cover: Optional maximum eo:cloud_cover percentage. Use -1 to disable.
        collection: STAC collection id. If omitted, uses the preset collection.
        limit: Maximum number of items to return.
        endpoint_url: STAC API root URL. If omitted, uses preset or Earth Search.
        preset_name: Optional satellite preset name from list_satellite_presets.
        timeout_seconds: Optional request timeout override. Uses GIS_AGENT_STAC_TIMEOUT_SECONDS when omitted.
        proxy_url: Optional HTTP proxy URL. Uses GIS_AGENT_STAC_PROXY_URL when omitted.

    Returns:
        JSON string with matching STAC item summaries.
    """
    try:
        from ..connectors.stac import StacConnector

        preset = _find_preset(preset_name)
        if preset and preset.get("source_type") != "stac":
            return json.dumps({
                "status": "error",
                "message": f"preset '{preset_name}' is not a STAC source",
            }, ensure_ascii=False)

        endpoint = endpoint_url or (preset or {}).get("endpoint_url") or _DEFAULT_STAC_ENDPOINT
        collection_id = collection or (preset or {}).get("collection") or ""
        query_config = {"collection_id": collection_id} if collection_id else {}

        max_items = max(1, min(int(limit or 20), 100))
        bbox_list = _parse_bbox(bbox)
        max_cloud = None
        if cloud_cover is not None and float(cloud_cover) >= 0:
            max_cloud = float(cloud_cover)
        items = _run_async(StacConnector().query(
            endpoint,
            _build_stac_client_config(timeout_seconds, proxy_url),
            query_config,
            bbox=bbox_list,
            filter_expr=_normalize_stac_datetime(datetime) or None,
            limit=max_items,
            extra_params=(
                {"query": {"eo:cloud_cover": {"lte": max_cloud}}}
                if max_cloud is not None
                else None
            ),
        ))

        if max_cloud is not None:
            items = [
                item for item in items
                if item.get("cloud_cover") is None or float(item["cloud_cover"]) <= max_cloud
            ]

        return json.dumps({
            "status": "success",
            "endpoint_url": endpoint,
            "collection": collection_id,
            "count": len(items),
            "items": items,
        }, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)


def stac_list_collections(
    endpoint_url: str = "",
    preset_name: str = "",
    timeout_seconds: float = 0.0,
    proxy_url: str = "",
) -> str:
    """List collections exposed by a STAC API endpoint.

    Args:
        endpoint_url: STAC API root URL. If omitted, uses preset or Earth Search.
        preset_name: Optional satellite preset name from list_satellite_presets.
        timeout_seconds: Optional request timeout override. Uses GIS_AGENT_STAC_TIMEOUT_SECONDS when omitted.
        proxy_url: Optional HTTP proxy URL. Uses GIS_AGENT_STAC_PROXY_URL when omitted.

    Returns:
        JSON string with collection summaries.
    """
    try:
        from ..connectors.stac import StacConnector

        preset = _find_preset(preset_name)
        if preset and preset.get("source_type") != "stac":
            return json.dumps({
                "status": "error",
                "message": f"preset '{preset_name}' is not a STAC source",
            }, ensure_ascii=False)

        endpoint = endpoint_url or (preset or {}).get("endpoint_url") or _DEFAULT_STAC_ENDPOINT
        caps = _run_async(StacConnector().get_capabilities(
            endpoint,
            _build_stac_client_config(timeout_seconds, proxy_url),
        ))
        collections = caps.get("layers", [])
        return json.dumps({
            "status": "success",
            "endpoint_url": endpoint,
            "service": caps.get("service", "STAC"),
            "count": len(collections),
            "collections": collections,
        }, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)


_ALL_FUNCS = [
    describe_raster, calculate_ndvi, raster_band_math,
    classify_raster, visualize_raster, download_lulc, download_dem,
    # Phase 1: spectral indices + experience pool + presets
    calculate_spectral_index, list_spectral_indices, recommend_indices,
    assess_cloud_cover, search_rs_experience, list_satellite_presets,
    # v24.2: STAC discovery wrappers
    stac_search, stac_list_collections,
]


class RemoteSensingToolset(BaseToolset):
    """Raster analysis and remote sensing tools."""

    async def get_tools(self, readonly_context=None):
        all_tools = [FunctionTool(f) for f in _ALL_FUNCS]
        if self.tool_filter is None:
            return all_tools
        return [t for t in all_tools if self._is_tool_selected(t, readonly_context)]

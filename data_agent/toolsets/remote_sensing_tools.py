"""Remote sensing toolset: raster profiling, NDVI, band math, classification, visualization, data download, spectral indices."""
import json
import os

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


# ---------------------------------------------------------------------------
# Experience pool + satellite preset tool functions
# ---------------------------------------------------------------------------

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
        path = os.path.join(_STANDARDS_DIR, "satellite_presets.yaml")
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        presets = []
        for p in data.get("presets", []):
            presets.append({
                "name": p["name"],
                "display_name": p.get("display_name", p["name"]),
                "resolution_m": p.get("resolution_m"),
                "revisit_days": p.get("revisit_days"),
                "source_type": p.get("source_type"),
                "bands": list(p.get("bands", {}).keys()),
                "description": p.get("description", ""),
            })
        return json.dumps({"status": "success", "presets": presets}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)


_ALL_FUNCS = [
    describe_raster, calculate_ndvi, raster_band_math,
    classify_raster, visualize_raster, download_lulc, download_dem,
    # Phase 1: spectral indices + experience pool + presets
    calculate_spectral_index, list_spectral_indices, recommend_indices,
    assess_cloud_cover, search_rs_experience, list_satellite_presets,
]


class RemoteSensingToolset(BaseToolset):
    """Raster analysis and remote sensing tools."""

    async def get_tools(self, readonly_context=None):
        all_tools = [FunctionTool(f) for f in _ALL_FUNCS]
        if self.tool_filter is None:
            return all_tools
        return [t for t in all_tools if self._is_tool_selected(t, readonly_context)]

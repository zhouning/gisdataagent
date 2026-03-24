"""WorldModelToolset — 地理空间世界模型工具集 (Plan D Tech Preview).

基于 AlphaEarth 64维嵌入 + LatentDynamicsNet 残差 CNN 的土地利用变化预测。
"""

import asyncio
import json
import logging
import os

from google.adk.tools import FunctionTool, LongRunningFunctionTool
from google.adk.tools.base_toolset import BaseToolset

logger = logging.getLogger(__name__)


# ====================================================================
#  Tool functions
# ====================================================================


def world_model_predict(
    bbox: str = "",
    scenario: str = "baseline",
    start_year: str = "2023",
    n_years: str = "5",
    file: str = "",
) -> str:
    """使用世界模型预测土地利用变化。基于 AlphaEarth 嵌入 + LatentDynamicsNet 残差 CNN
    进行潜空间动力学预测。

    可以通过 bbox 直接指定区域，也可以通过 file 参数传入已加载的 GeoJSON/Shapefile 文件名，
    系统会自动从文件中提取边界框。当用户说"对这个区域"或"对刚才加载的数据"时，
    应使用 file 参数传入之前加载的文件名。

    Args:
        bbox: 研究区域边界框，格式 "minx,miny,maxx,maxy" (WGS84)，例如 "121.2,31.0,121.3,31.1"。
              如果提供了 file 参数则可留空。
        scenario: 模拟情景名称，可选 urban_sprawl/ecological_restoration/agricultural_intensification/climate_adaptation/baseline
        start_year: 起始年份 (2017-2024)
        n_years: 向前预测年数 (1-50)
        file: 已加载的空间数据文件名（如 interactive_map_xxx.geojson），系统自动提取 bbox。
              当用户提到"这个区域"、"刚才加载的数据"时使用此参数。

    Returns:
        JSON 字符串包含面积分布时间线、转移矩阵、每年 GeoJSON 图层
    """
    from ..world_model import predict_sequence
    import os

    try:
        parts = None

        # If file is provided, extract bbox from it
        if file and not bbox:
            try:
                import geopandas as gpd
                from ..user_context import current_user_id
                uid = current_user_id.get("admin")
                upload_dir = os.path.join(
                    os.path.dirname(os.path.dirname(__file__)),
                    "uploads", uid,
                )
                fpath = os.path.join(upload_dir, file)
                if not os.path.exists(fpath):
                    # Try without directory prefix
                    fpath = file
                if os.path.exists(fpath):
                    gdf = gpd.read_file(fpath)
                    if gdf.crs and gdf.crs.to_epsg() != 4326:
                        gdf = gdf.to_crs(epsg=4326)
                    bounds = gdf.total_bounds  # [minx, miny, maxx, maxy]
                    parts = [float(bounds[0]), float(bounds[1]),
                             float(bounds[2]), float(bounds[3])]
                else:
                    return json.dumps(
                        {"error": f"文件不存在: {file}"},
                        ensure_ascii=False,
                    )
            except Exception as e:
                return json.dumps(
                    {"error": f"从文件提取bbox失败: {e}"},
                    ensure_ascii=False,
                )

        # Parse bbox string if not extracted from file
        if parts is None:
            if not bbox:
                # Auto-discover: find most recent GeoJSON in user uploads
                try:
                    import glob
                    from ..user_context import current_user_id
                    uid = current_user_id.get("admin")
                    upload_dir = os.path.join(
                        os.path.dirname(os.path.dirname(__file__)),
                        "uploads", uid,
                    )
                    candidates = (
                        glob.glob(os.path.join(upload_dir, "*.geojson"))
                        + glob.glob(os.path.join(upload_dir, "*.shp"))
                    )
                    if candidates:
                        latest = max(candidates, key=os.path.getmtime)
                        import geopandas as gpd
                        gdf = gpd.read_file(latest)
                        if gdf.crs and gdf.crs.to_epsg() != 4326:
                            gdf = gdf.to_crs(epsg=4326)
                        bounds = gdf.total_bounds
                        parts = [float(bounds[0]), float(bounds[1]),
                                 float(bounds[2]), float(bounds[3])]
                        logger.info("Auto-discovered bbox from %s: %s",
                                    os.path.basename(latest), parts)
                except Exception as e:
                    logger.debug("Auto-discover failed: %s", e)

            if parts is None and not bbox:
                return json.dumps(
                    {"error": "请提供 bbox 或 file 参数，或确保之前已加载行政区划数据"},
                    ensure_ascii=False,
                )
            if parts is None:            parts = [float(x.strip()) for x in bbox.split(",")]
            if len(parts) != 4:
                return json.dumps(
                    {"error": "bbox 格式错误，应为 'minx,miny,maxx,maxy'"},
                    ensure_ascii=False,
                )

        year = int(start_year)
        years = int(n_years)
        if years < 1 or years > 50:
            return json.dumps(
                {"error": "n_years 应在 1-50 之间"}, ensure_ascii=False
            )

        result = predict_sequence(parts, scenario, year, years)
        # Strip geojson_layers from LLM response to avoid token explosion
        # (GeoJSON is pushed to map via REST API separately)
        result.pop("geojson_layers", None)
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


async def world_model_predict_long_running(
    bbox: str = "",
    scenario: str = "baseline",
    start_year: str = "2023",
    n_years: str = "5",
    file: str = "",
) -> str:
    """使用世界模型预测土地利用变化。基于 AlphaEarth 嵌入 + LatentDynamicsNet 残差 CNN
    进行潜空间动力学预测。可通过 bbox 或 file 参数指定区域。"""
    return await asyncio.to_thread(
        world_model_predict, bbox, scenario, start_year, n_years, file
    )


# Preserve tool name for ADK FunctionTool registration
world_model_predict_long_running.__name__ = "world_model_predict"
world_model_predict_long_running.__qualname__ = "world_model_predict"


def world_model_scenarios() -> str:
    """列出世界模型支持的所有预测情景。返回情景 ID、中文名称、英文名称和描述。"""
    from ..world_model import list_scenarios

    try:
        scenarios = list_scenarios()
        return json.dumps({"scenarios": scenarios}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def world_model_status() -> str:
    """查询世界模型状态，包括模型权重是否存在、GEE 是否可用、LULC 解码器状态、参数量等。"""
    from ..world_model import get_model_info

    try:
        info = get_model_info()
        return json.dumps(info, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


# ====================================================================
#  Toolset class
# ====================================================================

_SYNC_FUNCS = [world_model_scenarios, world_model_status]
_LONG_RUNNING_FUNCS = [world_model_predict_long_running]


class WorldModelToolset(BaseToolset):
    """地理空间世界模型工具集 — 基于 AlphaEarth 嵌入的土地利用变化预测（Tech Preview）"""

    async def get_tools(self, readonly_context=None):
        all_tools = [FunctionTool(f) for f in _SYNC_FUNCS] + [
            LongRunningFunctionTool(f) for f in _LONG_RUNNING_FUNCS
        ]
        if self.tool_filter is None:
            return all_tools
        return [
            t for t in all_tools if self._is_tool_selected(t, readonly_context)
        ]

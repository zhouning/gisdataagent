"""WorldModelToolset — 地理空间世界模型工具集 (Plan D Tech Preview).

基于 AlphaEarth 64维嵌入 + LatentDynamicsNet 残差 CNN 的土地利用变化预测。
"""

import asyncio
import json

from google.adk.tools import FunctionTool, LongRunningFunctionTool
from google.adk.tools.base_toolset import BaseToolset


# ====================================================================
#  Tool functions
# ====================================================================


def world_model_predict(
    bbox: str,
    scenario: str = "baseline",
    start_year: str = "2023",
    n_years: str = "5",
) -> str:
    """使用世界模型预测土地利用变化。基于 AlphaEarth 嵌入 + LatentDynamicsNet 残差 CNN
    进行潜空间动力学预测。输入研究区域边界框、情景名称、起始年份和预测年数。

    Args:
        bbox: 研究区域边界框，格式 "minx,miny,maxx,maxy" (WGS84)，例如 "121.2,31.0,121.3,31.1"
        scenario: 模拟情景名称，可选 urban_sprawl/ecological_restoration/agricultural_intensification/climate_adaptation/baseline
        start_year: 起始年份 (2017-2024)
        n_years: 向前预测年数 (1-50)

    Returns:
        JSON 字符串包含面积分布时间线、转移矩阵、每年 GeoJSON 图层
    """
    from ..world_model import predict_sequence

    try:
        # Parse bbox
        parts = [float(x.strip()) for x in bbox.split(",")]
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
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


async def world_model_predict_long_running(
    bbox: str,
    scenario: str = "baseline",
    start_year: str = "2023",
    n_years: str = "5",
) -> str:
    """使用世界模型预测土地利用变化。基于 AlphaEarth 嵌入 + LatentDynamicsNet 残差 CNN
    进行潜空间动力学预测。输入研究区域边界框、情景名称、起始年份和预测年数。"""
    return await asyncio.to_thread(
        world_model_predict, bbox, scenario, start_year, n_years
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

"""DreamerToolset — World Model + DRL integration tools.

Dreamer-style 世界模型驱动的深度强化学习优化工具集。
在 DRL 布局优化过程中注入世界模型的 look-ahead 辅助奖励。
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


def dreamer_optimize(
    data_path: str,
    scenario_id: str = "",
    bbox: str = "",
    year: str = "2023",
    max_steps: str = "200",
    look_ahead_years: str = "3",
    aux_reward_weight: str = "0.1",
) -> str:
    """Dreamer-style DRL 优化：世界模型 look-ahead + 深度强化学习布局优化。

    在传统 DRL 布局优化基础上，每隔 K 步调用 AlphaEarth 世界模型进行
    未来 LULC 变化预测，将预测结果作为辅助奖励信号注入 DRL 训练循环。

    Args:
        data_path: 输入空间数据路径 (Shapefile/GeoJSON)
        scenario_id: DRL 场景模板 ID (farmland_optimization/urban_green_space/facility_siting)
        bbox: 可选，世界模型嵌入提取区域 "minx,miny,maxx,maxy"。留空则自动从数据提取。
        year: 世界模型基准年份 (2017-2024)
        max_steps: DRL 最大步数
        look_ahead_years: 世界模型预测年数 (1-10)
        aux_reward_weight: 辅助奖励权重 (0.0-1.0)

    Returns:
        JSON 包含优化结果、世界模型状态、情景向量和辅助奖励序列。
    """
    from ..gis_processors import _resolve_path
    from ..dreamer_env import run_dreamer_optimization

    try:
        res_path = _resolve_path(data_path)
        if not os.path.exists(res_path):
            return json.dumps({"error": f"文件不存在: {data_path}"}, ensure_ascii=False)

        bbox_list = None
        if bbox:
            bbox_list = [float(x.strip()) for x in bbox.split(",")]
            if len(bbox_list) != 4:
                return json.dumps(
                    {"error": "bbox 格式错误，应为 'minx,miny,maxx,maxy'"},
                    ensure_ascii=False,
                )

        result = run_dreamer_optimization(
            shp_path=res_path,
            bbox=bbox_list,
            year=int(year),
            max_steps=int(max_steps),
            look_ahead_years=int(look_ahead_years),
            aux_reward_weight=float(aux_reward_weight),
            scenario_id=scenario_id,
        )
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return json.dumps({"error": str(e)}, ensure_ascii=False)


async def dreamer_optimize_long_running(
    data_path: str,
    scenario_id: str = "",
    bbox: str = "",
    year: str = "2023",
    max_steps: str = "200",
    look_ahead_years: str = "3",
    aux_reward_weight: str = "0.1",
) -> str:
    """Dreamer-style DRL 优化：世界模型 look-ahead + 深度强化学习布局优化。"""
    return await asyncio.to_thread(
        dreamer_optimize, data_path, scenario_id, bbox, year,
        max_steps, look_ahead_years, aux_reward_weight,
    )


# Preserve tool name for ADK FunctionTool registration
dreamer_optimize_long_running.__name__ = "dreamer_optimize"
dreamer_optimize_long_running.__qualname__ = "dreamer_optimize"


def dreamer_status() -> str:
    """查询 Dreamer (World Model + DRL) 集成状态。

    返回世界模型权重状态、DRL 权重状态、GEE 可用性等信息。
    """
    import os as _os
    result = {}

    # World model weights
    try:
        from ..world_model import get_model_info
        result['world_model'] = get_model_info()
    except Exception as e:
        result['world_model'] = {"error": str(e)}

    # DRL weights
    weights_path = _os.path.join(
        _os.path.dirname(_os.path.dirname(__file__)), 'scorer_weights_v7.pt'
    )
    result['drl_weights_exist'] = _os.path.exists(weights_path)
    result['drl_weights_path'] = weights_path

    # Integration info
    result['integration'] = {
        'description': 'Dreamer-style World Model + DRL integration',
        'aux_reward': 'AlphaEarth look-ahead reward every K steps',
        'components': [
            'ParcelEmbeddingMapper (zonal mean 64D)',
            'ActionToScenarioEncoder (action→scenario)',
            'DreamerEnv (aux reward wrapper)',
        ],
    }
    return json.dumps(result, ensure_ascii=False, default=str)


# ====================================================================
#  Toolset class
# ====================================================================

_SYNC_FUNCS = [dreamer_status]
_LONG_RUNNING_FUNCS = [dreamer_optimize_long_running]


class DreamerToolset(BaseToolset):
    """Dreamer-style DRL + World Model 集成工具集 — look-ahead 辅助奖励优化"""

    async def get_tools(self, readonly_context=None):
        all_tools = [FunctionTool(f) for f in _SYNC_FUNCS] + [
            LongRunningFunctionTool(f) for f in _LONG_RUNNING_FUNCS
        ]
        if self.tool_filter is None:
            return all_tools
        return [
            t for t in all_tools if self._is_tool_selected(t, readonly_context)
        ]

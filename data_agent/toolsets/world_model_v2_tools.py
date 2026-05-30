"""WorldModelV2Toolset — Bishan county farmland optimization tools (Dual-Layer Geospatial Dreamer)."""

import asyncio
import json
import logging

from google.adk.tools import FunctionTool, LongRunningFunctionTool
from google.adk.tools.base_toolset import BaseToolset

logger = logging.getLogger(__name__)


def world_model_v2_status() -> str:
    """查询 World Model v2 状态（璧山区耕地布局优化模型）。

    返回模型版本、支持区域、检查点可用性等信息。

    Returns:
        JSON 字符串，包含模型状态信息。
    """
    from ..world_model_v2 import get_world_model_v2_service
    try:
        svc = get_world_model_v2_service()
        return json.dumps(svc.status(), ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def _world_model_v2_run_sync(n_episodes: str = "10", mode: str = "ppo") -> str:
    """运行 World Model v2 璧山区耕地布局优化。

    在璧山区全县 2600+ 地块上运行优化，输出优化布局和变化差异 GeoJSON 图层。

    三种推理模式：
    - "ppo"（默认，快速）：MaskablePPO 策略，每回合约 1 秒，坡度改善约 -0.335%
    - "dream_v5"（中等速度，中等质量）：Contrastive dream-trained PPO，
      每回合约 4 秒，坡度改善约 -0.859%（比 PPO 好 2.6 倍）
    - "mpc"（最高质量，慢速）：Contrastive 世界模型 + MPC 规划，每回合约 230 秒，
      坡度改善 -1.286% ± 0.079%（5-seed 统计，单次 -1.4235%，比 PPO 好约 3.8 倍，
      比 MPC baseline 好 6.2 倍，p < 10⁻⁴）

    Args:
        n_episodes: 评估回合数（1-50），取最佳回合结果。默认 10。
        mode: 推理模式，"ppo"、"dream_v5" 或 "mpc"。默认 "ppo"。

    Returns:
        JSON 字符串，包含优化结果摘要（总奖励、坡度改善、连片度改善等）。
        GeoJSON 图层自动推送到地图面板。
    """
    from ..world_model_v2 import get_world_model_v2_service
    try:
        svc = get_world_model_v2_service()
        n = max(1, min(50, int(n_episodes)))
        mode_str = str(mode).strip().lower() or "ppo"
        result = svc.run_optimization(n_episodes=n, mode=mode_str)

        map_config = result.pop("map_config", None)
        if map_config:
            try:
                from ..user_context import current_user_id
                from ..frontend_api import pending_map_updates, _pending_lock
                uid = current_user_id.get("admin")
                with _pending_lock:
                    pending_map_updates[uid] = map_config
            except Exception as e:
                logger.warning("Failed to push map update from tool: %s", e)

        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


async def world_model_v2_run(n_episodes: str = "10", mode: str = "ppo") -> str:
    """运行 World Model v2 璧山区耕地布局优化。

    在璧山区全县 2600+ 地块上运行优化，输出优化布局和变化差异 GeoJSON 图层。

    三种推理模式：
    - "ppo"（默认，快速）：PPO 策略，每回合约 1 秒
    - "dream_v5"（中等）：Contrastive dream-trained PPO，每回合约 4 秒，比 PPO 好 2.6 倍
    - "mpc"（高质量，慢速）：Contrastive 世界模型 + MPC 规划，每回合约 230 秒，
      5-seed 统计坡度改善 -1.286% ± 0.079%（p < 10⁻⁴）

    Args:
        n_episodes: 评估回合数（1-50）。默认 10。
        mode: 推理模式，"ppo"、"dream_v5" 或 "mpc"。默认 "ppo"。

    Returns:
        JSON 字符串，包含优化结果摘要。GeoJSON 图层自动推送到地图面板。
    """
    return await asyncio.to_thread(_world_model_v2_run_sync, n_episodes, mode)


world_model_v2_run.__name__ = "world_model_v2_run"
world_model_v2_run.__qualname__ = "world_model_v2_run"


_SYNC_FUNCS = [world_model_v2_status]
_LONG_RUNNING_FUNCS = [world_model_v2_run]


class WorldModelV2Toolset(BaseToolset):
    """璧山区耕地布局优化工具集 — Dual-Layer Geospatial Dreamer (v2)"""

    async def get_tools(self, readonly_context=None):
        all_tools = [FunctionTool(f) for f in _SYNC_FUNCS] + [
            LongRunningFunctionTool(f) for f in _LONG_RUNNING_FUNCS
        ]
        if self.tool_filter is None:
            return all_tools
        return [
            t for t in all_tools if self._is_tool_selected(t, readonly_context)
        ]

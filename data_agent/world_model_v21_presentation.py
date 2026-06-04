"""Presentation helpers for World Model v2.1 chat responses."""

from __future__ import annotations

import json
import os
from typing import Any


def parse_world_model_v21_tool_response(value: Any) -> dict[str, Any] | None:
    """Return the planning result dict from common ADK tool response shapes."""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            return parse_world_model_v21_tool_response(json.loads(value))
        except (json.JSONDecodeError, TypeError):
            return None
    if not isinstance(value, dict):
        return None

    if isinstance(value.get("summary"), dict) and value.get("status"):
        return value

    for key in ("result", "output", "response", "content"):
        if key in value:
            nested = parse_world_model_v21_tool_response(value[key])
            if nested:
                return nested
    return None


def _fmt_number(value: Any, digits: int = 2) -> str:
    if value is None:
        return "-"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:.{digits}f}"


def _artifact_names(artifacts: dict[str, Any]) -> str:
    names: list[str] = []
    for key in ("summary_json", "land_use_npy", "optimized_shp", "map_layer"):
        value = artifacts.get(key)
        if not value:
            continue
        names.append(os.path.basename(str(value)))
    return ", ".join(names) if names else "-"


def format_world_model_v21_result_for_chat(
    result: dict[str, Any],
    tool_args: dict[str, Any] | None = None,
) -> str:
    """Build a deterministic Chinese summary for the WorldModelV21 direct agent."""
    summary = result.get("summary") or {}
    artifacts = result.get("artifacts") or {}
    args = tool_args or {}
    map_update = result.get("map_update") or result.get("map_config") or {}
    layers = map_update.get("layers") if isinstance(map_update, dict) else []
    layer_name = layers[0].get("name") if layers else "World Model v2.1 optimized"

    horizon = args.get("horizon") or summary.get("horizon") or "-"
    top_k = args.get("top_k") or summary.get("top_k") or "-"
    env_kind = result.get("env_kind", "-")
    metric_lines = [
        f"- Steps Run: {_fmt_number(summary.get('steps_run'))}（环境实际执行步数）",
        f"- Horizon: {horizon}（MPC 前瞻步长）",
        f"- Top K: {top_k}（每步候选动作数）",
        f"- N Blocks: {_fmt_number(summary.get('n_blocks'))}",
    ]
    if summary.get("n_selected") is not None:
        metric_lines.append(f"- N Selected: {_fmt_number(summary.get('n_selected'))}")
    if summary.get("swaps_completed") is not None:
        metric_lines.append(f"- Swaps Completed: {_fmt_number(summary.get('swaps_completed'))}")
    if summary.get("slope_change_pct") is not None:
        metric_lines.append(f"- Slope Change: {_fmt_number(summary.get('slope_change_pct'), 4)}%")
    if summary.get("cont_change") is not None:
        metric_lines.append(f"- Contiguity Change: {_fmt_number(summary.get('cont_change'), 4)}")
    if summary.get("baimu_area_change_ha") is not None:
        metric_lines.append(f"- Baimu Area Change: {_fmt_number(summary.get('baimu_area_change_ha'), 2)} ha")
    metric_lines.extend([
        f"- Total Reward: {_fmt_number(summary.get('total_reward'))}",
        f"- Artifacts: {_artifact_names(artifacts)}",
    ])

    if env_kind == "county":
        map_description = (
            f"右侧地图展示 `{layer_name}` 图层，按优化后的地类字段 `OPT_DLBM` 分类显示；"
            "黄色代表 011（耕地），绿色代表 031（林地）。"
        )
    else:
        map_description = (
            f"右侧地图展示 `{layer_name}` 图层，绿色代表 MPC selected（选中的决策单元），"
            "灰色代表 Not selected（未选中的单元）。"
        )

    return "\n".join([
        "已成功完成。",
        "",
        "状态摘要：",
        f"- Status: {result.get('status', '-')}",
        f"- Version: {result.get('version', '-')}",
        f"- Mode: {result.get('mode', '-')}",
        f"- Env Kind: {env_kind}",
        *metric_lines,
        "",
        "地图说明：",
        map_description,
        "",
        "工具调用轨迹：",
        "world_model_v21_status -> world_model_v21_plan",
    ])

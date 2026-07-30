"""Presentation helpers for the county farmland planning agent."""

from __future__ import annotations

import json
import os
from typing import Any

PUBLIC_AGENT_NAME = "县域耕地规划 Agent"
PUBLIC_ENGINE_NAME = "县域耕地空间优化引擎"


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

    if value.get("mode") == "pipeline_a_to_d" and isinstance(value.get("plan_result"), dict):
        return value

    if isinstance(value.get("summary"), dict) and value.get("status"):
        return value

    for key in ("plan_result", "result", "output", "response", "content"):
        if key in value:
            nested = parse_world_model_v21_tool_response(value[key])
            if nested:
                return nested
    return None


def parse_structured_tool_response(value: Any) -> dict[str, Any] | None:
    """Return a JSON object from common ADK function-response wrappers."""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            return parse_structured_tool_response(json.loads(value))
        except (json.JSONDecodeError, TypeError):
            return None
    if not isinstance(value, dict):
        return None
    for key in ("result", "output", "response", "content"):
        if key in value:
            nested = parse_structured_tool_response(value[key])
            if nested is not None:
                return nested
    return value


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


def _fmt_duration(value: Any) -> str:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return ""
    if seconds < 0:
        return ""
    if seconds < 0.1:
        return f"{seconds:.3f} 秒"
    return f"{seconds:.1f} 秒"


def _artifact_names(artifacts: dict[str, Any]) -> str:
    names: list[str] = []
    for key in ("summary_json", "land_use_npy", "optimized_shp", "map_layer"):
        value = artifacts.get(key)
        if value:
            names.append(os.path.basename(str(value)))
    return "、".join(names) if names else "-"


def _step_status(value: Any) -> str:
    status = str(value or "ok")
    labels = {
        "skipped_reused": "已复用（未重复执行）",
        "ok": "完成",
        "ready": "就绪",
        "committed": "已写入",
        "passed": "通过",
        "failed": "失败",
        "error": "失败",
    }
    return labels.get(status, status)


def _normalize_trace(tool_trace: list[Any] | None) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for entry in tool_trace or []:
        if isinstance(entry, str):
            normalized.append({"tool_name": entry})
            continue
        if not isinstance(entry, dict):
            continue
        tool_name = entry.get("tool_name") or entry.get("name")
        if not tool_name:
            continue
        normalized.append({
            "tool_name": str(tool_name),
            "duration_s": entry.get("duration_s", entry.get("duration")),
            "status": entry.get("status"),
            "is_error": bool(entry.get("is_error", False)),
        })
    return normalized


def _trace_duration(trace: list[dict[str, Any]], names: set[str]) -> float | None:
    values: list[float] = []
    for entry in trace:
        if entry.get("tool_name") not in names:
            continue
        try:
            values.append(float(entry.get("duration_s")))
        except (TypeError, ValueError):
            continue
    return sum(values) if values else None


def _has_reused_pipeline_stages(result: dict[str, Any]) -> bool:
    return any(
        isinstance(step, dict) and step.get("status") == "skipped_reused"
        for step in result.get("steps") or []
    )


def _tool_trace_lines(
    trace: list[dict[str, Any]],
    *,
    result: dict[str, Any],
    status_result: dict[str, Any] | None,
    audit_result: dict[str, Any] | None,
    commit_result: dict[str, Any] | None,
) -> list[str]:
    finals_status = (status_result or {}).get("finals") or {}
    version_compatible = finals_status.get("version_compatible")
    reused = _has_reused_pipeline_stages(result)
    audit_passed = bool(audit_result and audit_result.get("hard_constraint_passed"))
    committed = bool(commit_result and commit_result.get("status") == "committed")

    descriptions = {
        "world_model_v21_status": (
            "观察版本与运行状态",
            "版本兼容" if version_compatible is True else "状态检查完成",
        ),
        "paper9_inspect_resources": (
            "检查规划资源",
            "数据与模型资源可复用" if reused else "资源检查完成",
        ),
        "paper9_recall_verified_episodes": (
            "召回已验证经验",
            "读取同作用域经验作为规划上下文",
        ),
        "world_model_v21_prepare": ("准备空间状态", "数据准备完成"),
        "world_model_v21_sample": ("生成转移样本", "样本生成完成"),
        "world_model_v21_train": ("训练状态转移模型", "模型训练完成"),
        "world_model_v21_pipeline": (
            "根据资源状态选择快速 MPC 路径",
            "复用准备与训练产物，执行空间规划" if reused else "执行 A/B/C/D 规划链",
        ),
        "world_model_v21_plan": ("选择 MPC 空间规划", "完成候选行动搜索"),
        "paper9_audit_run": (
            "检查面积、坡度、连片度与空间产物",
            "硬约束审计通过" if audit_passed else "硬约束审计未通过",
        ),
        "paper9_commit_verified_episode": (
            "根据审计结果决定是否写入经验",
            "已写入已验证经验库" if committed else "未写入经验库",
        ),
    }

    lines: list[str] = []
    for index, entry in enumerate(trace, start=1):
        name = str(entry.get("tool_name"))
        action, outcome = descriptions.get(name, ("执行领域函数", "调用完成"))
        if entry.get("is_error"):
            outcome = "调用失败"
        duration = _fmt_duration(entry.get("duration_s"))
        duration_text = f" · {duration}" if duration else ""
        lines.append(
            f"{index}. **{action}** → {outcome} · `{name}`{duration_text}"
        )
    return lines


def format_world_model_v21_progress_for_chat(
    result: dict[str, Any],
    pipeline_label: str = "@WorldModelV21",
    audit_result: dict[str, Any] | None = None,
    commit_result: dict[str, Any] | None = None,
    tool_trace: list[Any] | None = None,
    total_duration_s: float | None = None,
) -> str:
    """Build a concise Chinese progress summary for direct planning runs."""
    del pipeline_label
    step_labels = {
        "prepare": "A / 数据准备",
        "sample": "B / 样本生成",
        "train": "C / 状态转移模型训练",
        "plan": "D / MPC 规划执行",
    }
    lines = [f"**{PUBLIC_AGENT_NAME}** · Gemma 4 + Google ADK 受控自主闭环", ""]
    if result.get("mode") == "pipeline_a_to_d":
        for step in result.get("steps") or []:
            if not isinstance(step, dict):
                continue
            key = str(step.get("step") or "-")
            status = step.get("status") or step.get("mode") or "ok"
            lines.append(f"✓ {step_labels.get(key, key)}：{_step_status(status)}")
    else:
        lines.append("✓ MPC 规划执行：完成")

    if audit_result:
        passed = bool(audit_result.get("hard_constraint_passed"))
        lines.append(f"✓ 硬约束审计：{'通过' if passed else '未通过'}")
    if commit_result:
        lines.append(f"✓ 已验证经验库：{_step_status(commit_result.get('status'))}")

    trace = _normalize_trace(tool_trace)
    if trace:
        lines.append(f"原生函数调用：{len(trace)} 次")
    duration = _fmt_duration(total_duration_s)
    if duration:
        lines.append(f"总用时：{duration}")
    return "\n".join(lines)


def format_world_model_v21_result_for_chat(
    result: dict[str, Any],
    tool_args: dict[str, Any] | None = None,
    status_result: dict[str, Any] | None = None,
    audit_result: dict[str, Any] | None = None,
    commit_result: dict[str, Any] | None = None,
    tool_trace: list[Any] | None = None,
    total_duration_s: float | None = None,
) -> str:
    """Build an evidence-backed Chinese summary for the county planning agent."""
    is_pipeline = (
        result.get("mode") == "pipeline_a_to_d"
        and isinstance(result.get("plan_result"), dict)
    )
    plan_result = result.get("plan_result") if is_pipeline else result
    if not isinstance(plan_result, dict):
        plan_result = {}

    summary = plan_result.get("summary") or {}
    artifacts = plan_result.get("artifacts") or {}
    args = tool_args or {}
    trace = _normalize_trace(tool_trace)
    audit_passed = bool(audit_result and audit_result.get("hard_constraint_passed"))
    memory_committed = bool(commit_result and commit_result.get("status") == "committed")

    if audit_result is None:
        title = "### 规划结果尚未完成审计"
        headline = "该结果不得作为成功方案，也不会写入已验证经验库。"
    elif not audit_passed:
        title = "### 县域耕地规划已停止"
        headline = "规划未通过硬约束审计，系统已按受控策略停止。"
    elif not memory_committed:
        title = "### 规划已通过审计，尚未写入经验"
        headline = "只有经验提交成功后，才算完成本次受控自主闭环。"
    else:
        title = "### 县域耕地受控规划完成"
        headline = "硬约束审计通过后，已写入已验证经验库。"

    lines = [title, "", headline]
    if trace:
        lines.extend(["", f"**Gemma 4 + Google ADK** · {len(trace)} 次原生函数调用"])

    planning_duration = _trace_duration(
        trace,
        {"world_model_v21_pipeline", "world_model_v21_plan"},
    )
    governance_duration = _trace_duration(
        trace,
        {"paper9_audit_run", "paper9_commit_verified_episode"},
    )
    duration_parts: list[str] = []
    if _fmt_duration(total_duration_s):
        duration_parts.append(f"总用时 {_fmt_duration(total_duration_s)}")
    if _fmt_duration(planning_duration):
        duration_parts.append(f"MPC 规划 {_fmt_duration(planning_duration)}")
    if _fmt_duration(governance_duration):
        duration_parts.append(f"审计与经验提交 {_fmt_duration(governance_duration)}")
    if duration_parts:
        lines.extend(["", "**运行耗时**：" + " · ".join(duration_parts)])

    lines.extend(["", "#### 受控自主决策轨迹"])
    trace_lines = _tool_trace_lines(
        trace,
        result=result,
        status_result=status_result,
        audit_result=audit_result,
        commit_result=commit_result,
    )
    lines.extend(trace_lines or ["未捕获完整函数调用轨迹，请查看运行日志。"])

    status_engine = (status_result or {}).get("paper9") or {}
    dataset = str(args.get("dataset") or "-")
    dataset_label = {"bishan": "璧山（bishan）", "dongxing": "东兴（dongxing）"}.get(
        dataset,
        dataset,
    )
    lines.extend([
        "",
        "#### 规划结果",
        f"- 数据集：{dataset_label}",
        f"- 规划引擎：{PUBLIC_ENGINE_NAME}（学习型状态转移模型集成 + MPC）",
        (
            "- 版本："
            f"适配器 {plan_result.get('version', result.get('version', '-'))} · "
            f"引擎包 {status_engine.get('package_version', '-')} · "
            f"算法 {status_engine.get('algorithm_version', '-')}"
        ),
        f"- 环境执行步数：{_fmt_number(summary.get('steps_run'))}",
        f"- MPC 前瞻步长：{args.get('horizon') or summary.get('horizon') or '1'}",
        f"- 每步候选行动数：{args.get('top_k') or summary.get('top_k') or '1'}",
        f"- 空间块数：{_fmt_number(summary.get('n_blocks'))}",
    ])
    if summary.get("n_parcels") is not None:
        lines.append(f"- 图斑数：{_fmt_number(summary.get('n_parcels'))}")
    if summary.get("n_selected") is not None:
        lines.append(f"- 选中决策单元：{_fmt_number(summary.get('n_selected'))}")
    if summary.get("swaps_completed") is not None:
        lines.append(f"- 完成双向置换：{_fmt_number(summary.get('swaps_completed'))} 对")
    if summary.get("cultivated_area_change_ha") is not None:
        lines.append(
            "- 耕地面积变化："
            f"{_fmt_number(summary.get('cultivated_area_change_ha'), 4)} ha"
        )
    if summary.get("slope_change_pct") is not None:
        lines.append(f"- 平均坡度变化：{_fmt_number(summary.get('slope_change_pct'), 4)}%")
    if summary.get("cont_change") is not None:
        lines.append(f"- 连片度变化：{_fmt_number(summary.get('cont_change'), 4)}")
    if summary.get("baimu_area_change_ha") is not None:
        lines.append(
            "- 百亩方面积变化："
            f"{_fmt_number(summary.get('baimu_area_change_ha'), 2)} ha"
        )
    if summary.get("total_reward") is not None:
        lines.append(f"- 总奖励：{_fmt_number(summary.get('total_reward'))}")
    lines.append(f"- 交付成果：{_artifact_names(artifacts)}")

    if is_pipeline:
        step_labels = {
            "prepare": "A / 数据准备",
            "sample": "B / 样本生成",
            "train": "C / 状态转移模型训练",
            "plan": "D / MPC 规划执行",
        }
        lines.extend(["", "#### 算法阶段"])
        for step in result.get("steps") or []:
            if not isinstance(step, dict):
                continue
            key = str(step.get("step") or "-")
            status = step.get("status") or step.get("mode") or "ok"
            lines.append(f"- {step_labels.get(key, key)}：{_step_status(status)}")

    lines.extend(["", "#### 治理结果"])
    if audit_result:
        lines.append(f"- 硬约束校验：{'通过' if audit_passed else '未通过'}")
        lines.append(
            "- 下一动作："
            + (
                "写入已验证经验"
                if audit_result.get("next_action") == "commit_verified_episode"
                else "停止并转人工复核"
            )
        )
        audit_path = audit_result.get("audit_path")
        if audit_path:
            lines.append(f"- 审计证据：{os.path.basename(str(audit_path))}")
        if audit_result.get("failure_reasons"):
            lines.append("- 未通过原因：" + "；".join(audit_result["failure_reasons"]))
    else:
        lines.append("- 硬约束校验：未捕获")
    if commit_result:
        episode = commit_result.get("episode") or {}
        lines.extend([
            f"- 已验证经验库：{_step_status(commit_result.get('status'))}",
            f"- 经验编号：{episode.get('episode_id', '-')}",
        ])
    else:
        lines.append("- 已验证经验库：未写入")

    map_update = plan_result.get("map_update") or plan_result.get("map_config") or {}
    layers = map_update.get("layers") if isinstance(map_update, dict) else []
    if layers:
        if plan_result.get("env_kind") == "county":
            map_description = (
                "右侧地图已加载县域耕地优化结果：灰色为保持不变，"
                "红色为耕地 → 林地，绿色为林地 → 耕地。"
            )
        else:
            map_description = (
                "右侧地图已加载 MPC 决策结果：绿色为选中单元，灰色为未选中单元。"
            )
        lines.extend(["", "#### 地图", map_description])
    return "\n".join(lines)

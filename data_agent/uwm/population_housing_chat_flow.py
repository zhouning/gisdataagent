"""Deterministic chat flow for bounded population/housing optimization."""

from __future__ import annotations

import re
from typing import Any

from .population_housing_optimization_service import (
    BOUNDED_RESOURCE_PERCENT_LIMITS,
    PopulationHousingOptimizationService,
)

PROFILE_LABELS = {
    "balanced": "均衡方案",
    "fiscal": "财政优先方案",
    "commute": "通勤优先方案",
    "resident": "居民住房成本优先方案",
}

RESOURCE_LABELS = {
    "budget": "公共预算",
    "supply": "新增住房能力",
    "service": "公共服务扩容能力",
    "relocation": "全局跨区上限",
}

RESOURCE_ALIASES = {
    "budget": ("公共预算", "预算"),
    "supply": ("最大新增住房", "新增住房能力", "住房供给", "新增住房"),
    "service": ("服务扩容能力", "公共服务扩容", "服务扩容"),
    "relocation": ("全局跨区上限", "跨区上限", "跨区比例"),
}


def is_population_housing_chat_message(text: str) -> bool:
    normalized = str(text or "").strip().lower()
    mentions = ("@人口住房", "@人口与住房", "@住房配置", "@人口住房配置")
    if any(marker in normalized for marker in mentions):
        return True
    return any(
        phrase in normalized
        for phrase in (
            "人口住房配置",
            "人口与住房空间配置",
            "人口住房空间优化",
            "人口与住房优化",
        )
    )


def is_population_housing_followup(text: str) -> bool:
    normalized = str(text or "").strip().lower()
    return any(
        phrase in normalized
        for phrase in (
            "为什么不可行",
            "解释不可行",
            "发送到地图",
            "发到地图",
            "显示在地图",
        )
    )


def _profile_id(text: str) -> str:
    if "财政" in text:
        return "fiscal"
    if "通勤" in text:
        return "commute"
    if any(marker in text for marker in ("居住成本", "居民住房成本")):
        return "resident"
    return "balanced"


def _resource_percentages(text: str) -> dict[str, float]:
    resources = {"budget": 100.0, "supply": 100.0, "service": 100.0, "relocation": 20.0}
    for name, aliases in RESOURCE_ALIASES.items():
        alias_pattern = "|".join(re.escape(alias) for alias in aliases)
        match = re.search(
            rf"(?:{alias_pattern})[^0-9%]{{0,16}}([0-9]+(?:\.[0-9]+)?)\s*%",
            text,
        )
        if match:
            resources[name] = float(match.group(1))
    return resources


def build_population_housing_chat_draft(text: str) -> dict[str, Any]:
    normalized = str(text or "").strip()
    resources = _resource_percentages(normalized)
    blockers = []
    for name, value in resources.items():
        minimum, maximum = BOUNDED_RESOURCE_PERCENT_LIMITS[name]
        if value < minimum or value > maximum:
            blockers.append(
                f"{name}_percentage_outside_range::{value}::{minimum}::{maximum}"
            )

    has_solve_intent = any(
        marker in normalized
        for marker in (
            "重算",
            "求解",
            "运行",
            "计算",
            "方案",
            "%",
            "调整",
            "设为",
            "降到",
            "提高到",
        )
    )
    operation = "solve" if has_solve_intent else "show_default"
    if any(marker in normalized for marker in ("发送到地图", "发到地图", "显示在地图")):
        operation = "show_default"

    return {
        "schema": "uwm.population_housing_optimization.chat_draft.v1",
        "operation": operation,
        "profile_id": _profile_id(normalized),
        "profile_label": PROFILE_LABELS[_profile_id(normalized)],
        "resources_percent": resources,
        "blockers": blockers,
        "confirmation_required": operation == "solve",
        "input_transport": "verified_snapshot_plus_bounded_parameters",
        "full_input_sent_to_language_model": False,
        "empirical_policy_optimality_claim": False,
    }


def format_population_housing_chat_draft(draft: dict[str, Any]) -> str:
    resources = draft.get("resources_percent") or {}
    return (
        "## 人口与住房配置请求确认\n\n"
        f"- 目标方案：**{draft.get('profile_label')}**\n"
        f"- 公共预算：{resources.get('budget')}%\n"
        f"- 新增住房能力：{resources.get('supply')}%\n"
        f"- 公共服务扩容能力：{resources.get('service')}%\n"
        f"- 全局跨区上限：{resources.get('relocation')}%\n\n"
        "### 数据与方法\n\n"
        "系统将读取已做哈希校验的当前行政空间单元代理场景。人口总量是拟合代理；"
        "家庭结构、住房与服务容量、通勤和成本是情景假设。请求只传递方案标识和四个百分比参数，"
        "不会把完整输入交给语言模型。确认后由 SciPy/HiGHS 混合整数规划求解，"
        "不是由语言模型生成配置数值。\n\n"
        "> 输出只支持聚合代理情景比较，不构成政策建议、财政承诺或个人住房分配。"
    )


def execute_population_housing_chat_draft(
    draft: dict[str, Any],
    *,
    service: PopulationHousingOptimizationService,
    actor_id: str,
) -> dict[str, Any]:
    if draft.get("blockers"):
        raise ValueError("population-housing chat draft has blockers")
    if draft.get("operation") != "solve":
        portfolio = service.default_portfolio()
        result = next(
            (
                row
                for row in portfolio.get("results") or []
                if row.get("profile_id") == "balanced"
            ),
            (portfolio.get("results") or [{}])[0],
        )
        return {
            "portfolio": portfolio,
            "result": result,
            "profile_id": "balanced",
            "profile_label": PROFILE_LABELS["balanced"],
            "resources_percent": {
                "budget": 100.0,
                "supply": 100.0,
                "service": 100.0,
                "relocation": 20.0,
            },
            "execution_mode": "verified_frozen_result",
        }

    portfolio = service.solve_bounded_scenario(
        profile_id=str(draft.get("profile_id")),
        resources=dict(draft.get("resources_percent") or {}),
        actor=actor_id,
    )
    return {
        "portfolio": portfolio,
        "result": (portfolio.get("results") or [{}])[0],
        "profile_id": draft.get("profile_id"),
        "profile_label": draft.get("profile_label"),
        "resources_percent": draft.get("resources_percent"),
        "execution_mode": "confirmed_bounded_live_solve",
    }


def population_housing_result_map_update(
    run: dict[str, Any],
    service: PopulationHousingOptimizationService,
) -> dict[str, Any]:
    return service.map_update(
        dict(run.get("result") or {}),
        title="人口与住房空间配置优化",
        profile_label=str(run.get("profile_label") or "当前方案"),
    )


def format_population_housing_result(run: dict[str, Any]) -> str:
    result = run.get("result") or {}
    metrics = result.get("metrics") or {}
    costs = metrics.get("costs") or {}
    resources = run.get("resources_percent") or {}
    status = result.get("status")
    if status == "infeasible":
        return (
            "## 人口与住房配置结果：不可行\n\n"
            f"- 方案：{run.get('profile_label')}\n"
            f"- 公共预算 / 新增住房 / 服务扩容 / 跨区上限："
            f"{resources.get('budget')}% / {resources.get('supply')}% / "
            f"{resources.get('service')}% / {resources.get('relocation')}%\n"
            "- 系统没有放松硬约束，也没有伪造配置结果。\n\n"
            "这表示当前代理资源组合无法同时满足家庭守恒、住房容量、服务容量、预算和跨区上限。"
            "可调整受限参数后重新确认求解。"
        )

    return (
        f"## 人口与住房配置完成：{run.get('profile_label')}\n\n"
        f"- 配置家庭：**{int(metrics.get('assigned_households') or 0):,} 户**\n"
        f"- 跨区配置：{int(metrics.get('relocated_households') or 0):,} 户\n"
        f"- 新增住房代理：{int(metrics.get('new_units') or 0):,} 套\n"
        f"- 公共服务扩容代理：{float(metrics.get('service_expansion') or 0):,.2f}\n"
        f"- 公共成本代理：{float(costs.get('public_cost') or 0):,.2f}\n"
        f"- 约束审计：{(result.get('constraint_summary') or {}).get('passed')}/"
        f"{(result.get('constraint_summary') or {}).get('constraint_count')} 通过\n\n"
        "### 数据与方法边界\n\n"
        "结果来自哈希校验后的代理场景和 HiGHS 混合整数规划；行政区面与跨区配置流已发送到中间地图。"
        "流线表示聚合模型关系，不是实际搬迁路线。该结果不证明现实政策最优、财政节省或个人福利改善。"
    )


def format_population_housing_infeasible_explanation(run: dict[str, Any]) -> str:
    result = run.get("result") or {}
    if result.get("status") != "infeasible":
        return "上一轮人口与住房配置不是不可行状态，无需生成不可行解释。"
    resources = run.get("resources_percent") or {}
    reasons = []
    if float(resources.get("supply") or 0) == 0:
        reasons.append("新增住房能力被设为 0%，而冻结可行方案需要新增住房代理套数")
    if float(resources.get("service") or 0) == 0:
        reasons.append("公共服务扩容能力被设为 0%，可能无法覆盖配置后的服务需求")
    if float(resources.get("relocation") or 0) == 0:
        reasons.append("跨区上限被设为 0%，空间单元之间不能调剂住房容量")
    if float(resources.get("budget") or 100) <= 35:
        reasons.append("公共预算处于允许范围下限，可能无法承担住房和服务行动成本")
    if not reasons:
        reasons.append("住房、服务、预算或跨区约束的组合没有共同可行域")
    return (
        "## 不可行原因说明\n\n"
        + "\n".join(f"- {reason}。" for reason in reasons)
        + "\n\n约束审计不会把不可行解释成系统错误，也不会自动放松硬约束。"
        "这是代理场景的可行域诊断，不是现实住房短缺判断。"
    )


__all__ = [
    "PROFILE_LABELS",
    "build_population_housing_chat_draft",
    "execute_population_housing_chat_draft",
    "format_population_housing_chat_draft",
    "format_population_housing_infeasible_explanation",
    "format_population_housing_result",
    "is_population_housing_chat_message",
    "is_population_housing_followup",
    "population_housing_result_map_update",
]

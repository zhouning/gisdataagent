"""Gemma4-backed natural-language parser for UWM planning scenarios."""

from __future__ import annotations

import json
import re
from time import perf_counter
from typing import Any

from data_agent.intent_router import _get_router_model, _route_via_litellm

from .service import DEFAULT_ACTION_TYPES, DEFAULT_FOCUS_UNIT


ACTION_ALIASES = {
    "increase_green_infrastructure": "increase_green_infrastructure",
    "traffic_emission_control": "traffic_emission_control",
    "add_community_service": "add_community_service",
}


def _extract_json(text: str) -> dict[str, Any]:
    cleaned = str(text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL | re.IGNORECASE)
    if fenced:
        cleaned = fenced.group(1)
    else:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            cleaned = cleaned[start : end + 1]
    parsed = json.loads(cleaned)
    if not isinstance(parsed, dict):
        raise ValueError("Gemma4返回结果不是JSON对象")
    return parsed


def _prompt(user_text: str) -> str:
    return f"""你是GIS Data Agent中UWM多阶段城市干预规划的场景解析器。
用户已经通过@UWM规划明确选择了UWM能力；你不要重新分类到其他能力，只解析@之后的业务语义。

只输出一个JSON对象，不要Markdown，不要解释。字段如下：
{{
  "intent": "UWM_MULTISTAGE_PLANNING",
  "county": null或用户明确提到的区县名称,
  "township": null或用户明确提到的街道/乡镇名称,
  "neighborhood_hops": null或0到3整数,
  "horizon": null或2或3,
  "action_types": [],
  "excluded_action_types": [],
  "objectives": [],
  "uncertainty_preference": "conservative"或"balanced"或"exploratory",
  "explicit_constraints": [],
  "missing_information": [],
  "summary": "一句中文复述"
}}

action_types只允许以下值：
- increase_green_infrastructure：增绿、降温、绿地或绿色基础设施
- traffic_emission_control：交通减排、污染治理或交通排放控制
- add_community_service：补充公共服务、社区服务、养老、教育、医疗等服务设施

规则：
1. 用户未明确区域、步数或动作时必须返回null或空数组，不得猜测。
2. “先展示当前输入状态”是执行顺序，不是规划目标。
3. “不考虑某动作”要写入excluded_action_types和explicit_constraints，且不要放入action_types。
4. 不得生成内部unit_id、数字编号、指标数值或规划结论。
5. missing_information只列真正阻止理解的问题；未指定字段允许系统采用可见默认值，不必列为缺失。

用户原文：{user_text}
"""


def parse_uwm_scenario(user_text: str, service: Any) -> dict[str, Any]:
    started = perf_counter()
    model_name = _get_router_model()
    raw, input_tokens, output_tokens = _route_via_litellm(_prompt(user_text), model_name)
    parsed = _extract_json(raw)

    county = str(parsed.get("county") or "").strip()
    township = str(parsed.get("township") or "").strip()
    resolution = service.resolve_focus_area(county=county, township=township)

    raw_actions = parsed.get("action_types") or []
    action_types = [
        ACTION_ALIASES[str(value)]
        for value in raw_actions
        if str(value) in ACTION_ALIASES
    ]
    action_types = list(dict.fromkeys(action_types))
    excluded_action_types = [
        ACTION_ALIASES[str(value)]
        for value in (parsed.get("excluded_action_types") or [])
        if str(value) in ACTION_ALIASES
    ]
    excluded_action_types = list(dict.fromkeys(excluded_action_types))
    effective_actions = action_types or [
        value for value in DEFAULT_ACTION_TYPES if value not in excluded_action_types
    ]
    if not effective_actions:
        effective_actions = list(DEFAULT_ACTION_TYPES)

    horizon = parsed.get("horizon")
    try:
        horizon = int(horizon) if horizon is not None else None
    except (TypeError, ValueError):
        horizon = None
    if horizon not in {2, 3}:
        horizon = None

    hops = parsed.get("neighborhood_hops")
    try:
        hops = int(hops) if hops is not None else 1
    except (TypeError, ValueError):
        hops = 1
    hops = max(0, min(3, hops))

    preference = str(parsed.get("uncertainty_preference") or "balanced")
    penalty_by_preference = {
        "conservative": 1.0,
        "balanced": 0.5,
        "exploratory": 0.2,
    }
    if preference not in penalty_by_preference:
        preference = "balanced"

    request = {
        "focus_unit": str(resolution.get("focus_unit") if resolution.get("focus_unit") is not None else DEFAULT_FOCUS_UNIT),
        "county": resolution.get("county_filter") or "",
        "neighborhood_hops": hops,
        "action_types": effective_actions,
        "uncertainty_penalty": penalty_by_preference[preference],
    }
    return {
        "schema": "uwm.multistage_nl_scenario_parse.v1",
        "model_called": True,
        "model": model_name,
        "latency_ms": round((perf_counter() - started) * 1000.0, 3),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "interpretation": {
            "county": county or None,
            "township": township or None,
            "horizon": horizon,
            "neighborhood_hops": hops,
            "action_types": action_types,
            "excluded_action_types": excluded_action_types,
            "objectives": [str(value) for value in (parsed.get("objectives") or [])],
            "uncertainty_preference": preference,
            "explicit_constraints": [str(value) for value in (parsed.get("explicit_constraints") or [])],
            "missing_information": [str(value) for value in (parsed.get("missing_information") or [])],
            "summary": str(parsed.get("summary") or "").strip(),
        },
        "resolution": resolution,
        "planning_request": request,
        "audit_summary": {
            "model": model_name,
            "latency_ms": round((perf_counter() - started) * 1000.0, 3),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "resolved_focus_unit": request["focus_unit"],
            "resolved_county": request["county"],
            "effective_action_types": request["action_types"],
            "parsed_horizon": horizon,
            "uncertainty_penalty": request["uncertainty_penalty"],
        },
    }

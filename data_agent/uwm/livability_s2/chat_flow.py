"""Deterministic left-chat entry for the S2 livability workflow."""

from __future__ import annotations

import re
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any


PARCEL_PATTERN = re.compile(r"parcel_[a-zA-Z0-9]+")
RADIUS_PATTERN = re.compile(r"(?<!\d)(300|500|800)\s*米")
MAP_SELECTION_PHRASES = (
    "在地图上选择地块",
    "从地图选择地块",
    "地图上选地块",
    "地图选地",
)
PARCEL_LOCATION_PHRASES = (
    "在地图上加载地块",
    "地图上加载地块",
    "加载地块",
    "在地图上定位地块",
    "地图上定位地块",
    "定位地块",
    "在地图上查看地块",
    "地图上查看地块",
    "查看地块",
    "在地图上显示地块",
    "地图上显示地块",
    "显示地块",
)

LAND_USE_LABELS = {
    "village_residential_land": "村庄住宅用地",
    "village_public_service_land": "村庄公共服务用地",
    "village_independent_construction_land": "村庄独立建设用地",
    "village_mixed_construction_land": "村庄混合建设用地",
    "unresolved": "未解析用途",
}

FACILITY_LABELS = {
    "eldercare.station": "养老服务站",
    "education.school": "学校",
    "park.public": "公共公园",
}

EVIDENCE_LABELS = {
    "text_location_only": "文字位置证据",
    "geometry_verified": "几何位置已核验",
    "unavailable": "空间证据不可用",
}

S2_MAP_STYLES = {
    "target": {"color": "#f59e0b", "weight": 4, "opacity": 1.0, "fillColor": "#fbbf24", "fillOpacity": 0.34},
    "target_marker": {"color": "#7c2d12", "weight": 3, "opacity": 1.0, "fillColor": "#facc15", "fillOpacity": 0.96, "radius": 10},
    "affected": {"color": "#64748b", "weight": 1, "opacity": 0.7, "fillColor": "#94a3b8", "fillOpacity": 0.12},
    "baseline": {"color": "#475569", "weight": 2, "opacity": 0.85, "fillColor": "#cbd5e1", "fillOpacity": 0.10, "dashArray": "7 5"},
    "intervention": {"color": "#ea580c", "weight": 3, "opacity": 0.95, "fillColor": "#fb923c", "fillOpacity": 0.20},
    "newly_covered": {"color": "#15803d", "weight": 2, "opacity": 0.95, "fillColor": "#22c55e", "fillOpacity": 0.46},
    "newly_uncovered": {"color": "#b91c1c", "weight": 2, "opacity": 0.95, "fillColor": "#ef4444", "fillOpacity": 0.46},
    "planning_resource": {"color": "#7e22ce", "weight": 2, "opacity": 0.9, "fillColor": "#c084fc", "fillOpacity": 0.18},
    "facility": {"color": "#0f766e", "weight": 2, "opacity": 1.0, "fillColor": "#14b8a6", "fillOpacity": 0.86, "radius": 7},
}

RULE_LABELS = {
    "coverage_not_decreased": "干预后的地块覆盖代理没有下降",
    "coverage_decreased": "干预后的地块覆盖代理下降",
    "land_use_transition_requires_review": "住宅用地转公共服务用地仍需规划专业复核",
    "incomplete_facility_inventory_blocks_formal_agreement": "现状设施清单不完整，不能形成正式同意结论",
    "scenario_radius_blocks_statutory_claim": "服务半径来自用户情景假设，不能声明为法定标准",
    "critical_facility_coverage_proxy_decreases": "关键设施覆盖代理下降",
    "land_use_transition_resolved": "用途转换规则已解析",
    "required_evidence_missing_fail_closed": "必要证据缺失，系统已停止形成覆盖或审批结论",
}


def action_response_value(response: Any) -> str:
    if not isinstance(response, dict):
        return ""
    direct_value = response.get("value")
    if direct_value is not None:
        return str(direct_value)
    payload = response.get("payload")
    if isinstance(payload, dict) and payload.get("value") is not None:
        return str(payload["value"])
    return ""


def is_s2_chat_message(text: str) -> bool:
    normalized = text.strip().lower()
    return normalized.startswith("@s2") or normalized.startswith("@宜居性s2")


def is_s2_map_selection_request(text: str) -> bool:
    normalized = text.strip().lower()
    return is_s2_chat_message(text) and any(
        phrase in normalized for phrase in MAP_SELECTION_PHRASES
    )


def is_s2_parcel_location_request(text: str) -> bool:
    normalized = re.sub(r"\s+", "", text.strip().lower())
    return bool(PARCEL_PATTERN.search(text)) and any(
        re.sub(r"\s+", "", phrase) in normalized for phrase in PARCEL_LOCATION_PHRASES
    )


def s2_parcel_id(text: str) -> str:
    match = PARCEL_PATTERN.search(text)
    return match.group(0) if match else ""


def s2_map_selection_prompt_template(text: str) -> str:
    template = text.strip()
    for phrase in MAP_SELECTION_PHRASES:
        if phrase in template:
            return template.replace(phrase, "地块 {parcel_id}", 1)
    return "@S2 帮我判断地块 {parcel_id} 改成公共服务用地并新增养老服务站是否同意。"


def s2_followup_radius(text: str) -> str:
    match = RADIUS_PATTERN.search(text)
    if not match:
        return ""
    normalized = re.sub(r"\s+", "", text)
    markers = ("如果", "改成", "换成", "半径", "情景", "重算", "再算", "重新")
    return match.group(1) if any(marker in normalized for marker in markers) else ""


def build_s2_chat_draft(text: str, service: Any) -> dict[str, Any]:
    parcel_match = PARCEL_PATTERN.search(text)
    blockers = []
    parcel_id = parcel_match.group(0) if parcel_match else ""
    if not parcel_id:
        blockers.append("parcel_id_required")
        return _draft(text=text, blockers=blockers)
    try:
        parcel = service.parcel_detail(parcel_id)["parcel"]
    except ValueError:
        blockers.append("parcel_not_found")
        return _draft(text=text, parcel_id=parcel_id, blockers=blockers)

    target_class = _target_land_use(text)
    if not target_class:
        blockers.append("target_land_use_required")
    action_type, facility_class = _facility_action(text)
    if action_type == "change_land_use":
        blockers.append("facility_action_required_for_coverage_decision")
    project = _matching_project(service, parcel, facility_class)
    return _draft(
        text=text,
        parcel_id=parcel_id,
        parcel=parcel,
        action_type=action_type,
        facility_class=facility_class,
        target_land_use_class=target_class,
        planning_project=project,
        blockers=blockers,
    )


def execute_s2_chat_draft(
    draft: dict[str, Any],
    *,
    service: Any,
    actor_id: str,
    service_radius_m: float,
) -> dict[str, Any]:
    if draft.get("blockers"):
        raise ValueError("draft_invalid:" + str(draft["blockers"][0]))
    parcel = draft["parcel"]
    project = draft.get("planning_project") or {}
    return service.rollout(
        parcel_id=draft["parcel_id"],
        from_land_use_class=parcel["properties"]["current_land_use_class"],
        to_land_use_class=draft["target_land_use_class"],
        snapshot_digest=service.catalog()["snapshot_digest"],
        rationale=draft["rationale"],
        requested_at=datetime.now(timezone.utc).isoformat(),
        actor_id=actor_id,
        alternative_land_use_class=None,
        action_type=draft["action_type"],
        facility_class=draft["facility_class"],
        service_radius_m=float(service_radius_m),
        radius_evidence_source="user_scenario_assumption",
        critical_facility=False,
        planning_project_id=project.get("project_id"),
    )


def draft_map_update(draft: dict[str, Any]) -> dict[str, Any]:
    parcel = draft.get("parcel")
    payload = {
        "schema": "map_update.v1",
        "summary": {"title": "S2目标真实地块"},
        "layers": [
            {
                "name": "S2 目标真实地块",
                "type": "geojson",
                "geojsonData": {
                    "type": "FeatureCollection",
                    "features": [deepcopy(parcel)] if parcel else [],
                },
                "style": deepcopy(S2_MAP_STYLES["target"]),
            }
        ],
        "metadata": {"selected_parcel_id": draft.get("parcel_id")},
    }
    center = _feature_center(parcel)
    if center:
        payload["center"] = center
        payload["zoom"] = 15
    return payload


def parcel_location_map_update(parcel: dict[str, Any]) -> dict[str, Any]:
    properties = parcel.get("properties") or {}
    parcel_id = str(properties.get("parcel_id") or parcel.get("id") or "")
    center = _feature_center(parcel)
    layers = [
        {
            "name": "S2 目标真实地块",
            "type": "geojson",
            "geojsonData": {
                "type": "FeatureCollection",
                "features": [deepcopy(parcel)],
            },
            "style": deepcopy(S2_MAP_STYLES["target"]),
            "tooltip_fields": [
                "parcel_id",
                "planning_area_id",
                "source_land_use_name",
                "area_m2",
            ],
        }
    ]
    if center:
        layers.append(
            {
                "name": "S2 目标地块位置标记",
                "type": "geojson",
                "geojsonData": {
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "id": f"location:{parcel_id}",
                            "geometry": {"type": "Point", "coordinates": [center[1], center[0]]},
                            "properties": {
                                "parcel_id": parcel_id,
                                "planning_area_id": properties.get("planning_area_id"),
                                "source_land_use_name": properties.get("source_land_use_name"),
                                "area_m2": properties.get("area_m2"),
                            },
                        }
                    ],
                },
                "style": deepcopy(S2_MAP_STYLES["target_marker"]),
                "tooltip_fields": ["parcel_id", "planning_area_id", "source_land_use_name", "area_m2"],
            }
        )
    payload = {
        "schema": "map_update.v1",
        "summary": {"title": "S2真实地块定位"},
        "layers": layers,
        "metadata": {
            "view_mode": "s2_parcel_location",
            "selected_parcel_id": parcel_id,
            "evidence_only": True,
        },
    }
    if center:
        payload["center"] = center
        payload["zoom"] = 15
    return payload


def format_parcel_location_summary(parcel: dict[str, Any]) -> str:
    properties = parcel.get("properties") or {}
    parcel_id = str(properties.get("parcel_id") or parcel.get("id") or "unknown")
    area_m2 = float(properties.get("area_m2") or 0.0)
    return "\n".join(
        [
            "## 已在地图上加载真实地块",
            "",
            f"- 地块ID：`{parcel_id}`",
            f"- 村域：`{properties.get('planning_area_id') or 'unknown'}`",
            f"- 当前地类：{properties.get('source_land_use_name') or '未记录'}",
            f"- 当前用途编码：`{properties.get('current_land_use_class') or 'unresolved'}`",
            f"- 面积：{area_m2:.2f} 平方米",
            f"- 观测状态：`{properties.get('observability') or 'unknown'}`",
            "",
            "本次只执行真实地块检索和地图定位，**没有启动用途变更、设施覆盖或UWM反事实推演**。",
            f"如需继续分析，可直接输入：`@S2 帮我判断地块 {parcel_id} 改成公共服务用地并新增养老服务站是否同意。`",
        ]
    )


def parcel_selection_map_update(service: Any) -> dict[str, Any]:
    parcels = service.list_parcels()
    return {
        "schema": "map_update.v1",
        "summary": {"title": "S2地图选地"},
        "layers": [
            {
                "name": "S2 可选真实地块",
                "type": "polygon",
                "geojsonData": deepcopy(parcels),
                "style": {
                    "color": "#38bdf8",
                    "weight": 1,
                    "opacity": 0.8,
                    "fillColor": "#2563eb",
                    "fillOpacity": 0.12,
                },
                "tooltip_fields": [
                    "parcel_id",
                    "planning_area_id",
                    "source_land_use_name",
                    "area_m2",
                ],
            }
        ],
        "metadata": {
            "interaction_mode": "s2_parcel_selection",
            "parcel_count": len(parcels.get("features") or []),
        },
    }


def result_map_update(run: dict[str, Any]) -> dict[str, Any]:
    evidence = run.get("map_evidence") or {}
    layer_specs = [
        ("S2 目标真实地块", "target_parcel", "target"),
        ("S2 受影响地块", "affected_parcels", "affected"),
        ("S2 基线服务范围", "baseline_service_areas", "baseline"),
        ("S2 干预服务范围", "intervention_service_areas", "intervention"),
        ("S2 新增覆盖地块", "newly_covered_parcels", "newly_covered"),
        ("S2 失去覆盖地块", "newly_uncovered_parcels", "newly_uncovered"),
        ("S2 规划资源证据", "planning_resources", "planning_resource"),
        ("S2 设施证据", "facilities", "facility"),
    ]
    payload = {
        "schema": "map_update.v1",
        "summary": {"title": "S2覆盖与UWM反事实结果"},
        "layers": [
            {
                "name": name,
                "type": "geojson",
                "geojsonData": deepcopy(
                    evidence.get(key) or {"type": "FeatureCollection", "features": []}
                ),
                "style": deepcopy(S2_MAP_STYLES[style_key]),
            }
            for name, key, style_key in layer_specs
        ],
        "metadata": {
            "run_id": run.get("run_id"),
            "assessment_digest": (run.get("business_assessment") or {}).get(
                "assessment_digest"
            ),
        },
    }
    target_features = (evidence.get("target_parcel") or {}).get("features") or []
    center = _feature_center(target_features[0] if target_features else None)
    if center:
        payload["center"] = center
        payload["zoom"] = 15
    return payload


def newly_covered_map_update(run: dict[str, Any]) -> dict[str, Any]:
    payload = result_map_update(run)
    allowed = {"S2 目标真实地块", "S2 干预服务范围", "S2 新增覆盖地块"}
    payload["summary"] = {"title": "S2新增覆盖地块证据"}
    payload["layers"] = [
        layer for layer in payload["layers"] if layer.get("name") in allowed
    ]
    payload["metadata"] = {
        **payload.get("metadata", {}),
        "view_mode": "newly_covered_parcels",
    }
    return payload


def format_draft_summary(draft: dict[str, Any]) -> str:
    parcel = draft["parcel"]
    properties = parcel.get("properties") or {}
    project = draft.get("planning_project") or {}
    return (
        "### S2动作已识别\n\n"
        f"- **目标地块**：`{draft['parcel_id']}`\n"
        f"- **村域**：`{properties.get('planning_area_id')}`\n"
        f"- **当前用途**：{_label_with_code(properties.get('current_land_use_class'), LAND_USE_LABELS)}\n"
        f"- **目标用途**：{_label_with_code(draft['target_land_use_class'], LAND_USE_LABELS)}\n"
        f"- **业务动作**：新增设施\n"
        f"- **设施类别**：{_label_with_code(draft['facility_class'], FACILITY_LABELS)}\n"
        f"- **规划项目来源**：{project.get('project_name') or '未关联'}\n"
        f"- **规划项目空间证据**：{_label_with_code(project.get('spatial_evidence_status') or 'unavailable', EVIDENCE_LABELS)}\n\n"
        "目标地块已发送到中间地图。当前还需要明确本次情景的服务半径。"
    )


def format_confirmation_summary(draft: dict[str, Any], radius_value: str) -> str:
    parcel = draft["parcel"]
    properties = parcel.get("properties") or {}
    project = draft.get("planning_project") or {}
    return (
        "### 请确认S2业务动作\n\n"
        f"- 地块：`{draft['parcel_id']}`\n"
        f"- 拟议用途背景：{_label_with_code(properties.get('current_land_use_class'), LAND_USE_LABELS)} → "
        f"{_label_with_code(draft['target_land_use_class'], LAND_USE_LABELS)}\n"
        f"- 设施：{_label_with_code(draft['facility_class'], FACILITY_LABELS)}\n"
        f"- 规划项目来源：{project.get('project_name') or '未关联'}\n"
        f"- 服务半径：{radius_value}米（用户情景假设）\n"
        "- 执行边界：本次写回设施Action；土地用途变更需要独立Action，不会被静默合并。\n"
        "- 设施清单当前不完整，结果不会构成规划许可。"
    )


def format_result_summary(run: dict[str, Any]) -> str:
    assessment = run["business_assessment"]
    baseline = assessment.get("baseline") or {}
    intervention = assessment.get("intervention") or {}
    execution = run.get("execution_scope") or {}
    t2 = (((run.get("rollout") or {}).get("intervention") or {}).get("t2") or {})
    recommendation = {
        "agree": "同意",
        "conditional_agree": "有条件同意",
        "disagree": "不同意",
        "evidence_insufficient": "证据不足",
    }.get(assessment.get("recommendation"), str(assessment.get("recommendation")))
    rules = assessment.get("triggered_rules") or []
    action_type = str((assessment.get("action") or {}).get("action_type") or "")
    transition_boundary = (
        "- 本次写回的是设施Action；土地用途变更未在同一Action中执行，需单独验证和推演。\n"
        if action_type in {"add_facility", "remove_facility"}
        else "- 用途转换仍需规划专业复核。\n"
    )
    rule_lines = "\n".join(
        f"- {RULE_LABELS.get(str(rule), str(rule))}（`{rule}`）" for rule in rules
    ) or "- 未触发附加业务规则。"
    return (
        f"## S2结论：{recommendation}\n\n"
        "### GIS确定性覆盖计算\n\n"
        f"- **基线覆盖代理**：{baseline.get('covered_parcel_count', 0)}/"
        f"{baseline.get('demand_parcel_count', 0)}，{baseline.get('coverage_percent', 0)}%\n"
        f"- **干预覆盖代理**：{intervention.get('covered_parcel_count', 0)}/"
        f"{intervention.get('demand_parcel_count', 0)}，{intervention.get('coverage_percent', 0)}%\n"
        f"- **覆盖变化**：+{assessment.get('coverage_delta_percentage_points')} 个百分点\n"
        f"- **新增覆盖地块**：{len(assessment.get('newly_covered_parcel_ids') or [])} 个\n"
        "- **指标含义**：等权地块空间覆盖代理，不是人口覆盖率。\n\n"
        "### UWM反事实传播\n\n"
        "- **世界对比**：同一`t0`快照上的无行动基线世界与新增设施干预世界。\n"
        f"- **证据等级**：`{assessment.get('evidence_level')}`\n"
        f"- **业务规则版本**：`{assessment.get('business_rule_version')}`\n"
        f"- **UWM局部图**：{execution.get('rollout_node_count')} 个节点、"
        f"{execution.get('rollout_edge_count')} 条边\n"
        f"- **t2空间传播信号**：{len(t2.get('messages') or [])} 条\n"
        "- **解释边界**：空间传播信号不是新增覆盖地块数量，也不是人口迁移预测。\n\n"
        "### 触发的业务规则\n\n"
        f"{rule_lines}\n\n"
        "### 证据边界\n\n"
        "- 设施清单当前不完整。\n"
        "- 服务半径属于用户情景假设，不是法定服务标准。\n"
        f"{transition_boundary}"
        "- 本结果不是正式规划许可。\n\n"
        f"- **运行ID**：`{run.get('run_id')}`\n"
        "- **地图状态**：完整覆盖结果图层已经发送到中间地图。"
    )


def format_evidence_gap_summary(run: dict[str, Any]) -> str:
    assessment = run.get("business_assessment") or {}
    project = assessment.get("planning_project_evidence") or {}
    transition = (((run.get("rollout") or {}).get("intervention") or {}).get("action_validation") or {}).get("transition") or {}
    return (
        "## S2证据缺口\n\n"
        f"- **规划项目空间证据**：{_label_with_code(project.get('spatial_evidence_status') or 'unavailable', EVIDENCE_LABELS)}\n"
        f"- **用途转换状态**：`{transition.get('status') or 'unresolved'}`，"
        f"{'需要人工复核' if transition.get('human_review_required', True) else '无需额外复核'}。\n"
        f"- **设施清单完整性**：{'完整' if not assessment.get('completeness_warnings') else '不完整'}。\n"
        f"- **服务半径来源**：`{(assessment.get('parameters') or {}).get('radius_evidence_source')}`。\n"
        "- **人口覆盖结论**：未形成；当前是等权地块空间覆盖代理，不是人口覆盖率。\n"
        "- **正式许可结论**：未形成。"
    )


def format_run_audit_summary(run: dict[str, Any]) -> str:
    assessment = run.get("business_assessment") or {}
    rollout = run.get("rollout") or {}
    project = assessment.get("planning_project_evidence") or {}
    technical_audit = run.get("technical_audit") or {}
    classifications = technical_audit.get("world_model_classification") or {}
    stages = technical_audit.get("stage_attribution") or []
    t1_evidence = (
        stages[2].get("evidence")
        if len(stages) > 2 and isinstance(stages[2], dict)
        else {}
    )
    t2_evidence = (
        stages[3].get("evidence")
        if len(stages) > 3 and isinstance(stages[3], dict)
        else {}
    )
    attribution = technical_audit.get("result_attribution") or {}
    as_json_bool = lambda value: str(bool(value)).lower()
    return (
        "## S2运行审计\n\n"
        f"- **运行ID**：`{run.get('run_id')}`\n"
        f"- **数据快照摘要**：`{run.get('snapshot_digest')}`\n"
        f"- **反事实推演摘要**：`{rollout.get('rollout_digest')}`\n"
        f"- **业务评估摘要**：`{assessment.get('assessment_digest')}`\n"
        f"- **业务规则版本**：`{assessment.get('business_rule_version')}`\n"
        f"- **规划项目ID**：`{project.get('project_id') or '未关联'}`\n"
        f"- **持久化边界**：`{run.get('persistence_boundary')}`\n"
        f"- **正式审批声明**：`{run.get('approval_claim')}`\n\n"
        "### 地理空间世界模型归因\n\n"
        f"- **状态图 / 动作条件反事实 / 空间传播**："
        f"`{as_json_bool(classifications.get('geospatial_state_graph'))}` / "
        f"`{as_json_bool(classifications.get('action_conditioned_counterfactual'))}` / "
        f"`{as_json_bool(classifications.get('relation_aware_spatial_propagation'))}`。\n"
        f"- **t1状态语义**：`{t1_evidence.get('state_semantics')}`；"
        f"现实观测结果：`{as_json_bool(t1_evidence.get('observed_outcome'))}`。\n"
        f"- **t2空间关系信号**：`{t2_evidence.get('message_count')}` 条；"
        "其作用是空间上下文和复核信号，不是受益人口或政策效果。\n"
        f"- **覆盖代理与t2消息混同**：`{as_json_bool(attribution.get('coverage_proxy_is_not_t2_message_count'))}`。\n"
        f"- **学习转移模型 / 经验干预效果**："
        f"`{as_json_bool(classifications.get('learned_transition_model'))}` / "
        f"`{as_json_bool(classifications.get('empirical_intervention_effect'))}`。"
    )


def _target_land_use(text: str) -> str | None:
    if "公共服务" in text:
        return "village_public_service_land"
    if "独立建设" in text:
        return "village_independent_construction_land"
    return None


def _facility_action(text: str) -> tuple[str, str | None]:
    if "新增" in text and "养老" in text:
        return "add_facility", "eldercare.station"
    if "新增" in text and ("学校" in text or "教育" in text):
        return "add_facility", "education.school"
    if "新增" in text and "公园" in text:
        return "add_facility", "park.public"
    return "change_land_use", None


def _matching_project(service: Any, parcel: dict[str, Any], facility_class: str | None):
    if not facility_class:
        return None
    planning_area_id = str((parcel.get("properties") or {}).get("planning_area_id") or "")
    return next(
        (
            project
            for project in service.list_planning_projects().get("projects") or []
            if project.get("planning_area_id") == planning_area_id
            and project.get("canonical_facility_class") == facility_class
        ),
        None,
    )


def _label_with_code(value: Any, labels: dict[str, str]) -> str:
    code = str(value or "unavailable")
    label = labels.get(code, code)
    return f"{label}（`{code}`）"


def _feature_center(feature: dict[str, Any] | None) -> list[float] | None:
    geometry = (feature or {}).get("geometry") or {}
    points: list[tuple[float, float]] = []

    def collect(value: Any) -> None:
        if (
            isinstance(value, (list, tuple))
            and len(value) >= 2
            and isinstance(value[0], (int, float))
            and isinstance(value[1], (int, float))
        ):
            points.append((float(value[0]), float(value[1])))
            return
        if isinstance(value, (list, tuple)):
            for item in value:
                collect(item)

    collect(geometry.get("coordinates"))
    if not points:
        return None
    longitude = sum(point[0] for point in points) / len(points)
    latitude = sum(point[1] for point in points) / len(points)
    return [round(latitude, 7), round(longitude, 7)]


def _draft(
    *,
    text: str,
    parcel_id: str = "",
    parcel: dict[str, Any] | None = None,
    action_type: str = "change_land_use",
    facility_class: str | None = None,
    target_land_use_class: str | None = None,
    planning_project: dict[str, Any] | None = None,
    blockers: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "schema": "uwm.livability_s2.chat_draft.v1",
        "parcel_id": parcel_id,
        "parcel": deepcopy(parcel),
        "action_type": action_type,
        "facility_class": facility_class,
        "target_land_use_class": target_land_use_class,
        "planning_project": deepcopy(planning_project),
        "rationale": text.strip(),
        "blockers": list(blockers or []),
    }

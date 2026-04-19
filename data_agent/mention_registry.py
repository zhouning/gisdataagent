"""Mention Registry — aggregates all invocable targets for @SubAgent routing."""
from typing import Optional

try:
    from .capabilities import list_builtin_skills
except Exception:
    list_builtin_skills = None  # type: ignore[assignment]

try:
    from .custom_skills import list_custom_skills
except Exception:
    list_custom_skills = None  # type: ignore[assignment]

_PIPELINE_TARGETS = [
    {
        "handle": "General",
        "label": "General",
        "type": "pipeline",
        "description": "通用分析与查询",
        "allowed_roles": ["admin", "analyst", "viewer"],
        "required_state_keys": [],
        "pipeline": "GENERAL",
    },
    {
        "handle": "Governance",
        "label": "Governance",
        "type": "pipeline",
        "description": "数据治理与质量审计",
        "allowed_roles": ["admin", "analyst"],
        "required_state_keys": [],
        "pipeline": "GOVERNANCE",
    },
    {
        "handle": "Optimization",
        "label": "Optimization",
        "type": "pipeline",
        "description": "空间优化与DRL布局",
        "allowed_roles": ["admin", "analyst"],
        "required_state_keys": [],
        "pipeline": "OPTIMIZATION",
    },
]

_SUB_AGENT_TARGETS = [
    {"handle": "DataExploration", "label": "DataExploration", "type": "sub_agent",
     "description": "数据探查与画像", "allowed_roles": ["admin", "analyst"],
     "required_state_keys": [], "pipeline": "OPTIMIZATION"},
    {"handle": "DataProcessing", "label": "DataProcessing", "type": "sub_agent",
     "description": "数据处理与清洗", "allowed_roles": ["admin", "analyst"],
     "required_state_keys": ["data_profile"], "pipeline": "OPTIMIZATION"},
    {"handle": "DataAnalysis", "label": "DataAnalysis", "type": "sub_agent",
     "description": "空间分析与统计", "allowed_roles": ["admin", "analyst"],
     "required_state_keys": ["processed_data"], "pipeline": "OPTIMIZATION"},
    {"handle": "DataVisualization", "label": "DataVisualization", "type": "sub_agent",
     "description": "地图渲染、图表生成、3D可视化", "allowed_roles": ["admin", "analyst"],
     "required_state_keys": ["processed_data"], "pipeline": "OPTIMIZATION"},
    {"handle": "DataSummary", "label": "DataSummary", "type": "sub_agent",
     "description": "分析结果汇总", "allowed_roles": ["admin", "analyst"],
     "required_state_keys": ["processed_data"], "pipeline": "OPTIMIZATION"},
    {"handle": "GovExploration", "label": "GovExploration", "type": "sub_agent",
     "description": "治理数据探查", "allowed_roles": ["admin", "analyst"],
     "required_state_keys": [], "pipeline": "GOVERNANCE"},
    {"handle": "GovProcessing", "label": "GovProcessing", "type": "sub_agent",
     "description": "治理数据处理", "allowed_roles": ["admin", "analyst"],
     "required_state_keys": ["data_profile"], "pipeline": "GOVERNANCE"},
    {"handle": "GovernanceReporter", "label": "GovernanceReporter", "type": "sub_agent",
     "description": "治理报告生成", "allowed_roles": ["admin", "analyst"],
     "required_state_keys": ["processed_data"], "pipeline": "GOVERNANCE"},
    {"handle": "GeneralProcessing", "label": "GeneralProcessing", "type": "sub_agent",
     "description": "通用数据处理", "allowed_roles": ["admin", "analyst", "viewer"],
     "required_state_keys": [], "pipeline": "GENERAL"},
    {"handle": "GeneralViz", "label": "GeneralViz", "type": "sub_agent",
     "description": "通用可视化", "allowed_roles": ["admin", "analyst", "viewer"],
     "required_state_keys": ["processed_data"], "pipeline": "GENERAL"},
]


def build_registry(user_id: str, role: str) -> list[dict]:
    targets = list(_PIPELINE_TARGETS) + list(_SUB_AGENT_TARGETS)
    if list_builtin_skills is not None:
        try:
            for skill in list_builtin_skills():
                targets.append({
                    "handle": skill["name"],
                    "label": skill["name"],
                    "type": "adk_skill",
                    "description": skill.get("description", ""),
                    "allowed_roles": ["admin", "analyst"],
                    "required_state_keys": [],
                    "source": "builtin",
                })
        except Exception:
            pass
    if list_custom_skills is not None:
        try:
            from .user_context import current_user_id
            prev = current_user_id.get(None)
            current_user_id.set(user_id)
            try:
                for skill in list_custom_skills(include_shared=True):
                    targets.append({
                        "handle": skill["skill_name"],
                        "label": skill["skill_name"],
                        "type": "custom_skill",
                        "description": skill.get("description", ""),
                        "allowed_roles": ["admin", "analyst"],
                        "required_state_keys": [],
                        "skill_id": skill.get("id"),
                        "user_owned": skill.get("owner_username") == user_id,
                    })
            finally:
                if prev is not None:
                    current_user_id.set(prev)
        except Exception:
            pass
    seen = set()
    unique = []
    for t in targets:
        key = t["handle"].lower()
        if key not in seen:
            seen.add(key)
            unique.append(t)
    return unique


def lookup(registry: list[dict], handle: str) -> Optional[dict]:
    handle_lower = handle.lower()
    for t in registry:
        if t["handle"].lower() == handle_lower:
            return t
    return None

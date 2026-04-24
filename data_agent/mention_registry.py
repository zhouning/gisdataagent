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
    {"handle": "General", "label": "General", "type": "pipeline",
     "description": "通用分析与查询", "allowed_roles": ["admin", "analyst", "viewer"],
     "required_state_keys": [], "pipeline": "GENERAL"},
    {"handle": "Governance", "label": "Governance", "type": "pipeline",
     "description": "数据治理与质量审计", "allowed_roles": ["admin", "analyst"],
     "required_state_keys": [], "pipeline": "GOVERNANCE"},
    {"handle": "Optimization", "label": "Optimization", "type": "pipeline",
     "description": "空间优化与DRL布局", "allowed_roles": ["admin", "analyst"],
     "required_state_keys": [], "pipeline": "OPTIMIZATION"},
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
    {"handle": "NL2SQL", "label": "NL2SQL", "type": "sub_agent",
     "description": "自然语言直达数据库查询（跳过意图路由，更快）", "allowed_roles": ["admin", "analyst"],
     "required_state_keys": [], "pipeline": "GENERAL"},
]


def _load_user_aliases(user_id: str) -> list[dict]:
    """Load alias rows for a user from DB. Returns [] if DB unavailable."""
    try:
        from .api.agent_management_routes import list_aliases_for_user
        return list_aliases_for_user(user_id)
    except Exception:
        return []


def _apply_alias_defaults(target: dict) -> dict:
    """Ensure every target has aliases/display_name/pinned/hidden fields."""
    target.setdefault("aliases", [])
    target.setdefault("display_name", "")
    target.setdefault("pinned", False)
    target.setdefault("hidden", False)
    return target


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

    # Deduplicate by handle (case-insensitive)
    seen = set()
    unique = []
    for t in targets:
        key = t["handle"].lower()
        if key not in seen:
            seen.add(key)
            unique.append(_apply_alias_defaults(dict(t)))

    # Merge DB-backed aliases/display_name/pinned/hidden
    alias_map = {row["handle"]: row for row in _load_user_aliases(user_id)}
    for t in unique:
        row = alias_map.get(t["handle"])
        if row:
            t["aliases"] = list(row.get("aliases") or [])
            t["display_name"] = row.get("display_name") or ""
            t["pinned"] = bool(row.get("pinned"))
            t["hidden"] = bool(row.get("hidden"))
    return unique


def lookup(registry: list[dict], handle: str) -> Optional[dict]:
    """Match by handle > display_name > alias (case-insensitive)."""
    q = handle.lower()
    # Priority 1: exact handle
    for t in registry:
        if t["handle"].lower() == q:
            return t
    # Priority 2: exact display_name
    for t in registry:
        if (t.get("display_name") or "").lower() == q:
            return t
    # Priority 3: alias match
    for t in registry:
        aliases = t.get("aliases") or []
        if any(a.lower() == q for a in aliases):
            return t
    return None

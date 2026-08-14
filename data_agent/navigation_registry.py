"""Governed registry and runtime policy resolution for DataPanel navigation."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from sqlalchemy import text

from .db_engine import get_engine

NAVIGATION_SCHEMA = "gda.workspace_navigation.v1"


def _items(group_key: str, section_key: str, values: list[tuple[str, str, str]]) -> list[dict[str, Any]]:
    return [
        {
            "tab_key": tab_key,
            "label": label,
            "icon": icon,
            "group_key": group_key,
            "section_key": section_key,
            "sort_order": index,
            "default_visible": True,
            "required_roles": [],
            "required_capabilities": [],
            "lifecycle_status": "active",
        }
        for index, (tab_key, label, icon) in enumerate(values)
    ]


_GROUPS: list[dict[str, Any]] = [
    {
        "key": "data",
        "label": "数据资源",
        "icon": "database",
        "sort_order": 10,
        "sections": [
            {"key": "browse", "label": "文件与数据浏览", "sort_order": 10},
            {"key": "assets", "label": "数据资产", "sort_order": 20},
            {"key": "ingest", "label": "数据接入", "sort_order": 30},
        ],
    },
    {
        "key": "semantic",
        "label": "标准与语义",
        "icon": "tags",
        "sort_order": 20,
        "sections": [
            {"key": "standards", "label": "标准体系", "sort_order": 10},
            {"key": "models", "label": "语义模型", "sort_order": 20},
            {"key": "governance", "label": "治理与审批", "sort_order": 30},
        ],
    },
    {
        "key": "analysis",
        "label": "分析与模型",
        "icon": "brain",
        "sort_order": 30,
        "sections": [
            {"key": "general", "label": "通用分析", "sort_order": 10},
            {"key": "domain", "label": "领域专题", "sort_order": 20},
            {"key": "world_models", "label": "世界模型", "sort_order": 30},
            {"key": "regional", "label": "区域与实验模型", "sort_order": 40},
        ],
    },
    {
        "key": "ops",
        "label": "运营与质量",
        "icon": "activity",
        "sort_order": 40,
        "sections": [
            {"key": "tasks", "label": "任务与流程", "sort_order": 10},
            {"key": "monitoring", "label": "运行监控", "sort_order": 20},
            {"key": "quality", "label": "质量与评估", "sort_order": 30},
        ],
    },
    {
        "key": "extensions",
        "label": "扩展能力",
        "icon": "puzzle",
        "sort_order": 50,
        "sections": [
            {"key": "agent", "label": "智能体与知识", "sort_order": 10},
            {"key": "market", "label": "市场与扩展", "sort_order": 20},
        ],
    },
]


_ITEMS = (
    _items("data", "browse", [
        ("files", "文件", "folder"), ("table", "表格", "table"),
        ("geojson", "GeoJSON", "map-pin"), ("topology", "拓扑", "network"),
    ])
    + _items("data", "assets", [
        ("catalog", "资产", "database"), ("models", "数据模型", "layout-grid"),
        ("metadata", "元数据", "tag"),
    ])
    + _items("data", "ingest", [
        ("vsources", "数据源", "link"), ("intake", "接入", "inbox"),
        ("offline_ingest", "离线入湖", "upload"),
    ])
    + _items("semantic", "standards", [
        ("standards", "领域标准", "database"), ("std_platform", "数据标准", "file-text"),
    ])
    + _items("semantic", "models", [
        ("semantic", "语义层", "tags"), ("ontology", "本体模型", "network"),
        ("ontology_demo", "本体应用", "sparkles"),
    ])
    + _items("semantic", "governance", [
        ("classification", "分级", "shield"), ("governance", "治理", "shield"),
        ("approvals", "审批中心", "inbox"),
    ])
    + _items("analysis", "general", [
        ("capabilities", "能力", "zap"), ("tools", "工具", "wrench"),
        ("charts", "图表", "bar-chart"), ("causal", "因果推理", "flask"),
        ("optimization", "优化", "target"), ("fusion_quality", "融合质量", "git-branch"),
    ])
    + _items("analysis", "domain", [
        ("traditional_livability", "城市宜居性分析（传统方法）", "bar-chart"),
        ("cultural_heritage", "文化遗产与场所", "map-pin"),
        ("cross_domain_impact", "跨领域影响与优先级", "git-branch"),
        ("implementation_roadmap", "建议与实施路线图", "list-todo"),
        ("resilience_kernel", "韧性世界模型", "shield"),
        ("digital_readiness", "数字资产与智慧片区", "database"),
        ("operations_quality", "运维与服务质量", "activity"),
        ("business_licence", "企业执照与经济活动", "store"),
        ("development_control", "开发控制规则", "shield"),
        ("financial_readiness", "财务与投资证据", "bar-chart"),
        ("public_feedback_readiness", "公众反馈证据", "thumbs-up"),
        ("spatial_scope_registry", "空间范围注册", "map-pin"),
        ("planning_version_registry", "规划与地块版本", "file-text"),
        ("parcel_state_readiness", "用地与地块状态", "map-pin"),
        ("infrastructure_network_readiness", "基础设施与市政管网", "network"),
        ("asset_lifecycle_readiness", "资产生命周期", "wrench"),
        ("population_demographic_readiness", "人口与人口结构", "pie-chart"),
        ("population_housing_optimization", "人口住房配置", "home"),
        ("ai_demand_readiness", "AI应用需求矩阵", "clipboard-check"),
    ])
    + _items("analysis", "world_models", [
        ("worldmodel", "世界模型", "globe"), ("worldmodel_v11", "世界模型v1.1 · Paper58（阿布扎比）", "globe"),
        ("worldmodel_v2", "世界模型v2", "globe"), ("worldmodel_v21", "世界模型v2.1", "globe"),
        ("irrigation_demo", "灌区世界模型", "droplets"),
        ("twm", "TWM", "shield"), ("uwm_livability", "城市宜居性分析（UWM）", "brain"),
        ("uwm_multistage", "UWM多阶段城市干预规划", "git-branch"),
    ])
    + _items("analysis", "regional", [
        ("abu_land_use_compare", "阿布扎比 · 三模型对比", "bar-chart"),
        ("abu_flus", "阿布扎比 · GeoSOS-FLUS", "layout-grid"),
        ("abu_kernel", "阿布扎比 · Geospatial Kernel", "network"),
    ])
    + _items("ops", "tasks", [
        ("tasks", "任务", "list-todo"), ("workflows", "工作流", "git-branch"),
        ("templates", "模板", "file-text"),
    ])
    + _items("ops", "monitoring", [
        ("history", "历史", "history"), ("agent_logs", "运行日志", "file-text"),
        ("alerts", "告警", "bell"), ("observability", "追踪", "activity"),
        ("messagebus", "消息总线", "radio"),
    ])
    + _items("ops", "quality", [
        ("qcmonitor", "质检", "clipboard-check"), ("usage", "用量", "gauge"),
        ("analytics", "分析", "pie-chart"), ("feedback", "反馈", "thumbs-up"),
    ])
    + _items("extensions", "agent", [
        ("agents", "智能体", "network"), ("kb", "知识库", "book-open"),
        ("memory", "记忆", "brain"), ("suggestions", "建议", "lightbulb"),
    ])
    + _items("extensions", "market", [
        ("market", "市场", "store"),
    ])
)


def _registry_items() -> list[dict[str, Any]]:
    """Return a deep copy so request-level policy resolution never mutates defaults."""
    group_labels = {group["key"]: group["label"] for group in _GROUPS}
    group_sort_orders = {group["key"]: group["sort_order"] for group in _GROUPS}
    section_labels = {
        (group["key"], section["key"]): section["label"]
        for group in _GROUPS
        for section in group["sections"]
    }
    section_sort_orders = {
        (group["key"], section["key"]): section["sort_order"]
        for group in _GROUPS
        for section in group["sections"]
    }
    items = []
    for item in deepcopy(_ITEMS):
        item["group_label"] = group_labels[item["group_key"]]
        item["group_sort_order"] = group_sort_orders[item["group_key"]]
        item["section_label"] = section_labels[(item["group_key"], item["section_key"])]
        item["section_sort_order"] = section_sort_orders[(item["group_key"], item["section_key"])]
        items.append(item)
    return items


def _policies(scope_type: str, scope_key: str) -> dict[str, dict[str, Any]]:
    engine = get_engine(readonly=True)
    if engine is None:
        return {}
    try:
        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT tab_key, visible, group_key, section_key, sort_order
                    FROM app_navigation_policies
                    WHERE scope_type = :scope_type AND scope_key = :scope_key
                    """
                ),
                {"scope_type": scope_type, "scope_key": scope_key},
            ).mappings().all()
        return {str(row["tab_key"]): dict(row) for row in rows}
    except Exception:
        return {}


def _apply_policy(item: dict[str, Any], policy: dict[str, Any] | None) -> None:
    if not policy:
        return
    if policy.get("visible") is not None:
        item["visible"] = bool(policy["visible"])
    if policy.get("group_key"):
        item["group_key"] = policy["group_key"]
    if policy.get("section_key"):
        item["section_key"] = policy["section_key"]
    if policy.get("sort_order") is not None:
        item["sort_order"] = int(policy["sort_order"])


def _refresh_location_metadata(item: dict[str, Any]) -> None:
    """Keep item location labels/order metadata aligned after policy overrides."""
    groups = {group["key"]: group for group in _GROUPS}
    group = groups.get(item["group_key"])
    if not group:
        return
    sections = {section["key"]: section for section in group["sections"]}
    section = sections.get(item["section_key"])
    if not section:
        return
    item["group_label"] = group["label"]
    item["group_sort_order"] = group["sort_order"]
    item["section_label"] = section["label"]
    item["section_sort_order"] = section["sort_order"]


def _effective_items(role: str = "analyst", tenant_id: str = "") -> list[dict[str, Any]]:
    items = _registry_items()
    global_policy = _policies("global", "default")
    tenant_policy = _policies("tenant", tenant_id) if tenant_id else {}
    role_policy = _policies("role", role) if role else {}
    for item in items:
        item["visible"] = bool(item.pop("default_visible", True))
        _apply_policy(item, global_policy.get(item["tab_key"]))
        _apply_policy(item, tenant_policy.get(item["tab_key"]))
        _apply_policy(item, role_policy.get(item["tab_key"]))
        _refresh_location_metadata(item)
    return items


def _group_payload(items: list[dict[str, Any]], *, include_hidden: bool = False) -> dict[str, Any]:
    groups = []
    for group in sorted(_GROUPS, key=lambda value: value["sort_order"]):
        group_items = [
            item for item in items
            if item["group_key"] == group["key"] and (include_hidden or item.get("visible", True))
        ]
        sections = []
        for section in sorted(group["sections"], key=lambda value: value["sort_order"]):
            section_items = [
                item for item in group_items if item["section_key"] == section["key"]
            ]
            section_items.sort(key=lambda value: (value.get("sort_order", 0), value["label"]))
            if section_items:
                sections.append({**section, "items": section_items})
        if sections:
            groups.append({**group, "sections": sections})
    return {"schema": NAVIGATION_SCHEMA, "groups": groups}


def get_effective_navigation(role: str = "analyst", tenant_id: str = "") -> dict[str, Any]:
    return _group_payload(_effective_items(role, tenant_id))


def get_admin_navigation() -> dict[str, Any]:
    items = _effective_items("admin", "")
    return {**_group_payload(items, include_hidden=True), "items": items}


def save_navigation_policies(changes: list[dict[str, Any]], updated_by: str) -> dict[str, Any]:
    known = {item["tab_key"] for item in _registry_items()}
    group_keys = {group["key"] for group in _GROUPS}
    section_keys = {
        (group["key"], section["key"])
        for group in _GROUPS
        for section in group["sections"]
    }
    prepared: list[dict[str, Any]] = []
    for change in changes:
        if not isinstance(change, dict):
            raise ValueError("each navigation item must be an object")
        tab_key = str(change.get("tab_key") or "").strip()
        if tab_key not in known:
            raise ValueError(f"unknown navigation tab: {tab_key}")
        visible = change.get("visible")
        if visible is not None and not isinstance(visible, bool):
            raise ValueError(f"navigation visible must be boolean for: {tab_key}")
        group_key = str(change.get("group_key") or "").strip() or None
        section_key = str(change.get("section_key") or "").strip() or None
        if bool(group_key) != bool(section_key):
            raise ValueError("navigation group_key and section_key must be provided together")
        if group_key and group_key not in group_keys:
            raise ValueError(f"unknown navigation group: {group_key}")
        if section_key and (group_key, section_key) not in section_keys:
            raise ValueError(f"unknown navigation section: {group_key}/{section_key}")
        sort_order = change.get("sort_order")
        if sort_order is not None:
            try:
                sort_order = max(0, int(sort_order))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"navigation sort_order must be an integer for: {tab_key}") from exc
        prepared.append({
            "tab_key": tab_key,
            "visible": visible,
            "group_key": group_key,
            "section_key": section_key,
            "sort_order": sort_order,
        })
    engine = get_engine()
    if engine is None:
        raise RuntimeError("Database not available")
    with engine.begin() as connection:
        for change in prepared:
            connection.execute(
                text(
                    """
                    INSERT INTO app_navigation_policies
                        (scope_type, scope_key, tab_key, visible, group_key,
                         section_key, sort_order, updated_by, updated_at)
                    VALUES
                        ('global', 'default', :tab_key, :visible, :group_key,
                         :section_key, :sort_order, :updated_by, NOW())
                    ON CONFLICT (scope_type, scope_key, tab_key)
                    DO UPDATE SET visible = EXCLUDED.visible,
                        group_key = EXCLUDED.group_key,
                        section_key = EXCLUDED.section_key,
                        sort_order = EXCLUDED.sort_order,
                        updated_by = EXCLUDED.updated_by,
                        updated_at = NOW()
                    """
                ),
                {
                    "tab_key": change["tab_key"],
                    "visible": change["visible"],
                    "group_key": change["group_key"],
                    "section_key": change["section_key"],
                    "sort_order": change["sort_order"],
                    "updated_by": updated_by,
                },
            )
    return get_admin_navigation()


def navigation_defaults() -> dict[str, Any]:
    return _group_payload(_effective_items("admin", ""), include_hidden=True)

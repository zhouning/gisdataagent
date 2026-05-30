"""Capability Q&A Toolset — lets the agent introspect and explain system capabilities.

Part A: ``query_capabilities`` tool for user-initiated "what can you do?" questions.
Part B: ``suggest_for_ambiguous`` helper for proactive hints on AMBIGUOUS intent.
"""
from __future__ import annotations

import re
from typing import Optional

from google.adk.tools import FunctionTool
from google.adk.tools.base_toolset import BaseToolset

from ..capabilities import list_builtin_skills, list_toolsets


_capability_index: list[dict] | None = None


_CATEGORY_DESCRIPTIONS: dict[str, str] = {
    "spatial_processing": "缓冲区、叠加、裁剪、镶嵌、聚类等空间处理 / Buffer, overlay, clip, tessellation, clustering",
    "poi_location": "POI搜索、地理编码、人口查询、行政区划 / POI search, geocoding, population, admin boundaries",
    "remote_sensing": "遥感影像处理、NDVI、DEM、流域提取 / Remote sensing, NDVI, DEM, watershed",
    "database_management": "PostGIS数据导入导出与表管理 / PostGIS import/export and table management",
    "quality_audit": "拓扑检查、字段规范、语义层注册 / Topology check, field standards, semantic layer",
    "streaming_iot": "实时数据流、地理围栏 / Real-time streaming, geofence",
    "collaboration": "团队协作、资产共享 / Team collaboration, asset sharing",
    "advanced_analysis": "时序预测、网络分析、数据融合、知识图谱 / Time series, network, fusion, knowledge graph",
    "world_model": "土地利用预测、情景模拟 / LULC prediction, scenario simulation",
    "causal_reasoning": "因果DAG、反事实推理、干预分析 / Causal DAG, counterfactual, intervention",
}


_DOMAIN_MAP: dict[str, str] = {
    "ExplorationToolset": "general",
    "GeoProcessingToolset": "spatial",
    "LocationToolset": "spatial",
    "AnalysisToolset": "analysis",
    "VisualizationToolset": "visualization",
    "DatabaseToolset": "database",
    "FileToolset": "general",
    "MemoryToolset": "general",
    "AdminToolset": "admin",
    "RemoteSensingToolset": "remote_sensing",
    "SpatialStatisticsToolset": "spatial",
    "SemanticLayerToolset": "governance",
    "StreamingToolset": "general",
    "TeamToolset": "collaboration",
    "DataLakeToolset": "database",
    "McpHubToolset": "integration",
    "FusionToolset": "analysis",
    "KnowledgeGraphToolset": "analysis",
    "KnowledgeBaseToolset": "knowledge",
    "AdvancedAnalysisToolset": "analysis",
    "SpatialAnalysisTier2Toolset": "analysis",
    "WatershedToolset": "remote_sensing",
    "UserToolset": "extension",
    "VirtualSourceToolset": "integration",
    "GovernanceToolset": "governance",
    "DataCleaningToolset": "governance",
    "ChartToolset": "visualization",
    "PrecisionToolset": "governance",
    "WorldModelToolset": "world_model",
    "CausalInferenceToolset": "causal",
    "DomainStandardToolset": "governance",
}


_EXAMPLE_PROMPTS: dict[str, str] = {
    # Toolset example prompts (by name)
    "GeoProcessingToolset": "对这个图层做500米缓冲区",
    "LocationToolset": "查找北京市朝阳区附近的医院",
    "RemoteSensingToolset": "下载重庆2020年的LULC土地利用数据",
    "SpatialStatisticsToolset": "对耕地图层做热点分析",
    "DatabaseToolset": "把这个shp导入到PostGIS",
    "GovernanceToolset": "检查这份数据的拓扑错误",
    "DataCleaningToolset": "修复图层中的重复要素",
    "FusionToolset": "把这两个数据源做语义融合",
    "KnowledgeGraphToolset": "构建关于长江流域的地理知识图谱",
    "WorldModelToolset": "预测2030年重庆的土地利用",
    "CausalInferenceToolset": "分析退耕还林对植被覆盖的因果效应",
    "ChartToolset": "画出人口分布柱状图",
    # Tool category example prompts
    "spatial_processing": "对农田图层做500米缓冲区",
    "poi_location": "查询北京所有三甲医院",
    "remote_sensing": "下载DEM并计算坡度",
    "quality_audit": "检查这份数据的拓扑一致性",
    "advanced_analysis": "对销售数据做时间序列预测",
    "world_model": "模拟2030年土地利用变化",
    "causal_reasoning": "分析政策X对指标Y的因果影响",
}


def _tokenize(text: str) -> list[str]:
    """Split text into lowercase tokens for keyword matching.

    Handles mixed Chinese/English by extracting ASCII words and keeping Chinese
    chars as individual tokens plus contiguous spans.
    """
    text = text.lower()
    # ASCII words
    ascii_tokens = re.findall(r"[a-z0-9_]+", text)
    # Chinese spans (for substring matching)
    cjk_spans = re.findall(r"[一-鿿]+", text)
    # Individual CJK chars
    cjk_chars = [c for s in cjk_spans for c in s]
    return ascii_tokens + cjk_spans + cjk_chars


def _detect_language(text: str) -> str:
    """Return 'zh' if text contains Chinese chars, else 'en'.

    Empty or whitespace-only input defaults to 'zh' (matches the platform's
    primary locale used elsewhere).
    """
    if not text or not text.strip():
        return "zh"
    if re.search(r"[一-鿿]", text):
        return "zh"
    return "en"


def _build_capability_index() -> list[dict]:
    """Merge skills, toolsets, and tool categories into a unified searchable list.

    Module-level cache — index is built once per process.
    """
    global _capability_index
    if _capability_index is not None:
        return _capability_index

    index: list[dict] = []

    # 1. Built-in skills
    try:
        for skill in list_builtin_skills():
            triggers = skill.get("intent_triggers", "") or ""
            keywords = [t.strip() for t in triggers.split(",") if t.strip()]
            index.append({
                "name": skill.get("name", ""),
                "description": skill.get("description", ""),
                "category": "skill",
                "domain": skill.get("domain", ""),
                "keywords": keywords,
                "example_prompt": keywords[0] if keywords else "",
            })
    except Exception:
        pass

    # 2. Toolsets
    try:
        for ts in list_toolsets():
            name = ts.get("name", "")
            desc = ts.get("description", "")
            index.append({
                "name": name,
                "description": desc,
                "category": "toolset",
                "domain": _DOMAIN_MAP.get(name, ""),
                "keywords": _tokenize(desc),
                "example_prompt": _EXAMPLE_PROMPTS.get(name, ""),
            })
    except Exception:
        pass

    # 3. Tool categories
    try:
        from ..tool_filter import TOOL_CATEGORIES
        for cat_name, tools in TOOL_CATEGORIES.items():
            desc = _CATEGORY_DESCRIPTIONS.get(cat_name, "")
            sample_tools = list(tools)[:5]
            index.append({
                "name": cat_name,
                "description": desc,
                "category": "tool_category",
                "domain": cat_name,
                "keywords": sample_tools + _tokenize(desc),
                "example_prompt": _EXAMPLE_PROMPTS.get(cat_name, ""),
            })
    except Exception:
        pass

    _capability_index = index
    return index


def _clear_cache() -> None:
    """Reset the module-level cache — used by tests."""
    global _capability_index
    _capability_index = None


def _score_match(query_tokens: list[str], entry: dict) -> float:
    """Return 0.0-1.0 relevance score based on token overlap with entry."""
    if not query_tokens:
        return 0.0

    haystack_parts = [
        entry.get("name", ""),
        entry.get("description", ""),
        entry.get("domain", ""),
        " ".join(entry.get("keywords", []) or []),
    ]
    haystack = " ".join(haystack_parts).lower()
    haystack_tokens = set(_tokenize(haystack))

    # Substring hits (stronger signal for Chinese queries)
    substring_hits = sum(1 for t in query_tokens if t and t in haystack)
    # Exact token overlap
    token_overlap = len(set(query_tokens) & haystack_tokens)

    combined = substring_hits * 2 + token_overlap
    max_possible = len(query_tokens) * 3
    if max_possible == 0:
        return 0.0
    return min(1.0, combined / max_possible)


def query_capabilities(
    query: str = "",
    domain: str = "",
    list_all: bool = False,
) -> dict:
    """查询系统能力。用户问"你能做什么"/"能做X吗"时调用此工具。

    Args:
        query: 能力查询关键词（支持中英文，可为空）。
        domain: 可选领域过滤，例如 spatial / remote_sensing / governance / causal。
        list_all: 为 True 时返回按类别分组的全部能力摘要，忽略 query 与 domain。

    Returns:
        dict — {query, language, matches, total_capabilities, suggestion}
        matches 每项含 name, description, category, domain, example_prompt, relevance。
    """
    index = _build_capability_index()
    language = _detect_language(query) if query else "zh"

    if list_all or (not query and not domain):
        grouped: dict[str, list[dict]] = {}
        for entry in index:
            d = entry.get("domain") or entry.get("category") or "other"
            grouped.setdefault(d, []).append({
                "name": entry["name"],
                "description": entry["description"],
                "category": entry["category"],
                "domain": entry.get("domain", ""),
                "example_prompt": entry.get("example_prompt", ""),
            })
        # Flatten with deterministic ordering
        matches: list[dict] = []
        for d in sorted(grouped.keys()):
            matches.extend(grouped[d])
        return {
            "query": query,
            "language": language,
            "matches": matches,
            "total_capabilities": len(index),
            "grouped_by_domain": {d: [e["name"] for e in items] for d, items in grouped.items()},
            "suggestion": (
                "以下是系统当前全部能力，共{n}项，按领域分组。"
                if language == "zh"
                else "Here are all {n} capabilities grouped by domain."
            ).format(n=len(index)),
        }

    # Filtered / scored search
    query_tokens = _tokenize(query) if query else []
    scored: list[tuple[float, dict]] = []
    for entry in index:
        if domain and entry.get("domain") != domain and entry.get("category") != domain:
            continue
        score = _score_match(query_tokens, entry) if query_tokens else 1.0
        if score > 0 or not query_tokens:
            scored.append((score, entry))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:10]

    matches = [
        {
            "name": e["name"],
            "description": e["description"],
            "category": e["category"],
            "domain": e.get("domain", ""),
            "example_prompt": e.get("example_prompt", ""),
            "relevance": round(score, 3),
        }
        for score, e in top
    ]

    if matches:
        suggestion = (
            f"找到 {len(matches)} 项相关能力。"
            if language == "zh"
            else f"Found {len(matches)} relevant capabilities."
        )
    else:
        suggestion = (
            "暂无匹配的能力，可尝试更宽泛的关键词或用 list_all=True 查看全部。"
            if language == "zh"
            else "No match. Try broader keywords or list_all=True to see everything."
        )

    return {
        "query": query,
        "language": language,
        "matches": matches,
        "total_capabilities": len(index),
        "suggestion": suggestion,
    }


def suggest_for_ambiguous(user_text: str, language: str = "zh", top_k: int = 4) -> list[dict]:
    """Return top-K capability suggestions for an AMBIGUOUS intent.

    Used by app.py to enrich the clarification prompt shown to the user.
    Returns an empty list if the user text has no usable tokens.
    """
    if not user_text or not user_text.strip():
        return []
    index = _build_capability_index()
    query_tokens = _tokenize(user_text)
    if not query_tokens:
        return []
    scored: list[tuple[float, dict]] = []
    for entry in index:
        s = _score_match(query_tokens, entry)
        if s > 0:
            scored.append((s, entry))
    scored.sort(key=lambda x: x[0], reverse=True)

    # If no keyword matches, return a curated fallback of top-level categories
    if not scored:
        fallback_names = {"spatial_processing", "quality_audit", "remote_sensing", "advanced_analysis"}
        scored = [(0.0, e) for e in index if e["name"] in fallback_names]

    results: list[dict] = []
    for _, e in scored[:top_k]:
        results.append({
            "name": e["name"],
            "description": e["description"],
            "category": e["category"],
            "example_prompt": e.get("example_prompt", ""),
        })
    return results


class CapabilityQAToolset(BaseToolset):
    """System capability introspection — answers "what can you do?" questions."""

    async def get_tools(self, readonly_context=None):
        all_tools = [FunctionTool(query_capabilities)]
        if self.tool_filter is None:
            return all_tools
        return [t for t in all_tools if self._is_tool_selected(t, readonly_context)]

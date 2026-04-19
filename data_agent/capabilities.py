"""
Capabilities introspection — list built-in ADK skills and toolsets with metadata.

Uses ADK's list_skills_in_dir() for skill discovery (v1.27+).
Results are module-level cached since skills/toolsets are static at runtime.
"""
import pathlib

_SKILLS_DIR = pathlib.Path(__file__).parent / "skills"

_builtin_skills_cache: list[dict] | None = None
_toolsets_cache: list[dict] | None = None


def list_builtin_skills() -> list[dict]:
    """Discover skills via ADK list_skills_in_dir(). Cached."""
    global _builtin_skills_cache
    if _builtin_skills_cache is not None:
        return _builtin_skills_cache

    results: list[dict] = []
    try:
        import logging as _logging
        from google.adk.skills import list_skills_in_dir
        # Suppress ADK warning for __pycache__ dirs (upstream bug)
        _adk_logger = _logging.getLogger("google.adk.skills._utils")
        _prev_level = _adk_logger.level
        _adk_logger.setLevel(_logging.ERROR)
        try:
            raw = list_skills_in_dir(str(_SKILLS_DIR))
        finally:
            _adk_logger.setLevel(_prev_level)
        for skill_id, frontmatter in sorted(raw.items()):
            data = frontmatter.model_dump() if hasattr(frontmatter, "model_dump") else {}
            meta = data.get("metadata") or {}
            results.append({
                "name": data.get("name", skill_id),
                "description": data.get("description", ""),
                "domain": meta.get("domain", ""),
                "version": meta.get("version", ""),
                "intent_triggers": meta.get("intent_triggers", ""),
                "type": "builtin_skill",
            })
    except Exception:
        pass

    _builtin_skills_cache = results
    return results


_TOOLSET_DESCRIPTIONS: dict[str, str] = {
    "ExplorationToolset": "数据探查、画像与质量审计",
    "GeoProcessingToolset": "缓冲区、叠加、裁剪等空间处理",
    "LocationToolset": "地理编码、POI搜索、行政区划",
    "AnalysisToolset": "空间统计与属性分析",
    "VisualizationToolset": "地图渲染、图表生成、3D可视化",
    "DatabaseToolset": "PostGIS查询与数据管理",
    "FileToolset": "文件读写与格式转换",
    "MemoryToolset": "空间记忆存储与检索",
    "AdminToolset": "用户管理与系统配置",
    "RemoteSensingToolset": "遥感影像处理与DEM下载",
    "SpatialStatisticsToolset": "空间自相关与热点分析",
    "SemanticLayerToolset": "语义目录浏览与查询",
    "StreamingToolset": "流式输出与进度推送",
    "TeamToolset": "团队协作与资产共享",
    "DataLakeToolset": "数据湖资产注册与检索",
    "McpHubToolset": "MCP外部工具集成",
    "FusionToolset": "多源数据融合与匹配",
    "KnowledgeGraphToolset": "地理知识图谱构建与查询",
    "KnowledgeBaseToolset": "知识库管理与RAG检索",
    "AdvancedAnalysisToolset": "时序预测、网络分析、假设分析",
    "SpatialAnalysisTier2Toolset": "高级空间分析（Tier-2）",
    "WatershedToolset": "流域提取与水文分析",
    "UserToolset": "用户自定义工具（HTTP/SQL/文件/链式）",
    "VirtualSourceToolset": "虚拟数据源连接（WFS/STAC/OGC API/自定义API）",
    "ToolEvolutionToolset": "工具演化：动态工具库管理、失败驱动发现、元数据查询",
    "DomainStandardToolset": "自然资源领域数据模型编译、模块查询与类关系检索",
}


def list_toolsets() -> list[dict]:
    """Return toolset metadata list. Cached."""
    global _toolsets_cache
    if _toolsets_cache is not None:
        return _toolsets_cache

    from .custom_skills import TOOLSET_NAMES
    _toolsets_cache = [
        {
            "name": name,
            "description": _TOOLSET_DESCRIPTIONS.get(name, ""),
            "type": "toolset",
        }
        for name in sorted(TOOLSET_NAMES)
    ]
    return _toolsets_cache

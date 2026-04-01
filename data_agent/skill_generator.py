"""AI-assisted Skill generation: natural language → Skill configuration.

Uses keyword analysis to recommend toolsets, generate instruction text,
and produce a complete Skill configuration ready for user preview and DB save.
"""
import json
import re
from typing import Optional


# ---------------------------------------------------------------------------
# Toolset recommendation table: keywords → toolset names + reason
# ---------------------------------------------------------------------------

_TOOLSET_KEYWORDS: dict[str, list[tuple[str, str]]] = {
    # Spatial processing
    "缓冲": [("GeoProcessingToolset", "缓冲区分析")],
    "buffer": [("GeoProcessingToolset", "buffer analysis")],
    "裁剪": [("GeoProcessingToolset", "空间裁剪")],
    "clip": [("GeoProcessingToolset", "spatial clipping")],
    "叠加": [("GeoProcessingToolset", "空间叠加")],
    "overlay": [("GeoProcessingToolset", "spatial overlay")],
    "空间处理": [("GeoProcessingToolset", "通用空间处理")],
    "spatial": [("GeoProcessingToolset", "spatial processing")],
    # Exploration
    "探查": [("ExplorationToolset", "数据探查")],
    "画像": [("ExplorationToolset", "数据画像")],
    "profile": [("ExplorationToolset", "data profiling")],
    "explore": [("ExplorationToolset", "data exploration")],
    # Remote sensing
    "遥感": [("RemoteSensingToolset", "遥感影像处理")],
    "影像": [("RemoteSensingToolset", "影像分析")],
    "植被": [("RemoteSensingToolset", "植被指数分析")],
    "ndvi": [("RemoteSensingToolset", "植被指数计算")],
    "dem": [("RemoteSensingToolset", "数字高程模型")],
    "remote_sensing": [("RemoteSensingToolset", "remote sensing")],
    "raster": [("RemoteSensingToolset", "raster processing")],
    "光谱": [("RemoteSensingToolset", "光谱分析")],
    "spectral": [("RemoteSensingToolset", "spectral analysis")],
    # Visualization
    "可视化": [("VisualizationToolset", "地图可视化")],
    "地图": [("VisualizationToolset", "地图渲染")],
    "visualize": [("VisualizationToolset", "visualization")],
    "map": [("VisualizationToolset", "map rendering")],
    "图表": [("ChartToolset", "图表生成")],
    "chart": [("ChartToolset", "chart generation")],
    "热力图": [("VisualizationToolset", "热力图")],
    "heatmap": [("VisualizationToolset", "heatmap")],
    # Database
    "数据库": [("DatabaseToolset", "数据库查询")],
    "sql": [("DatabaseToolset", "SQL查询")],
    "postgis": [("DatabaseToolset", "PostGIS空间数据库")],
    "database": [("DatabaseToolset", "database operations")],
    "入库": [("DatabaseToolset", "数据导入")],
    # Analysis
    "统计": [("SpatialStatisticsToolset", "空间统计")],
    "热点": [("SpatialStatisticsToolset", "热点分析")],
    "聚类": [("SpatialStatisticsToolset", "空间聚类")],
    "hotspot": [("SpatialStatisticsToolset", "hotspot analysis")],
    "autocorrelation": [("SpatialStatisticsToolset", "spatial autocorrelation")],
    # Location
    "poi": [("LocationToolset", "POI搜索")],
    "地理编码": [("LocationToolset", "地理编码")],
    "geocode": [("LocationToolset", "geocoding")],
    "行政区划": [("LocationToolset", "行政边界")],
    # Advanced
    "因果": [("CausalInferenceToolset", "因果推断")],
    "causal": [("CausalInferenceToolset", "causal inference")],
    "预测": [("WorldModelToolset", "时空预测")],
    "world_model": [("WorldModelToolset", "world model prediction")],
    "优化": [("AnalysisToolset", "DRL优化")],
    "drl": [("AnalysisToolset", "DRL optimization")],
    # Fusion
    "融合": [("FusionToolset", "多源融合")],
    "fusion": [("FusionToolset", "data fusion")],
    # Knowledge
    "知识": [("KnowledgeBaseToolset", "知识库检索")],
    "knowledge": [("KnowledgeBaseToolset", "knowledge base")],
    # Data management
    "清洗": [("DataCleaningToolset", "数据清洗")],
    "clean": [("DataCleaningToolset", "data cleaning")],
    "治理": [("GovernanceToolset", "数据治理")],
    "governance": [("GovernanceToolset", "data governance")],
    "质检": [("GovernanceToolset", "质量检查"), ("DataCleaningToolset", "数据清洗")],
    "quality": [("GovernanceToolset", "quality check")],
    # Operators
    "分析": [("OperatorToolset", "语义分析算子")],
    "analyze": [("OperatorToolset", "semantic analysis")],
    # File
    "文件": [("FileToolset", "文件管理")],
    "file": [("FileToolset", "file management")],
    # Semantic
    "语义": [("SemanticLayerToolset", "语义目录")],
    "semantic": [("SemanticLayerToolset", "semantic layer")],
    # Watershed
    "流域": [("WatershedToolset", "流域分析")],
    "watershed": [("WatershedToolset", "watershed analysis")],
    "水文": [("WatershedToolset", "水文分析")],
}

# Category detection keywords
_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "spatial_analysis": ["空间", "缓冲", "叠加", "裁剪", "拓扑", "spatial", "buffer", "clip", "overlay"],
    "remote_sensing": ["遥感", "影像", "卫星", "光谱", "ndvi", "dem", "raster", "remote", "spectral"],
    "data_management": ["数据库", "入库", "导入", "清洗", "治理", "质检", "database", "clean", "governance"],
    "advanced_analysis": ["因果", "预测", "优化", "融合", "聚类", "causal", "predict", "optimize", "cluster"],
    "visualization": ["可视化", "地图", "图表", "热力图", "visualize", "map", "chart", "heatmap"],
    "other": [],
}


def _detect_model_tier(description: str) -> str:
    """Detect appropriate model tier from description."""
    desc_lower = description.lower()
    premium_keywords = ["复杂", "推理", "规划", "多步", "complex", "reasoning", "planning",
                        "因果", "causal", "world_model", "预测"]
    fast_keywords = ["简单", "查询", "列出", "simple", "list", "query", "describe", "探查"]

    if any(k in desc_lower for k in premium_keywords):
        return "premium"
    if any(k in desc_lower for k in fast_keywords):
        return "fast"
    return "standard"


def _recommend_toolsets(description: str) -> list[dict]:
    """Recommend toolsets based on description keywords."""
    desc_lower = description.lower()
    scored: dict[str, dict] = {}  # toolset_name → {score, reasons}

    for keyword, toolsets in _TOOLSET_KEYWORDS.items():
        if keyword in desc_lower:
            for ts_name, reason in toolsets:
                if ts_name not in scored:
                    scored[ts_name] = {"score": 0, "reasons": []}
                scored[ts_name]["score"] += 1
                if reason not in scored[ts_name]["reasons"]:
                    scored[ts_name]["reasons"].append(reason)

    # Always include ExplorationToolset as base
    if "ExplorationToolset" not in scored:
        scored["ExplorationToolset"] = {"score": 0, "reasons": ["基础数据探查 (默认)"]}

    ranked = sorted(scored.items(), key=lambda x: x[1]["score"], reverse=True)
    return [{"name": name, "reasons": info["reasons"]} for name, info in ranked[:6]]


def _detect_category(description: str) -> str:
    """Detect skill category from description."""
    desc_lower = description.lower()
    scores: dict[str, int] = {}
    for cat, keywords in _CATEGORY_KEYWORDS.items():
        scores[cat] = sum(1 for k in keywords if k in desc_lower)
    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] > 0 else "other"


def _generate_skill_name(description: str) -> str:
    """Generate a snake_case skill name from description."""
    # Try to extract English keywords first
    eng_words = re.findall(r'[a-zA-Z]{3,}', description)
    if len(eng_words) >= 2:
        return "_".join(w.lower() for w in eng_words[:3])

    # Map common Chinese terms to English
    cn_to_en = {
        "植被": "vegetation", "监测": "monitor", "分析": "analyze",
        "城市": "urban", "热岛": "heat_island", "水体": "water",
        "检测": "detect", "变化": "change", "土地利用": "landuse",
        "优化": "optimize", "流域": "watershed", "评估": "assess",
        "预测": "predict", "质检": "quality_check", "清洗": "clean",
        "可视化": "visualize", "统计": "statistics", "融合": "fusion",
        "遥感": "remote_sensing", "因果": "causal",
    }
    parts = []
    for cn, en in cn_to_en.items():
        if cn in description:
            parts.append(en)
            if len(parts) >= 3:
                break

    return "_".join(parts) if parts else "custom_skill"


def _generate_trigger_keywords(description: str, skill_name: str) -> list[str]:
    """Generate trigger keywords from description."""
    keywords = []
    # Extract Chinese 2-4 char terms
    cn_terms = re.findall(r'[\u4e00-\u9fff]{2,4}', description)
    keywords.extend(cn_terms[:4])
    # Add skill name parts
    keywords.extend(skill_name.split("_")[:2])
    return list(dict.fromkeys(keywords))[:6]  # deduplicate, max 6


def _generate_instruction(description: str, toolsets: list[str], category: str) -> str:
    """Generate a structured skill instruction from description."""
    toolset_list = "、".join(toolsets)

    instruction = f"""你是一个专业的 GIS 数据分析智能体，专注于{description}。

## 核心职责
1. 理解用户的分析需求，确认输入数据和期望输出
2. 使用 {toolset_list} 中的工具执行分析
3. 对分析结果进行质量检查和解读
4. 生成结构化的分析报告

## 工作流程
1. **数据探查**: 使用 describe_geodataframe 了解数据结构和质量
2. **预处理**: 检查坐标系、缺失值，必要时进行数据清洗
3. **核心分析**: 执行主要分析任务
4. **结果验证**: 检查输出合理性
5. **报告生成**: 汇总关键发现和建议

## 输出格式
- 分析结果以 JSON 格式返回
- 可视化结果保存为文件并返回路径
- 关键指标和统计量需要明确标注

## 注意事项
- 处理前务必检查坐标系一致性
- 大数据集先采样验证再全量处理
- 遇到错误时提供明确的诊断信息"""

    return instruction


def generate_skill_config(description: str) -> dict:
    """Generate a complete skill configuration from natural language description.

    Args:
        description: Natural language description of the desired skill
    Returns:
        dict with: skill_name, description, instruction, toolset_names,
                   trigger_keywords, model_tier, category, tags, toolset_recommendations
    """
    if not description or len(description.strip()) < 5:
        return {"status": "error", "message": "描述过短，请提供至少 5 个字符的技能描述"}

    desc = description.strip()

    # 1. Recommend toolsets
    toolset_recs = _recommend_toolsets(desc)
    toolset_names = [r["name"] for r in toolset_recs]

    # 2. Detect category
    category = _detect_category(desc)

    # 3. Detect model tier
    model_tier = _detect_model_tier(desc)

    # 4. Generate skill name
    skill_name = _generate_skill_name(desc)

    # 5. Generate trigger keywords
    trigger_keywords = _generate_trigger_keywords(desc, skill_name)

    # 6. Generate instruction
    instruction = _generate_instruction(desc, toolset_names, category)

    # 7. Extract tags
    tags = trigger_keywords[:4]

    return {
        "status": "success",
        "config": {
            "skill_name": skill_name,
            "description": desc[:200],
            "instruction": instruction,
            "toolset_names": toolset_names,
            "trigger_keywords": trigger_keywords,
            "model_tier": model_tier,
            "category": category,
            "tags": tags,
            "is_shared": False,
        },
        "toolset_recommendations": toolset_recs,
        "preview": {
            "skill_name": skill_name,
            "description": desc[:200],
            "toolsets": len(toolset_names),
            "model_tier": model_tier,
            "category": category,
        },
    }

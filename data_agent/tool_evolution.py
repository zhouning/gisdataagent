"""Tool Evolution Engine: dynamic tool library management, failure-driven discovery, rich metadata.

Provides:
- Unified ToolMetadata registry aggregating info from TOOL_CATEGORIES, failure_learning, error_recovery
- Reliability scoring from historical success/failure ratios
- Task-based tool recommendation using keyword matching
- Failure-driven tool discovery — analyze failures, suggest alternatives or missing tools
- Dynamic tool registration / deactivation for runtime extensibility
"""
import json
import fnmatch
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class ToolMetadata:
    """Rich metadata for a single tool."""

    name: str
    description: str = ""
    category: str = "uncategorized"
    cost_level: str = "low"  # low / medium / high
    reliability_score: float = 1.0  # 0.0 - 1.0
    applicable_scenarios: list[str] = field(default_factory=list)
    alternatives: list[str] = field(default_factory=list)
    is_core: bool = False
    source: str = "builtin"  # builtin / mcp / user_defined / dynamic
    failure_count: int = 0
    success_count: int = 0
    tags: list[str] = field(default_factory=list)
    active: bool = True
    deactivation_reason: str = ""


# ---------------------------------------------------------------------------
# Static enrichment tables
# ---------------------------------------------------------------------------

_TOOL_DESCRIPTIONS: dict[str, str] = {
    # spatial_processing
    "generate_tessellation": "生成规则格网 (六边形/矩形) 用于空间聚合分析",
    "raster_to_polygon": "将栅格数据转换为矢量多边形",
    "pairwise_clip": "逐对裁剪 — 按叠加范围裁剪目标图层",
    "tabulate_intersection": "面积统计交叉表 — 计算各类别面积占比",
    "surface_parameters": "地表参数 (坡度、坡向、曲率) 计算",
    "zonal_statistics_as_table": "分区统计 — 按区域汇总栅格值",
    "perform_clustering": "空间聚类分析 (DBSCAN/K-Means)",
    "create_buffer": "缓冲区分析 — 围绕要素生成缓冲区",
    "summarize_within": "区域内统计汇总 (面积、计数、平均值)",
    "overlay_difference": "叠加差集 — 提取不重叠区域",
    "generate_heatmap": "热力图渲染 — 点密度可视化",
    "find_within_distance": "邻近搜索 — 查找指定距离内的要素",
    "polygon_neighbors": "多边形邻接关系分析",
    "add_field": "添加字段到属性表",
    "add_join": "属性表连接 (表关联)",
    "calculate_field": "字段计算 — 批量更新属性值",
    "summary_statistics": "汇总统计 (均值、中位数、标准差等)",
    "reproject_spatial_data": "坐标系转换 — 重投影空间数据",
    "engineer_spatial_features": "空间特征工程 — 生成衍生空间特征",
    "batch_geocode": "批量地理编码 — 地址 → 坐标",
    "reverse_geocode": "逆地理编码 — 坐标 → 地址",
    "get_admin_boundary": "获取行政区划边界",
    # poi_location
    "search_nearby_poi": "搜索附近 POI (兴趣点)",
    "search_poi_by_keyword": "按关键词搜索 POI",
    "get_population_data": "获取人口数据",
    "aggregate_population": "人口数据聚合统计",
    "calculate_driving_distance": "计算驾车距离和时间",
    # remote_sensing
    "describe_raster": "栅格数据概要 — 波段、分辨率、范围、统计",
    "calculate_ndvi": "计算 NDVI (归一化植被指数)",
    "raster_band_math": "通用波段运算 — 自定义公式",
    "classify_raster": "栅格分类 (等距/自然间断/分位数)",
    "visualize_raster": "栅格可视化渲染",
    "download_lulc": "下载 Esri 全球 10m 土地利用/覆盖",
    "download_dem": "下载 Copernicus 30m 数字高程模型",
    "extract_watershed": "流域提取",
    "extract_stream_network": "水系网络提取",
    "compute_flow_accumulation": "流量累积计算",
    "idw_interpolation": "IDW 反距离加权插值",
    "kriging_interpolation": "克里金插值",
    "gwr_analysis": "地理加权回归分析",
    "spatial_change_detection": "空间变化检测",
    "viewshed_analysis": "可视域分析",
    # spectral
    "calculate_spectral_index": "计算光谱指数 (15+ 种)",
    "list_spectral_indices": "列出所有可用光谱指数",
    "recommend_indices": "根据任务智能推荐光谱指数",
    "assess_cloud_cover": "云覆盖率检测与质量评估",
    "search_rs_experience": "搜索遥感分析经验库",
    "list_satellite_presets": "列出卫星数据预置源",
    # database
    "describe_table": "数据库表结构描述",
    "share_table": "共享数据库表",
    "import_to_postgis": "导入数据到 PostGIS",
    "query_database": "SQL 查询数据库",
    "list_tables": "列出数据库表",
    # quality_audit
    "check_topology": "拓扑检查 — 面重叠、缝隙、悬挂点",
    "check_field_standards": "字段标准检查 — 值域、类型、编码合规",
    "check_consistency": "一致性检查 — 跨图层逻辑一致性",
    # exploration
    "describe_geodataframe": "GeoDataFrame 数据画像",
    "list_user_files": "列出用户文件",
    "filter_vector_data": "矢量数据过滤",
    # visualization
    "visualize_interactive_map": "交互式地图可视化",
    # advanced
    "spatial_autocorrelation": "全局空间自相关 (Moran's I)",
    "local_moran": "局部空间自相关 (LISA)",
    "hotspot_analysis": "热点分析 (Getis-Ord Gi*)",
    # fusion
    "fuse_datasets": "多源数据融合",
    "profile_fusion_sources": "融合源数据画像",
    # DRL
    "drl_model": "DRL 土地利用优化 (单目标)",
    "drl_multi_objective": "DRL 多目标帕累托优化 (NSGA-II)",
    # world model
    "world_model_predict": "World Model 时空预测",
    "world_model_scenarios": "World Model 情景模拟",
    # causal
    "construct_causal_dag": "构建因果 DAG",
    "counterfactual_reasoning": "反事实推理",
}

_TOOL_COSTS: dict[str, str] = {
    # high: LLM-intensive or external API
    "world_model_predict": "high",
    "world_model_scenarios": "high",
    "construct_causal_dag": "high",
    "counterfactual_reasoning": "high",
    "explain_causal_mechanism": "high",
    "generate_what_if_scenarios": "high",
    "intervention_predict": "high",
    "counterfactual_comparison": "high",
    "drl_model": "high",
    "drl_multi_objective": "high",
    "kriging_interpolation": "high",
    "gwr_analysis": "high",
    "fuse_datasets": "medium",
    "batch_geocode": "medium",
    "search_nearby_poi": "medium",
    "search_poi_by_keyword": "medium",
    "calculate_driving_distance": "medium",
    "download_lulc": "medium",
    "download_dem": "medium",
    "spatial_autocorrelation": "medium",
    "local_moran": "medium",
    "hotspot_analysis": "medium",
    "perform_clustering": "medium",
    "spatial_change_detection": "medium",
}

_TOOL_SCENARIOS: dict[str, list[str]] = {
    "calculate_ndvi": ["植被监测", "农田评估", "生态分析"],
    "calculate_spectral_index": ["遥感分析", "光谱指数计算", "环境监测"],
    "download_lulc": ["土地利用分析", "变化检测", "城市扩张"],
    "download_dem": ["地形分析", "流域提取", "坡度计算"],
    "create_buffer": ["邻近分析", "服务范围", "缓冲区"],
    "pairwise_clip": ["区域裁剪", "数据预处理", "范围提取"],
    "spatial_autocorrelation": ["空间格局分析", "聚集性检验", "空间统计"],
    "hotspot_analysis": ["热点探测", "空间聚类", "犯罪分析", "疫情分析"],
    "check_topology": ["数据质量", "拓扑检查", "质检"],
    "import_to_postgis": ["数据入库", "数据管理", "PostGIS"],
    "fuse_datasets": ["多源融合", "数据集成", "异构数据"],
    "drl_model": ["用地优化", "空间优化", "规划"],
    "world_model_predict": ["时空预测", "变化模拟", "趋势分析"],
    "kriging_interpolation": ["空间插值", "环境建模", "采样估计"],
    "batch_geocode": ["地址匹配", "地理编码", "位置查找"],
    "generate_heatmap": ["密度可视化", "热力图", "点密度"],
    "perform_clustering": ["空间聚类", "区域划分", "模式识别"],
    "extract_watershed": ["水文分析", "流域划分", "汇水区"],
    "viewshed_analysis": ["可视域", "景观分析", "选址评估"],
    "reproject_spatial_data": ["坐标转换", "投影变换", "CRS统一"],
}

# Keyword → tool mapping for task-based recommendation
_TASK_KEYWORDS: dict[str, list[str]] = {
    "植被": ["calculate_ndvi", "calculate_spectral_index", "recommend_indices"],
    "vegetation": ["calculate_ndvi", "calculate_spectral_index", "recommend_indices"],
    "ndvi": ["calculate_ndvi", "calculate_spectral_index"],
    "遥感": ["calculate_spectral_index", "describe_raster", "recommend_indices", "assess_cloud_cover"],
    "remote_sensing": ["calculate_spectral_index", "describe_raster", "recommend_indices"],
    "土地利用": ["download_lulc", "classify_raster", "drl_model"],
    "landuse": ["download_lulc", "classify_raster", "drl_model"],
    "优化": ["drl_model", "drl_multi_objective"],
    "optimize": ["drl_model", "drl_multi_objective"],
    "地形": ["download_dem", "surface_parameters", "extract_watershed"],
    "dem": ["download_dem", "surface_parameters"],
    "terrain": ["download_dem", "surface_parameters"],
    "流域": ["extract_watershed", "extract_stream_network", "compute_flow_accumulation"],
    "watershed": ["extract_watershed", "extract_stream_network"],
    "水体": ["calculate_spectral_index", "recommend_indices"],
    "water": ["calculate_spectral_index", "recommend_indices"],
    "缓冲": ["create_buffer"],
    "buffer": ["create_buffer"],
    "裁剪": ["pairwise_clip"],
    "clip": ["pairwise_clip"],
    "插值": ["idw_interpolation", "kriging_interpolation"],
    "interpolation": ["idw_interpolation", "kriging_interpolation"],
    "热点": ["hotspot_analysis", "local_moran"],
    "hotspot": ["hotspot_analysis", "local_moran"],
    "聚类": ["perform_clustering", "hotspot_analysis"],
    "cluster": ["perform_clustering", "hotspot_analysis"],
    "拓扑": ["check_topology"],
    "topology": ["check_topology"],
    "质检": ["check_topology", "check_field_standards", "check_consistency"],
    "quality": ["check_topology", "check_field_standards", "check_consistency"],
    "入库": ["import_to_postgis"],
    "编码": ["batch_geocode"],
    "geocode": ["batch_geocode", "reverse_geocode"],
    "融合": ["fuse_datasets", "profile_fusion_sources"],
    "fusion": ["fuse_datasets", "profile_fusion_sources"],
    "预测": ["world_model_predict", "world_model_scenarios"],
    "predict": ["world_model_predict", "world_model_scenarios"],
    "因果": ["construct_causal_dag", "counterfactual_reasoning"],
    "causal": ["construct_causal_dag", "counterfactual_reasoning"],
    "可视化": ["visualize_interactive_map", "generate_heatmap"],
    "visualize": ["visualize_interactive_map", "generate_heatmap"],
    "地图": ["visualize_interactive_map"],
    "map": ["visualize_interactive_map"],
    "坐标": ["reproject_spatial_data"],
    "crs": ["reproject_spatial_data"],
    "火灾": ["calculate_spectral_index", "recommend_indices"],
    "fire": ["calculate_spectral_index", "recommend_indices"],
    "城市": ["calculate_spectral_index", "recommend_indices", "download_lulc"],
    "urban": ["calculate_spectral_index", "recommend_indices", "download_lulc"],
    "积雪": ["calculate_spectral_index", "recommend_indices"],
    "snow": ["calculate_spectral_index", "recommend_indices"],
}

# Failure pattern → suggested tool mapping (beyond TOOL_ALTERNATIVES)
_FAILURE_TOOL_SUGGESTIONS: dict[str, dict] = {
    "crs_mismatch": {
        "pattern": ["crs", "projection", "坐标系", "epsg", "coordinate system"],
        "suggested_tool": "reproject_spatial_data",
        "reason": "坐标系不匹配，需先统一投影",
    },
    "topology_error": {
        "pattern": ["topology", "overlap", "gap", "self-intersect", "拓扑", "重叠", "缝隙"],
        "suggested_tool": "check_topology",
        "reason": "数据存在拓扑错误，建议先做拓扑检查与修复",
    },
    "null_geometry": {
        "pattern": ["null geometry", "empty geometry", "none geometry", "空几何"],
        "suggested_tool": "filter_vector_data",
        "reason": "存在空几何要素，建议先过滤清洗",
    },
    "cloud_cover": {
        "pattern": ["cloud", "cloudy", "云", "遮挡"],
        "suggested_tool": "assess_cloud_cover",
        "reason": "影像云覆盖率高，建议先评估云覆盖",
    },
    "large_dataset": {
        "pattern": ["memory", "oom", "out of memory", "too large", "exceeded"],
        "suggested_tool": "filter_vector_data",
        "reason": "数据量过大，建议先过滤或采样",
    },
    "missing_bands": {
        "pattern": ["band", "波段", "channel"],
        "suggested_tool": "describe_raster",
        "reason": "波段信息缺失，建议先描述栅格数据",
    },
}


class ToolEvolutionEngine:
    """Manages tool metadata, failure-driven discovery, and dynamic tool registration."""

    def __init__(self) -> None:
        self._metadata: dict[str, ToolMetadata] = {}
        self._dynamic_tools: dict[str, ToolMetadata] = {}  # runtime-registered tools
        self._build_metadata()

    # ------------------------------------------------------------------
    # Metadata construction
    # ------------------------------------------------------------------

    def _build_metadata(self) -> None:
        """Build metadata registry from TOOL_CATEGORIES + enrichment tables."""
        from .tool_filter import TOOL_CATEGORIES, CORE_TOOLS
        from .error_recovery import TOOL_ALTERNATIVES

        # Invert TOOL_CATEGORIES: tool → category
        tool_to_cat: dict[str, str] = {}
        for cat, tools in TOOL_CATEGORIES.items():
            for t in tools:
                tool_to_cat.setdefault(t, cat)

        # Collect all known tool names
        all_names: set[str] = set()
        all_names.update(tool_to_cat.keys())
        all_names.update(CORE_TOOLS)
        all_names.update(_TOOL_DESCRIPTIONS.keys())
        all_names.update(TOOL_ALTERNATIVES.keys())
        for alts in TOOL_ALTERNATIVES.values():
            all_names.update(alts)

        # Build metadata for each
        for name in sorted(all_names):
            alts = TOOL_ALTERNATIVES.get(name, [])
            meta = ToolMetadata(
                name=name,
                description=_TOOL_DESCRIPTIONS.get(name, ""),
                category=tool_to_cat.get(name, "uncategorized"),
                cost_level=_TOOL_COSTS.get(name, "low"),
                applicable_scenarios=_TOOL_SCENARIOS.get(name, []),
                alternatives=list(alts),
                is_core=name in CORE_TOOLS,
                source="builtin",
                tags=_TOOL_SCENARIOS.get(name, [])[:3],
            )
            self._metadata[name] = meta

    @property
    def all_metadata(self) -> dict[str, ToolMetadata]:
        merged = dict(self._metadata)
        merged.update(self._dynamic_tools)
        return merged

    # ------------------------------------------------------------------
    # Public API (all return JSON strings for ADK tool compatibility)
    # ------------------------------------------------------------------

    def get_tool_metadata(self, tool_name: str) -> str:
        """获取工具的详细元数据 (描述、成本、可靠性、适用场景、替代方案)。

        Args:
            tool_name: 工具名称
        Returns:
            JSON: 工具元数据
        """
        meta = self.all_metadata.get(tool_name)
        if not meta:
            return json.dumps({"status": "error", "message": f"Unknown tool: {tool_name}"}, ensure_ascii=False)
        return json.dumps({"status": "success", "tool": asdict(meta)}, ensure_ascii=False)

    def list_tools_with_metadata(self, category: str = "", sort_by: str = "name") -> str:
        """列出工具及其元数据，可按类别筛选，按名称/成本/可靠性排序。

        Args:
            category: 可选类别过滤 (如 "spatial_processing", "remote_sensing")
            sort_by: 排序字段 — "name" / "cost" / "reliability" / "category"
        Returns:
            JSON: 工具列表
        """
        all_meta = self.all_metadata
        items = list(all_meta.values())

        if category:
            items = [m for m in items if m.category == category or fnmatch.fnmatch(m.category, category)]

        # Only active tools
        items = [m for m in items if m.active]

        cost_order = {"low": 0, "medium": 1, "high": 2}
        if sort_by == "cost":
            items.sort(key=lambda m: cost_order.get(m.cost_level, 0))
        elif sort_by == "reliability":
            items.sort(key=lambda m: m.reliability_score, reverse=True)
        elif sort_by == "category":
            items.sort(key=lambda m: (m.category, m.name))
        else:
            items.sort(key=lambda m: m.name)

        result = []
        for m in items:
            result.append({
                "name": m.name,
                "description": m.description,
                "category": m.category,
                "cost_level": m.cost_level,
                "reliability_score": round(m.reliability_score, 2),
                "alternatives": m.alternatives,
                "is_core": m.is_core,
                "source": m.source,
                "active": m.active,
            })

        return json.dumps({
            "status": "success",
            "count": len(result),
            "tools": result,
        }, ensure_ascii=False)

    def suggest_tools_for_task(self, task_description: str) -> str:
        """根据任务描述推荐最佳工具组合。

        Args:
            task_description: 任务描述 (中文或英文)
        Returns:
            JSON: 推荐的工具列表及理由
        """
        desc_lower = task_description.lower()
        scored: dict[str, int] = {}

        for keyword, tools in _TASK_KEYWORDS.items():
            if keyword in desc_lower:
                for t in tools:
                    scored[t] = scored.get(t, 0) + 1

        if not scored:
            return json.dumps({
                "status": "success",
                "task": task_description,
                "recommended": [],
                "message": "未找到匹配的工具推荐，请提供更具体的任务描述",
            }, ensure_ascii=False)

        ranked = sorted(scored.items(), key=lambda x: x[1], reverse=True)[:8]
        recommendations = []
        all_meta = self.all_metadata
        for tool_name, score in ranked:
            meta = all_meta.get(tool_name)
            recommendations.append({
                "tool": tool_name,
                "relevance_score": score,
                "description": meta.description if meta else "",
                "cost_level": meta.cost_level if meta else "low",
                "scenarios": meta.applicable_scenarios[:3] if meta else [],
            })

        return json.dumps({
            "status": "success",
            "task": task_description,
            "recommended": recommendations,
        }, ensure_ascii=False)

    def analyze_tool_failures(self, tool_name: str = "") -> str:
        """分析工具失败模式，推荐改进措施。从失败学习数据库获取历史数据。

        Args:
            tool_name: 可选 — 指定工具名称。为空则分析全局。
        Returns:
            JSON: 失败分析报告
        """
        try:
            from .failure_learning import get_failure_hints
            from .db_engine import get_engine

            engine = get_engine()
            if engine is None:
                return json.dumps({"status": "success", "failures": [], "message": "数据库不可用，无历史失败数据"}, ensure_ascii=False)

            from sqlalchemy import text
            with engine.connect() as conn:
                if tool_name:
                    rows = conn.execute(
                        text("SELECT tool_name, error_snippet, hint_applied, resolved, created_at "
                             "FROM agent_tool_failures WHERE tool_name = :tn ORDER BY created_at DESC LIMIT 20"),
                        {"tn": tool_name},
                    ).fetchall()
                else:
                    rows = conn.execute(
                        text("SELECT tool_name, COUNT(*) as cnt, "
                             "SUM(CASE WHEN resolved THEN 1 ELSE 0 END) as resolved_cnt "
                             "FROM agent_tool_failures GROUP BY tool_name ORDER BY cnt DESC LIMIT 20"),
                    ).fetchall()

            if tool_name:
                failures = []
                for r in rows:
                    failures.append({
                        "tool": r[0], "error": r[1][:200] if r[1] else "",
                        "hint": r[2][:200] if r[2] else "", "resolved": bool(r[3]),
                    })
                # Suggest alternatives
                from .error_recovery import TOOL_ALTERNATIVES
                alts = TOOL_ALTERNATIVES.get(tool_name, [])
                return json.dumps({
                    "status": "success",
                    "tool": tool_name,
                    "failure_count": len(failures),
                    "failures": failures[:10],
                    "alternatives": alts,
                    "recommendations": self._failure_recommendations(tool_name, failures),
                }, ensure_ascii=False)
            else:
                summary = []
                for r in rows:
                    total = r[1]
                    resolved = r[2] or 0
                    summary.append({
                        "tool": r[0], "total_failures": total,
                        "resolved": resolved,
                        "reliability": round(1 - (total - resolved) / max(total, 1), 2),
                    })
                return json.dumps({
                    "status": "success",
                    "tool_failure_summary": summary,
                }, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)

    def _failure_recommendations(self, tool_name: str, failures: list[dict]) -> list[str]:
        """Generate recommendations from failure patterns."""
        recs: list[str] = []
        error_texts = " ".join(f.get("error", "") for f in failures).lower()

        for key, info in _FAILURE_TOOL_SUGGESTIONS.items():
            if any(p in error_texts for p in info["pattern"]):
                recs.append(f"建议先调用 {info['suggested_tool']} — {info['reason']}")

        if not recs:
            recs.append("建议检查输入数据质量和参数设置")
        return recs[:5]

    def register_tool(self, name: str, description: str, category: str = "uncategorized",
                      cost_level: str = "low", scenarios: Optional[list[str]] = None,
                      source: str = "dynamic") -> str:
        """注册一个新的动态工具到演化注册表。

        Args:
            name: 工具名称
            description: 工具描述
            category: 工具类别
            cost_level: 成本等级 (low/medium/high)
            scenarios: 适用场景列表
            source: 来源 (dynamic/mcp/user_defined)
        Returns:
            JSON: 注册结果
        """
        if name in self._metadata or name in self._dynamic_tools:
            return json.dumps({"status": "error", "message": f"Tool '{name}' already exists"}, ensure_ascii=False)

        meta = ToolMetadata(
            name=name,
            description=description,
            category=category,
            cost_level=cost_level,
            applicable_scenarios=scenarios or [],
            source=source,
            tags=(scenarios or [])[:3],
        )
        self._dynamic_tools[name] = meta
        return json.dumps({"status": "success", "message": f"Tool '{name}' registered", "tool": asdict(meta)}, ensure_ascii=False)

    def deactivate_tool(self, name: str, reason: str = "") -> str:
        """停用一个工具 (标记为不活跃，不物理删除)。

        Args:
            name: 工具名称
            reason: 停用原因
        Returns:
            JSON: 操作结果
        """
        meta = self._dynamic_tools.get(name) or self._metadata.get(name)
        if not meta:
            return json.dumps({"status": "error", "message": f"Unknown tool: {name}"}, ensure_ascii=False)
        if not meta.active:
            return json.dumps({"status": "error", "message": f"Tool '{name}' is already inactive"}, ensure_ascii=False)
        meta.active = False
        meta.deactivation_reason = reason
        return json.dumps({"status": "success", "message": f"Tool '{name}' deactivated", "reason": reason}, ensure_ascii=False)

    def get_failure_driven_suggestions(self, failed_tool: str, error_message: str) -> str:
        """根据工具失败信息，推荐替代工具或前置修复工具。

        Args:
            failed_tool: 失败的工具名称
            error_message: 错误信息
        Returns:
            JSON: 推荐的替代/修复工具
        """
        from .error_recovery import TOOL_ALTERNATIVES

        suggestions: list[dict] = []
        error_lower = error_message.lower()

        # 1. Direct alternatives from TOOL_ALTERNATIVES
        alts = TOOL_ALTERNATIVES.get(failed_tool, [])
        for alt in alts:
            meta = self.all_metadata.get(alt)
            suggestions.append({
                "tool": alt,
                "type": "alternative",
                "reason": f"{failed_tool} 的替代工具",
                "description": meta.description if meta else "",
            })

        # 2. Error-pattern-driven suggestions
        for key, info in _FAILURE_TOOL_SUGGESTIONS.items():
            if any(p in error_lower for p in info["pattern"]):
                if info["suggested_tool"] != failed_tool:
                    suggestions.append({
                        "tool": info["suggested_tool"],
                        "type": "prerequisite",
                        "reason": info["reason"],
                        "description": _TOOL_DESCRIPTIONS.get(info["suggested_tool"], ""),
                    })

        if not suggestions:
            suggestions.append({
                "tool": "",
                "type": "escalate",
                "reason": "未找到自动替代方案，建议人工介入或检查输入数据",
                "description": "",
            })

        return json.dumps({
            "status": "success",
            "failed_tool": failed_tool,
            "error_summary": error_message[:200],
            "suggestions": suggestions,
        }, ensure_ascii=False)

    def get_evolution_report(self) -> str:
        """生成工具生态系统健康报告 — 工具总数、类别分布、成本分布、活跃率。

        Returns:
            JSON: 工具生态系统报告
        """
        all_meta = self.all_metadata
        active = [m for m in all_meta.values() if m.active]
        inactive = [m for m in all_meta.values() if not m.active]

        # Category distribution
        cat_dist: dict[str, int] = {}
        for m in active:
            cat_dist[m.category] = cat_dist.get(m.category, 0) + 1

        # Cost distribution
        cost_dist: dict[str, int] = {"low": 0, "medium": 0, "high": 0}
        for m in active:
            cost_dist[m.cost_level] = cost_dist.get(m.cost_level, 0) + 1

        # Source distribution
        source_dist: dict[str, int] = {}
        for m in active:
            source_dist[m.source] = source_dist.get(m.source, 0) + 1

        # Tools with alternatives
        with_alts = sum(1 for m in active if m.alternatives)

        return json.dumps({
            "status": "success",
            "total_tools": len(all_meta),
            "active_tools": len(active),
            "inactive_tools": len(inactive),
            "category_distribution": dict(sorted(cat_dist.items(), key=lambda x: x[1], reverse=True)),
            "cost_distribution": cost_dist,
            "source_distribution": source_dist,
            "tools_with_alternatives": with_alts,
            "dynamic_tools_count": len(self._dynamic_tools),
            "core_tools_count": sum(1 for m in active if m.is_core),
        }, ensure_ascii=False)

    def update_reliability_from_db(self) -> str:
        """从失败学习数据库更新工具可靠性评分。

        Returns:
            JSON: 更新结果
        """
        try:
            from .db_engine import get_engine
            engine = get_engine()
            if engine is None:
                return json.dumps({"status": "success", "updated": 0, "message": "DB unavailable"}, ensure_ascii=False)

            from sqlalchemy import text
            with engine.connect() as conn:
                rows = conn.execute(
                    text("SELECT tool_name, COUNT(*) as total, "
                         "SUM(CASE WHEN resolved THEN 1 ELSE 0 END) as resolved "
                         "FROM agent_tool_failures GROUP BY tool_name"),
                ).fetchall()

            updated = 0
            for r in rows:
                tool_name, total, resolved = r[0], r[1], r[2] or 0
                meta = self._metadata.get(tool_name) or self._dynamic_tools.get(tool_name)
                if meta:
                    meta.failure_count = total
                    meta.success_count = resolved
                    # Reliability = resolved_ratio weighted toward 1.0 for low failure counts
                    meta.reliability_score = round(max(0.0, 1.0 - (total - resolved) / max(total + 10, 1)), 2)
                    updated += 1

            return json.dumps({"status": "success", "updated": updated}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)


# Module-level singleton
_engine: Optional[ToolEvolutionEngine] = None


def get_evolution_engine() -> ToolEvolutionEngine:
    """Get or create the singleton ToolEvolutionEngine."""
    global _engine
    if _engine is None:
        _engine = ToolEvolutionEngine()
    return _engine

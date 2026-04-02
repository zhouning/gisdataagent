"""
GIS Data Agent — Agent definitions and pipeline assembly.
Tool functions live in data_agent/toolsets/; prompts in data_agent/prompts/.

Agents use BaseToolset instances for tool registration (see data_agent/toolsets/).
"""
from datetime import date

from google.adk.agents.llm_agent import Agent
from google.adk.agents import LlmAgent, SequentialAgent, LoopAgent, ParallelAgent
from google.adk.tools import VertexAiSearchTool, AgentTool

import os

# --- Prompt loading ---
from .prompts import get_prompt

# --- Utility helpers ---
from .utils import (
    _load_spatial_data,
    _configure_fonts,
    _add_basemap_layers,
    TIANDITU_TOKEN,
    _quality_gate_check,
    _self_correction_after_tool,
    _tool_retry_counts,
    approve_quality,
    _generate_upload_preview,
)

# --- Toolset classes (BaseToolset instances for agent tools=[]) ---
from .toolsets import (
    ExplorationToolset,
    GeoProcessingToolset,
    LocationToolset,
    AnalysisToolset,
    VisualizationToolset,
    DatabaseToolset,
    FileToolset,
    MemoryToolset,
    AdminToolset,
    RemoteSensingToolset,
    SpatialStatisticsToolset,
    SemanticLayerToolset,
    StreamingToolset,
    TeamToolset,
    DataLakeToolset,
    McpHubToolset,
    FusionToolset,
    KnowledgeGraphToolset,
    KnowledgeBaseToolset,
    AdvancedAnalysisToolset,
)
from .toolsets.governance_tools import GovernanceToolset
from .toolsets.chart_tools import ChartToolset
from .toolsets.watershed_tools import WatershedToolset
from .toolsets.virtual_source_tools import VirtualSourceToolset
from .toolsets.world_model_tools import WorldModelToolset
from .toolsets.nl2sql_tools import NL2SQLToolset
from .toolsets.causal_inference_tools import CausalInferenceToolset
from .toolsets.llm_causal_tools import LLMCausalToolset
from .toolsets.causal_world_model_tools import CausalWorldModelToolset
from .toolsets.dreamer_tools import DreamerToolset
from .toolsets.operator_tools import OperatorToolset
from .toolsets.evolution_tools import ToolEvolutionToolset
from .toolsets.data_cleaning_tools import DataCleaningToolset
from .toolsets.precision_tools import PrecisionToolset
from .toolsets.report_tools import ReportToolset
from .toolsets.skill_bundles import build_all_skills_toolset

# ArcPy conditional function lists (for governance agents needing specific subsets)
from .toolsets.geo_processing_tools import (
    ARCPY_AVAILABLE,
    _arcpy_funcs as _arcpy_tools,
    _arcpy_gov_explore_funcs as _arcpy_gov_explore_tools,
    _arcpy_gov_process_funcs as _arcpy_gov_process_tools,
)

# --- Backward-compatible re-exports (used by tests and app.py) ---
from .toolsets.exploration_tools import (
    describe_geodataframe,
    reproject_spatial_data,
    engineer_spatial_features,
)
from .toolsets.analysis_tools import ffi, drl_model, _plot_land_use_result
from .toolsets.visualization_tools import (
    visualize_optimization_comparison,
    visualize_interactive_map,
    generate_choropleth,
    generate_bubble_map,
    visualize_geodataframe,
    export_map_png,
    compose_map,
)
from .toolsets.file_tools import list_user_files, delete_user_file
from .spatial_statistics import spatial_autocorrelation, local_moran, hotspot_analysis
from .gis_processors import _generate_output_path, _resolve_path
from .database_tools import T_TABLE_OWNERSHIP
from .tool_filter import intent_tool_predicate

# ---------------------------------------------------------------------------
# Tool filter presets — reusable across agents
# ---------------------------------------------------------------------------

_AUDIT_TOOLS = [
    "describe_geodataframe", "check_topology",
    "check_field_standards", "check_consistency",
]
_TRANSFORM_TOOLS = ["reproject_spatial_data", "engineer_spatial_features"]
_DB_READ = ["query_database", "list_tables"]
_DB_READ_DESCRIBE = ["query_database", "list_tables", "describe_table"]
_DATALAKE_READ = ["list_data_assets", "describe_data_asset", "search_data_assets", "download_cloud_asset"]

# --- Model Tiering (configurable via env vars) ---
MODEL_FAST = os.environ.get("MODEL_FAST", "gemini-2.0-flash")
MODEL_STANDARD = os.environ.get("MODEL_STANDARD", "gemini-2.5-flash")
MODEL_PREMIUM = os.environ.get("MODEL_PREMIUM", "gemini-2.5-pro")

# --- Retry Configuration for 429 RESOURCE_EXHAUSTED ---
def _create_model_with_retry(model_name: str):
    """Create a Gemini model instance with retry configuration for 429 errors."""
    from google.adk.models.google_llm import Gemini
    from google.genai import types
    return Gemini(
        model_name=model_name,
        retry_options=types.HttpRetryOptions(
            initial_delay=2.0,  # 2 seconds initial backoff
            attempts=3,         # retry up to 3 times
        ),
    )

# --- Dynamic Model Selection ---
MODEL_TIER_MAP = {
    "fast": MODEL_FAST,
    "standard": MODEL_STANDARD,
    "premium": MODEL_PREMIUM,
}


def get_model_config() -> dict:
    """Return current model configuration for API exposure."""
    return {
        "tiers": {
            "fast": {"model": MODEL_FAST, "env_var": "MODEL_FAST"},
            "standard": {"model": MODEL_STANDARD, "env_var": "MODEL_STANDARD"},
            "premium": {"model": MODEL_PREMIUM, "env_var": "MODEL_PREMIUM"},
        },
        "router_model": os.environ.get("ROUTER_MODEL", "gemini-2.0-flash"),
    }


def get_model_for_tier(base_tier: str = "standard", task_type: str = None,
                       context_tokens: int = 0):
    """Get Gemini model instance with retry config based on ContextVar override or base tier.

    The current_model_tier ContextVar is set per-request by app.py
    based on assess_complexity(). Factory functions call this to
    select the appropriate model.

    When the ContextVar is at its default ('standard'), ``base_tier``
    takes precedence so that module-level agent creation honours the
    intended tier (e.g. 'fast' for PlannerExplorer).

    If task_type is provided, uses ModelRouter for task-aware selection.

    Returns:
        Gemini instance with retry configuration for 429 errors.
    """
    from .user_context import current_model_tier
    tier = current_model_tier.get()
    # Use base_tier when ContextVar hasn't been explicitly overridden
    if tier == "standard":
        tier = base_tier

    # Task-aware routing if task_type provided
    if task_type:
        try:
            from .model_gateway import ModelRouter
            router = ModelRouter()
            model_name = router.route(task_type=task_type, context_tokens=context_tokens,
                                     quality_requirement=tier)
        except Exception:
            model_name = MODEL_TIER_MAP.get(tier, MODEL_STANDARD)
    else:
        model_name = MODEL_TIER_MAP.get(tier, MODEL_STANDARD)

    return _create_model_with_retry(model_name)

# --- Vertex AI Search Datastore ---
DATASTORE_ID = os.environ.get(
    "DATASTORE_ID",
    "projects/gen-lang-client-0977577668/locations/global/collections/default_collection/dataStores/adktest20260101_1767273453936",
)

# ============================================================================
# Optimization Pipeline (data_pipeline)
# ============================================================================

knowledge_agent = Agent(
    name="vertex_search_agent",
    model=_create_model_with_retry(MODEL_STANDARD),
    instruction=get_prompt("optimization", "knowledge_agent_instruction"),
    description="Vertex AI Search 企业文档搜索助手",
    output_key="domain_knowledge",
    tools=[VertexAiSearchTool(data_store_id=DATASTORE_ID)],
)

# Wrap knowledge_agent as an on-demand tool (ADK Optimization 2.1).
# Processing agent can call it when domain knowledge is needed,
# instead of running it blindly in parallel.
knowledge_tool = AgentTool(agent=knowledge_agent, skip_summarization=False)

data_exploration_agent = LlmAgent(
    name="DataExploration",
    instruction=get_prompt("optimization", "data_exploration_opt_instruction"),
    description="优化管道数据准备专家",
    model=_create_model_with_retry(MODEL_STANDARD),
    output_key="data_profile",
    after_tool_callback=_self_correction_after_tool,
    tools=[
        ExplorationToolset(tool_filter=_AUDIT_TOOLS),
        DatabaseToolset(tool_filter=_DB_READ),
        DataLakeToolset(tool_filter=_DATALAKE_READ),
    ],
)

semantic_prefetch_agent = LlmAgent(
    name="SemanticPreFetch",
    instruction=(
        "你是语义层预取助手。在数据探查阶段并行运行，预加载语义目录和数据资产信息。\n"
        "1. 调用 list_semantic_sources 获取可用语义源列表\n"
        "2. 调用 search_data_assets 或 list_data_assets 浏览数据目录\n"
        "3. 对相关源调用 resolve_semantic_context 获取字段映射\n"
        "4. 将发现的语义上下文和数据目录信息写入 semantic_context\n"
        "保持只读操作，不修改任何数据。"
    ),
    description="语义层预取助手——并行加载语义目录与数据资产信息",
    model=_create_model_with_retry(MODEL_FAST),
    output_key="semantic_context",
    tools=[
        SemanticLayerToolset(tool_filter=[
            "resolve_semantic_context", "describe_table_semantic",
            "list_semantic_sources", "browse_hierarchy",
            "discover_column_equivalences",
        ]),
        DataLakeToolset(tool_filter=_DATALAKE_READ),
    ],
)

parallel_data_ingestion = ParallelAgent(
    name="ParallelDataIngestion",
    description="并行数据摄入——同时执行数据探查和语义预取",
    sub_agents=[data_exploration_agent, semantic_prefetch_agent],
)

data_processing_agent = LlmAgent(
    name="DataProcessing",
    instruction=get_prompt("optimization", "data_processing_opt_instruction"),
    description="优化管道数据预处理专家",
    model=_create_model_with_retry(MODEL_STANDARD),
    output_key="processed_data",
    after_tool_callback=_self_correction_after_tool,
    tools=[
        ExplorationToolset(tool_filter=_TRANSFORM_TOOLS),
        GeoProcessingToolset(tool_filter=[
            "generate_tessellation", "raster_to_polygon", "pairwise_clip",
            "tabulate_intersection", "surface_parameters", "zonal_statistics_as_table",
            "polygon_neighbors", "add_field", "add_join",
            "calculate_field", "summary_statistics",
        ]),
        LocationToolset(tool_filter=["batch_geocode", "reverse_geocode"]),
        RemoteSensingToolset(tool_filter=["download_lulc", "download_dem"]),
        FusionToolset(),
        knowledge_tool,  # on-demand domain knowledge (2.1)
    ] + _arcpy_tools,
)

data_engineering_agent = SequentialAgent(
    name="DataEngineering",
    sub_agents=[parallel_data_ingestion, data_processing_agent],
)

data_analysis_agent = LlmAgent(
    name="DataAnalysis",
    instruction=get_prompt("optimization", "data_analysis_agent_instruction"),
    description="空间分析与优化专家",
    model=_create_model_with_retry(MODEL_STANDARD),
    output_key="analysis_report",
    tools=[AnalysisToolset(), RemoteSensingToolset(), SpatialStatisticsToolset(), AdvancedAnalysisToolset(), CausalInferenceToolset(), LLMCausalToolset(), DreamerToolset()],
)

# --- Quality Checker + LoopAgent (ADK Optimization 2.2) ---
# Generator-Critic pattern: analysis runs, quality checker evaluates,
# loop repeats if checker finds business-level issues (max 3 iterations).
quality_checker_agent = LlmAgent(
    name="QualityChecker",
    instruction=get_prompt("optimization", "quality_checker_instruction"),
    description="分析结果质量审查员。验证DRL优化/遥感指标合理性。",
    model=_create_model_with_retry(MODEL_FAST),
    output_key="quality_verdict",
    tools=[approve_quality],
)

analysis_quality_loop = LoopAgent(
    name="AnalysisQualityLoop",
    sub_agents=[data_analysis_agent, quality_checker_agent],
    max_iterations=3,
)

data_visualization_agent = LlmAgent(
    name="DataVisualization",
    instruction=get_prompt("optimization", "data_visualization_agent_instruction"),
    description="制图与可视化专家",
    model=_create_model_with_retry(MODEL_STANDARD),
    output_key="visualizations",
    tools=[
        VisualizationToolset(tool_filter=[
            "visualize_geodataframe", "visualize_optimization_comparison",
            "visualize_interactive_map", "generate_choropleth",
            "generate_bubble_map", "export_map_png", "compose_map",
        ]),
    ],
)

data_summary_agent = LlmAgent(
    name="DataSummary",
    instruction=get_prompt("optimization", "data_summary_agent_instruction"),
    global_instruction=f"今天的时间是： {date.today()}",
    description="决策总结专家",
    model=_create_model_with_retry(MODEL_STANDARD),
    output_key="final_summary",
)

# Pipeline: ParallelDataIngestion(Exploration || SemanticPreFetch) → Processing → QualityLoop → Viz → Summary
data_pipeline = SequentialAgent(
    name="DataPipeline",
    sub_agents=[
        data_engineering_agent,
        analysis_quality_loop,
        data_visualization_agent,
        data_summary_agent,
    ],
)

# ============================================================================
# Governance Pipeline
# ============================================================================

governance_exploration_agent = LlmAgent(
    name="GovExploration",
    instruction=get_prompt("governance", "governance_exploration_instruction"),
    description="数据质量审计员 — 7 项治理检查 + 综合评分",
    model=_create_model_with_retry(MODEL_STANDARD),
    output_key="data_profile",
    after_tool_callback=_self_correction_after_tool,
    tools=[
        ExplorationToolset(tool_filter=_AUDIT_TOOLS),
        DatabaseToolset(tool_filter=_DB_READ),
        GovernanceToolset(tool_filter=[
            "check_completeness", "check_attribute_range",
            "check_crs_consistency", "check_topology_integrity",
            "check_area_consistency", "check_building_height",
            "check_coordinate_precision", "generate_governance_plan",
        ]),
    ] + _arcpy_gov_explore_tools,
)

governance_processing_agent = LlmAgent(
    name="GovProcessing",
    instruction=get_prompt("governance", "governance_processing_instruction"),
    description="数据修复专家",
    model=_create_model_with_retry(MODEL_STANDARD),
    output_key="processed_data",
    after_tool_callback=_self_correction_after_tool,
    tools=[
        ExplorationToolset(tool_filter=_TRANSFORM_TOOLS),
        GeoProcessingToolset(tool_filter=[
            "polygon_neighbors", "add_field", "calculate_field",
        ]),
        LocationToolset(tool_filter=["batch_geocode", "reverse_geocode"]),
        FusionToolset(),
        GovernanceToolset(tool_filter=[
            "check_gaps", "check_duplicates",
            "governance_score", "governance_summary", "classify_defects",
        ]),
        PrecisionToolset(),
    ] + _arcpy_gov_process_tools,
)

governance_viz_agent = LlmAgent(
    name="GovernanceViz",
    instruction=get_prompt("governance", "governance_viz_instruction"),
    description="治理审计可视化 — 雷达图 + 问题分布图",
    model=_create_model_with_retry(MODEL_STANDARD),
    output_key="governance_visualizations",
    tools=[
        VisualizationToolset(tool_filter=[
            "visualize_interactive_map", "generate_choropleth", "compose_map",
        ]),
        ChartToolset(),
    ],
)

governance_report_agent = LlmAgent(
    name="GovernanceReporter",
    instruction=get_prompt("governance", "governance_reporter_instruction"),
    model=_create_model_with_retry(MODEL_STANDARD),
    output_key="governance_report",
    tools=[
        ReportToolset(),
    ],
)

# --- Governance Quality Checker + LoopAgent (v7.1.6) ---
governance_checker_agent = LlmAgent(
    name="GovernanceChecker",
    instruction=get_prompt("governance", "governance_checker_instruction"),
    description="治理报告合规性审查员。验证评分、方法覆盖和整改建议。",
    model=_create_model_with_retry(MODEL_FAST),
    output_key="gov_quality_verdict",
    tools=[approve_quality],
)

governance_report_loop = LoopAgent(
    name="GovernanceReportLoop",
    sub_agents=[governance_report_agent, governance_checker_agent],
    max_iterations=3,
)

governance_pipeline = SequentialAgent(
    name="GovernancePipeline",
    sub_agents=[governance_exploration_agent, governance_processing_agent, governance_viz_agent, governance_report_loop],
)

# ============================================================================
# General Pipeline
# ============================================================================

general_processing_agent = LlmAgent(
    name="GeneralProcessing",
    instruction=get_prompt("general", "general_processing_instruction"),
    description="通用数据处理与语义映射",
    model=_create_model_with_retry(MODEL_STANDARD),
    output_key="processed_data",
    after_tool_callback=_self_correction_after_tool,
    tools=[
        ExplorationToolset(tool_filter=_TRANSFORM_TOOLS + _AUDIT_TOOLS),
        GeoProcessingToolset(tool_filter=intent_tool_predicate),
        LocationToolset(tool_filter=intent_tool_predicate),
        DatabaseToolset(tool_filter=_DB_READ_DESCRIBE + ["share_table", "import_to_postgis"]),
        FileToolset(),
        MemoryToolset(),
        AdminToolset(tool_filter=intent_tool_predicate),
        RemoteSensingToolset(tool_filter=intent_tool_predicate),
        SpatialStatisticsToolset(tool_filter=intent_tool_predicate),
        SemanticLayerToolset(tool_filter=intent_tool_predicate),
        StreamingToolset(tool_filter=intent_tool_predicate),
        TeamToolset(tool_filter=intent_tool_predicate),
        DataLakeToolset(tool_filter=intent_tool_predicate),
        McpHubToolset(pipeline="general"),
        FusionToolset(tool_filter=intent_tool_predicate),
        KnowledgeGraphToolset(tool_filter=intent_tool_predicate),
        KnowledgeBaseToolset(tool_filter=intent_tool_predicate),
        AdvancedAnalysisToolset(tool_filter=intent_tool_predicate),
        VirtualSourceToolset(tool_filter=intent_tool_predicate),
        WorldModelToolset(tool_filter=intent_tool_predicate),
        CausalWorldModelToolset(tool_filter=intent_tool_predicate),
        LLMCausalToolset(tool_filter=intent_tool_predicate),
        GovernanceToolset(),
        DataCleaningToolset(),
        PrecisionToolset(),
        ReportToolset(),
    ] + _arcpy_tools,
)

general_viz_agent = LlmAgent(
    name="GeneralViz",
    instruction=get_prompt("general", "general_viz_instruction"),
    model=_create_model_with_retry(MODEL_STANDARD),
    output_key="visualizations",
    tools=[
        VisualizationToolset(tool_filter=[
            "visualize_geodataframe", "visualize_interactive_map",
            "generate_heatmap", "generate_choropleth",
            "generate_bubble_map", "export_map_png", "compose_map",
        ]),
        ChartToolset(),
    ],
)

general_summary_agent = LlmAgent(
    name="GeneralSummary",
    instruction=get_prompt("general", "general_summary_instruction"),
    model=_create_model_with_retry(MODEL_STANDARD),
    output_key="final_summary",
)

# --- General Result Checker + LoopAgent (v7.1.6) ---
general_result_checker = LlmAgent(
    name="GeneralResultChecker",
    instruction=get_prompt("general", "general_result_checker_instruction"),
    description="分析结果完整性审查员。验证输出文件、方法说明和汇报质量。",
    model=_create_model_with_retry(MODEL_FAST),
    output_key="general_quality_verdict",
    tools=[approve_quality],
)

general_summary_loop = LoopAgent(
    name="GeneralSummaryLoop",
    sub_agents=[general_summary_agent, general_result_checker],
    max_iterations=3,
)

general_pipeline = SequentialAgent(
    name="GeneralPipeline",
    sub_agents=[general_processing_agent, general_viz_agent, general_summary_loop],
)

# ============================================================================
# Dynamic Planner
# ============================================================================

# --- Planner agent factory functions (ADK Optimization 2.3) ---
# ADK enforces a one-parent constraint: an agent instance cannot be shared
# across multiple parent agents.  Factory functions let us create independent
# copies with identical configuration for use in sub-workflows.

_SEMANTIC_READONLY = [
    "resolve_semantic_context", "describe_table_semantic",
    "list_semantic_sources", "discover_column_equivalences",
    "export_semantic_model",
]


def _make_planner_explorer(name: str, **overrides) -> LlmAgent:
    """Factory for PlannerExplorer-like agents."""
    defaults = dict(
        name=name,
        instruction=get_prompt("planner", "planner_explorer_instruction"),
        description="数据探查与质量审计专家。数据画像、拓扑检查、字段标准、数据库查询、表结构分析。",
        model=get_model_for_tier("fast"),
        output_key="data_profile",
        disallow_transfer_to_peers=True,
        after_tool_callback=_self_correction_after_tool,
        tools=[
            ExplorationToolset(tool_filter=_AUDIT_TOOLS),
            DatabaseToolset(tool_filter=_DB_READ_DESCRIBE),
            FileToolset(),
            SemanticLayerToolset(tool_filter=_SEMANTIC_READONLY),
            DataLakeToolset(tool_filter=_DATALAKE_READ),
        ] + _arcpy_gov_explore_tools,
    )
    defaults.update(overrides)
    return LlmAgent(**defaults)


def _make_planner_processor(name: str, **overrides) -> LlmAgent:
    """Factory for PlannerProcessor-like agents."""
    defaults = dict(
        name=name,
        instruction=get_prompt("planner", "planner_processor_instruction"),
        description="数据修复与空间处理专家。坐标转换、地理编码、裁剪、缓冲区、聚类、POI、行政区划。",
        model=get_model_for_tier("standard"),
        output_key="processed_data",
        disallow_transfer_to_peers=True,
        after_tool_callback=_self_correction_after_tool,
        tools=[
            ExplorationToolset(tool_filter=_TRANSFORM_TOOLS),
            GeoProcessingToolset(tool_filter=intent_tool_predicate),
            LocationToolset(tool_filter=intent_tool_predicate),
            RemoteSensingToolset(tool_filter=["download_lulc", "download_dem"]),
            StreamingToolset(tool_filter=intent_tool_predicate),
            DatabaseToolset(tool_filter=["import_to_postgis"]),
            McpHubToolset(pipeline="planner"),
            FusionToolset(tool_filter=intent_tool_predicate),
            KnowledgeGraphToolset(tool_filter=intent_tool_predicate),
            KnowledgeBaseToolset(tool_filter=["search_knowledge_base", "get_kb_context", "list_knowledge_bases"]),
            VirtualSourceToolset(tool_filter=intent_tool_predicate),
        ] + _arcpy_tools,
    )
    defaults.update(overrides)
    return LlmAgent(**defaults)


def _make_planner_analyzer(name: str, **overrides) -> LlmAgent:
    """Factory for PlannerAnalyzer-like agents."""
    defaults = dict(
        name=name,
        instruction=get_prompt("planner", "planner_analyzer_instruction"),
        description="DRL深度强化学习布局优化、遥感分析、空间统计专家。",
        model=get_model_for_tier("standard"),
        output_key="analysis_report",
        disallow_transfer_to_peers=True,
        after_tool_callback=_self_correction_after_tool,
        tools=[AnalysisToolset(), RemoteSensingToolset(tool_filter=["calculate_ndvi", "calculate_spectral_index", "assess_cloud_cover", "describe_raster"]), SpatialStatisticsToolset(), AdvancedAnalysisToolset(), CausalInferenceToolset(), LLMCausalToolset(), DreamerToolset()],
    )
    defaults.update(overrides)
    return LlmAgent(**defaults)


def _make_planner_visualizer(name: str, **overrides) -> LlmAgent:
    """Factory for PlannerVisualizer-like agents."""
    defaults = dict(
        name=name,
        instruction=get_prompt("planner", "planner_visualizer_instruction"),
        description="地理空间可视化专家。交互地图、Choropleth、热力图、气泡图、PNG导出。",
        model=get_model_for_tier("standard"),
        output_key="visualizations",
        disallow_transfer_to_peers=True,
        tools=[
            VisualizationToolset(),
            ChartToolset(),
        ],
    )
    defaults.update(overrides)
    return LlmAgent(**defaults)


# --- Standalone planner sub-agents (via factories) ---
planner_explorer = _make_planner_explorer("PlannerExplorer")
planner_processor = _make_planner_processor("PlannerProcessor")
planner_analyzer = _make_planner_analyzer("PlannerAnalyzer")
planner_visualizer = _make_planner_visualizer("PlannerVisualizer")

planner_reporter = LlmAgent(
    name="PlannerReporter",
    instruction=get_prompt("planner", "planner_reporter_instruction"),
    description="综合分析报告撰写专家。汇总所有分析步骤为专业报告。",
    model=_create_model_with_retry(MODEL_PREMIUM),
    output_key="final_report",
    disallow_transfer_to_peers=True,
)

# --- Sub-workflows (ADK Optimization 2.3 + v9.0.2 Parallel) ---
# Common sequential patterns packaged as SequentialAgent to eliminate
# unnecessary Planner routing hops (8 hops → 3 for optimization flow).
# v9.0.2: Exploration + SemanticPreFetch run in parallel.


def _make_semantic_prefetch(name: str) -> LlmAgent:
    """Factory for SemanticPreFetch agent instances (ADK one-parent constraint)."""
    return LlmAgent(
        name=name,
        instruction=(
            "你是语义层预取助手。在数据探查阶段并行运行，预加载语义目录和数据资产信息。\n"
            "1. 调用 list_semantic_sources 获取可用语义源列表\n"
            "2. 调用 search_data_assets 或 list_data_assets 浏览数据目录\n"
            "3. 对相关源调用 resolve_semantic_context 获取字段映射\n"
            "4. 将发现的语义上下文和数据目录信息写入 semantic_context\n"
            "保持只读操作，不修改任何数据。"
        ),
        description="语义层预取助手——并行加载语义目录与数据资产信息",
        model=get_model_for_tier("fast"),
        output_key="semantic_context",
        disallow_transfer_to_peers=True,
        tools=[
            SemanticLayerToolset(tool_filter=[
                "resolve_semantic_context", "describe_table_semantic",
                "list_semantic_sources", "browse_hierarchy",
                "discover_column_equivalences",
            ]),
            DataLakeToolset(tool_filter=_DATALAKE_READ),
        ],
    )


explore_process_workflow = SequentialAgent(
    name="ExploreAndProcess",
    description="并行数据探查(探查+语义预取)→数据处理 一体化工作流。",
    sub_agents=[
        ParallelAgent(
            name="WFParallelIngestion",
            description="并行探查+语义预取",
            sub_agents=[
                _make_planner_explorer("WFExplorer"),
                _make_semantic_prefetch("WFSemanticPreFetch"),
            ],
        ),
        _make_planner_processor("WFProcessor"),
    ],
)

analyze_viz_workflow = SequentialAgent(
    name="AnalyzeAndVisualize",
    description="分析→可视化 一体化工作流。执行DRL/统计分析后自动生成可视化。",
    sub_agents=[
        _make_planner_analyzer("WFAnalyzer"),
        _make_planner_visualizer("WFVisualizer"),
    ],
)

# --- S-5: Specialized Agent factory functions (Multi-Agent Collaboration) ---


def _make_data_engineer(name: str, **overrides) -> LlmAgent:
    """Factory for DataEngineer agents — data cleaning, integration, standardization."""
    defaults = dict(
        name=name,
        instruction=get_prompt("multi_agent", "data_engineer_instruction"),
        description="数据工程专家: 清洗/集成/标准化/质量保障。使用语义算子自动选择策略。",
        model=get_model_for_tier("standard"),
        output_key="prepared_data",
        disallow_transfer_to_peers=True,
        after_tool_callback=_self_correction_after_tool,
        tools=[
            OperatorToolset(tool_filter=["clean_data", "integrate_data", "list_operators"]),
            DataCleaningToolset(),
            GovernanceToolset(),
            PrecisionToolset(),
            ExplorationToolset(tool_filter=_AUDIT_TOOLS),
            DatabaseToolset(tool_filter=_DB_READ_DESCRIBE),
            FileToolset(),
        ],
    )
    defaults.update(overrides)
    return LlmAgent(**defaults)


def _make_analyst(name: str, **overrides) -> LlmAgent:
    """Factory for Analyst agents — spatial statistics, DRL, causal, world model."""
    defaults = dict(
        name=name,
        instruction=get_prompt("multi_agent", "analyst_instruction"),
        description="空间分析专家: 空间统计/DRL优化/因果推断/地形/世界模型。",
        model=get_model_for_tier("standard"),
        output_key="analysis_result",
        disallow_transfer_to_peers=True,
        after_tool_callback=_self_correction_after_tool,
        tools=[
            OperatorToolset(tool_filter=["analyze_data", "list_operators"]),
            AnalysisToolset(),
            SpatialStatisticsToolset(),
            AdvancedAnalysisToolset(),
            CausalInferenceToolset(),
            LLMCausalToolset(),
            WorldModelToolset(),
            CausalWorldModelToolset(),
            DreamerToolset(),
        ],
    )
    defaults.update(overrides)
    return LlmAgent(**defaults)


def _make_visualizer_agent(name: str, **overrides) -> LlmAgent:
    """Factory for Visualizer agents — maps, charts, reports."""
    defaults = dict(
        name=name,
        instruction=get_prompt("multi_agent", "visualizer_instruction"),
        description="可视化专家: 交互地图/统计图表/报告生成/PNG导出。",
        model=get_model_for_tier("standard"),
        output_key="visualization_output",
        disallow_transfer_to_peers=True,
        tools=[
            OperatorToolset(tool_filter=["visualize_data", "list_operators"]),
            VisualizationToolset(),
            ChartToolset(),
            ReportToolset(),
            DataLakeToolset(tool_filter=_DATALAKE_READ),
            ExplorationToolset(tool_filter=["describe_geodataframe"]),
            FileToolset(),
        ],
    )
    defaults.update(overrides)
    return LlmAgent(**defaults)


def _make_remote_sensing(name: str, **overrides) -> LlmAgent:
    """Factory for RemoteSensing agents — spectral, DEM, watershed, LULC."""
    defaults = dict(
        name=name,
        instruction=get_prompt("multi_agent", "remote_sensing_instruction"),
        description="遥感分析专家: 光谱指数/DEM/流域/LULC/变化检测。",
        model=get_model_for_tier("standard"),
        output_key="rs_analysis",
        disallow_transfer_to_peers=True,
        after_tool_callback=_self_correction_after_tool,
        tools=[
            RemoteSensingToolset(),
            WatershedToolset(),
            SpatialStatisticsToolset(),
            VisualizationToolset(tool_filter=["visualize_interactive_map", "export_map_png"]),
            ExplorationToolset(tool_filter=["describe_geodataframe", "describe_raster"]),
        ] + _arcpy_tools,
    )
    defaults.update(overrides)
    return LlmAgent(**defaults)


# --- S-5 Standalone specialized agents ---
data_engineer_agent = _make_data_engineer("DataEngineerAgent")
analyst_agent = _make_analyst("AnalystAgent")
visualizer_agent = _make_visualizer_agent("VisualizerAgent")
remote_sensing_agent = _make_remote_sensing("RemoteSensingAgent")

# --- S-5 Multi-agent workflows ---
full_analysis_workflow = SequentialAgent(
    name="FullAnalysis",
    description="数据准备→分析→可视化 端到端流程。适用于从原始数据到完整分析报告。",
    sub_agents=[
        _make_data_engineer("FADataEngineer"),
        _make_analyst("FAAnalyst"),
        _make_visualizer_agent("FAVisualizer"),
    ],
)

rs_analysis_workflow = SequentialAgent(
    name="RSAnalysis",
    description="遥感分析→可视化 专业流程。适用于卫星影像和地形分析。",
    sub_agents=[
        _make_remote_sensing("RSRemoteSensing"),
        _make_visualizer_agent("RSVisualizer"),
    ],
)

planner_agent = LlmAgent(
    name="Planner",
    instruction=get_prompt("planner", "planner_instruction"),
    global_instruction=f"今天的日期是：{date.today()}",
    description="GIS数据智能体总调度（动态规划模式）",
    model=_create_model_with_retry(MODEL_STANDARD),
    output_key="planner_summary",
    tools=[
        build_all_skills_toolset(),  # 5 domain skills, incremental loading
        MemoryToolset(),
        NL2SQLToolset(),  # Schema-aware NL2SQL for dynamic table queries
        OperatorToolset(),  # Semantic operators: clean/integrate/analyze/visualize (L3)
        ToolEvolutionToolset(),  # Tool evolution: metadata, failure-driven discovery, dynamic management (L3)
    ],
    sub_agents=[
        planner_explorer, planner_processor, planner_analyzer,
        planner_visualizer, planner_reporter,
    ],
)

root_agent = data_pipeline

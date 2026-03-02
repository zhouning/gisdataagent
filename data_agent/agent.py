"""
GIS Data Agent — Agent definitions and pipeline assembly.
Tool functions live in data_agent/toolsets/; prompts in data_agent/prompts/.

Agents use BaseToolset instances for tool registration (see data_agent/toolsets/).
"""
from datetime import date

from google.adk.agents.llm_agent import Agent
from google.adk.agents import LlmAgent, SequentialAgent, LoopAgent
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
)

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
_DATALAKE_READ = ["list_data_assets", "describe_data_asset", "search_data_assets"]

# --- Model Tiering ---
MODEL_FAST = "gemini-2.0-flash"
MODEL_STANDARD = "gemini-2.5-flash"
MODEL_PREMIUM = "gemini-2.5-pro"

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
    model=MODEL_STANDARD,
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
    instruction=get_prompt("optimization", "data_exploration_agent_instruction"),
    description="数据质量审计与治理专家",
    model=MODEL_STANDARD,
    output_key="data_profile",
    after_tool_callback=_self_correction_after_tool,
    tools=[
        ExplorationToolset(tool_filter=_AUDIT_TOOLS),
        DatabaseToolset(tool_filter=_DB_READ),
        DataLakeToolset(tool_filter=_DATALAKE_READ),
    ],
)

data_processing_agent = LlmAgent(
    name="DataProcessing",
    instruction=get_prompt("optimization", "data_processing_agent_instruction"),
    description="特征工程与预处理专家",
    model=MODEL_STANDARD,
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
        knowledge_tool,  # on-demand domain knowledge (2.1)
    ] + _arcpy_tools,
)

data_engineering_agent = SequentialAgent(
    name="DataEngineering",
    sub_agents=[data_exploration_agent, data_processing_agent],
)

data_analysis_agent = LlmAgent(
    name="DataAnalysis",
    instruction=get_prompt("optimization", "data_analysis_agent_instruction"),
    description="空间分析与优化专家",
    model=MODEL_STANDARD,
    output_key="analysis_report",
    tools=[AnalysisToolset(), RemoteSensingToolset(), SpatialStatisticsToolset()],
)

# --- Quality Checker + LoopAgent (ADK Optimization 2.2) ---
# Generator-Critic pattern: analysis runs, quality checker evaluates,
# loop repeats if checker finds business-level issues (max 3 iterations).
quality_checker_agent = LlmAgent(
    name="QualityChecker",
    instruction=get_prompt("optimization", "quality_checker_instruction"),
    description="分析结果质量审查员。验证FFI/DRL/遥感指标合理性。",
    model=MODEL_FAST,
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
    model=MODEL_STANDARD,
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
    model=MODEL_STANDARD,
    output_key="final_summary",
)

# Simplified pipeline: no ParallelAgent, knowledge is on-demand via tool,
# analysis wrapped in quality loop.
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
    instruction=get_prompt("optimization", "data_exploration_agent_instruction"),
    description="数据质量审计员",
    model=MODEL_STANDARD,
    output_key="data_profile",
    after_tool_callback=_self_correction_after_tool,
    tools=[
        ExplorationToolset(tool_filter=_AUDIT_TOOLS),
        DatabaseToolset(tool_filter=_DB_READ),
    ] + _arcpy_gov_explore_tools,
)

governance_processing_agent = LlmAgent(
    name="GovProcessing",
    instruction=get_prompt("optimization", "data_processing_agent_instruction"),
    description="数据修复专家",
    model=MODEL_STANDARD,
    output_key="processed_data",
    after_tool_callback=_self_correction_after_tool,
    tools=[
        ExplorationToolset(tool_filter=_TRANSFORM_TOOLS),
        GeoProcessingToolset(tool_filter=[
            "polygon_neighbors", "add_field", "calculate_field",
        ]),
        LocationToolset(tool_filter=["batch_geocode", "reverse_geocode"]),
    ] + _arcpy_gov_process_tools,
)

governance_report_agent = LlmAgent(
    name="GovernanceReporter",
    instruction=get_prompt("general", "governance_reporter_instruction"),
    model=MODEL_STANDARD,
    output_key="governance_report",
)

governance_pipeline = SequentialAgent(
    name="GovernancePipeline",
    sub_agents=[governance_exploration_agent, governance_processing_agent, governance_report_agent],
)

# ============================================================================
# General Pipeline
# ============================================================================

general_processing_agent = LlmAgent(
    name="GeneralProcessing",
    instruction=get_prompt("general", "general_processing_instruction"),
    description="通用数据处理与语义映射",
    model=MODEL_STANDARD,
    output_key="processed_data",
    after_tool_callback=_self_correction_after_tool,
    tools=[
        ExplorationToolset(tool_filter=_TRANSFORM_TOOLS),
        GeoProcessingToolset(),
        LocationToolset(),
        DatabaseToolset(tool_filter=_DB_READ_DESCRIBE + ["share_table", "import_to_postgis"]),
        FileToolset(),
        MemoryToolset(),
        AdminToolset(),
        RemoteSensingToolset(),
        SpatialStatisticsToolset(),
        SemanticLayerToolset(),
        StreamingToolset(),
        TeamToolset(),
        DataLakeToolset(),
    ] + _arcpy_tools,
)

general_viz_agent = LlmAgent(
    name="GeneralViz",
    instruction=get_prompt("general", "general_viz_instruction"),
    model=MODEL_STANDARD,
    output_key="visualizations",
    tools=[
        VisualizationToolset(tool_filter=[
            "visualize_geodataframe", "visualize_interactive_map",
            "generate_heatmap", "generate_choropleth",
            "generate_bubble_map", "export_map_png", "compose_map",
        ]),
    ],
)

general_summary_agent = LlmAgent(
    name="GeneralSummary",
    instruction=get_prompt("general", "general_summary_instruction"),
    model=MODEL_STANDARD,
    output_key="final_summary",
)

general_pipeline = SequentialAgent(
    name="GeneralPipeline",
    sub_agents=[general_processing_agent, general_viz_agent, general_summary_agent],
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
        model=MODEL_FAST,
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
        model=MODEL_STANDARD,
        output_key="processed_data",
        disallow_transfer_to_peers=True,
        after_tool_callback=_self_correction_after_tool,
        tools=[
            ExplorationToolset(tool_filter=_TRANSFORM_TOOLS),
            GeoProcessingToolset(),
            LocationToolset(),
            RemoteSensingToolset(tool_filter=["describe_raster", "download_lulc", "download_dem"]),
            StreamingToolset(),
            DataLakeToolset(tool_filter=_DATALAKE_READ),
            DatabaseToolset(tool_filter=["import_to_postgis"]),
        ] + _arcpy_tools,
    )
    defaults.update(overrides)
    return LlmAgent(**defaults)


def _make_planner_analyzer(name: str, **overrides) -> LlmAgent:
    """Factory for PlannerAnalyzer-like agents."""
    defaults = dict(
        name=name,
        instruction=get_prompt("planner", "planner_analyzer_instruction"),
        description="FFI破碎化指数、DRL深度强化学习布局优化、遥感分析、空间统计专家。",
        model=MODEL_STANDARD,
        output_key="analysis_report",
        disallow_transfer_to_peers=True,
        after_tool_callback=_self_correction_after_tool,
        tools=[AnalysisToolset(), RemoteSensingToolset(), SpatialStatisticsToolset()],
    )
    defaults.update(overrides)
    return LlmAgent(**defaults)


def _make_planner_visualizer(name: str, **overrides) -> LlmAgent:
    """Factory for PlannerVisualizer-like agents."""
    defaults = dict(
        name=name,
        instruction=get_prompt("planner", "planner_visualizer_instruction"),
        description="地理空间可视化专家。交互地图、Choropleth、热力图、气泡图、PNG导出。",
        model=MODEL_FAST,
        output_key="visualizations",
        disallow_transfer_to_peers=True,
        tools=[VisualizationToolset()],
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
    model=MODEL_PREMIUM,
    output_key="final_report",
    disallow_transfer_to_peers=True,
)

# --- Sub-workflows (ADK Optimization 2.3) ---
# Common sequential patterns packaged as SequentialAgent to eliminate
# unnecessary Planner routing hops (8 hops → 3 for optimization flow).

explore_process_workflow = SequentialAgent(
    name="ExploreAndProcess",
    description="数据探查→数据处理 一体化工作流。先审计数据质量再自动执行空间处理，无需中间路由。",
    sub_agents=[
        _make_planner_explorer("WFExplorer"),
        _make_planner_processor("WFProcessor"),
    ],
)

analyze_viz_workflow = SequentialAgent(
    name="AnalyzeAndVisualize",
    description="分析→可视化 一体化工作流。执行FFI/DRL/统计分析后自动生成可视化。",
    sub_agents=[
        _make_planner_analyzer("WFAnalyzer"),
        _make_planner_visualizer("WFVisualizer"),
    ],
)

planner_agent = LlmAgent(
    name="Planner",
    instruction=get_prompt("planner", "planner_instruction"),
    global_instruction=f"今天的日期是：{date.today()}",
    description="GIS数据智能体总调度（动态规划模式）",
    model=MODEL_STANDARD,
    output_key="planner_summary",
    tools=[
        MemoryToolset(),
        AdminToolset(),
        TeamToolset(),
        DataLakeToolset(tool_filter=_DATALAKE_READ),
    ],
    sub_agents=[
        planner_explorer, planner_processor, planner_analyzer,
        planner_visualizer, planner_reporter,
        explore_process_workflow,
        analyze_viz_workflow,
    ],
)

root_agent = data_pipeline

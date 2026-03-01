"""
GIS Data Agent — Agent definitions and pipeline assembly.
Tool functions live in data_agent/toolsets/; prompts in data_agent/prompts/.

Agents use BaseToolset instances for tool registration (see data_agent/toolsets/).
"""
from datetime import date

from google.adk.agents.llm_agent import Agent
from google.adk.agents import LlmAgent, SequentialAgent
from google.adk.tools import VertexAiSearchTool

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
)

# --- Toolset classes (BaseToolset instances for agent tools=[]) ---
from .toolsets import (
    ExplorationToolset,
    ProcessingToolset,
    AnalysisToolset,
    VisualizationToolset,
    DatabaseToolset,
    PlatformToolset,
    RemoteSensingToolset,
    SpatialStatisticsToolset,
    SemanticLayerToolset,
    StreamingToolset,
)

# ArcPy conditional function lists (for governance agents needing specific subsets)
from .toolsets.processing_tools import (
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
from .toolsets.platform_tools import list_user_files, delete_user_file
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
_MEMORY_TOOLS = [
    "save_memory", "recall_memories", "list_memories", "delete_memory",
]
_ADMIN_TOOLS = [
    "get_usage_summary", "query_audit_log",
    "list_templates", "delete_template", "share_template",
]

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
        ProcessingToolset(tool_filter=[
            "generate_tessellation", "raster_to_polygon", "pairwise_clip",
            "tabulate_intersection", "surface_parameters", "zonal_statistics_as_table",
            "batch_geocode", "reverse_geocode",
            "polygon_neighbors", "add_field", "add_join",
            "calculate_field", "summary_statistics",
        ]),
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

data_pipeline = SequentialAgent(
    name="DataPipeline",
    sub_agents=[
        knowledge_agent,
        data_engineering_agent,
        data_analysis_agent,
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
        ProcessingToolset(tool_filter=[
            "batch_geocode", "reverse_geocode",
            "polygon_neighbors", "add_field", "calculate_field",
        ]),
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
        ProcessingToolset(),
        DatabaseToolset(tool_filter=_DB_READ_DESCRIBE + ["share_table"]),
        PlatformToolset(),
        RemoteSensingToolset(),
        SpatialStatisticsToolset(),
        SemanticLayerToolset(),
        StreamingToolset(),
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

planner_explorer = LlmAgent(
    name="PlannerExplorer",
    instruction=get_prompt("planner", "planner_explorer_instruction"),
    description="数据探查与质量审计专家。数据画像、拓扑检查、字段标准、数据库查询、表结构分析。",
    model=MODEL_FAST,
    output_key="data_profile",
    disallow_transfer_to_peers=True,
    after_tool_callback=_self_correction_after_tool,
    tools=[
        ExplorationToolset(tool_filter=_AUDIT_TOOLS),
        DatabaseToolset(tool_filter=_DB_READ_DESCRIBE),
        PlatformToolset(tool_filter=["list_user_files", "delete_user_file"]),
        SemanticLayerToolset(tool_filter=[
            "resolve_semantic_context", "describe_table_semantic",
            "list_semantic_sources", "discover_column_equivalences",
            "export_semantic_model",
        ]),
    ] + _arcpy_gov_explore_tools,
)

planner_processor = LlmAgent(
    name="PlannerProcessor",
    instruction=get_prompt("planner", "planner_processor_instruction"),
    description="数据修复与空间处理专家。坐标转换、地理编码、裁剪、缓冲区、聚类、POI、行政区划。",
    model=MODEL_STANDARD,
    output_key="processed_data",
    disallow_transfer_to_peers=True,
    after_tool_callback=_self_correction_after_tool,
    tools=[
        ExplorationToolset(tool_filter=_TRANSFORM_TOOLS),
        ProcessingToolset(),
        RemoteSensingToolset(tool_filter=["describe_raster"]),
        StreamingToolset(),
    ] + _arcpy_tools,
)

planner_analyzer = LlmAgent(
    name="PlannerAnalyzer",
    instruction=get_prompt("planner", "planner_analyzer_instruction"),
    description="FFI破碎化指数、DRL深度强化学习布局优化、遥感分析、空间统计专家。",
    model=MODEL_STANDARD,
    output_key="analysis_report",
    disallow_transfer_to_peers=True,
    after_tool_callback=_self_correction_after_tool,
    tools=[AnalysisToolset(), RemoteSensingToolset(), SpatialStatisticsToolset()],
)

planner_visualizer = LlmAgent(
    name="PlannerVisualizer",
    instruction=get_prompt("planner", "planner_visualizer_instruction"),
    description="地理空间可视化专家。交互地图、Choropleth、热力图、气泡图、PNG导出。",
    model=MODEL_FAST,
    output_key="visualizations",
    disallow_transfer_to_peers=True,
    tools=[VisualizationToolset()],
)

planner_reporter = LlmAgent(
    name="PlannerReporter",
    instruction=get_prompt("planner", "planner_reporter_instruction"),
    description="综合分析报告撰写专家。汇总所有分析步骤为专业报告。",
    model=MODEL_PREMIUM,
    output_key="final_report",
    disallow_transfer_to_peers=True,
)

planner_agent = LlmAgent(
    name="Planner",
    instruction=get_prompt("planner", "planner_instruction"),
    global_instruction=f"今天的日期是：{date.today()}",
    description="GIS数据智能体总调度（动态规划模式）",
    model=MODEL_STANDARD,
    output_key="planner_summary",
    tools=[
        PlatformToolset(tool_filter=_MEMORY_TOOLS + _ADMIN_TOOLS),
    ],
    sub_agents=[
        planner_explorer, planner_processor, planner_analyzer,
        planner_visualizer, planner_reporter,
    ],
)

root_agent = data_pipeline

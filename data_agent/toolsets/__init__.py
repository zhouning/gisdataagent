"""Lazy toolset re-exports.

Importing this package should not load every optional tool backend. Several
toolsets have heavyweight dependencies, so resolve public classes only when a
caller asks for them.
"""

from importlib import import_module
from typing import Any


_EXPORTS = {
    "AdminToolset": ".admin_tools",
    "AdvancedAnalysisToolset": ".advanced_analysis_tools",
    "AnalysisToolset": ".analysis_tools",
    "ArcPyMcpToolset": ".arcpy_mcp_toolset",
    "CausalInferenceToolset": ".causal_inference_tools",
    "CausalWorldModelToolset": ".causal_world_model_tools",
    "ChartToolset": ".chart_tools",
    "DataCleaningToolset": ".data_cleaning_tools",
    "DataLakeToolset": ".datalake_tools",
    "DatabaseToolset": ".database_tools_set",
    "DomainStandardToolset": ".domain_standard_tools",
    "DreamerToolset": ".dreamer_tools",
    "ExplorationToolset": ".exploration_tools",
    "FileToolset": ".file_tools",
    "FusionToolset": ".fusion_tools",
    "GeoProcessingToolset": ".geo_processing_tools",
    "GovernanceToolset": ".governance_tools",
    "KnowledgeBaseToolset": ".knowledge_base_tools",
    "KnowledgeGraphToolset": ".knowledge_graph_tools",
    "LLMCausalToolset": ".llm_causal_tools",
    "LocationToolset": ".location_tools",
    "McpHubToolset": ".mcp_hub_toolset",
    "MemoryToolset": ".memory_tools",
    "NL2SQLEnhancedToolset": ".nl2sql_enhanced_tools",
    "NL2SQLToolset": ".nl2sql_tools",
    "OperatorToolset": ".operator_tools",
    "PrecisionToolset": ".precision_tools",
    "RemoteSensingToolset": ".remote_sensing_tools",
    "ReportToolset": ".report_tools",
    "SemanticLayerToolset": ".semantic_layer_tools",
    "SparkToolset": ".spark_tools",
    "SpatialStatisticsToolset": ".spatial_statistics_tools",
    "StorageToolset": ".storage_tools",
    "StreamingToolset": ".streaming_tools",
    "TeamToolset": ".team_tools",
    "ToolEvolutionToolset": ".evolution_tools",
    "TerritoryWorldModelToolset": ".territory_world_model_tools",
    "UserToolset": ".user_tools_toolset",
    "VirtualSourceToolset": ".virtual_source_tools",
    "VisualizationToolset": ".visualization_tools",
    "WorldModelToolset": ".world_model_tools",
    "WorldModelV21Toolset": ".world_model_v21_tools",
    "WorldModelV2Toolset": ".world_model_v2_tools",
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(module_name, __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value

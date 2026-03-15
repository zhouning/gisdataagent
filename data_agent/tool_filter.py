"""
Dynamic tool filtering based on intent-classified tool categories (v7.5.6).

Uses ContextVar to read the current request's tool categories set by classify_intent().
Implements the ADK ToolPredicate Protocol — called on every get_tools() invocation,
enabling per-request dynamic filtering on module-level singleton agents.

When current_tool_categories is empty (default), all tools pass (no filtering).
When categories are set, only CORE_TOOLS + tools in active categories pass.
"""
from __future__ import annotations

from typing import Optional

from .user_context import current_tool_categories

# ---------------------------------------------------------------------------
# Core tools — always available regardless of intent
# ---------------------------------------------------------------------------
CORE_TOOLS: frozenset[str] = frozenset({
    "describe_geodataframe",
    "query_database",
    "list_tables",
    "list_user_files",
    "save_memory",
    "recall_memories",
    "list_memories",
    "filter_vector_data",
    "list_data_assets",
    "search_data_assets",
})

# ---------------------------------------------------------------------------
# Tool categories — mapped from classify_intent() subcategory output
# ---------------------------------------------------------------------------
TOOL_CATEGORIES: dict[str, frozenset[str]] = {
    # Spatial operations: buffer, clip, overlay, tessellation, clustering, geocoding
    "spatial_processing": frozenset({
        "generate_tessellation", "raster_to_polygon", "pairwise_clip",
        "tabulate_intersection", "surface_parameters", "zonal_statistics_as_table",
        "perform_clustering", "create_buffer", "summarize_within",
        "overlay_difference", "generate_heatmap", "find_within_distance",
        "polygon_neighbors", "add_field", "add_join", "calculate_field",
        "summary_statistics", "reproject_spatial_data", "engineer_spatial_features",
        "batch_geocode", "reverse_geocode", "get_admin_boundary",
    }),
    # POI / location / population queries
    "poi_location": frozenset({
        "search_nearby_poi", "search_poi_by_keyword",
        "get_population_data", "aggregate_population",
        "batch_geocode", "reverse_geocode", "get_admin_boundary",
        "calculate_driving_distance",
    }),
    # Raster / remote sensing analysis
    "remote_sensing": frozenset({
        "describe_raster", "calculate_ndvi", "raster_band_math",
        "classify_raster", "visualize_raster", "download_lulc", "download_dem",
        "extract_watershed", "extract_stream_network", "compute_flow_accumulation",
        "idw_interpolation", "kriging_interpolation", "gwr_analysis",
        "spatial_change_detection", "viewshed_analysis",
    }),
    # Full database operations (beyond core query/list)
    "database_management": frozenset({
        "describe_table", "share_table", "import_to_postgis",
    }),
    # Data quality audit + semantic layer
    "quality_audit": frozenset({
        "check_topology", "check_field_standards", "check_consistency",
        "resolve_semantic_context", "describe_table_semantic",
        "register_semantic_annotation", "register_source_metadata",
        "list_semantic_sources", "register_semantic_domain",
        "discover_column_equivalences", "export_semantic_model", "browse_hierarchy",
    }),
    # Real-time / IoT data streams
    "streaming_iot": frozenset({
        "create_iot_stream", "list_active_streams", "stop_data_stream",
        "get_stream_statistics", "set_geofence_alert",
    }),
    # Team management + admin + asset management
    "collaboration": frozenset({
        "create_team", "list_my_teams", "invite_to_team", "remove_from_team",
        "list_team_members", "list_team_resources", "leave_team", "delete_team",
        "get_usage_summary", "query_audit_log",
        "list_templates", "delete_template", "share_template",
        "delete_user_file",
        "register_data_asset", "tag_data_asset", "delete_data_asset",
        "share_data_asset", "get_data_lineage", "download_cloud_asset",
        "describe_data_asset",
    }),
    # Spatial statistics + data fusion + knowledge graph
    "advanced_analysis": frozenset({
        "spatial_autocorrelation", "local_moran", "hotspot_analysis",
        "profile_fusion_sources", "assess_fusion_compatibility",
        "fuse_datasets", "validate_fusion_quality",
        "build_knowledge_graph", "query_knowledge_graph", "export_knowledge_graph",
    }),
}

# All valid category names (for logging / validation)
VALID_CATEGORIES: frozenset[str] = frozenset(TOOL_CATEGORIES.keys())


class IntentToolPredicate:
    """ToolPredicate that dynamically filters tools based on
    intent-classified categories stored in a ContextVar.

    Protocol compliance: implements __call__(tool, readonly_context) -> bool
    matching google.adk.tools.base_toolset.ToolPredicate.
    """

    def __call__(self, tool, readonly_context=None) -> bool:
        categories = current_tool_categories.get()
        if not categories:
            return True  # no filtering when categories is empty set

        if tool.name in CORE_TOOLS:
            return True

        for cat in categories:
            cat_tools = TOOL_CATEGORIES.get(cat)
            if cat_tools and tool.name in cat_tools:
                return True

        return False


# Module-level singleton — shared across all toolset instances
intent_tool_predicate = IntentToolPredicate()

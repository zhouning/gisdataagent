"""Tests for the toolset architecture and BaseToolset integration."""
import unittest
import asyncio


class TestToolsetCounts(unittest.TestCase):
    """Verify each toolset returns the expected number of tools."""

    def _run(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_exploration_toolset(self):
        from data_agent.toolsets.exploration_tools import ExplorationToolset
        ts = ExplorationToolset()
        tools = self._run(ts.get_tools())
        names = [t.name for t in tools]
        self.assertIn("describe_geodataframe", names)
        self.assertIn("check_topology", names)
        self.assertIn("reproject_spatial_data", names)
        self.assertEqual(len(tools), 9)

    def test_geo_processing_toolset(self):
        from data_agent.toolsets.geo_processing_tools import GeoProcessingToolset
        ts = GeoProcessingToolset(include_arcpy=False)
        tools = self._run(ts.get_tools())
        names = [t.name for t in tools]
        self.assertIn("create_buffer", names)
        self.assertIn("generate_tessellation", names)
        self.assertIn("polygon_neighbors", names)
        self.assertEqual(len(tools), 17)

    def test_location_toolset(self):
        from data_agent.toolsets.location_tools import LocationToolset
        ts = LocationToolset()
        tools = self._run(ts.get_tools())
        names = [t.name for t in tools]
        self.assertIn("batch_geocode", names)
        self.assertIn("reverse_geocode", names)
        self.assertIn("calculate_driving_distance", names)
        self.assertIn("search_nearby_poi", names)
        self.assertIn("get_admin_boundary", names)
        self.assertIn("get_population_data", names)
        self.assertEqual(len(tools), 8)

    def test_analysis_toolset(self):
        from data_agent.toolsets.analysis_tools import AnalysisToolset
        ts = AnalysisToolset()
        tools = self._run(ts.get_tools())
        names = [t.name for t in tools]
        self.assertIn("ffi", names)
        self.assertIn("drl_model", names)
        self.assertEqual(len(tools), 4)

    def test_visualization_toolset(self):
        from data_agent.toolsets.visualization_tools import VisualizationToolset
        ts = VisualizationToolset()
        tools = self._run(ts.get_tools())
        names = [t.name for t in tools]
        self.assertIn("visualize_interactive_map", names)
        self.assertIn("generate_choropleth", names)
        self.assertIn("generate_heatmap", names)
        self.assertIn("compose_map", names)
        self.assertIn("control_map_layer", names)
        self.assertIn("generate_3d_map", names)
        self.assertEqual(len(tools), 11)

    def test_database_toolset(self):
        from data_agent.toolsets.database_tools_set import DatabaseToolset
        ts = DatabaseToolset()
        tools = self._run(ts.get_tools())
        names = [t.name for t in tools]
        self.assertIn("query_database", names)
        self.assertIn("list_tables", names)
        self.assertIn("import_to_postgis", names)
        self.assertEqual(len(tools), 5)

    def test_file_toolset(self):
        from data_agent.toolsets.file_tools import FileToolset
        ts = FileToolset()
        tools = self._run(ts.get_tools())
        names = [t.name for t in tools]
        self.assertIn("list_user_files", names)
        self.assertIn("delete_user_file", names)
        self.assertEqual(len(tools), 2)

    def test_memory_toolset(self):
        from data_agent.toolsets.memory_tools import MemoryToolset
        ts = MemoryToolset()
        tools = self._run(ts.get_tools())
        names = [t.name for t in tools]
        self.assertIn("save_memory", names)
        self.assertIn("recall_memories", names)
        self.assertIn("list_memories", names)
        self.assertIn("delete_memory", names)
        self.assertEqual(len(tools), 4)

    def test_admin_toolset(self):
        from data_agent.toolsets.admin_tools import AdminToolset
        ts = AdminToolset()
        tools = self._run(ts.get_tools())
        names = [t.name for t in tools]
        self.assertIn("get_usage_summary", names)
        self.assertIn("query_audit_log", names)
        self.assertIn("list_templates", names)
        self.assertIn("delete_template", names)
        self.assertIn("share_template", names)
        self.assertEqual(len(tools), 5)

    def test_spatial_statistics_toolset(self):
        from data_agent.toolsets.spatial_statistics_tools import SpatialStatisticsToolset
        ts = SpatialStatisticsToolset()
        tools = self._run(ts.get_tools())
        names = [t.name for t in tools]
        self.assertIn("spatial_autocorrelation", names)
        self.assertIn("local_moran", names)
        self.assertIn("hotspot_analysis", names)
        self.assertEqual(len(tools), 3)

    def test_semantic_layer_toolset(self):
        from data_agent.toolsets.semantic_layer_tools import SemanticLayerToolset
        ts = SemanticLayerToolset()
        tools = self._run(ts.get_tools())
        names = [t.name for t in tools]
        self.assertIn("resolve_semantic_context", names)
        self.assertIn("export_semantic_model", names)
        self.assertIn("browse_hierarchy", names)
        self.assertEqual(len(tools), 9)

    def test_streaming_toolset(self):
        from data_agent.toolsets.streaming_tools import StreamingToolset
        ts = StreamingToolset()
        tools = self._run(ts.get_tools())
        names = [t.name for t in tools]
        self.assertIn("create_iot_stream", names)
        self.assertIn("set_geofence_alert", names)
        self.assertEqual(len(tools), 5)

    def test_remote_sensing_toolset(self):
        from data_agent.toolsets.remote_sensing_tools import RemoteSensingToolset
        ts = RemoteSensingToolset()
        tools = self._run(ts.get_tools())
        names = [t.name for t in tools]
        self.assertIn("describe_raster", names)
        self.assertIn("calculate_ndvi", names)
        self.assertIn("download_lulc", names)
        self.assertIn("download_dem", names)
        self.assertEqual(len(tools), 13)

    def test_team_toolset(self):
        from data_agent.toolsets.team_tools import TeamToolset
        ts = TeamToolset()
        tools = self._run(ts.get_tools())
        names = [t.name for t in tools]
        self.assertIn("create_team", names)
        self.assertIn("list_my_teams", names)
        self.assertIn("invite_to_team", names)
        self.assertIn("delete_team", names)
        self.assertEqual(len(tools), 8)

    def test_datalake_toolset(self):
        from data_agent.toolsets.datalake_tools import DataLakeToolset
        ts = DataLakeToolset()
        tools = self._run(ts.get_tools())
        names = [t.name for t in tools]
        self.assertIn("list_data_assets", names)
        self.assertIn("describe_data_asset", names)
        self.assertIn("search_data_assets", names)
        self.assertIn("register_data_asset", names)
        self.assertIn("tag_data_asset", names)
        self.assertIn("delete_data_asset", names)
        self.assertIn("share_data_asset", names)
        self.assertIn("get_data_lineage", names)
        self.assertIn("download_cloud_asset", names)
        self.assertEqual(len(tools), 9)


class TestToolFilter(unittest.TestCase):
    """Verify tool_filter correctly restricts tool sets."""

    def _run(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()
        from data_agent.toolsets.exploration_tools import ExplorationToolset
        ts = ExplorationToolset(tool_filter=["describe_geodataframe", "check_topology"])
        tools = self._run(ts.get_tools())
        names = [t.name for t in tools]
        self.assertEqual(set(names), {"describe_geodataframe", "check_topology"})

    def test_filter_empty(self):
        from data_agent.toolsets.database_tools_set import DatabaseToolset
        ts = DatabaseToolset(tool_filter=["nonexistent_tool"])
        tools = self._run(ts.get_tools())
        self.assertEqual(len(tools), 0)

    def test_memory_filter(self):
        from data_agent.toolsets.memory_tools import MemoryToolset
        ts = MemoryToolset(tool_filter=["save_memory", "recall_memories"])
        tools = self._run(ts.get_tools())
        names = {t.name for t in tools}
        self.assertEqual(names, {"save_memory", "recall_memories"})

    def test_location_filter_geocoding_only(self):
        from data_agent.toolsets.location_tools import LocationToolset
        ts = LocationToolset(tool_filter=[
            "batch_geocode", "reverse_geocode", "calculate_driving_distance",
        ])
        tools = self._run(ts.get_tools())
        names = {t.name for t in tools}
        self.assertEqual(names, {"batch_geocode", "reverse_geocode", "calculate_driving_distance"})

    def test_geo_processing_filter_buffer_only(self):
        from data_agent.toolsets.geo_processing_tools import GeoProcessingToolset
        ts = GeoProcessingToolset(include_arcpy=False, tool_filter=["create_buffer"])
        tools = self._run(ts.get_tools())
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0].name, "create_buffer")

    def test_visualization_filter_excludes_optimization(self):
        from data_agent.toolsets.visualization_tools import VisualizationToolset
        ts = VisualizationToolset(tool_filter=[
            "visualize_geodataframe", "visualize_interactive_map",
            "generate_choropleth", "generate_bubble_map",
            "export_map_png", "compose_map", "generate_heatmap",
        ])
        tools = self._run(ts.get_tools())
        names = {t.name for t in tools}
        self.assertNotIn("visualize_optimization_comparison", names)
        self.assertEqual(len(tools), 7)

    def test_semantic_layer_filter_readonly(self):
        from data_agent.toolsets.semantic_layer_tools import SemanticLayerToolset
        ts = SemanticLayerToolset(tool_filter=[
            "resolve_semantic_context", "describe_table_semantic",
            "list_semantic_sources", "discover_column_equivalences",
            "export_semantic_model",
        ])
        tools = self._run(ts.get_tools())
        names = {t.name for t in tools}
        self.assertEqual(len(tools), 5)
        self.assertNotIn("register_semantic_annotation", names)

    def test_streaming_filter_single(self):
        from data_agent.toolsets.streaming_tools import StreamingToolset
        ts = StreamingToolset(tool_filter=["create_iot_stream"])
        tools = self._run(ts.get_tools())
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0].name, "create_iot_stream")

    def test_admin_filter_audit_only(self):
        from data_agent.toolsets.admin_tools import AdminToolset
        ts = AdminToolset(tool_filter=["query_audit_log"])
        tools = self._run(ts.get_tools())
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0].name, "query_audit_log")

    def test_team_filter_read_only(self):
        from data_agent.toolsets.team_tools import TeamToolset
        ts = TeamToolset(tool_filter=["list_my_teams", "list_team_members"])
        tools = self._run(ts.get_tools())
        self.assertEqual(len(tools), 2)
        names = {t.name for t in tools}
        self.assertEqual(names, {"list_my_teams", "list_team_members"})

    def test_datalake_filter_read_only(self):
        from data_agent.toolsets.datalake_tools import DataLakeToolset
        from data_agent.agent import _DATALAKE_READ
        ts = DataLakeToolset(tool_filter=_DATALAKE_READ)
        tools = self._run(ts.get_tools())
        names = {t.name for t in tools}
        self.assertEqual(len(tools), 4)
        self.assertEqual(names, {"list_data_assets", "describe_data_asset", "search_data_assets", "download_cloud_asset"})


class TestControlMapLayer(unittest.TestCase):
    """Tests for the control_map_layer NL layer control tool."""

    def test_hide_action(self):
        from data_agent.toolsets.visualization_tools import control_map_layer
        result = control_map_layer(action="hide", layer_name="土地利用")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["layer_control"]["action"], "hide")
        self.assertEqual(result["layer_control"]["layer_name"], "土地利用")
        self.assertIn("隐藏", result["message"])

    def test_show_action(self):
        from data_agent.toolsets.visualization_tools import control_map_layer
        result = control_map_layer(action="show", layer_name="缓冲区")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["layer_control"]["action"], "show")

    def test_style_action(self):
        from data_agent.toolsets.visualization_tools import control_map_layer
        result = control_map_layer(action="style", layer_name="用地", color="#e63946", opacity=0.5)
        self.assertEqual(result["status"], "success")
        ctrl = result["layer_control"]
        self.assertEqual(ctrl["action"], "style")
        self.assertEqual(ctrl["style"]["fillColor"], "#e63946")
        self.assertEqual(ctrl["style"]["fillOpacity"], 0.5)

    def test_remove_action(self):
        from data_agent.toolsets.visualization_tools import control_map_layer
        result = control_map_layer(action="remove", layer_name="旧图层")
        self.assertEqual(result["status"], "success")
        self.assertIn("移除", result["message"])

    def test_list_action(self):
        from data_agent.toolsets.visualization_tools import control_map_layer
        result = control_map_layer(action="list")
        self.assertEqual(result["status"], "success")

    def test_invalid_action(self):
        from data_agent.toolsets.visualization_tools import control_map_layer
        result = control_map_layer(action="delete", layer_name="test")
        self.assertEqual(result["status"], "error")
        self.assertIn("无效操作", result["message"])

    def test_missing_layer_name(self):
        from data_agent.toolsets.visualization_tools import control_map_layer
        result = control_map_layer(action="hide")
        self.assertEqual(result["status"], "error")
        self.assertIn("图层名称", result["message"])


class TestFilterPresets(unittest.TestCase):
    """Verify the named filter presets in agent.py resolve correctly."""

    def _run(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_audit_tools_preset(self):
        from data_agent.agent import _AUDIT_TOOLS
        from data_agent.toolsets.exploration_tools import ExplorationToolset
        ts = ExplorationToolset(tool_filter=_AUDIT_TOOLS)
        tools = self._run(ts.get_tools())
        names = {t.name for t in tools}
        self.assertEqual(len(tools), 4)
        self.assertIn("describe_geodataframe", names)
        self.assertIn("check_topology", names)
        self.assertNotIn("reproject_spatial_data", names)

    def test_transform_tools_preset(self):
        from data_agent.agent import _TRANSFORM_TOOLS
        from data_agent.toolsets.exploration_tools import ExplorationToolset
        ts = ExplorationToolset(tool_filter=_TRANSFORM_TOOLS)
        tools = self._run(ts.get_tools())
        names = {t.name for t in tools}
        self.assertEqual(len(tools), 2)
        self.assertIn("reproject_spatial_data", names)
        self.assertIn("engineer_spatial_features", names)

    def test_db_read_preset(self):
        from data_agent.agent import _DB_READ
        from data_agent.toolsets.database_tools_set import DatabaseToolset
        ts = DatabaseToolset(tool_filter=_DB_READ)
        tools = self._run(ts.get_tools())
        names = {t.name for t in tools}
        self.assertEqual(names, {"query_database", "list_tables"})

    def test_datalake_read_preset(self):
        from data_agent.agent import _DATALAKE_READ
        from data_agent.toolsets.datalake_tools import DataLakeToolset
        ts = DataLakeToolset(tool_filter=_DATALAKE_READ)
        tools = self._run(ts.get_tools())
        names = {t.name for t in tools}
        self.assertEqual(names, {"list_data_assets", "describe_data_asset", "search_data_assets", "download_cloud_asset"})


class TestNoDuplicateToolNames(unittest.TestCase):
    """Verify no name collisions across all toolsets."""

    def _run(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_all_toolset_names_unique(self):
        from data_agent.toolsets.exploration_tools import ExplorationToolset
        from data_agent.toolsets.geo_processing_tools import GeoProcessingToolset
        from data_agent.toolsets.location_tools import LocationToolset
        from data_agent.toolsets.analysis_tools import AnalysisToolset
        from data_agent.toolsets.visualization_tools import VisualizationToolset
        from data_agent.toolsets.database_tools_set import DatabaseToolset
        from data_agent.toolsets.file_tools import FileToolset
        from data_agent.toolsets.memory_tools import MemoryToolset
        from data_agent.toolsets.admin_tools import AdminToolset
        from data_agent.toolsets.remote_sensing_tools import RemoteSensingToolset
        from data_agent.toolsets.spatial_statistics_tools import SpatialStatisticsToolset
        from data_agent.toolsets.semantic_layer_tools import SemanticLayerToolset
        from data_agent.toolsets.streaming_tools import StreamingToolset
        from data_agent.toolsets.team_tools import TeamToolset
        from data_agent.toolsets.datalake_tools import DataLakeToolset

        all_names = []
        for ts_cls, kwargs in [
            (ExplorationToolset, {}),
            (GeoProcessingToolset, {"include_arcpy": False}),
            (LocationToolset, {}),
            (AnalysisToolset, {}),
            (VisualizationToolset, {}),
            (DatabaseToolset, {}),
            (FileToolset, {}),
            (MemoryToolset, {}),
            (AdminToolset, {}),
            (RemoteSensingToolset, {}),
            (SpatialStatisticsToolset, {}),
            (SemanticLayerToolset, {}),
            (StreamingToolset, {}),
            (TeamToolset, {}),
            (DataLakeToolset, {}),
        ]:
            ts = ts_cls(**kwargs)
            tools = self._run(ts.get_tools())
            all_names.extend(t.name for t in tools)

        duplicates = [n for n in all_names if all_names.count(n) > 1]
        # generate_heatmap is in both GeoProcessing and Visualization — known overlap
        allowed_overlaps = {"generate_heatmap"}
        unexpected = set(duplicates) - allowed_overlaps
        self.assertEqual(unexpected, set(), f"Unexpected duplicate tool names: {unexpected}")


class TestPromptLoading(unittest.TestCase):
    """Verify prompt loading from YAML files."""

    def test_optimization_prompts(self):
        from data_agent.prompts import get_prompt
        prompt = get_prompt("optimization", "knowledge_agent_instruction")
        self.assertIn("FFI", prompt)
        self.assertIn("Vertex AI Search", prompt)

    def test_planner_prompts(self):
        from data_agent.prompts import get_prompt
        prompt = get_prompt("planner", "planner_instruction")
        self.assertIn("PlannerExplorer", prompt)

    def test_general_prompts(self):
        from data_agent.prompts import get_prompt
        prompt = get_prompt("general", "governance_reporter_instruction")
        self.assertIn("审计", prompt)

    def test_all_prompt_keys(self):
        from data_agent.prompts import load_prompts
        opt = load_prompts("optimization")
        self.assertEqual(len(opt), 9)
        planner = load_prompts("planner")
        self.assertEqual(len(planner), 7)
        general = load_prompts("general")
        self.assertEqual(len(general), 6)


class TestBackwardCompat(unittest.TestCase):
    """Verify backward-compatible imports from data_agent.agent still work."""

    def test_pipeline_imports(self):
        from data_agent.agent import root_agent, data_pipeline, governance_pipeline, general_pipeline, planner_agent
        self.assertIsNotNone(root_agent)
        self.assertIsNotNone(data_pipeline)
        self.assertIsNotNone(governance_pipeline)
        self.assertIsNotNone(general_pipeline)
        self.assertIsNotNone(planner_agent)

    def test_utility_imports(self):
        from data_agent.agent import _load_spatial_data, _add_basemap_layers, TIANDITU_TOKEN, ARCPY_AVAILABLE
        self.assertIsNotNone(_load_spatial_data)
        self.assertIsNotNone(_add_basemap_layers)

    def test_tool_function_imports(self):
        from data_agent.agent import (
            ffi, drl_model, describe_geodataframe, engineer_spatial_features,
            reproject_spatial_data, visualize_optimization_comparison,
            visualize_interactive_map, list_user_files, delete_user_file,
            MODEL_STANDARD,
        )
        self.assertTrue(callable(ffi))
        self.assertTrue(callable(drl_model))
        self.assertTrue(callable(describe_geodataframe))

    def test_callback_imports(self):
        from data_agent.agent import _self_correction_after_tool, _tool_retry_counts, _quality_gate_check
        self.assertTrue(callable(_self_correction_after_tool))
        self.assertIsInstance(_tool_retry_counts, dict)

    def test_filter_preset_imports(self):
        from data_agent.agent import _AUDIT_TOOLS, _TRANSFORM_TOOLS, _DB_READ
        self.assertIsInstance(_AUDIT_TOOLS, list)
        self.assertIn("describe_geodataframe", _AUDIT_TOOLS)
        self.assertIn("reproject_spatial_data", _TRANSFORM_TOOLS)

    def test_gis_processor_re_exports(self):
        from data_agent.agent import _generate_output_path, _resolve_path
        self.assertTrue(callable(_generate_output_path))
        self.assertTrue(callable(_resolve_path))

    def test_spatial_statistics_imports(self):
        from data_agent.agent import spatial_autocorrelation, local_moran, hotspot_analysis
        self.assertTrue(callable(spatial_autocorrelation))
        self.assertTrue(callable(local_moran))
        self.assertTrue(callable(hotspot_analysis))


class TestSkillBundles(unittest.TestCase):
    """Tests for skill bundle registration and intent mapping."""

    def test_all_bundles_registered(self):
        from data_agent.toolsets.skill_bundles import ALL_BUNDLES, get_bundle
        self.assertEqual(len(ALL_BUNDLES), 5)
        for bundle in ALL_BUNDLES:
            self.assertIs(get_bundle(bundle.name), bundle)

    def test_bundle_builds_toolsets(self):
        from data_agent.toolsets.skill_bundles import SPATIAL_ANALYSIS
        toolsets = SPATIAL_ANALYSIS.build_toolsets()
        self.assertGreater(len(toolsets), 0)
        names = [type(ts).__name__ for ts in toolsets]
        self.assertIn("ExplorationToolset", names)
        self.assertIn("GeoProcessingToolset", names)

    def test_intent_mapping(self):
        from data_agent.toolsets.skill_bundles import get_bundles_for_intent
        gov_bundles = get_bundles_for_intent("governance")
        names = [b.name for b in gov_bundles]
        self.assertIn("spatial_analysis", names)
        self.assertIn("data_quality", names)

    def test_no_duplicate_toolsets(self):
        from data_agent.toolsets.skill_bundles import build_toolsets_for_intent
        toolsets = build_toolsets_for_intent("governance")
        class_names = [type(ts).__name__ for ts in toolsets]
        # No duplicates
        self.assertEqual(len(class_names), len(set(class_names)))

    def test_visualization_bundle(self):
        from data_agent.toolsets.skill_bundles import VISUALIZATION
        toolsets = VISUALIZATION.build_toolsets()
        self.assertEqual(len(toolsets), 1)
        self.assertEqual(type(toolsets[0]).__name__, "VisualizationToolset")


if __name__ == "__main__":
    unittest.main()

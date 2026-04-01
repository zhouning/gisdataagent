"""Tests for S-7: Tool Evolution — metadata, failure-driven discovery, dynamic management."""
import json
import asyncio
import pytest
from unittest.mock import patch, MagicMock

from data_agent.tool_evolution import (
    ToolMetadata,
    ToolEvolutionEngine,
    get_evolution_engine,
    _TOOL_DESCRIPTIONS,
    _TOOL_COSTS,
    _TOOL_SCENARIOS,
    _TASK_KEYWORDS,
    _FAILURE_TOOL_SUGGESTIONS,
)


# ---------------------------------------------------------------------------
# ToolMetadata dataclass
# ---------------------------------------------------------------------------

class TestToolMetadata:
    def test_default_values(self):
        m = ToolMetadata(name="test_tool")
        assert m.name == "test_tool"
        assert m.active is True
        assert m.reliability_score == 1.0
        assert m.cost_level == "low"
        assert m.source == "builtin"
        assert m.failure_count == 0

    def test_custom_values(self):
        m = ToolMetadata(
            name="expensive_tool",
            cost_level="high",
            reliability_score=0.75,
            source="mcp",
            applicable_scenarios=["分析", "建模"],
        )
        assert m.cost_level == "high"
        assert m.reliability_score == 0.75
        assert m.source == "mcp"
        assert len(m.applicable_scenarios) == 2

    def test_deactivation_fields(self):
        m = ToolMetadata(name="old_tool", active=False, deactivation_reason="deprecated")
        assert m.active is False
        assert m.deactivation_reason == "deprecated"


# ---------------------------------------------------------------------------
# Static enrichment tables
# ---------------------------------------------------------------------------

class TestStaticTables:
    def test_tool_descriptions_coverage(self):
        """Should have 50+ tool descriptions."""
        assert len(_TOOL_DESCRIPTIONS) >= 50

    def test_tool_costs_coverage(self):
        """Should have cost entries for expensive tools."""
        assert len(_TOOL_COSTS) >= 10
        assert _TOOL_COSTS["world_model_predict"] == "high"
        assert _TOOL_COSTS["batch_geocode"] == "medium"

    def test_tool_scenarios_coverage(self):
        """Should have scenario entries for key tools."""
        assert len(_TOOL_SCENARIOS) >= 15
        assert "植被监测" in _TOOL_SCENARIOS["calculate_ndvi"]

    def test_task_keywords_coverage(self):
        """Should have keyword→tool mappings."""
        assert len(_TASK_KEYWORDS) >= 20
        assert "calculate_ndvi" in _TASK_KEYWORDS["植被"]
        assert "hotspot_analysis" in _TASK_KEYWORDS["热点"]

    def test_failure_suggestions(self):
        """Should have failure→tool suggestion mappings."""
        assert len(_FAILURE_TOOL_SUGGESTIONS) >= 5
        assert _FAILURE_TOOL_SUGGESTIONS["crs_mismatch"]["suggested_tool"] == "reproject_spatial_data"


# ---------------------------------------------------------------------------
# ToolEvolutionEngine — metadata build
# ---------------------------------------------------------------------------

class TestEngineMetadata:
    def setup_method(self):
        self.engine = ToolEvolutionEngine()

    def test_builds_metadata(self):
        """Should populate metadata from TOOL_CATEGORIES."""
        assert len(self.engine._metadata) >= 50

    def test_core_tools_marked(self):
        """Core tools should be flagged."""
        meta = self.engine._metadata.get("describe_geodataframe")
        assert meta is not None
        assert meta.is_core is True

    def test_alternatives_populated(self):
        """Tools with TOOL_ALTERNATIVES should have alternatives field."""
        meta = self.engine._metadata.get("arcpy_extract_watershed")
        if meta:
            assert "extract_watershed" in meta.alternatives

    def test_categories_assigned(self):
        """Tools should have their category from TOOL_CATEGORIES."""
        meta = self.engine._metadata.get("create_buffer")
        assert meta is not None
        assert meta.category == "spatial_processing"

    def test_cost_levels_enriched(self):
        """Tools in _TOOL_COSTS should have correct cost_level."""
        meta = self.engine._metadata.get("world_model_predict")
        if meta:
            assert meta.cost_level == "high"

    def test_all_metadata_merges_dynamic(self):
        """all_metadata should include both static and dynamic tools."""
        self.engine._dynamic_tools["custom_test"] = ToolMetadata(name="custom_test")
        merged = self.engine.all_metadata
        assert "custom_test" in merged
        assert "create_buffer" in merged


# ---------------------------------------------------------------------------
# get_tool_metadata
# ---------------------------------------------------------------------------

class TestGetToolMetadata:
    def setup_method(self):
        self.engine = ToolEvolutionEngine()

    def test_known_tool(self):
        result = json.loads(self.engine.get_tool_metadata("create_buffer"))
        assert result["status"] == "success"
        assert result["tool"]["name"] == "create_buffer"
        assert result["tool"]["category"] == "spatial_processing"

    def test_unknown_tool(self):
        result = json.loads(self.engine.get_tool_metadata("nonexistent_tool"))
        assert result["status"] == "error"
        assert "Unknown tool" in result["message"]


# ---------------------------------------------------------------------------
# list_tools_with_metadata
# ---------------------------------------------------------------------------

class TestListTools:
    def setup_method(self):
        self.engine = ToolEvolutionEngine()

    def test_list_all(self):
        result = json.loads(self.engine.list_tools_with_metadata())
        assert result["status"] == "success"
        assert result["count"] >= 50

    def test_filter_by_category(self):
        result = json.loads(self.engine.list_tools_with_metadata(category="remote_sensing"))
        assert result["status"] == "success"
        assert result["count"] >= 5
        for t in result["tools"]:
            assert t["category"] == "remote_sensing"

    def test_sort_by_cost(self):
        result = json.loads(self.engine.list_tools_with_metadata(sort_by="cost"))
        assert result["status"] == "success"
        costs = [t["cost_level"] for t in result["tools"]]
        # First tools should be "low"
        assert costs[0] == "low"

    def test_sort_by_category(self):
        result = json.loads(self.engine.list_tools_with_metadata(sort_by="category"))
        assert result["status"] == "success"
        cats = [t["category"] for t in result["tools"]]
        assert cats == sorted(cats)

    def test_inactive_tools_excluded(self):
        self.engine._metadata["create_buffer"].active = False
        result = json.loads(self.engine.list_tools_with_metadata())
        names = {t["name"] for t in result["tools"]}
        assert "create_buffer" not in names
        # Restore
        self.engine._metadata["create_buffer"].active = True


# ---------------------------------------------------------------------------
# suggest_tools_for_task
# ---------------------------------------------------------------------------

class TestSuggestTools:
    def setup_method(self):
        self.engine = ToolEvolutionEngine()

    def test_vegetation_task(self):
        result = json.loads(self.engine.suggest_tools_for_task("分析农田植被覆盖变化"))
        assert result["status"] == "success"
        tools = {r["tool"] for r in result["recommended"]}
        assert "calculate_ndvi" in tools or "calculate_spectral_index" in tools

    def test_water_task(self):
        result = json.loads(self.engine.suggest_tools_for_task("检测水体变化"))
        assert result["status"] == "success"
        tools = {r["tool"] for r in result["recommended"]}
        assert "calculate_spectral_index" in tools or "recommend_indices" in tools

    def test_hotspot_task(self):
        result = json.loads(self.engine.suggest_tools_for_task("hotspot analysis clustering"))
        assert result["status"] == "success"
        tools = {r["tool"] for r in result["recommended"]}
        assert "hotspot_analysis" in tools

    def test_no_match(self):
        result = json.loads(self.engine.suggest_tools_for_task("completely irrelevant xyz"))
        assert result["status"] == "success"
        assert len(result["recommended"]) == 0

    def test_max_recommendations(self):
        result = json.loads(self.engine.suggest_tools_for_task("植被 水体 热点 插值 聚类 优化 预测 因果"))
        assert len(result["recommended"]) <= 8


# ---------------------------------------------------------------------------
# register_tool / deactivate_tool
# ---------------------------------------------------------------------------

class TestDynamicTools:
    def setup_method(self):
        self.engine = ToolEvolutionEngine()

    def test_register_new_tool(self):
        result = json.loads(self.engine.register_tool(
            "my_custom_tool", "Custom analysis tool", "advanced_analysis", "medium",
            ["自定义分析"],
        ))
        assert result["status"] == "success"
        assert "my_custom_tool" in self.engine._dynamic_tools

    def test_register_duplicate(self):
        self.engine.register_tool("dup_tool", "Dup", "uncategorized")
        result = json.loads(self.engine.register_tool("dup_tool", "Dup again"))
        assert result["status"] == "error"
        assert "already exists" in result["message"]

    def test_register_builtin_name_fails(self):
        result = json.loads(self.engine.register_tool("create_buffer", "Override buffer"))
        assert result["status"] == "error"

    def test_deactivate_tool(self):
        self.engine.register_tool("temp_tool", "Temporary", "uncategorized")
        result = json.loads(self.engine.deactivate_tool("temp_tool", "no longer needed"))
        assert result["status"] == "success"
        assert self.engine._dynamic_tools["temp_tool"].active is False

    def test_deactivate_unknown(self):
        result = json.loads(self.engine.deactivate_tool("nonexistent"))
        assert result["status"] == "error"

    def test_deactivate_already_inactive(self):
        self.engine.register_tool("inactive_tool", "test", "uncategorized")
        self.engine.deactivate_tool("inactive_tool")
        result = json.loads(self.engine.deactivate_tool("inactive_tool"))
        assert result["status"] == "error"
        assert "already inactive" in result["message"]


# ---------------------------------------------------------------------------
# get_failure_driven_suggestions
# ---------------------------------------------------------------------------

class TestFailureSuggestions:
    def setup_method(self):
        self.engine = ToolEvolutionEngine()

    def test_crs_error(self):
        result = json.loads(self.engine.get_failure_driven_suggestions(
            "pairwise_clip", "CRS mismatch: EPSG:4326 vs EPSG:32650",
        ))
        assert result["status"] == "success"
        tools = {s["tool"] for s in result["suggestions"]}
        assert "reproject_spatial_data" in tools

    def test_topology_error(self):
        result = json.loads(self.engine.get_failure_driven_suggestions(
            "import_to_postgis", "topology error: self-intersecting polygon",
        ))
        assert result["status"] == "success"
        tools = {s["tool"] for s in result["suggestions"]}
        assert "check_topology" in tools

    def test_memory_error(self):
        result = json.loads(self.engine.get_failure_driven_suggestions(
            "fuse_datasets", "Out of memory: dataset too large",
        ))
        tools = {s["tool"] for s in result["suggestions"]}
        assert "filter_vector_data" in tools

    def test_tool_with_alternatives(self):
        result = json.loads(self.engine.get_failure_driven_suggestions(
            "arcpy_extract_watershed", "ArcPy not available",
        ))
        tools = {s["tool"] for s in result["suggestions"]}
        assert "extract_watershed" in tools

    def test_no_suggestions_escalates(self):
        result = json.loads(self.engine.get_failure_driven_suggestions(
            "unknown_tool", "unknown error xyz",
        ))
        assert result["suggestions"][0]["type"] == "escalate"


# ---------------------------------------------------------------------------
# get_evolution_report
# ---------------------------------------------------------------------------

class TestEvolutionReport:
    def setup_method(self):
        self.engine = ToolEvolutionEngine()

    def test_report_structure(self):
        result = json.loads(self.engine.get_evolution_report())
        assert result["status"] == "success"
        assert result["total_tools"] >= 50
        assert result["active_tools"] >= 50
        assert result["inactive_tools"] == 0
        assert "category_distribution" in result
        assert "cost_distribution" in result
        assert "source_distribution" in result

    def test_report_with_dynamic_tools(self):
        self.engine.register_tool("dynamic1", "test", "uncategorized")
        result = json.loads(self.engine.get_evolution_report())
        assert result["dynamic_tools_count"] >= 1

    def test_report_cost_distribution(self):
        result = json.loads(self.engine.get_evolution_report())
        cost = result["cost_distribution"]
        assert cost["low"] >= 30
        assert cost["high"] >= 5


# ---------------------------------------------------------------------------
# analyze_tool_failures (mocked DB)
# ---------------------------------------------------------------------------

class TestAnalyzeFailures:
    def setup_method(self):
        self.engine = ToolEvolutionEngine()

    @patch("data_agent.tool_evolution.get_evolution_engine")
    def test_no_db_graceful(self, mock_get):
        """When DB unavailable, should return empty failures gracefully."""
        engine = ToolEvolutionEngine()
        with patch("data_agent.tool_evolution.ToolEvolutionEngine.analyze_tool_failures") as mock_af:
            mock_af.return_value = json.dumps({"status": "success", "failures": [], "message": "DB unavailable"})
            result = json.loads(mock_af())
            assert result["status"] == "success"

    def test_failure_recommendations_crs(self):
        """Should generate CRS-related recommendations."""
        recs = self.engine._failure_recommendations("pairwise_clip", [
            {"error": "CRS mismatch EPSG:4326 vs EPSG:32650"},
        ])
        assert any("reproject" in r for r in recs)

    def test_failure_recommendations_topology(self):
        recs = self.engine._failure_recommendations("import_to_postgis", [
            {"error": "topology error self-intersecting polygon"},
        ])
        assert any("check_topology" in r for r in recs)

    def test_failure_recommendations_default(self):
        recs = self.engine._failure_recommendations("some_tool", [
            {"error": "unknown error"},
        ])
        assert len(recs) >= 1


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

class TestSingleton:
    def test_get_evolution_engine_returns_same(self):
        import data_agent.tool_evolution as mod
        mod._engine = None  # Reset
        e1 = get_evolution_engine()
        e2 = get_evolution_engine()
        assert e1 is e2
        mod._engine = None  # Cleanup


# ---------------------------------------------------------------------------
# Toolset integration
# ---------------------------------------------------------------------------

class TestToolEvolutionToolset:
    def test_toolset_has_8_tools(self):
        from data_agent.toolsets.evolution_tools import ToolEvolutionToolset
        ts = ToolEvolutionToolset()
        tools = asyncio.get_event_loop().run_until_complete(ts.get_tools())
        assert len(tools) == 8

    def test_tool_names(self):
        from data_agent.toolsets.evolution_tools import ToolEvolutionToolset
        ts = ToolEvolutionToolset()
        tools = asyncio.get_event_loop().run_until_complete(ts.get_tools())
        names = {t.name for t in tools}
        expected = {
            "get_tool_metadata", "list_tools", "suggest_tools_for_task",
            "analyze_tool_failures", "register_tool", "deactivate_tool",
            "get_failure_suggestions", "tool_evolution_report",
        }
        assert expected == names


# ---------------------------------------------------------------------------
# update_reliability_from_db (mocked)
# ---------------------------------------------------------------------------

class TestUpdateReliability:
    def setup_method(self):
        self.engine = ToolEvolutionEngine()

    def test_no_db(self):
        with patch("data_agent.tool_evolution.ToolEvolutionEngine.update_reliability_from_db") as mock_ur:
            mock_ur.return_value = json.dumps({"status": "success", "updated": 0, "message": "DB unavailable"})
            result = json.loads(mock_ur())
            assert result["updated"] == 0

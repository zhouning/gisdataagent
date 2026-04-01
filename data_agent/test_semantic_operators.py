"""Tests for semantic_operators.py and OperatorToolset."""
import json
import pytest
from unittest.mock import patch, MagicMock
from data_agent.semantic_operators import (
    SemanticOperator,
    OperatorResult,
    OperatorPlan,
    ToolCall,
    OperatorRegistry,
    CleanOperator,
    IntegrateOperator,
    AnalyzeOperator,
    VisualizeOperator,
    _safe_call,
)
from data_agent.agent_composer import DataProfile


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def landuse_profile():
    return DataProfile(
        file_path="/tmp/test.shp",
        file_name="test.shp",
        extension=".shp",
        row_count=500,
        column_count=10,
        columns=["DLBM", "DLMC", "TBMJ", "geometry", "phone"],
        geometry_types=["Polygon"],
        crs="EPSG:4547",
        numeric_columns=["TBMJ"],
        domain="landuse",
        domain_keywords=["dlbm", "地类"],
    )


@pytest.fixture
def csv_profile():
    return DataProfile(
        file_path="/tmp/data.csv",
        file_name="data.csv",
        extension=".csv",
        row_count=1000,
        column_count=5,
        columns=["name", "value", "lng", "lat", "category"],
        has_coordinates=True,
        numeric_columns=["value", "lng", "lat"],
        domain="general",
    )


@pytest.fixture
def empty_profile():
    return DataProfile()


# ---------------------------------------------------------------------------
# OperatorRegistry
# ---------------------------------------------------------------------------

class TestOperatorRegistry:
    def test_builtin_operators_registered(self):
        ops = OperatorRegistry.list_all()
        names = {op["name"] for op in ops}
        assert names == {"clean", "integrate", "analyze", "visualize"}

    def test_get_existing(self):
        op = OperatorRegistry.get("clean")
        assert op is not None
        assert isinstance(op, CleanOperator)

    def test_get_nonexistent(self):
        assert OperatorRegistry.get("nonexistent") is None

    def test_list_all_has_descriptions(self):
        for op in OperatorRegistry.list_all():
            assert "name" in op
            assert "description" in op
            assert len(op["description"]) > 0


# ---------------------------------------------------------------------------
# CleanOperator
# ---------------------------------------------------------------------------

class TestCleanOperator:
    def test_plan_crs_standardize(self, landuse_profile):
        op = CleanOperator()
        plan = op.plan(landuse_profile)
        assert plan.operator_name == "clean"
        assert "crs_standardize" in plan.strategy
        tool_names = [tc.tool_name for tc in plan.tool_calls]
        assert "standardize_crs" in tool_names

    def test_plan_pii_masking(self, landuse_profile):
        op = CleanOperator()
        plan = op.plan(landuse_profile)
        assert "masking" in plan.strategy
        tool_names = [tc.tool_name for tc in plan.tool_calls]
        assert "mask_sensitive_fields_tool" in tool_names

    def test_plan_standard_validation(self, landuse_profile):
        op = CleanOperator()
        plan = op.plan(landuse_profile, task_description="按 DLTB 标准清洗")
        assert "standard_validate" in plan.strategy
        tool_names = [tc.tool_name for tc in plan.tool_calls]
        assert "validate_against_standard" in tool_names
        assert "add_missing_fields" in tool_names

    def test_plan_defect_classify(self, landuse_profile):
        op = CleanOperator()
        plan = op.plan(landuse_profile)
        assert "defect_classify" in plan.strategy
        tool_names = [tc.tool_name for tc in plan.tool_calls]
        assert "classify_defects" in tool_names

    def test_plan_no_crs_when_standard(self, csv_profile):
        """CSV with no CRS should not trigger CRS standardization."""
        op = CleanOperator()
        plan = op.plan(csv_profile)
        tool_names = [tc.tool_name for tc in plan.tool_calls]
        assert "standardize_crs" not in tool_names

    def test_plan_empty_profile_warns(self, empty_profile):
        op = CleanOperator()
        plan = op.plan(empty_profile)
        assert len(plan.precondition_warnings) > 0

    @patch("data_agent.semantic_operators.CleanOperator.execute")
    def test_execute_returns_result(self, mock_exec, landuse_profile):
        mock_exec.return_value = OperatorResult(
            status="success", summary="done", metrics={"total_steps": 3, "errors": 0})
        op = CleanOperator()
        plan = op.plan(landuse_profile)
        result = op.execute(plan)
        assert result.status == "success"

    def test_execute_with_mock_tools(self, landuse_profile):
        """Execute with all tools mocked."""
        op = CleanOperator()
        plan = OperatorPlan(
            operator_name="clean",
            strategy="auto_fix",
            tool_calls=[ToolCall("auto_fix_defects", {"file_path": "/tmp/test.shp"})],
            estimated_steps=1,
        )
        with patch("data_agent.toolsets.data_cleaning_tools.auto_fix_defects",
                    return_value=json.dumps({"status": "success", "output_path": "/tmp/fixed.shp", "fixed_count": 5})):
            result = op.execute(plan)
        assert result.status == "success"
        assert len(result.details) == 1

    def test_validate_preconditions(self, landuse_profile, empty_profile):
        op = CleanOperator()
        assert op.validate_preconditions(landuse_profile) == []
        warnings = op.validate_preconditions(empty_profile)
        assert any("文件路径" in w for w in warnings)


# ---------------------------------------------------------------------------
# IntegrateOperator
# ---------------------------------------------------------------------------

class TestIntegrateOperator:
    def test_plan_default_strategy(self, landuse_profile):
        op = IntegrateOperator()
        plan = op.plan(landuse_profile)
        assert plan.operator_name == "integrate"
        assert "fuse_auto" in plan.strategy
        tool_names = [tc.tool_name for tc in plan.tool_calls]
        assert "profile_fusion_sources" in tool_names
        assert "fuse_datasets" in tool_names

    def test_plan_spatial_join_keyword(self, landuse_profile):
        op = IntegrateOperator()
        plan = op.plan(landuse_profile, task_description="空间连接两个数据集")
        fuse_call = [tc for tc in plan.tool_calls if tc.tool_name == "fuse_datasets"][0]
        assert fuse_call.kwargs["strategy"] == "spatial_join"

    def test_plan_overlay_keyword(self, landuse_profile):
        op = IntegrateOperator()
        plan = op.plan(landuse_profile, task_description="overlay analysis")
        fuse_call = [tc for tc in plan.tool_calls if tc.tool_name == "fuse_datasets"][0]
        assert fuse_call.kwargs["strategy"] == "overlay"

    def test_validate_empty(self, empty_profile):
        op = IntegrateOperator()
        warnings = op.validate_preconditions(empty_profile)
        assert len(warnings) > 0


# ---------------------------------------------------------------------------
# AnalyzeOperator
# ---------------------------------------------------------------------------

class TestAnalyzeOperator:
    def test_detect_spatial_stats(self, landuse_profile):
        op = AnalyzeOperator()
        plan = op.plan(landuse_profile, task_description="分析空间分布聚类")
        assert plan.strategy == "spatial_stats"
        tool_names = [tc.tool_name for tc in plan.tool_calls]
        assert "spatial_autocorrelation" in tool_names
        assert "hotspot_analysis" in tool_names

    def test_detect_drl_optimize(self, landuse_profile):
        op = AnalyzeOperator()
        plan = op.plan(landuse_profile, task_description="优化土地布局")
        assert plan.strategy == "drl_optimize"
        tool_names = [tc.tool_name for tc in plan.tool_calls]
        assert "drl_model" in tool_names

    def test_detect_causal(self, csv_profile):
        op = AnalyzeOperator()
        plan = op.plan(csv_profile, task_description="因果分析 PSM")
        assert plan.strategy == "causal"

    def test_detect_terrain(self, landuse_profile):
        op = AnalyzeOperator()
        plan = op.plan(landuse_profile, task_description="DEM 地形 watershed 分析")
        assert plan.strategy == "terrain"

    def test_detect_world_model(self, csv_profile):
        op = AnalyzeOperator()
        plan = op.plan(csv_profile, task_description="预测 LULC 趋势")
        assert plan.strategy == "world_model"

    def test_detect_governance(self, landuse_profile):
        op = AnalyzeOperator()
        plan = op.plan(landuse_profile, task_description="数据质量评分")
        assert plan.strategy == "governance"

    def test_fallback_landuse(self, landuse_profile):
        op = AnalyzeOperator()
        plan = op.plan(landuse_profile, task_description="")
        assert plan.strategy == "spatial_stats"  # landuse domain fallback

    def test_no_geometry_warning(self, csv_profile):
        csv_profile.geometry_types = []
        csv_profile.has_coordinates = False
        op = AnalyzeOperator()
        warnings = op.validate_preconditions(csv_profile)
        assert any("几何" in w for w in warnings)


# ---------------------------------------------------------------------------
# VisualizeOperator
# ---------------------------------------------------------------------------

class TestVisualizeOperator:
    def test_detect_choropleth(self, landuse_profile):
        op = VisualizeOperator()
        plan = op.plan(landuse_profile, task_description="着色图")
        assert plan.strategy == "choropleth"
        tool_names = [tc.tool_name for tc in plan.tool_calls]
        assert "generate_choropleth" in tool_names

    def test_detect_heatmap(self, csv_profile):
        op = VisualizeOperator()
        plan = op.plan(csv_profile, task_description="热力图")
        assert plan.strategy == "heatmap"

    def test_detect_charts(self, csv_profile):
        op = VisualizeOperator()
        plan = op.plan(csv_profile, task_description="统计图表")
        assert plan.strategy == "charts"
        tool_names = [tc.tool_name for tc in plan.tool_calls]
        assert "create_bar_chart" in tool_names

    def test_detect_radar(self, landuse_profile):
        op = VisualizeOperator()
        plan = op.plan(landuse_profile, task_description="雷达图 多维评价")
        assert plan.strategy == "radar"

    def test_detect_report(self, landuse_profile):
        op = VisualizeOperator()
        plan = op.plan(landuse_profile, task_description="导出报告")
        assert plan.strategy == "report"
        tool_names = [tc.tool_name for tc in plan.tool_calls]
        assert "export_map_png" in tool_names

    def test_default_interactive_map(self, landuse_profile):
        op = VisualizeOperator()
        plan = op.plan(landuse_profile, task_description="")
        assert plan.strategy == "interactive_map"

    def test_csv_with_numbers_defaults_to_charts(self):
        profile = DataProfile(
            file_path="/tmp/stats.csv",
            numeric_columns=["val1", "val2"],
            columns=["name", "val1", "val2"],
        )
        op = VisualizeOperator()
        plan = op.plan(profile, task_description="")
        assert plan.strategy == "charts"


# ---------------------------------------------------------------------------
# OperatorPlan / OperatorResult serialization
# ---------------------------------------------------------------------------

class TestDataStructures:
    def test_operator_plan_to_dict(self):
        plan = OperatorPlan(
            operator_name="clean",
            strategy="crs_standardize+masking",
            tool_calls=[
                ToolCall("standardize_crs", {"file_path": "a.shp", "target_crs": "EPSG:4490"}),
                ToolCall("mask_sensitive_fields_tool", {"file_path": "a.shp"}),
            ],
            estimated_steps=2,
        )
        d = plan.to_dict()
        assert d["operator"] == "clean"
        assert d["strategy"] == "crs_standardize+masking"
        assert len(d["steps"]) == 2
        assert d["steps"][0]["tool"] == "standardize_crs"

    def test_operator_result_to_dict(self):
        result = OperatorResult(
            status="success",
            output_files=["/tmp/out.shp"],
            metrics={"errors": 0},
            summary="done",
        )
        d = result.to_dict()
        assert d["status"] == "success"
        assert "/tmp/out.shp" in d["output_files"]


# ---------------------------------------------------------------------------
# _safe_call helper
# ---------------------------------------------------------------------------

class TestSafeCall:
    def test_json_string_result(self):
        def fn(): return '{"status": "success", "count": 5}'
        result = _safe_call(fn)
        assert result["status"] == "success"
        assert result["count"] == 5

    def test_dict_result(self):
        def fn(): return {"status": "success"}
        result = _safe_call(fn)
        assert result["status"] == "success"

    def test_plain_string_result(self):
        def fn(): return "hello"
        result = _safe_call(fn)
        assert result["raw"] == "hello"

    def test_exception_result(self):
        def fn(): raise ValueError("bad input")
        result = _safe_call(fn)
        assert result["status"] == "error"
        assert "bad input" in result["message"]


# ---------------------------------------------------------------------------
# OperatorToolset
# ---------------------------------------------------------------------------

class TestOperatorToolset:
    @patch("data_agent.toolsets.operator_tools.extract_profile")
    @patch("data_agent.toolsets.operator_tools.OperatorRegistry")
    def test_clean_data_tool(self, mock_registry, mock_extract):
        from data_agent.toolsets.operator_tools import clean_data

        mock_extract.return_value = DataProfile(file_path="/tmp/a.shp", row_count=100)
        mock_op = MagicMock()
        mock_op.plan.return_value = OperatorPlan("clean", "auto_fix")
        mock_op.execute.return_value = OperatorResult(status="success", summary="done")
        mock_registry.get.return_value = mock_op

        result = json.loads(clean_data("/tmp/a.shp"))
        assert result["status"] == "success"
        mock_op.plan.assert_called_once()
        mock_op.execute.assert_called_once()

    @patch("data_agent.toolsets.operator_tools.extract_profile")
    @patch("data_agent.toolsets.operator_tools.OperatorRegistry")
    def test_analyze_data_tool(self, mock_registry, mock_extract):
        from data_agent.toolsets.operator_tools import analyze_data

        mock_extract.return_value = DataProfile(
            file_path="/tmp/a.shp", numeric_columns=["val"], geometry_types=["Polygon"])
        mock_op = MagicMock()
        mock_op.plan.return_value = OperatorPlan("analyze", "spatial_stats")
        mock_op.execute.return_value = OperatorResult(status="success", summary="analyzed")
        mock_registry.get.return_value = mock_op

        result = json.loads(analyze_data("/tmp/a.shp", analysis_type="spatial_stats"))
        assert result["status"] == "success"

    def test_list_operators_tool(self):
        from data_agent.toolsets.operator_tools import list_operators
        result = json.loads(list_operators())
        names = {op["name"] for op in result}
        assert "clean" in names
        assert "analyze" in names

    def test_toolset_get_tools(self):
        import asyncio
        from data_agent.toolsets.operator_tools import OperatorToolset
        ts = OperatorToolset()
        tools = asyncio.get_event_loop().run_until_complete(ts.get_tools())
        tool_names = {t.name for t in tools}
        assert "clean_data" in tool_names
        assert "integrate_data" in tool_names
        assert "analyze_data" in tool_names
        assert "visualize_data" in tool_names
        assert "list_operators" in tool_names
        assert len(tools) == 5


# ---------------------------------------------------------------------------
# Operator Composition (S-4: chaining operators)
# ---------------------------------------------------------------------------

class TestOperatorComposition:
    """Verify operators can be chained: clean → integrate → analyze → visualize."""

    def test_clean_then_analyze_plans_compatible(self, landuse_profile):
        """Clean plan output can feed into Analyze plan."""
        clean_op = CleanOperator()
        analyze_op = AnalyzeOperator()

        clean_plan = clean_op.plan(landuse_profile)
        analyze_plan = analyze_op.plan(landuse_profile, task_description="空间分布分析")

        # Both plans should be valid
        assert len(clean_plan.tool_calls) > 0
        assert len(analyze_plan.tool_calls) > 0
        # They should target different tools
        clean_tools = {tc.tool_name for tc in clean_plan.tool_calls}
        analyze_tools = {tc.tool_name for tc in analyze_plan.tool_calls}
        assert clean_tools != analyze_tools

    def test_full_pipeline_all_operators_plan(self, landuse_profile):
        """All four operators can independently plan for the same profile."""
        operators = [CleanOperator(), IntegrateOperator(),
                     AnalyzeOperator(), VisualizeOperator()]
        plans = []
        for op in operators:
            plan = op.plan(landuse_profile, task_description="分析土地利用数据")
            assert plan.operator_name in ("clean", "integrate", "analyze", "visualize")
            plans.append(plan)
        assert len(plans) == 4

    def test_registry_orchestration(self, landuse_profile):
        """OperatorRegistry.get() returns correct operators for chaining."""
        sequence = ["clean", "analyze", "visualize"]
        for name in sequence:
            op = OperatorRegistry.get(name)
            assert op is not None
            plan = op.plan(landuse_profile)
            assert plan.operator_name == name

    def test_analyze_strategy_auto_select(self, landuse_profile):
        """Analyze auto-selects strategy based on task description keywords."""
        op = AnalyzeOperator()
        cases = {
            "空间聚类分析": "spatial_stats",
            "优化土地利用": "drl_optimize",
            "因果推断": "causal",
            "DEM 地形分析": "terrain",
            "质量评分": "governance",
        }
        for task, expected_strategy in cases.items():
            plan = op.plan(landuse_profile, task_description=task)
            assert plan.strategy == expected_strategy, \
                f"Task '{task}' expected strategy '{expected_strategy}', got '{plan.strategy}'"

    def test_visualize_strategy_auto_select(self, csv_profile):
        """Visualize auto-selects strategy based on data characteristics."""
        op = VisualizeOperator()
        cases = {
            "着色图": "choropleth",
            "热力图": "heatmap",
            "柱状图": "charts",
        }
        for task, expected_strategy in cases.items():
            plan = op.plan(csv_profile, task_description=task)
            assert plan.strategy == expected_strategy, \
                f"Task '{task}' expected '{expected_strategy}', got '{plan.strategy}'"

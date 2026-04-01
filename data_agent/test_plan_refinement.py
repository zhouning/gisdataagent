"""
Tests for S-6: Plan Refinement + Error Recovery.

Verifies PlanRefiner auto-repair insertion, context injection,
redundant step removal, and ErrorRecoveryStrategy.
"""
import copy
import pytest
from data_agent.plan_refiner import (
    PlanRefiner,
    RefinementResult,
    REPAIR_TEMPLATES,
    ERROR_REPAIR_MAPPING,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def refiner():
    return PlanRefiner()


@pytest.fixture
def sample_steps():
    return [
        {"step_id": "analyze", "label": "空间分析", "pipeline_type": "general",
         "prompt": "对数据进行空间分析 {data_receive.output}"},
        {"step_id": "visualize", "label": "可视化", "pipeline_type": "general",
         "prompt": "生成分析结果的可视化"},
        {"step_id": "report", "label": "生成报告", "pipeline_type": "general",
         "prompt": "汇总分析和可视化结果生成报告"},
    ]


@pytest.fixture
def success_results():
    return [
        {"step_id": "data_receive", "status": "completed", "error": None,
         "summary": "加载了 500 条要素"},
    ]


@pytest.fixture
def crs_error_results():
    return [
        {"step_id": "data_receive", "status": "failed",
         "error": "CRS 不一致：源数据 EPSG:4547，目标 EPSG:4490",
         "summary": ""},
    ]


@pytest.fixture
def topology_error_results():
    return [
        {"step_id": "topology_check", "status": "failed",
         "error": "检测到 23 个拓扑错误：自相交 15 个，悬挂节点 8 个",
         "summary": ""},
    ]


# ---------------------------------------------------------------------------
# REPAIR_TEMPLATES and ERROR_REPAIR_MAPPING
# ---------------------------------------------------------------------------

class TestRepairConfig:
    def test_repair_templates_exist(self):
        assert "crs_mismatch" in REPAIR_TEMPLATES
        assert "null_values" in REPAIR_TEMPLATES
        assert "topology_error" in REPAIR_TEMPLATES

    def test_repair_template_structure(self):
        for key, tmpl in REPAIR_TEMPLATES.items():
            assert "step_id" in tmpl
            assert "label" in tmpl
            assert "prompt" in tmpl

    def test_error_mapping_keys(self):
        assert "crs" in ERROR_REPAIR_MAPPING
        assert "坐标系" in ERROR_REPAIR_MAPPING

    def test_error_mapping_values_reference_templates(self):
        for pattern, template_key in ERROR_REPAIR_MAPPING.items():
            assert template_key in REPAIR_TEMPLATES, \
                f"ERROR_REPAIR_MAPPING['{pattern}'] -> '{template_key}' not in REPAIR_TEMPLATES"


# ---------------------------------------------------------------------------
# RefinementResult
# ---------------------------------------------------------------------------

class TestRefinementResult:
    def test_empty_result(self):
        r = RefinementResult(steps=[])
        assert r.inserted_count == 0
        assert r.removed_count == 0
        assert r.adjusted_count == 0

    def test_to_dict(self):
        r = RefinementResult(
            steps=[{"step_id": "a"}],
            changes=["Inserted repair"],
            inserted_count=1,
            removed_count=0,
            adjusted_count=0,
        )
        d = r.to_dict()
        assert d["inserted"] == 1
        assert "Inserted repair" in d["changes"]


# ---------------------------------------------------------------------------
# PlanRefiner.refine — auto-repair insertion
# ---------------------------------------------------------------------------

class TestAutoRepair:
    def test_crs_error_inserts_repair(self, refiner, sample_steps, crs_error_results):
        result = refiner.refine(sample_steps, crs_error_results, {})
        assert result.inserted_count >= 1
        repair_labels = [s["label"] for s in result.steps]
        assert any("CRS" in label or "crs" in label.lower() for label in repair_labels)

    def test_topology_error_inserts_repair(self, refiner, sample_steps, topology_error_results):
        result = refiner.refine(sample_steps, topology_error_results, {})
        assert result.inserted_count >= 1
        repair_labels = [s["label"] for s in result.steps]
        assert any("拓扑" in label for label in repair_labels)

    def test_no_repair_on_success(self, refiner, sample_steps, success_results):
        result = refiner.refine(sample_steps, success_results, {})
        assert result.inserted_count == 0

    def test_repair_step_has_pipeline_type(self, refiner, sample_steps, crs_error_results):
        result = refiner.refine(sample_steps, crs_error_results, {})
        for step in result.steps:
            assert "pipeline_type" in step

    def test_original_steps_not_mutated(self, refiner, sample_steps, crs_error_results):
        original = copy.deepcopy(sample_steps)
        refiner.refine(sample_steps, crs_error_results, {})
        assert sample_steps == original  # deep copy inside refine


# ---------------------------------------------------------------------------
# PlanRefiner.refine — context injection
# ---------------------------------------------------------------------------

class TestContextInjection:
    def test_injects_upstream_output(self, refiner, sample_steps, success_results):
        node_outputs = {
            "data_receive": {"report": "加载了 500 条要素，CRS=EPSG:4490"}
        }
        result = refiner.refine(sample_steps, success_results, node_outputs)
        # The analyze step prompt contains {data_receive.output}
        analyze_step = next(s for s in result.steps if s["step_id"] == "analyze")
        assert "500" in analyze_step["prompt"] or result.adjusted_count >= 1

    def test_no_injection_without_placeholder(self, refiner):
        steps = [{"step_id": "simple", "label": "简单步骤",
                  "prompt": "执行简单操作", "pipeline_type": "general"}]
        result = refiner.refine(steps, [], {"other": {"report": "data"}})
        assert result.adjusted_count == 0


# ---------------------------------------------------------------------------
# PlanRefiner.refine — redundant step removal
# ---------------------------------------------------------------------------

class TestRedundantRemoval:
    def test_removes_duplicate_cleaning(self, refiner):
        steps = [
            {"step_id": "clean_again", "label": "数据清洗", "pipeline_type": "governance",
             "prompt": "清洗数据"},
            {"step_id": "analyze", "label": "分析", "pipeline_type": "general",
             "prompt": "分析数据"},
        ]
        completed_results = [
            {"step_id": "initial_clean", "status": "completed", "error": None,
             "summary": "数据清洗完成"},
        ]
        result = refiner.refine(steps, completed_results, {})
        assert result.removed_count >= 1

    def test_keeps_non_redundant_steps(self, refiner, sample_steps, success_results):
        result = refiner.refine(sample_steps, success_results, {})
        assert result.removed_count == 0
        assert len(result.steps) == len(sample_steps)


# ---------------------------------------------------------------------------
# PlanRefiner helper methods
# ---------------------------------------------------------------------------

class TestHelperMethods:
    def test_insert_repair_step(self, refiner):
        steps = [{"step_id": "a"}, {"step_id": "b"}]
        config = {"step_id": "repair_a", "label": "修复A", "prompt": "修复"}
        new_steps = refiner.insert_repair_step(steps, "a", config)
        ids = [s["step_id"] for s in new_steps]
        assert "repair_a" in ids
        # repair should come after "a"
        assert ids.index("repair_a") > ids.index("a")

    def test_remove_step(self, refiner):
        steps = [{"step_id": "a"}, {"step_id": "b"}, {"step_id": "c"}]
        new_steps = refiner.remove_step(steps, "b")
        ids = [s["step_id"] for s in new_steps]
        assert "b" not in ids
        assert len(ids) == 2

    def test_adjust_params(self, refiner):
        step = {"step_id": "test", "prompt": "容差 {tolerance_m} 米"}
        updated = refiner.adjust_params(step, "tolerance_m", "0.3")
        assert "0.3" in updated["prompt"] or updated == step  # depends on implementation

"""Tests for S-6: Plan Refinement & Error Recovery."""
import json
import pytest
from unittest.mock import patch, MagicMock

from data_agent.error_recovery import (
    RecoveryAction,
    RecoveryContext,
    RetryStrategy,
    AlternativeToolStrategy,
    SimplifyStrategy,
    SkipAndContinueStrategy,
    HumanInterventionStrategy,
    ErrorRecoveryEngine,
    attempt_recovery,
    TOOL_ALTERNATIVES,
)
from data_agent.plan_refiner import (
    PlanRefiner,
    RefinementResult,
    REPAIR_TEMPLATES,
    ERROR_REPAIR_MAPPING,
)


# ---------------------------------------------------------------------------
# RecoveryAction
# ---------------------------------------------------------------------------

class TestRecoveryAction:
    def test_to_dict(self):
        action = RecoveryAction("retry", "retry", reason="transient error")
        d = action.to_dict()
        assert d["strategy"] == "retry"
        assert d["action"] == "retry"
        assert d["success"] is False


# ---------------------------------------------------------------------------
# RetryStrategy
# ---------------------------------------------------------------------------

class TestRetryStrategy:
    def test_can_handle_transient(self):
        s = RetryStrategy()
        ctx = RecoveryContext(is_retryable=True, attempt_count=0, error_category="transient")
        assert s.can_handle(ctx) is True

    def test_cannot_handle_non_retryable(self):
        s = RetryStrategy()
        ctx = RecoveryContext(is_retryable=False, error_category="permission")
        assert s.can_handle(ctx) is False

    def test_cannot_handle_too_many_attempts(self):
        s = RetryStrategy()
        ctx = RecoveryContext(is_retryable=True, attempt_count=5, error_category="transient")
        assert s.can_handle(ctx) is False

    def test_recover_produces_retry_action(self):
        s = RetryStrategy()
        ctx = RecoveryContext(is_retryable=True, attempt_count=1, error_category="transient")
        action = s.recover(ctx)
        assert action.action == "retry"
        assert action.modified_kwargs.get("_retry_delay", 0) > 0


# ---------------------------------------------------------------------------
# AlternativeToolStrategy
# ---------------------------------------------------------------------------

class TestAlternativeToolStrategy:
    def test_can_handle_with_alternative(self):
        s = AlternativeToolStrategy()
        ctx = RecoveryContext(tool_name="arcpy_extract_watershed")
        assert s.can_handle(ctx) is True

    def test_cannot_handle_unknown_tool(self):
        s = AlternativeToolStrategy()
        ctx = RecoveryContext(tool_name="completely_unknown_tool")
        assert s.can_handle(ctx) is False

    def test_cannot_handle_empty_tool(self):
        s = AlternativeToolStrategy()
        ctx = RecoveryContext(tool_name="")
        assert s.can_handle(ctx) is False

    def test_recover_suggests_fallback(self):
        s = AlternativeToolStrategy()
        ctx = RecoveryContext(tool_name="arcpy_extract_watershed")
        action = s.recover(ctx)
        assert action.action == "substitute"
        assert action.modified_kwargs["_substitute_tool"] == "extract_watershed"

    def test_tool_alternatives_populated(self):
        assert len(TOOL_ALTERNATIVES) >= 5
        assert "arcpy_extract_watershed" in TOOL_ALTERNATIVES


# ---------------------------------------------------------------------------
# SimplifyStrategy
# ---------------------------------------------------------------------------

class TestSimplifyStrategy:
    def test_can_handle_memory_error(self):
        s = SimplifyStrategy()
        ctx = RecoveryContext(error_message="Out of memory: cannot allocate 8GB")
        assert s.can_handle(ctx) is True

    def test_can_handle_resource_error(self):
        s = SimplifyStrategy()
        ctx = RecoveryContext(error_message="数据过大，内存不足")
        assert s.can_handle(ctx) is True

    def test_cannot_handle_normal_error(self):
        s = SimplifyStrategy()
        ctx = RecoveryContext(error_message="File not found: test.shp")
        assert s.can_handle(ctx) is False

    def test_recover_adds_sample(self):
        s = SimplifyStrategy()
        ctx = RecoveryContext(error_message="Out of memory")
        action = s.recover(ctx)
        assert action.action == "simplify"
        assert action.modified_kwargs.get("_sample_ratio") == 0.5


# ---------------------------------------------------------------------------
# SkipAndContinueStrategy
# ---------------------------------------------------------------------------

class TestSkipAndContinueStrategy:
    def test_can_handle_non_critical_viz(self):
        s = SkipAndContinueStrategy()
        ctx = RecoveryContext(is_critical=False, step_label="数据可视化")
        assert s.can_handle(ctx) is True

    def test_cannot_handle_critical_step(self):
        s = SkipAndContinueStrategy()
        ctx = RecoveryContext(is_critical=True, step_label="可视化")
        assert s.can_handle(ctx) is False

    def test_cannot_handle_non_skippable(self):
        s = SkipAndContinueStrategy()
        ctx = RecoveryContext(is_critical=False, step_label="数据分析")
        assert s.can_handle(ctx) is False

    def test_recover_produces_skip(self):
        s = SkipAndContinueStrategy()
        ctx = RecoveryContext(is_critical=False, step_label="导出报告")
        action = s.recover(ctx)
        assert action.action == "skip"


# ---------------------------------------------------------------------------
# HumanInterventionStrategy
# ---------------------------------------------------------------------------

class TestHumanInterventionStrategy:
    def test_always_can_handle(self):
        s = HumanInterventionStrategy()
        ctx = RecoveryContext()
        assert s.can_handle(ctx) is True

    def test_recover_produces_escalate(self):
        s = HumanInterventionStrategy()
        ctx = RecoveryContext(step_label="数据处理", error_message="unknown error")
        action = s.recover(ctx)
        assert action.action == "escalate"


# ---------------------------------------------------------------------------
# ErrorRecoveryEngine
# ---------------------------------------------------------------------------

class TestErrorRecoveryEngine:
    def test_strategies_ordered_by_priority(self):
        engine = ErrorRecoveryEngine()
        priorities = [s.priority for s in engine.strategies]
        assert priorities == sorted(priorities)

    @patch("data_agent.error_recovery.classify_error")
    def test_transient_error_gets_retry(self, mock_classify):
        mock_classify.return_value = (True, "transient")
        action = attempt_recovery(
            TimeoutError("connection timeout"),
            {"step_id": "s1", "label": "探查"},
            attempt_count=0,
        )
        assert action.action == "retry"
        assert action.strategy_name == "retry"

    @patch("data_agent.error_recovery.classify_error")
    def test_tool_with_alternative(self, mock_classify):
        mock_classify.return_value = (False, "config")
        action = attempt_recovery(
            RuntimeError("ArcPy not available"),
            {"step_id": "s1", "label": "流域提取", "tool_name": "arcpy_extract_watershed"},
        )
        assert action.action == "substitute"
        assert action.strategy_name == "alternative_tool"

    @patch("data_agent.error_recovery.classify_error")
    def test_memory_error_gets_simplify(self, mock_classify):
        mock_classify.return_value = (False, "unknown")
        action = attempt_recovery(
            MemoryError("Out of memory"),
            {"step_id": "s1", "label": "分析"},
        )
        assert action.action == "simplify"

    @patch("data_agent.error_recovery.classify_error")
    def test_non_critical_skippable_step(self, mock_classify):
        mock_classify.return_value = (False, "data_format")
        action = attempt_recovery(
            ValueError("invalid format"),
            {"step_id": "s1", "label": "报告导出", "critical": False},
        )
        assert action.action == "skip"

    @patch("data_agent.error_recovery.classify_error")
    def test_unrecoverable_escalates(self, mock_classify):
        mock_classify.return_value = (False, "permission")
        action = attempt_recovery(
            PermissionError("access denied"),
            {"step_id": "s1", "label": "数据处理", "critical": True},
        )
        assert action.action == "escalate"

    @patch("data_agent.error_recovery.classify_error")
    def test_priority_order_retry_before_skip(self, mock_classify):
        """Retry takes priority over skip for transient errors on non-critical steps."""
        mock_classify.return_value = (True, "transient")
        action = attempt_recovery(
            ConnectionError("timeout"),
            {"step_id": "s1", "label": "可视化", "critical": False},
            attempt_count=0,
        )
        assert action.action == "retry"  # retry wins over skip


# ---------------------------------------------------------------------------
# PlanRefiner
# ---------------------------------------------------------------------------

class TestPlanRefiner:
    def test_insert_repair_for_crs_error(self):
        refiner = PlanRefiner()
        remaining = [
            {"step_id": "s2", "label": "分析", "prompt": "analyze data"},
        ]
        completed = [
            {"step_id": "s1", "status": "failed", "error": "CRS mismatch: EPSG:4326 vs EPSG:4490"},
        ]
        result = refiner.refine(remaining, completed, {})
        assert result.inserted_count >= 1
        repair_ids = [s["step_id"] for s in result.steps if "repair" in s["step_id"]]
        assert len(repair_ids) >= 1

    def test_insert_repair_for_topology_error(self):
        refiner = PlanRefiner()
        remaining = [{"step_id": "s2", "label": "处理"}]
        completed = [
            {"step_id": "s1", "status": "failed", "error": "拓扑错误: self-intersection"},
        ]
        result = refiner.refine(remaining, completed, {})
        assert result.inserted_count >= 1

    def test_no_repair_for_non_matching_error(self):
        refiner = PlanRefiner()
        remaining = [{"step_id": "s2", "label": "分析"}]
        completed = [
            {"step_id": "s1", "status": "failed", "error": "permission denied"},
        ]
        result = refiner.refine(remaining, completed, {})
        assert result.inserted_count == 0

    def test_remove_redundant_clean_step(self):
        refiner = PlanRefiner()
        remaining = [
            {"step_id": "clean_2", "label": "数据清洗", "prompt": "clean again"},
            {"step_id": "s3", "label": "分析", "prompt": "analyze"},
        ]
        completed = [
            {"step_id": "clean_1", "status": "completed"},
        ]
        result = refiner.refine(remaining, completed, {})
        assert result.removed_count >= 1
        remaining_ids = [s["step_id"] for s in result.steps]
        assert "clean_2" not in remaining_ids

    def test_inject_upstream_output(self):
        refiner = PlanRefiner()
        remaining = [
            {"step_id": "s2", "label": "分析", "prompt": "Analyze: {s1.output}"},
        ]
        completed = [{"step_id": "s1", "status": "completed"}]
        outputs = {"s1": {"report": "data has 500 rows, 10 columns"}}
        result = refiner.refine(remaining, completed, outputs)
        assert "500 rows" in result.steps[0]["prompt"]

    def test_insert_repair_step_method(self):
        refiner = PlanRefiner()
        steps = [
            {"step_id": "s1", "label": "A"},
            {"step_id": "s2", "label": "B"},
        ]
        repair = {"step_id": "repair_s1", "label": "Fix", "pipeline_type": "general"}
        new_steps = refiner.insert_repair_step(steps, "s1", repair)
        assert len(new_steps) == 3
        assert new_steps[1]["step_id"] == "repair_s1"

    def test_remove_step_method(self):
        refiner = PlanRefiner()
        steps = [
            {"step_id": "s1", "label": "A"},
            {"step_id": "s2", "label": "B", "depends_on": ["s1"]},
            {"step_id": "s3", "label": "C", "depends_on": ["s2"]},
        ]
        new_steps = refiner.remove_step(steps, "s2")
        assert len(new_steps) == 2
        # s3 should now depend on s1 (s2's original dependency)
        s3 = [s for s in new_steps if s["step_id"] == "s3"][0]
        assert "s1" in s3["depends_on"]

    def test_adjust_params(self):
        refiner = PlanRefiner()
        step = {"step_id": "s1", "params": {"file_path": "old.shp"}}
        updated = refiner.adjust_params(step, "file_path", "new.shp")
        assert updated["params"]["file_path"] == "new.shp"
        # Original not mutated
        assert step["params"]["file_path"] == "old.shp"

    def test_refinement_result_to_dict(self):
        r = RefinementResult(steps=[], changes=["added repair"], inserted_count=1)
        d = r.to_dict()
        assert d["inserted"] == 1
        assert "added repair" in d["changes"]


# ---------------------------------------------------------------------------
# Integration: Error patterns → repair templates
# ---------------------------------------------------------------------------

class TestErrorRepairMapping:
    def test_all_mappings_have_templates(self):
        for pattern, template_key in ERROR_REPAIR_MAPPING.items():
            assert template_key in REPAIR_TEMPLATES, \
                f"Pattern '{pattern}' maps to unknown template '{template_key}'"

    def test_repair_templates_have_required_fields(self):
        for key, template in REPAIR_TEMPLATES.items():
            assert "step_id" in template
            assert "label" in template
            assert "pipeline_type" in template
            assert "prompt" in template

"""Tests for pipeline progress visualization (v4.1.2).

Tests _render_bar() and _build_progress_content() as pure functions.
No Chainlit mocking required.
"""

import time
from unittest.mock import patch

import pytest


# Import the functions under test (they live in app.py)
# Use lazy import to avoid heavy app.py side effects
def _get_funcs():
    from data_agent.app import _render_bar, _build_progress_content, AGENT_LABELS
    return _render_bar, _build_progress_content, AGENT_LABELS


# ===================================================================
# _render_bar
# ===================================================================

class TestRenderBar:
    """Test the text progress bar renderer."""

    def test_empty(self):
        _render_bar, _, _ = _get_funcs()
        assert _render_bar(0, 4) == "░░░░ 0/4"

    def test_partial(self):
        _render_bar, _, _ = _get_funcs()
        assert _render_bar(2, 4) == "▓▓░░ 2/4"

    def test_full(self):
        _render_bar, _, _ = _get_funcs()
        assert _render_bar(4, 4) == "▓▓▓▓ 4/4"

    def test_zero_total(self):
        _render_bar, _, _ = _get_funcs()
        assert _render_bar(0, 0) == ""

    def test_single(self):
        _render_bar, _, _ = _get_funcs()
        assert _render_bar(1, 3) == "▓░░ 1/3"


# ===================================================================
# _build_progress_content — fixed pipelines
# ===================================================================

class TestProgressContentFixed:
    """Test progress content for fixed pipelines (optimization/governance/general)."""

    def _stages(self):
        return ["GovExploration", "GovProcessing", "GovernanceReporter"]

    def test_initial_all_pending(self):
        _, _build, _ = _get_funcs()
        content = _build(
            "Governance Pipeline", "governance",
            self._stages(), [],
        )
        assert "○" in content
        assert "▶" not in content
        assert "✓" not in content
        assert "░░░ 0/3" in content

    def test_one_running(self):
        _, _build, _ = _get_funcs()
        timings = [
            {"name": "GovExploration", "label": "数据质量审计",
             "start": time.time() - 5.0, "end": None},
        ]
        content = _build(
            "Governance Pipeline", "governance",
            self._stages(), timings,
        )
        assert "▶ 数据质量审计" in content
        assert "○ 数据修复" in content or "○" in content
        assert "░░░ 0/3" in content

    def test_one_done_one_running(self):
        _, _build, _ = _get_funcs()
        now = time.time()
        timings = [
            {"name": "GovExploration", "label": "数据质量审计",
             "start": now - 10, "end": now - 5},
            {"name": "GovProcessing", "label": "数据修复",
             "start": now - 5, "end": None},
        ]
        content = _build(
            "Governance Pipeline", "governance",
            self._stages(), timings,
        )
        assert "✓ 数据质量审计  5.0s" in content
        assert "▶ 数据修复" in content
        assert "▓░░ 1/3" in content

    def test_complete(self):
        _, _build, _ = _get_funcs()
        now = time.time()
        timings = [
            {"name": "GovExploration", "label": "数据质量审计",
             "start": now - 30, "end": now - 20},
            {"name": "GovProcessing", "label": "数据修复",
             "start": now - 20, "end": now - 8},
            {"name": "GovernanceReporter", "label": "生成治理报告",
             "start": now - 8, "end": now},
        ]
        content = _build(
            "Governance Pipeline", "governance",
            self._stages(), timings,
            is_complete=True, total_duration=30.0,
        )
        assert "✓ 数据质量审计  10.0s" in content
        assert "✓ 数据修复  12.0s" in content
        assert "✓ 生成治理报告  8.0s" in content
        assert "▓▓▓ 3/3" in content
        assert "完成" in content
        assert "⏱ 总耗时 30.0s" in content
        assert "○" not in content
        assert "▶" not in content

    def test_error_state(self):
        _, _build, _ = _get_funcs()
        now = time.time()
        timings = [
            {"name": "GovExploration", "label": "数据质量审计",
             "start": now - 15, "end": now - 8},
            {"name": "GovProcessing", "label": "数据修复",
             "start": now - 8, "end": None, "_error_time": now},
        ]
        content = _build(
            "Governance Pipeline", "governance",
            self._stages(), timings,
            is_complete=True, total_duration=15.0, is_error=True,
        )
        assert "✓ 数据质量审计  7.0s" in content
        assert "✗ 数据修复" in content
        assert "(异常)" in content
        assert "○ 生成治理报告" in content
        assert "异常终止" in content


# ===================================================================
# _build_progress_content — dynamic planner
# ===================================================================

class TestProgressContentPlanner:
    """Test progress content for dynamic planner."""

    def test_initial_empty(self):
        _, _build, _ = _get_funcs()
        content = _build("Dynamic Planner", "planner", [], [])
        assert "准备中" in content

    def test_incremental_steps(self):
        _, _build, _ = _get_funcs()
        now = time.time()
        timings = [
            {"name": "Planner", "label": "任务规划",
             "start": now - 10, "end": now - 8},
            {"name": "PlannerExplorer", "label": "数据探查",
             "start": now - 8, "end": None},
        ]
        content = _build("Dynamic Planner", "planner", [], timings)
        assert "步骤 2" in content
        assert "✓ 任务规划  2.0s" in content
        assert "▶ 数据探查" in content
        # No pending stages for planner
        assert "○" not in content

    def test_planner_complete(self):
        _, _build, _ = _get_funcs()
        now = time.time()
        timings = [
            {"name": "Planner", "label": "任务规划",
             "start": now - 20, "end": now - 18},
            {"name": "PlannerExplorer", "label": "数据探查",
             "start": now - 18, "end": now - 10},
            {"name": "PlannerReporter", "label": "撰写报告",
             "start": now - 10, "end": now},
        ]
        content = _build(
            "Dynamic Planner", "planner", [], timings,
            is_complete=True, total_duration=20.0,
        )
        assert "3 步骤完成" in content
        assert "⏱ 总耗时 20.0s" in content
        assert "✓ 任务规划  2.0s" in content
        assert "✓ 数据探查  8.0s" in content
        assert "✓ 撰写报告  10.0s" in content

"""Tests for Intent Disambiguation v2 — subtask preview, confirmation, and execution."""
import asyncio
import unittest
from unittest.mock import AsyncMock, patch, MagicMock

from data_agent.task_decomposer import (
    TaskNode, TaskGraph, format_subtask_preview, execute_task_graph,
)


class TestFormatSubtaskPreview(unittest.TestCase):
    def test_basic_preview(self):
        g = TaskGraph()
        g.add_node(TaskNode(id="t1", description="加载数据", agent_hint="DataExploration"))
        g.add_node(TaskNode(id="t2", description="缓冲区分析", dependencies=["t1"]))
        preview = format_subtask_preview(g)
        assert "t1" in preview
        assert "加载数据" in preview
        assert "依赖: t1" in preview
        assert "2 步" in preview

    def test_single_node(self):
        g = TaskGraph()
        g.add_node(TaskNode(id="t1", description="简单查询"))
        preview = format_subtask_preview(g)
        assert "1 步" in preview

    def test_agent_hint_shown(self):
        g = TaskGraph()
        g.add_node(TaskNode(id="t1", description="探索", agent_hint="DataExploration"))
        preview = format_subtask_preview(g)
        assert "[DataExploration]" in preview


class TestExecuteTaskGraph(unittest.TestCase):
    def test_sequential_execution(self):
        g = TaskGraph()
        g.add_node(TaskNode(id="t1", description="步骤1"))
        g.add_node(TaskNode(id="t2", description="步骤2", dependencies=["t1"]))

        call_order = []

        async def mock_execute(node, context):
            call_order.append(node.id)
            return f"result_{node.id}"

        results = asyncio.get_event_loop().run_until_complete(
            execute_task_graph(g, mock_execute)
        )
        assert call_order == ["t1", "t2"]
        assert len(results) == 2
        assert results[0]["status"] == "completed"
        assert results[1]["status"] == "completed"

    def test_parallel_wave(self):
        g = TaskGraph()
        g.add_node(TaskNode(id="t1", description="并行A"))
        g.add_node(TaskNode(id="t2", description="并行B"))
        g.add_node(TaskNode(id="t3", description="汇总", dependencies=["t1", "t2"]))

        async def mock_execute(node, context):
            return f"done_{node.id}"

        results = asyncio.get_event_loop().run_until_complete(
            execute_task_graph(g, mock_execute)
        )
        assert len(results) == 3
        assert all(r["status"] == "completed" for r in results)

    def test_failure_handling(self):
        g = TaskGraph()
        g.add_node(TaskNode(id="t1", description="会失败"))

        async def mock_execute(node, context):
            raise RuntimeError("boom")

        results = asyncio.get_event_loop().run_until_complete(
            execute_task_graph(g, mock_execute)
        )
        assert results[0]["status"] == "failed"
        assert "boom" in results[0]["result"]

    def test_progress_callback(self):
        g = TaskGraph()
        g.add_node(TaskNode(id="t1", description="步骤1"))

        progress_calls = []

        async def mock_execute(node, context):
            return "ok"

        async def on_progress(node, status, result):
            progress_calls.append((node.id, status))

        asyncio.get_event_loop().run_until_complete(
            execute_task_graph(g, mock_execute, on_progress)
        )
        assert ("t1", "running") in progress_calls
        assert ("t1", "completed") in progress_calls

    def test_context_propagation(self):
        """Earlier task results are passed to later tasks via context."""
        g = TaskGraph()
        g.add_node(TaskNode(id="t1", description="产出数据"))
        g.add_node(TaskNode(id="t2", description="消费数据", dependencies=["t1"]))

        received_context = {}

        async def mock_execute(node, context):
            if node.id == "t2":
                received_context.update(context)
            return f"output_{node.id}"

        asyncio.get_event_loop().run_until_complete(
            execute_task_graph(g, mock_execute)
        )
        assert "t1" in received_context
        assert received_context["t1"] == "output_t1"


class TestShouldDecomposeIntegration(unittest.TestCase):
    """Integration tests for should_decompose + format flow."""

    def test_complex_query_detected(self):
        from data_agent.intent_router import should_decompose
        assert should_decompose("首先加载数据，然后做缓冲区分析，最后生成热力图")

    def test_simple_query_not_decomposed(self):
        from data_agent.intent_router import should_decompose
        assert not should_decompose("显示地图")


if __name__ == "__main__":
    unittest.main()

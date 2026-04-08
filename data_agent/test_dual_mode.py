"""Tests for Agentic/Workflow dual mode detection (v20.0)."""
import pytest
from unittest.mock import patch, MagicMock

from data_agent.intent_router import _detect_execution_mode


def test_workflow_mode_from_intent():
    assert _detect_execution_mode("anything", "WORKFLOW") == "workflow"


def test_agentic_mode_default():
    assert _detect_execution_mode("分析土地利用", "GENERAL") == "agentic"


def test_workflow_mode_zh_keywords():
    assert _detect_execution_mode("请执行工作流处理数据", "GENERAL") == "workflow"
    assert _detect_execution_mode("按模板运行质检", "GOVERNANCE") == "workflow"
    assert _detect_execution_mode("批量处理所有文件", "GENERAL") == "workflow"


def test_workflow_mode_en_keywords():
    assert _detect_execution_mode("run workflow on this data", "GENERAL") == "workflow"
    assert _detect_execution_mode("execute workflow for QC", "GOVERNANCE") == "workflow"


def test_agentic_mode_no_keywords():
    assert _detect_execution_mode("统计耕地面积", "GENERAL") == "agentic"
    assert _detect_execution_mode("show me the land use map", "GENERAL") == "agentic"


def test_classify_intent_returns_6_tuple():
    """classify_intent now returns 6 values including execution_mode."""
    with patch("data_agent.intent_router._router_client") as mock_client:
        mock_response = MagicMock()
        mock_response.text = "GENERAL|Test query"
        mock_response.usage_metadata = None
        mock_client.models.generate_content.return_value = mock_response

        from data_agent.intent_router import classify_intent
        result = classify_intent("分析数据")
        assert len(result) == 6
        intent, reason, tokens, cats, lang, mode = result
        assert mode in ("agentic", "workflow")


def test_classify_intent_workflow_mode():
    """classify_intent detects workflow mode from keywords."""
    with patch("data_agent.intent_router._router_client") as mock_client:
        mock_response = MagicMock()
        mock_response.text = "GENERAL|Running template"
        mock_response.usage_metadata = None
        mock_client.models.generate_content.return_value = mock_response

        from data_agent.intent_router import classify_intent
        result = classify_intent("执行工作流处理质检数据")
        assert result[5] == "workflow"

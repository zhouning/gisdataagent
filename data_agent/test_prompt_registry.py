"""Tests for prompt_registry module"""
import pytest
from unittest.mock import patch, MagicMock
from data_agent.prompt_registry import PromptRegistry


def test_get_prompt_db_unavailable_falls_back_to_yaml():
    """When DB unavailable, should fall back to YAML"""
    registry = PromptRegistry()

    with patch('data_agent.prompt_registry.get_engine', return_value=None):
        with patch('data_agent.prompts.load_prompts') as mock_load:
            mock_load.return_value = {"test_key": "test prompt from yaml"}
            result = registry.get_prompt("general", "test_key", env="prod")
            assert result == "test prompt from yaml"
            mock_load.assert_called_once_with("general")


def test_get_prompt_from_db_when_available():
    """When DB available and has active version, use DB"""
    registry = PromptRegistry()

    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_result = MagicMock()
    mock_result.fetchone.return_value = ("prompt from db",)
    mock_conn.execute.return_value = mock_result
    mock_engine.connect.return_value.__enter__.return_value = mock_conn

    with patch('data_agent.prompt_registry.get_engine', return_value=mock_engine):
        result = registry.get_prompt("general", "test_key", env="prod")
        assert result == "prompt from db"

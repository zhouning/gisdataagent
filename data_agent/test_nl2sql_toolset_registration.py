"""Tests for NL2SQLEnhancedToolset registration."""


def test_enhanced_toolset_exported_from_toolsets_package():
    from data_agent.toolsets import NL2SQLEnhancedToolset
    assert NL2SQLEnhancedToolset is not None


def test_enhanced_toolset_allowed_for_custom_skills():
    from data_agent.custom_skills import TOOLSET_NAMES, _get_toolset_registry
    assert "NL2SQLEnhancedToolset" in TOOLSET_NAMES
    registry = _get_toolset_registry()
    assert "NL2SQLEnhancedToolset" in registry


def test_enhanced_toolset_exposes_two_tools():
    import asyncio
    from data_agent.toolsets.nl2sql_enhanced_tools import NL2SQLEnhancedToolset
    ts = NL2SQLEnhancedToolset()
    tools = asyncio.run(ts.get_tools())
    tool_names = sorted([t.name for t in tools])
    assert tool_names == ["execute_nl2sql", "prepare_nl2sql_context"]

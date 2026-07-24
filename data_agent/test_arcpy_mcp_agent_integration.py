"""Tests for ArcPy MCP registration across agent pipelines."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from data_agent.hitl_approval import HITLApprovalPlugin, ensure_hitl_plugin
from data_agent.toolsets.arcpy_mcp_toolset import ArcPyMcpToolset


GOVERNANCE_EXPLORATION_TOOLS = [
    "arcpy_service_status",
    "arcpy_inspect_dataset",
    "arcpy_check_geometry",
    "arcpy_calculate_slope",
    "arcpy_zonal_statistics",
]

GOVERNANCE_PROCESSING_TOOLS = [
    "arcpy_project_features",
    "arcpy_project_raster",
    "arcpy_repair_geometry",
]


def _arcpy_toolsets(agent):
    return [
        toolset
        for toolset in agent.tools
        if isinstance(toolset, ArcPyMcpToolset)
    ]


def test_requested_pipelines_register_scoped_arcpy_toolsets():
    from data_agent.agent import (
        _make_planner_processor,
        general_processing_agent,
        governance_exploration_agent,
        governance_processing_agent,
    )

    planner_processor = _make_planner_processor("ArcPyPlannerTest")
    registrations = {
        "general": _arcpy_toolsets(general_processing_agent),
        "governance_exploration": _arcpy_toolsets(
            governance_exploration_agent
        ),
        "governance_processing": _arcpy_toolsets(
            governance_processing_agent
        ),
        "planner": _arcpy_toolsets(planner_processor),
    }

    assert all(len(toolsets) == 1 for toolsets in registrations.values())
    assert registrations["general"][0].tool_filter is None
    assert registrations["planner"][0].tool_filter is None
    assert registrations["governance_exploration"][0].tool_filter == (
        GOVERNANCE_EXPLORATION_TOOLS
    )
    assert registrations["governance_processing"][0].tool_filter == (
        GOVERNANCE_PROCESSING_TOOLS
    )
    assert {
        tool.name
        for tool in asyncio.run(
            registrations["governance_exploration"][0].get_tools()
        )
    } == set(GOVERNANCE_EXPLORATION_TOOLS)
    assert {
        tool.name
        for tool in asyncio.run(
            registrations["governance_processing"][0].get_tools()
        )
    } == set(GOVERNANCE_PROCESSING_TOOLS)

    instances = [toolsets[0] for toolsets in registrations.values()]
    assert len({id(toolset) for toolset in instances}) == len(instances)


@pytest.mark.asyncio
@patch("data_agent.pipeline_runner.Runner")
async def test_headless_and_streaming_runners_install_hitl_by_default(
    runner_class,
):
    from data_agent.pipeline_runner import (
        run_pipeline_headless,
        run_pipeline_streaming,
    )

    async def empty_events():
        if False:
            yield None

    runner = MagicMock()
    runner.run_async.side_effect = lambda **kwargs: empty_events()
    runner_class.return_value = runner
    session_service = SimpleNamespace(
        get_session=AsyncMock(return_value=None)
    )

    await run_pipeline_headless(
        agent=MagicMock(),
        session_service=session_service,
        user_id="test-user",
        session_id="headless-session",
        prompt="test",
    )
    async for _ in run_pipeline_streaming(
        agent=MagicMock(),
        session_service=session_service,
        user_id="test-user",
        session_id="stream-session",
        prompt="test",
    ):
        pass

    assert len(runner_class.call_args_list) == 2
    for runner_call in runner_class.call_args_list:
        plugins = runner_call.kwargs["plugins"]
        assert sum(
            isinstance(plugin, HITLApprovalPlugin) for plugin in plugins
        ) == 1


def test_runner_plugin_assembly_preserves_configured_hitl_instance():
    configured = HITLApprovalPlugin()
    duplicate = HITLApprovalPlugin()
    approval_function = AsyncMock(
        return_value=SimpleNamespace(payload={"value": "REJECT"})
    )
    configured.set_approval_function(approval_function)
    unrelated = MagicMock()

    configured_first = ensure_hitl_plugin(
        [unrelated, configured, duplicate]
    )
    unconfigured_first = ensure_hitl_plugin(
        [unrelated, duplicate, configured]
    )

    assert configured_first == [unrelated, configured]
    assert unconfigured_first == [unrelated, configured]
    assert configured._approval_fn is approval_function

    result = asyncio.run(
        unconfigured_first[1].before_tool_callback(
            tool=SimpleNamespace(name="import_to_postgis"),
            tool_args={"table": "sensitive"},
            tool_context=None,
        )
    )
    assert result is not None
    assert result["status"] == "blocked"
    approval_function.assert_awaited_once()

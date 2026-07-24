"""Tests for ArcPy MCP registration across agent pipelines."""

import asyncio

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

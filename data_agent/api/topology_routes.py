"""
Agent Topology API — Visualize multi-agent system structure.

Extracts agent hierarchy from agent.py and exposes as JSON for ReactFlow visualization.
"""
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from ..observability import get_logger

logger = get_logger("topology_api")


def _extract_toolset_info(tool):
    """Extract toolset metadata from an ADK tool/toolset object."""
    cls = tool.__class__
    name = cls.__name__

    # BaseToolset subclasses: tools are registered as methods
    # Count public methods that look like tool functions
    tool_count = 0
    for attr_name in dir(tool):
        if attr_name.startswith('_'):
            continue
        attr = getattr(tool, attr_name, None)
        if callable(attr) and attr_name not in ('get_tools', 'close'):
            tool_count += 1

    doc = (cls.__doc__ or '').strip().split('\n')[0]
    return {'name': name, 'description': doc, 'tool_count': tool_count}


def _extract_agents(agent, parent_id, agents_out, toolsets_out, seen_toolsets):
    """Recursively extract agent hierarchy."""
    agent_id = getattr(agent, 'name', str(id(agent)))
    agent_type = agent.__class__.__name__

    # Collect tools/toolsets
    tools = []
    agent_tools = getattr(agent, 'tools', None)
    if agent_tools:
        for tool in agent_tools:
            ts_name = tool.__class__.__name__
            tools.append(ts_name)
            if ts_name not in seen_toolsets:
                seen_toolsets.add(ts_name)
                toolsets_out.append(_extract_toolset_info(tool))

    # Get model info for LlmAgents
    model = None
    if hasattr(agent, 'model') and agent.model:
        model = str(agent.model)

    # Get instruction snippet
    instruction = None
    if hasattr(agent, 'instruction') and agent.instruction:
        inst = agent.instruction
        if callable(inst):
            inst = "(dynamic)"
        elif len(inst) > 120:
            inst = inst[:120] + '...'
        instruction = inst

    # Recurse into children — ADK uses `sub_agents`
    children = []
    sub_agents = getattr(agent, 'sub_agents', None)
    if sub_agents:
        for child in sub_agents:
            child_id = _extract_agents(child, agent_id, agents_out, toolsets_out, seen_toolsets)
            children.append(child_id)

    agents_out.append({
        'id': agent_id,
        'name': agent_id,
        'type': agent_type,
        'parent_id': parent_id,
        'tools': tools,
        'children': children,
        'model': model,
        'instruction_snippet': instruction,
    })

    return agent_id


async def _api_agent_topology(request: Request):
    """GET /api/agent-topology — return full agent hierarchy."""
    try:
        from data_agent.agent import (
            data_pipeline, governance_pipeline, general_pipeline,
        )

        agents = []
        toolsets = []
        seen = set()

        _extract_agents(data_pipeline, None, agents, toolsets, seen)
        _extract_agents(governance_pipeline, None, agents, toolsets, seen)
        _extract_agents(general_pipeline, None, agents, toolsets, seen)

        return JSONResponse(content={
            'agents': agents,
            'toolsets': toolsets,
            'pipelines': [
                {'id': data_pipeline.name, 'label': 'Optimization Pipeline (空间优化)', 'color': '#3b82f6'},
                {'id': governance_pipeline.name, 'label': 'Governance Pipeline (数据治理)', 'color': '#f59e0b'},
                {'id': general_pipeline.name, 'label': 'General Pipeline (通用分析)', 'color': '#10b981'},
            ],
        })
    except Exception as e:
        logger.error("Agent topology error: %s", e)
        return JSONResponse(content={'error': str(e)}, status_code=500)


def get_topology_routes():
    """Return Starlette routes for agent topology."""
    return [
        Route("/api/agent-topology", endpoint=_api_agent_topology, methods=["GET"]),
    ]

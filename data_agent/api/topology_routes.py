"""
Agent Topology API — Visualize multi-agent system structure.

Extracts agent hierarchy from agent.py and exposes as JSON for ReactFlow visualization.
"""
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from ..observability import get_logger

logger = get_logger("topology_api")

_MENTIONABLE_SUB_AGENTS = {
    "DataExploration", "DataProcessing", "DataAnalysis", "DataVisualization",
    "DataSummary", "GovExploration", "GovProcessing", "GovernanceReporter",
    "GeneralProcessing", "GeneralViz",
}

_PIPELINE_META = {
    "DataPipeline": ("OPTIMIZATION", "空间优化 (Optimization)"),
    "GovernancePipeline": ("GOVERNANCE", "数据治理 (Governance)"),
    "GeneralPipeline": ("GENERAL", "通用分析 (General)"),
}


def _extract_toolset_info(tool):
    cls = tool.__class__
    name = cls.__name__
    tool_count = 0
    for attr_name in dir(tool):
        if attr_name.startswith('_'):
            continue
        attr = getattr(tool, attr_name, None)
        if callable(attr) and attr_name not in ('get_tools', 'close'):
            tool_count += 1
    doc = (cls.__doc__ or '').strip().split('\n')[0]
    return {'name': name, 'description': doc, 'tool_count': tool_count}


def _extract_agents(agent, parent_id, agents_out, toolsets_out, seen_toolsets, pipeline_label):
    agent_id = getattr(agent, 'name', str(id(agent)))
    agent_type = agent.__class__.__name__

    if agent_id in _PIPELINE_META:
        pipeline_label = _PIPELINE_META[agent_id][1]

    tools = []
    agent_tools = getattr(agent, 'tools', None)
    if agent_tools:
        for tool in agent_tools:
            ts_name = tool.__class__.__name__
            tools.append(ts_name)
            if ts_name not in seen_toolsets:
                seen_toolsets.add(ts_name)
                toolsets_out.append(_extract_toolset_info(tool))

    model = None
    if hasattr(agent, 'model') and agent.model:
        model = str(agent.model)

    instruction = None
    if hasattr(agent, 'instruction') and agent.instruction:
        inst = agent.instruction
        if callable(inst):
            inst = "(dynamic)"
        elif len(inst) > 120:
            inst = inst[:120] + '...'
        instruction = inst

    children = []
    sub_agents = getattr(agent, 'sub_agents', None)
    if sub_agents:
        for child in sub_agents:
            child_id = _extract_agents(child, agent_id, agents_out, toolsets_out,
                                       seen_toolsets, pipeline_label)
            children.append(child_id)

    mentionable = agent_id in _MENTIONABLE_SUB_AGENTS or agent_id in _PIPELINE_META

    agents_out.append({
        'id': agent_id,
        'name': agent_id,
        'type': agent_type,
        'parent_id': parent_id,
        'tools': tools,
        'children': children,
        'model': model,
        'instruction_snippet': instruction,
        'mentionable': mentionable,
        'pipeline_label': pipeline_label or "",
    })

    return agent_id


def _list_custom_skills_safe():
    try:
        from ..custom_skills import list_custom_skills
        return list_custom_skills(include_shared=True)
    except Exception:
        return []


def _append_custom_skill_agents(agents_out):
    for skill in _list_custom_skills_safe():
        name = skill.get("skill_name") or f"custom_{skill.get('id', '?')}"
        tools = list(skill.get("toolset_names") or [])
        agents_out.append({
            'id': f"custom_{skill.get('id')}",
            'name': name,
            'type': 'CustomSkill',
            'parent_id': None,
            'tools': tools,
            'children': [],
            'model': skill.get("model_tier"),
            'instruction_snippet': (skill.get("description") or "")[:120],
            'mentionable': True,
            'pipeline_label': "自定义技能 (Custom Skills)",
        })


async def _api_agent_topology(request: Request):
    """GET /api/agent-topology — return full agent hierarchy with Custom Skills."""
    try:
        from data_agent.agent import (
            data_pipeline, governance_pipeline, general_pipeline,
        )

        agents = []
        toolsets = []
        seen = set()

        _extract_agents(data_pipeline, None, agents, toolsets, seen, None)
        _extract_agents(governance_pipeline, None, agents, toolsets, seen, None)
        _extract_agents(general_pipeline, None, agents, toolsets, seen, None)
        _append_custom_skill_agents(agents)

        return JSONResponse(content={
            'agents': agents,
            'toolsets': toolsets,
            'pipelines': [
                {'id': data_pipeline.name, 'label': 'Optimization Pipeline (空间优化)', 'color': '#3b82f6'},
                {'id': governance_pipeline.name, 'label': 'Governance Pipeline (数据治理)', 'color': '#f59e0b'},
                {'id': general_pipeline.name, 'label': 'General Pipeline (通用分析)', 'color': '#10b981'},
                {'id': 'CustomSkills', 'label': '自定义技能', 'color': '#a855f7'},
            ],
        })
    except Exception as e:
        logger.error("Agent topology error: %s", e)
        return JSONResponse(content={'error': str(e)}, status_code=500)


def get_topology_routes():
    return [
        Route("/api/agent-topology", endpoint=_api_agent_topology, methods=["GET"]),
    ]

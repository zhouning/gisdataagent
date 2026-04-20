import asyncio
from unittest.mock import patch, MagicMock
from starlette.requests import Request


def _make_request():
    scope = {"type": "http", "method": "GET", "path": "/api/agent-topology",
             "headers": [], "query_string": b"", "path_params": {}}
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}
    return Request(scope, receive=receive)


def test_topology_includes_mentionable_field():
    from data_agent.api.topology_routes import _api_agent_topology
    resp = asyncio.run(_api_agent_topology(_make_request()))
    import json
    data = json.loads(resp.body.decode())
    for a in data["agents"]:
        assert "mentionable" in a
        assert isinstance(a["mentionable"], bool)


def test_topology_includes_pipeline_label():
    from data_agent.api.topology_routes import _api_agent_topology
    resp = asyncio.run(_api_agent_topology(_make_request()))
    import json
    data = json.loads(resp.body.decode())
    for a in data["agents"]:
        assert "pipeline_label" in a


def test_topology_mentionable_matches_sub_agents():
    from data_agent.api.topology_routes import _api_agent_topology
    resp = asyncio.run(_api_agent_topology(_make_request()))
    import json
    data = json.loads(resp.body.decode())
    de = next((a for a in data["agents"] if a["name"] == "DataExploration"), None)
    assert de is not None
    assert de["mentionable"] is True
    pi = next((a for a in data["agents"] if a["name"] == "ParallelDataIngestion"), None)
    if pi is not None:
        assert pi["mentionable"] is False


def test_topology_includes_custom_skills_section():
    from data_agent.api.topology_routes import _api_agent_topology
    fake_custom = [{"id": 1, "skill_name": "MyCustomSkill", "description": "test",
                    "owner_username": "alice", "toolset_names": ["ExplorationToolset"]}]
    with patch("data_agent.api.topology_routes._list_custom_skills_safe", return_value=fake_custom):
        resp = asyncio.run(_api_agent_topology(_make_request()))
    import json
    data = json.loads(resp.body.decode())
    skill_agents = [a for a in data["agents"] if a["type"] == "CustomSkill"]
    assert len(skill_agents) == 1
    assert skill_agents[0]["name"] == "MyCustomSkill"
    assert skill_agents[0]["mentionable"] is True

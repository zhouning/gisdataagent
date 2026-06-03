import asyncio
import json


class FakeWorldModelV21Service:
    def __init__(self):
        self.payload = None
        self.user_id = None

    def status(self):
        return {
            "status": "ready",
            "version": "2.1.0",
            "paper9": {"repo_path": "paper9", "importable": True},
        }

    def run_plan(self, payload, user_id):
        self.payload = payload
        self.user_id = user_id
        return {
            "status": "ok",
            "version": "2.1.0",
            "summary": {
                "steps_run": 50,
                "n_selected": 50,
                "total_reward": 230.75,
            },
            "map_config": {"layers": []},
            "warnings": [],
        }


def test_world_model_v21_status_tool_returns_service_status(monkeypatch):
    from data_agent.toolsets import world_model_v21_tools as tools

    monkeypatch.setattr(
        tools,
        "get_world_model_v21_service",
        lambda: FakeWorldModelV21Service(),
    )

    result = json.loads(tools.world_model_v21_status())

    assert result["status"] == "ready"
    assert result["version"] == "2.1.0"
    assert result["paper9"]["repo_path"] == "paper9"


def test_world_model_v21_plan_tool_normalizes_payload_and_removes_map_config(monkeypatch):
    from data_agent.toolsets import world_model_v21_tools as tools

    fake = FakeWorldModelV21Service()
    monkeypatch.setattr(tools, "get_world_model_v21_service", lambda: fake)

    result = json.loads(
        tools._world_model_v21_plan_sync(
            prepared_dir="prepared",
            ensemble_dir="ensemble",
            env_kind="restoration",
            horizon="2",
            top_k="5",
            n_episodes="1",
            continuation="greedy",
            scoring="reward",
            threads="0",
            seed_offset="0",
            cultivated_area_floor_delta_ha="",
            baimu_area_floor_delta_ha="",
            gamma_conn="",
            delta_conn="",
        )
    )

    assert fake.user_id == "agent_world_model_v21"
    assert fake.payload["prepared_dir"] == "prepared"
    assert fake.payload["ensemble_dir"] == "ensemble"
    assert fake.payload["env_kind"] == "restoration"
    assert fake.payload["horizon"] == 2
    assert fake.payload["top_k"] == 5
    assert fake.payload["n_episodes"] == 1
    assert fake.payload["threads"] == 0
    assert fake.payload["cultivated_area_floor_delta_ha"] is None
    assert result["status"] == "ok"
    assert result["summary"]["steps_run"] == 50
    assert "map_config" not in result


def test_world_model_v21_toolset_lists_status_and_plan_tools():
    from data_agent.toolsets.world_model_v21_tools import WorldModelV21Toolset

    toolset = WorldModelV21Toolset()
    tools = asyncio.run(toolset.get_tools())
    names = {tool.name for tool in tools}

    assert "world_model_v21_status" in names
    assert "world_model_v21_plan" in names


def test_world_model_category_includes_v21_tools():
    from data_agent.tool_filter import TOOL_CATEGORIES

    assert "world_model_v21_status" in TOOL_CATEGORIES["world_model"]
    assert "world_model_v21_plan" in TOOL_CATEGORIES["world_model"]


def test_general_and_analyst_agents_include_world_model_v21_toolset():
    from data_agent.agent import analyst_agent, general_processing_agent

    general_names = [type(toolset).__name__ for toolset in general_processing_agent.tools]
    analyst_names = [type(toolset).__name__ for toolset in analyst_agent.tools]

    assert "WorldModelV21Toolset" in general_names
    assert "WorldModelV21Toolset" in analyst_names

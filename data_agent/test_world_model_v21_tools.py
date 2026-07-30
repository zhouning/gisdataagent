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

    def inspect_resources(self, *, dataset, prepared_dir, ensemble_dir):
        self.payload = {
            "dataset": dataset,
            "prepared_dir": prepared_dir,
            "ensemble_dir": ensemble_dir,
        }
        return {"status": "ready", "planning_ready": True, **self.payload}

    def audit_run(self, *, out_dir, attempt, cultivated_area_floor_delta_ha):
        self.payload = {
            "out_dir": out_dir,
            "attempt": attempt,
            "cultivated_area_floor_delta_ha": cultivated_area_floor_delta_ha,
        }
        return {
            "hard_constraint_passed": True,
            "next_action": "commit_verified_episode",
            **self.payload,
        }

    def recall_verified_episodes(self, *, dataset, limit):
        self.payload = {"dataset": dataset, "limit": limit}
        return {"status": "ok", "count": 0, "episodes": []}

    def commit_verified_episode(self, *, out_dir, dataset, goal, plan_args):
        self.payload = {
            "out_dir": out_dir,
            "dataset": dataset,
            "goal": goal,
            "plan_args": plan_args,
        }
        return {"status": "committed", "episode": {"episode_id": "demo"}}

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

    def run_prepare(self, payload, user_id):
        self.payload = payload
        self.user_id = user_id
        return {
            "status": "ok",
            "mode": "tool1_prepare",
            "prepared_dir": payload.get("prepared_dir") or "prepared",
        }

    def run_sample(self, payload, user_id):
        self.payload = payload
        self.user_id = user_id
        return {
            "status": "ok",
            "mode": "tool2_sample",
            "prepared_dir": payload.get("prepared_dir"),
        }

    def run_train(self, payload, user_id):
        self.payload = payload
        self.user_id = user_id
        return {
            "status": "ok",
            "mode": "tool3_train",
            "ensemble_dir": "prepared/tool3",
            "onnx_member_count": payload.get("n_members", 3),
        }

    def run_pipeline(self, payload, user_id):
        self.payload = payload
        self.user_id = user_id
        return {
            "status": "ok",
            "mode": "pipeline_a_to_d",
            "steps": [{"step": "prepare", "status": "skipped_reused"}],
            "plan_result": {"status": "ok", "map_config": {"layers": []}},
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


def test_paper9_governance_tools_call_service_with_structured_values(monkeypatch):
    from data_agent.toolsets import world_model_v21_tools as tools

    fake = FakeWorldModelV21Service()
    monkeypatch.setattr(tools, "get_world_model_v21_service", lambda: fake)

    inspected = json.loads(tools.paper9_inspect_resources(dataset="东兴"))
    assert inspected["planning_ready"] is True
    assert fake.payload["dataset"] == "dongxing"
    assert fake.payload["prepared_dir"] == "/app/dongxing-runs/prepared"

    recalled = json.loads(tools.paper9_recall_verified_episodes("东兴", "5"))
    assert recalled["count"] == 0
    assert fake.payload == {"dataset": "dongxing", "limit": 5}

    audited = json.loads(tools.paper9_audit_run("/tmp/run", "1", "0"))
    assert audited["hard_constraint_passed"] is True
    assert fake.payload["attempt"] == 1

    committed = json.loads(
        tools.paper9_commit_verified_episode(
            "/tmp/run",
            "东兴",
            "优化耕地布局",
            '{"horizon": 1, "top_k": 1}',
        )
    )
    assert committed["status"] == "committed"
    assert fake.payload["plan_args"] == {"horizon": 1, "top_k": 1}


def test_world_model_v21_plan_tool_normalizes_payload_and_returns_map_update(monkeypatch):
    from data_agent.toolsets import world_model_v21_tools as tools
    from data_agent.user_context import current_user_id

    fake = FakeWorldModelV21Service()
    monkeypatch.setattr(tools, "get_world_model_v21_service", lambda: fake)

    token = current_user_id.set("demo_user")
    try:
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
    finally:
        current_user_id.reset(token)

    assert fake.user_id == "demo_user"
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
    assert result["map_update"] == {"layers": []}
    assert result["map_update_queued"] is True


def test_world_model_v21_plan_normalizes_common_env_kind_typo(monkeypatch):
    from data_agent.toolsets import world_model_v21_tools as tools

    fake = FakeWorldModelV21Service()
    monkeypatch.setattr(tools, "get_world_model_v21_service", lambda: fake)

    result = json.loads(tools._world_model_v21_plan_sync(env_kind="rest_oration"))

    assert result["status"] == "ok"
    assert fake.payload["env_kind"] == "restoration"


def test_world_model_v21_plan_uses_demo_defaults_and_env_paths(monkeypatch):
    from data_agent.toolsets import world_model_v21_tools as tools

    fake = FakeWorldModelV21Service()
    monkeypatch.setattr(tools, "get_world_model_v21_service", lambda: fake)
    monkeypatch.setenv("PAPER9_FARMLAND_MPC_DEFAULT_PREPARED_DIR", "/app/bishan-runs/prepared")
    monkeypatch.setenv(
        "PAPER9_FARMLAND_MPC_DEFAULT_ENSEMBLE_DIR",
        "/app/bishan-runs/prepared/ensemble_seed0",
    )

    result = json.loads(tools._world_model_v21_plan_sync())

    assert result["status"] == "ok"
    assert fake.payload["prepared_dir"] == "/app/bishan-runs/prepared"
    assert fake.payload["ensemble_dir"] == "/app/bishan-runs/prepared/ensemble_seed0"
    assert fake.payload["env_kind"] == "county"
    assert fake.payload["horizon"] == 1
    assert fake.payload["top_k"] == 1
    assert fake.payload["n_episodes"] == 1
    assert fake.payload["continuation"] == "greedy"
    assert fake.payload["scoring"] == "reward"
    assert fake.payload["threads"] == 0


def test_world_model_v21_pipeline_uses_demo_defaults_and_env_paths(monkeypatch):
    from data_agent.toolsets import world_model_v21_tools as tools

    fake = FakeWorldModelV21Service()
    monkeypatch.setattr(tools, "get_world_model_v21_service", lambda: fake)
    monkeypatch.setenv("PAPER9_FARMLAND_MPC_DEFAULT_PREPARED_DIR", "/app/bishan-runs/prepared")
    monkeypatch.setenv(
        "PAPER9_FARMLAND_MPC_DEFAULT_ENSEMBLE_DIR",
        "/app/bishan-runs/prepared/ensemble_seed0",
    )

    result = json.loads(tools._world_model_v21_pipeline_sync())

    assert result["status"] == "ok"
    assert fake.payload["prepared_dir"] == "/app/bishan-runs/prepared"
    assert fake.payload["ensemble_dir"] == "/app/bishan-runs/prepared/ensemble_seed0"
    assert fake.payload["reuse_existing"] is True
    assert fake.payload["run_prepare"] is True
    assert fake.payload["run_sample"] is True
    assert fake.payload["run_train"] is True
    assert fake.payload["run_plan"] is True
    assert fake.payload["horizon"] == 1
    assert fake.payload["top_k"] == 1
    assert fake.payload["continuation"] == "greedy"
    assert fake.payload["cultivated_area_floor_delta_ha"] == 0.0
    assert fake.payload["baimu_area_floor_delta_ha"] is None


def test_world_model_v21_pipeline_forwards_planning_constraints(monkeypatch):
    from data_agent.toolsets import world_model_v21_tools as tools

    fake = FakeWorldModelV21Service()
    monkeypatch.setattr(tools, "get_world_model_v21_service", lambda: fake)

    result = json.loads(
        tools._world_model_v21_pipeline_sync(
            cultivated_area_floor_delta_ha="1.25",
            baimu_area_floor_delta_ha="2.5",
            gamma_conn="3.5",
            delta_conn="4.5",
        )
    )

    assert result["status"] == "ok"
    assert fake.payload["cultivated_area_floor_delta_ha"] == 1.25
    assert fake.payload["baimu_area_floor_delta_ha"] == 2.5
    assert fake.payload["gamma_conn"] == 3.5
    assert fake.payload["delta_conn"] == 4.5


def test_world_model_v21_pipeline_cannot_lower_cultivated_area_floor(monkeypatch):
    from data_agent.toolsets import world_model_v21_tools as tools

    fake = FakeWorldModelV21Service()
    monkeypatch.setattr(tools, "get_world_model_v21_service", lambda: fake)

    result = json.loads(
        tools._world_model_v21_pipeline_sync(
            cultivated_area_floor_delta_ha="-100",
        )
    )

    assert result["status"] == "ok"
    assert fake.payload["cultivated_area_floor_delta_ha"] == 0.0


def test_world_model_v21_pipeline_dataset_dongxing_overrides_bishan_env(monkeypatch):
    from data_agent.toolsets import world_model_v21_tools as tools

    fake = FakeWorldModelV21Service()
    monkeypatch.setattr(tools, "get_world_model_v21_service", lambda: fake)
    monkeypatch.setenv("PAPER9_FARMLAND_MPC_DEFAULT_PREPARED_DIR", "/app/bishan-runs/prepared")
    monkeypatch.setenv(
        "PAPER9_FARMLAND_MPC_DEFAULT_ENSEMBLE_DIR",
        "/app/bishan-runs/prepared/ensemble_seed0",
    )

    result = json.loads(tools._world_model_v21_pipeline_sync(dataset="dongxing"))

    assert result["status"] == "ok"
    assert fake.payload["dataset"] == "dongxing"
    assert fake.payload["prepared_dir"] == "/app/dongxing-runs/prepared"
    assert fake.payload["ensemble_dir"] == "/app/dongxing-runs/prepared/ensemble_seed0"


def test_world_model_v21_plan_dataset_dongxing_overrides_bishan_env(monkeypatch):
    from data_agent.toolsets import world_model_v21_tools as tools

    fake = FakeWorldModelV21Service()
    monkeypatch.setattr(tools, "get_world_model_v21_service", lambda: fake)
    monkeypatch.setenv("PAPER9_FARMLAND_MPC_DEFAULT_PREPARED_DIR", "/app/bishan-runs/prepared")
    monkeypatch.setenv(
        "PAPER9_FARMLAND_MPC_DEFAULT_ENSEMBLE_DIR",
        "/app/bishan-runs/prepared/ensemble_seed0",
    )

    result = json.loads(tools._world_model_v21_plan_sync(dataset="东兴"))

    assert result["status"] == "ok"
    assert fake.payload["dataset"] == "dongxing"
    assert fake.payload["prepared_dir"] == "/app/dongxing-runs/prepared"
    assert fake.payload["ensemble_dir"] == "/app/dongxing-runs/prepared/ensemble_seed0"


def test_world_model_v21_prepare_sample_train_pipeline_tools_call_service(monkeypatch):
    from data_agent.toolsets import world_model_v21_tools as tools
    from data_agent.user_context import current_user_id

    fake = FakeWorldModelV21Service()
    monkeypatch.setattr(tools, "get_world_model_v21_service", lambda: fake)
    token = current_user_id.set("demo_user")
    try:
        prepared = json.loads(tools._world_model_v21_prepare_sync(
            dltb_path="/data/dltb.shp",
            dem_path="/data/dem.tif",
            prepared_dir="/out/prepared",
        ))
        assert prepared["mode"] == "tool1_prepare"
        assert fake.user_id == "demo_user"
        assert fake.payload["dltb_path"] == "/data/dltb.shp"

        sampled = json.loads(tools._world_model_v21_sample_sync(
            prepared_dir="/out/prepared",
            n_transition_episodes="2",
        ))
        assert sampled["mode"] == "tool2_sample"
        assert fake.payload["n_transition_episodes"] == 2

        trained = json.loads(tools._world_model_v21_train_sync(
            prepared_dir="/out/prepared",
            n_members="1",
            epochs="1",
        ))
        assert trained["mode"] == "tool3_train"
        assert fake.payload["n_members"] == 1

        piped = json.loads(tools._world_model_v21_pipeline_sync(
            prepared_dir="/out/prepared",
            ensemble_dir="/out/ensemble",
            run_prepare="false",
            run_sample="false",
            run_train="false",
        ))
        assert piped["mode"] == "pipeline_a_to_d"
        assert fake.payload["run_prepare"] is False
    finally:
        current_user_id.reset(token)


def test_world_model_v21_toolset_lists_all_v21_tools():
    from data_agent.toolsets.world_model_v21_tools import WorldModelV21Toolset

    toolset = WorldModelV21Toolset()
    tools = asyncio.run(toolset.get_tools())
    names = {tool.name for tool in tools}

    assert "world_model_v21_status" in names
    assert "world_model_v21_prepare" in names
    assert "world_model_v21_sample" in names
    assert "world_model_v21_train" in names
    assert "world_model_v21_plan" in names
    assert "world_model_v21_pipeline" in names
    assert "paper9_inspect_resources" in names
    assert "paper9_recall_verified_episodes" in names
    assert "paper9_audit_run" in names
    assert "paper9_commit_verified_episode" in names
    assert len(names) == 10


def test_world_model_category_includes_v21_tools():
    from data_agent.tool_filter import TOOL_CATEGORIES

    assert "world_model_v21_status" in TOOL_CATEGORIES["world_model"]
    assert "world_model_v21_prepare" in TOOL_CATEGORIES["world_model"]
    assert "world_model_v21_sample" in TOOL_CATEGORIES["world_model"]
    assert "world_model_v21_train" in TOOL_CATEGORIES["world_model"]
    assert "world_model_v21_plan" in TOOL_CATEGORIES["world_model"]
    assert "world_model_v21_pipeline" in TOOL_CATEGORIES["world_model"]
    assert "paper9_inspect_resources" in TOOL_CATEGORIES["world_model"]
    assert "paper9_recall_verified_episodes" in TOOL_CATEGORIES["world_model"]
    assert "paper9_audit_run" in TOOL_CATEGORIES["world_model"]
    assert "paper9_commit_verified_episode" in TOOL_CATEGORIES["world_model"]


def test_world_model_category_includes_twm_tools():
    from data_agent.tool_filter import TOOL_CATEGORIES

    expected = {
        "twm_status",
        "twm_create_project",
        "twm_build_state",
        "twm_evaluate_rules",
        "twm_generate_audit_report",
        "twm_forecast",
        "twm_list_rule_hits",
    }

    assert expected.issubset(TOOL_CATEGORIES["world_model"])


def test_general_and_analyst_agents_include_world_model_toolsets():
    from data_agent.agent import analyst_agent, general_processing_agent

    general_names = [type(toolset).__name__ for toolset in general_processing_agent.tools]
    analyst_names = [type(toolset).__name__ for toolset in analyst_agent.tools]

    assert "WorldModelV21Toolset" in general_names
    assert "WorldModelV21Toolset" in analyst_names
    assert "TerritoryWorldModelToolset" in general_names
    assert "TerritoryWorldModelToolset" in analyst_names


def test_world_model_v21_agent_is_directly_mentionable():
    from data_agent.agent import _make_agent_by_name

    agent = _make_agent_by_name("WorldModelV21")
    toolset_names = [type(toolset).__name__ for toolset in agent.tools]

    assert agent.name == "MentionWorldModelV21"
    assert toolset_names == ["WorldModelV21Toolset"]


def test_world_model_v21_agent_instruction_uses_fast_defaults():
    from data_agent.agent import _make_agent_by_name

    agent = _make_agent_by_name("WorldModelV21")
    instruction = agent.instruction

    assert "horizon=1, top_k=1" in instruction
    assert "horizon=2, top_k=5" not in instruction
    assert "默认调用 world_model_v21_pipeline" in instruction
    assert "只有用户明确要求“只运行 Tool 4”" in instruction
    assert "dataset='dongxing'" in instruction
    assert "dataset='bishan'" in instruction
    assert "CHG_FLAG" in instruction
    assert "红色为耕地 -> 林地" in instruction
    assert "paper9_inspect_resources" in instruction
    assert "paper9_audit_run" in instruction
    assert "paper9_commit_verified_episode" in instruction
    assert "只允许再调用一次" in instruction
    assert "算法版本 2.2.3" in instruction
    assert "首次 pipeline 必须设置 cultivated_area_floor_delta_ha='0'" in instruction


def test_territory_world_model_agent_is_directly_mentionable():
    from data_agent.agent import _make_agent_by_name

    agent = _make_agent_by_name("TerritoryWorldModel")
    toolset_names = [type(toolset).__name__ for toolset in agent.tools]

    assert agent.name == "MentionTerritoryWorldModel"
    assert toolset_names == ["TerritoryWorldModelToolset"]
    assert "twm_*" in agent.instruction

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from data_agent.api.uwm_multistage_intervention_routes import (
    get_uwm_multistage_intervention_routes,
)
from data_agent.uwm.multistage_intervention_planner import (
    MultiStageInterventionPlannerService,
)
from data_agent.uwm.multistage_intervention_planner.chat_flow import (
    format_scenario_parse,
    format_state_inspection,
    is_multistage_uwm_chat_message,
)
from data_agent.uwm.multistage_intervention_planner.scenario_parser import (
    parse_uwm_scenario,
)


ROOT = Path(__file__).resolve().parents[1]


def test_multistage_planner_retrains_and_changes_second_action_ranking(tmp_path: Path) -> None:
    service = MultiStageInterventionPlannerService(root=ROOT, run_root=tmp_path)

    run = service.plan({})

    assert run["schema"] == "uwm.multistage_intervention_run.v1"
    assert run["training_summary"]["transition_count"] == 6817
    assert run["training_summary"]["retrained_for_run"] is True
    assert run["candidate_action_summary"]["candidate_action_count"] == 9
    assert [
        action["action_id"] for action in run["selected_sequence"]["action_sequence"]
    ] == [
        "increase_green_infrastructure-沙坪坝区|石井坡街道|793",
        "add_community_service-沙坪坝区|石井坡街道|793",
    ]
    dependency = run["state_dependency_diagnostic"]
    assert dependency["state_update_changes_second_step_ranking"] is True
    assert dependency["state_update_changes_top_second_action"] is True
    assert dependency["top_second_action_without_state_update"] == (
        "increase_green_infrastructure-沙坪坝区|渝碚路街道|791"
    )
    assert dependency["top_second_action_after_state_update"] == (
        "add_community_service-沙坪坝区|石井坡街道|793"
    )
    assert dependency["ranking_before_state_update"][0]["target_unit_id"] == "沙坪坝区|渝碚路街道|791"
    assert dependency["ranking_after_state_update"][0]["target_unit_id"] == "沙坪坝区|石井坡街道|793"
    assert run["planner_search_summary"]["evaluated_imagined_action_count"] == 73
    assert run["planner_search_summary"]["completed_sequence_count"] == 64
    assert run["decision_story"]["headline"] == "世界状态更新改变了下一步决策"
    assert run["training_transparency"]["training_required"] is True
    assert run["training_transparency"]["coefficient_count"] == 138
    assert run["training_transparency"]["deep_neural_world_model_claim"] is False
    assert run["runtime_profile"]["dynamics_training_ms"] > 0
    assert run["baselines"]["advantages"]["over_multi_step_without_state_update"] > 0
    ablation_rows = run["baselines"]["validated_action_ablation_benchmark"]["baseline_rows"]
    assert {row["policy_baseline"] for row in ablation_rows} >= {
        "no_action_signal_world_model_policy",
        "shuffled_action_signal_world_model_policy",
    }
    assert run["observed_policy_outcome_superiority_claim"] is False
    assert run["empirical_superiority_claim"] is False


def test_multistage_run_is_persisted_and_map_ready(tmp_path: Path) -> None:
    service = MultiStageInterventionPlannerService(root=ROOT, run_root=tmp_path)

    run = service.plan({})
    persisted = service.get_run(run["run_id"])
    map_update = service.get_map(run["run_id"])

    assert persisted["audit"]["request_digest"] == run["audit"]["request_digest"]
    assert persisted["audit"]["state_update_verified"] is True
    assert map_update["schema"] == "map_update.v1"
    assert map_update["metadata"]["fit_bounds"] is True
    assert len(map_update["layers"]) >= 4
    assert {layer["style"]["color"] for layer in map_update["layers"]} >= {
        "#dc2626",
        "#7c3aed",
    }
    assert set(persisted["map_scenes"]) == {"t0", "t1", "branch", "t2"}
    assert len(persisted["map_scenes"]["branch"]["layers"]) == 2


def test_multistage_api_and_frontend_contract() -> None:
    paths = {route.path for route in get_uwm_multistage_intervention_routes()}
    assert paths == {
        "/api/uwm/multistage-intervention/overview",
        "/api/uwm/multistage-intervention/actions",
        "/api/uwm/multistage-intervention/plan",
        "/api/uwm/multistage-intervention/runs/{run_id}",
        "/api/uwm/multistage-intervention/runs/{run_id}/map",
    }
    data_panel = (ROOT / "frontend/src/components/DataPanel.tsx").read_text(encoding="utf-8")
    page = (
        ROOT / "frontend/src/components/datapanel/UwmMultistageInterventionTab.tsx"
    ).read_text(encoding="utf-8")
    assert "UWM多阶段城市干预规划" in data_panel
    assert "/api/uwm/multistage-intervention/plan" in page
    assert "window.__handleMapUpdate" in page
    assert "第二步分叉" in page
    assert "第二步候选排名真的发生了变化" in page
    assert "当前模型等级" in page
    assert "不是1,137种政策" in page
    assert "展开查看全部23个输入字段" in page
    assert "参数量核对" in page
    assert "138" not in page


def test_multistage_overview_explains_data_actions_and_model_shape() -> None:
    service = MultiStageInterventionPlannerService(root=ROOT)

    overview = service.overview()

    foundation = overview["data_foundation"]
    assert foundation["joined_admin_count"] == 1017
    assert foundation["service_matched_admin_count"] == 1017
    assert len(foundation["data_layers"]) == 5
    assert "模拟器回放" in foundation["evidence_note"]

    catalog = overview["action_catalog"]
    assert catalog["template_count"] == 3
    assert catalog["instance_count"] == 1137
    assert "不是1137种不同政策" in catalog["instance_definition"]
    assert {row["action_type"]: row["instance_count"] for row in catalog["rows"]} == {
        "increase_green_infrastructure": 81,
        "traffic_emission_control": 77,
        "add_community_service": 979,
    }
    assert all(len(row["examples"]) == 3 for row in catalog["rows"])

    simulator = overview["simulator_specification"]
    assert simulator["input_dimension"] == 23
    assert simulator["output_dimension"] == 6
    assert simulator["coefficient_matrix_shape"] == [23, 6]
    assert simulator["coefficient_count"] == 138
    assert simulator["extra_intercept_count"] == 0
    assert sum(group["dimension"] for group in simulator["input_groups"]) == 23
    assert len(simulator["input_features"]) == 23
    assert len(simulator["output_targets"]) == 6
    assert "136不是当前实现" in simulator["parameter_explanation"]


def test_multistage_chat_inspects_state_before_training_or_planning() -> None:
    service = MultiStageInterventionPlannerService(root=ROOT)

    inspection = service.inspect_state({})

    assert inspection["schema"] == "uwm.multistage_intervention_state_inspection.v1"
    assert inspection["state_snapshot"]["unit_count"] == 6
    assert inspection["state_snapshot"]["state_dimension_count"] == 5
    assert inspection["candidate_action_summary"]["candidate_action_count"] == 9
    assert inspection["candidate_action_summary"]["action_type_counts"] == {
        "add_community_service": 5,
        "increase_green_infrastructure": 2,
        "traffic_emission_control": 2,
    }
    assert inspection["execution_status"] == {
        "simulator_trained": False,
        "future_rollout_executed": False,
        "planner_executed": False,
        "message": "当前仅检查输入状态；尚未训练Simulator，也未进行未来推演。",
    }
    assert inspection["map_update"]["metadata"]["future_rollout_executed"] is False
    assert len(inspection["map_update"]["layers"]) == 1
    assert len(inspection["map_update"]["layers"][0]["geojsonData"]["features"]) == 6
    summary = format_state_inspection(inspection)
    assert "尚未训练Simulator" in summary
    assert "当前输入UWM的状态" in summary
    assert "23维输入 → 6维下一状态变化" in summary
    assert is_multistage_uwm_chat_message("@UWM规划 请进行多阶段城市干预规划")
    assert not is_multistage_uwm_chat_message("帮我做普通地图查询")


def test_gemma4_scenario_parser_resolves_real_area_and_constraints() -> None:
    service = MultiStageInterventionPlannerService(root=ROOT)
    model_json = """{
      "intent": "UWM_MULTISTAGE_PLANNING",
      "county": "沙坪坝区",
      "township": "石井坡街道",
      "neighborhood_hops": 2,
      "horizon": 3,
      "action_types": ["add_community_service"],
      "excluded_action_types": ["traffic_emission_control"],
      "objectives": ["改善公共服务可达性", "提升公平性"],
      "uncertainty_preference": "conservative",
      "explicit_constraints": ["不考虑交通排放治理"],
      "missing_information": [],
      "summary": "在石井坡街道及周边优先改善公共服务。"
    }"""
    with patch(
        "data_agent.uwm.multistage_intervention_planner.scenario_parser._get_router_model",
        return_value="gemma4-26b-ollama",
    ), patch(
        "data_agent.uwm.multistage_intervention_planner.scenario_parser._route_via_litellm",
        return_value=(model_json, 120, 80),
    ) as model_call:
        parsed = parse_uwm_scenario(
            "@UWM规划 在沙坪坝区石井坡街道规划3步，只补公共服务，不考虑交通治理",
            service,
        )

    model_call.assert_called_once()
    assert parsed["model_called"] is True
    assert parsed["model"] == "gemma4-26b-ollama"
    assert parsed["resolution"]["focus_unit"] == "沙坪坝区|石井坡街道|793"
    assert parsed["planning_request"]["neighborhood_hops"] == 2
    assert parsed["planning_request"]["action_types"] == ["add_community_service"]
    assert parsed["planning_request"]["uncertainty_penalty"] == 1.0
    assert parsed["interpretation"]["horizon"] == 3
    assert parsed["audit_summary"]["model"] == "gemma4-26b-ollama"
    assert parsed["audit_summary"]["resolved_focus_unit"] == "沙坪坝区|石井坡街道|793"
    summary = format_scenario_parse(parsed)
    assert "Gemma4场景语义解析" in summary
    assert "已真实调用" in summary
    assert "沙坪坝区 · 石井坡街道" in summary


def test_gemma4_scenario_parser_uses_visible_defaults_without_inventing_area() -> None:
    service = MultiStageInterventionPlannerService(root=ROOT)
    model_json = """{
      "intent": "UWM_MULTISTAGE_PLANNING",
      "county": null,
      "township": null,
      "neighborhood_hops": null,
      "horizon": null,
      "action_types": [],
      "excluded_action_types": ["traffic_emission_control"],
      "objectives": [],
      "uncertainty_preference": "balanced",
      "explicit_constraints": ["不考虑交通治理"],
      "missing_information": [],
      "summary": "先查看当前状态，再规划。"
    }"""
    with patch(
        "data_agent.uwm.multistage_intervention_planner.scenario_parser._get_router_model",
        return_value="gemma4-26b-ollama",
    ), patch(
        "data_agent.uwm.multistage_intervention_planner.scenario_parser._route_via_litellm",
        return_value=(model_json, 100, 60),
    ):
        parsed = parse_uwm_scenario("@UWM规划 请先展示状态", service)

    assert parsed["resolution"]["used_default"] is True
    assert parsed["planning_request"]["focus_unit"] == "沙坪坝区|土湾街道|975"
    assert parsed["planning_request"]["action_types"] == [
        "increase_green_infrastructure",
        "add_community_service",
    ]


def test_multistage_chainlit_chat_contract() -> None:
    app = (ROOT / "data_agent/app.py").read_text(encoding="utf-8")
    assert "uwm_multistage_state_inspection" in app
    assert "确认2步推演" in app
    assert "改为3步推演" in app
    assert "uwm_multistage_scene" in app
    assert "查看第二步分叉" in app
    assert "uwm_multistage_audit" in app
    assert "parse_uwm_scenario" in app
    assert "正在调用本机Gemma4解析" in app
    assert "系统不会静默套用默认场景" in app

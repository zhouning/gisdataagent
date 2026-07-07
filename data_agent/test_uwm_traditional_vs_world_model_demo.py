import json
from pathlib import Path

from data_agent.uwm.traditional_livability_baseline import (
    UWM_TRADITIONAL_LIVABILITY_BASELINE_SCHEMA,
    build_traditional_livability_baseline,
)
from data_agent.uwm.traditional_vs_world_model_demo import (
    UWM_TRADITIONAL_VS_WORLD_MODEL_DEMO_SCHEMA,
    build_traditional_vs_world_model_demo,
)


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data/uwm_public_proxy/chongqing_central"


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _build_traditional() -> dict:
    return build_traditional_livability_baseline(
        baseline_id="uwm-traditional-livability-baseline-real-data-test",
        created_at="2026-07-07T15:00:00Z",
        multisource_livability_scene=_read_json(
            DATA_ROOT
            / "multisource_livability_scene_2026_07_06/uwm_multisource_livability_scene.json"
        ),
    )


def _build_demo() -> dict:
    return build_traditional_vs_world_model_demo(
        demo_id="uwm-traditional-vs-world-model-demo-real-data-test",
        created_at="2026-07-07T15:10:00Z",
        multisource_livability_scene=_read_json(
            DATA_ROOT
            / "multisource_livability_scene_2026_07_06/uwm_multisource_livability_scene.json"
        ),
        traditional_livability_baseline=_build_traditional(),
        uwm_livability_decision_package=_read_json(
            DATA_ROOT
            / "livability_decision_package_2026_07_07/uwm_livability_decision_package.json"
        ),
    )


def test_traditional_livability_baseline_outputs_static_ranking_on_same_scene():
    baseline = _build_traditional()

    assert baseline["schema"] == UWM_TRADITIONAL_LIVABILITY_BASELINE_SCHEMA
    assert baseline["baseline_method"] == (
        "static_indicator_weighted_ranking_without_world_model"
    )
    assert baseline["admin_unit_count"] == 36
    assert baseline["data_scene_id"] == "uwm-multisource-livability-scene-2026-07-06"
    assert baseline["simulator_used"] is False
    assert baseline["planner_used"] is False
    assert baseline["counterfactual_output_available"] is False
    assert baseline["final_output_type"] == "static_problem_ranking"
    assert baseline["top_priority_units"][:2] == [
        "九龙坡区|九龙镇|77",
        "南岸区|南坪镇|299",
    ]
    assert baseline["static_action_recommendation"]["action_count"] == 2
    assert baseline["observed_policy_outcome_superiority_claim"] is False


def test_side_by_side_demo_shows_uwm_outputs_traditional_method_cannot():
    demo = _build_demo()

    assert demo["schema"] == UWM_TRADITIONAL_VS_WORLD_MODEL_DEMO_SCHEMA
    assert demo["shared_data_contract"] == {
        "scene_id": "uwm-multisource-livability-scene-2026-07-06",
        "admin_unit_count": 36,
        "same_data_basis": True,
        "same_livability_scenario": True,
    }

    traditional = demo["traditional_method_output"]
    assert traditional["final_output_type"] == "static_problem_ranking"
    assert traditional["top_priority_units"][:2] == [
        "九龙坡区|九龙镇|77",
        "南岸区|南坪镇|299",
    ]
    assert traditional["counterfactual_output_available"] is False

    uwm = demo["uwm_output"]
    assert uwm["final_output_type"] == "counterfactual_decision_package"
    assert uwm["target_units"] == [
        "江北区|观音桥街道|653",
        "九龙坡区|九龙镇|77",
    ]
    assert uwm["counterfactual_output_available"] is True
    assert uwm["endpoint_aligned_advantage_over_static"] == 0.0007457
    assert uwm["risk_adjusted_advantage_over_static"] == 0.012777213
    assert uwm["neighbor_livability_delta_advantage"] == 0.272680076
    assert uwm["empirical_p_value_vs_single_action_baselines"] == 0.002809
    assert uwm["trained_model_based_rl_ready"] is True
    assert uwm["trained_model_based_rl_algorithm"] == "dyna_q_tabular_model_based_rl"
    assert uwm["trained_model_based_rl_advantage_over_static"] > 0
    assert uwm["trained_graph_drl_ready"] is True
    assert uwm["trained_graph_drl_algorithm"] == "graph_dqn_fitted_q_model_based_rl"
    assert uwm["trained_graph_drl_advantage_over_static"] > 0

    assert "counterfactual_state_delta" in demo["capability_delta"]["uwm_only_outputs"]
    assert "multi_step_action_sequence" in demo["capability_delta"]["uwm_only_outputs"]
    assert "risk_adjusted_planning_evidence" in demo["capability_delta"]["uwm_only_outputs"]
    assert "trained_model_based_rl_policy_evidence" in demo["capability_delta"]["uwm_only_outputs"]
    assert "trained_graph_drl_value_network_evidence" in demo["capability_delta"]["uwm_only_outputs"]
    assert demo["claim_boundary"]["max_claim_level"] == "bounded_support"
    assert demo["observed_policy_outcome_superiority_claim"] is False

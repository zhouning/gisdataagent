import json
from pathlib import Path

from data_agent.uwm.livability_graph_mdp_env import (
    LIVABILITY_GRAPH_MDP_ENV_SCHEMA,
    build_livability_graph_mdp_env,
)
from data_agent.uwm.livability_rl_training import (
    UWM_LIVABILITY_RL_TRAINING_REPORT_SCHEMA,
    train_livability_model_based_q_agent,
)
from data_agent.uwm.model_based_rl import build_admin_livability_graph_observation


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data/uwm_public_proxy/chongqing_central"
ADMIN_GRAPH_PATH = (
    DATA_ROOT
    / "admin_spatial_graph_2026_07_05/uwm_admin_spatial_adjacency_graph.json"
)
ADMIN_PANEL_PATH = (
    DATA_ROOT
    / "admin_livability_target_2024_07_2026_07_05/uwm_admin_livability_target_panel.json"
)
MECHANISM_TABLE_PATH = (
    DATA_ROOT
    / "data_calibrated_mechanism_table_2026_07_06/uwm_data_calibrated_mechanism_table.json"
)
SPATIAL_KERNEL_PATH = (
    DATA_ROOT
    / "data_calibrated_spatial_spillover_kernel_2026_07_07/uwm_data_calibrated_spatial_spillover_kernel.json"
)
SCENE_AIR_QUALITY_HOLDOUT_PATH = (
    DATA_ROOT
    / "scene_aligned_gridded_air_quality_holdout_2026_07_06/uwm_scene_aligned_gridded_air_quality_holdout.json"
)


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _observation() -> dict:
    return build_admin_livability_graph_observation(
        _load_json(ADMIN_PANEL_PATH),
        observation_id="admin-livability-real-data-graph-mdp-rl-test",
        created_at="2026-07-07T15:00:00Z",
        max_units=36,
        admin_spatial_graph=_load_json(ADMIN_GRAPH_PATH),
    )


def _scenario() -> dict:
    return {
        "scenario_id": "real_data_graph_mdp_rl_heat_pollution_service_stress",
        "heat_stress_multiplier": 1.2,
        "air_pollution_stress_multiplier": 1.15,
        "vulnerability_multiplier": 1.1,
    }


def test_livability_graph_mdp_env_steps_real_simulator_with_spatial_kernel():
    env = build_livability_graph_mdp_env(
        _observation(),
        action_types=[
            "increase_green_infrastructure",
            "traffic_emission_control",
            "add_community_service",
        ],
        scenario=_scenario(),
        horizon=2,
        thresholds={
            "heat_risk": 0.7,
            "air_pollution_exposure": 0.6,
            "service_accessibility": 0.5,
        },
        mechanism_table=_load_json(MECHANISM_TABLE_PATH),
        spatial_spillover_kernel=_load_json(SPATIAL_KERNEL_PATH),
        air_quality_uncertainty_context=_load_json(SCENE_AIR_QUALITY_HOLDOUT_PATH),
    )

    reset = env.reset()
    assert env.metadata["schema"] == LIVABILITY_GRAPH_MDP_ENV_SCHEMA
    assert env.metadata["real_data_sources"]["admin_unit_count"] == 36
    assert env.metadata["real_data_sources"]["admin_spatial_edge_count"] == 96
    assert env.metadata["real_data_sources"]["available_action_count"] == 60
    assert env.metadata["real_data_sources"]["spatial_spillover_directional_edge_count"] == 227
    assert reset["state"]["step_index"] == 0
    assert reset["state"]["remaining_horizon"] == 2
    assert len(reset["action_mask"]) == 60

    first_action_index = next(
        index
        for index, action in enumerate(env.available_actions)
        if action["action_type"] == "traffic_emission_control"
    )
    step = env.step(first_action_index)

    assert step["reward"] < 0
    assert step["done"] is False
    assert step["state"]["step_index"] == 1
    assert step["transition"]["action"]["action_type"] == "traffic_emission_control"
    assert step["transition"]["reward_components"]["livability_delta"] > 0
    assert step["transition"]["reward_components"]["air_pollution_exposure_delta"] < 0
    assert step["transition"]["reward_components"]["uncertainty_penalty"] > 0
    assert step["transition"]["simulator_mechanism_sources"] == [
        "data_calibrated_mechanism_table",
        "data_calibrated_spatial_spillover_kernel",
    ]
    assert "apply_spatial_spillover_kernel" in step["transition"][
        "simulator_trace_steps"
    ]
    assert env.metadata["observed_policy_outcome_superiority_claim"] is False


def test_real_data_model_based_q_training_beats_static_without_policy_outcome_claim():
    env = build_livability_graph_mdp_env(
        _observation(),
        action_types=[
            "increase_green_infrastructure",
            "traffic_emission_control",
            "add_community_service",
        ],
        scenario=_scenario(),
        horizon=2,
        thresholds={
            "heat_risk": 0.7,
            "air_pollution_exposure": 0.6,
            "service_accessibility": 0.5,
        },
        mechanism_table=_load_json(MECHANISM_TABLE_PATH),
        spatial_spillover_kernel=_load_json(SPATIAL_KERNEL_PATH),
        air_quality_uncertainty_context=_load_json(SCENE_AIR_QUALITY_HOLDOUT_PATH),
    )

    report = train_livability_model_based_q_agent(
        env,
        report_id="uwm-livability-real-data-model-based-q-training-test",
        created_at="2026-07-07T15:05:00Z",
        episodes=160,
        seed=20260707,
        learning_rate=0.35,
        discount_factor=0.9,
        epsilon_start=0.75,
        epsilon_end=0.05,
        planning_updates_per_step=8,
    )

    assert report["schema"] == UWM_LIVABILITY_RL_TRAINING_REPORT_SCHEMA
    assert report["rl_algorithm"]["algorithm"] == "dyna_q_tabular_model_based_rl"
    assert report["training_summary"]["episode_count"] == 160
    assert report["training_summary"]["real_data_graph_node_count"] == 36
    assert report["training_summary"]["real_data_available_action_count"] == 60
    assert report["training_summary"]["spatial_spillover_directional_edge_count"] == 227
    assert report["training_curve"]["last_20_mean_reward"] > report[
        "training_curve"
    ]["first_20_mean_reward"]
    assert report["learned_policy_evaluation"][
        "learned_policy_cumulative_reward"
    ] > report["baseline_evaluation"]["traditional_static_cumulative_reward"]
    assert report["learned_policy_evaluation"][
        "advantage_over_traditional_static"
    ] > 0
    assert report["learned_policy_evaluation"]["action_count"] == 2
    assert report["learned_policy_evaluation"]["uses_spatial_spillover_kernel"] is True
    assert report["supported_claim"] == (
        "trained_model_based_q_agent_improves_same_scene_static_livability_baseline"
    )
    assert report["observed_policy_outcome_superiority_claim"] is False
    assert report["empirical_superiority_claim"] is False
    assert "observed_policy_outcome_holdout_required" in report["remaining_gates"]

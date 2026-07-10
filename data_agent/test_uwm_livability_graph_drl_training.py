import json
from pathlib import Path

from data_agent.uwm.livability_graph_drl import (
    GRAPH_NODE_FEATURE_NAMES,
    UWM_LIVABILITY_GRAPH_DRL_TRAINING_REPORT_SCHEMA,
    train_livability_graph_dqn_agent,
)
from data_agent.uwm.livability_graph_mdp_env import build_livability_graph_mdp_env
from data_agent.uwm.model_based_rl import build_admin_livability_graph_observation


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data/uwm_public_proxy/chongqing_central"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _env():
    observation = build_admin_livability_graph_observation(
        _load_json(
            DATA_ROOT
            / "admin_livability_target_2024_07_2026_07_05/uwm_admin_livability_target_panel.json"
        ),
        observation_id="admin-livability-real-data-graph-drl-test",
        created_at="2026-07-07T16:10:00Z",
        max_units=36,
        admin_spatial_graph=_load_json(
            DATA_ROOT
            / "admin_spatial_graph_2026_07_05/uwm_admin_spatial_adjacency_graph.json"
        ),
    )
    return build_livability_graph_mdp_env(
        observation,
        action_types=[
            "increase_green_infrastructure",
            "traffic_emission_control",
            "add_community_service",
        ],
        scenario={
            "scenario_id": "real_data_graph_drl_heat_pollution_service_stress",
            "heat_stress_multiplier": 1.2,
            "air_pollution_stress_multiplier": 1.15,
            "vulnerability_multiplier": 1.1,
        },
        horizon=2,
        thresholds={
            "heat_risk": 0.7,
            "air_pollution_exposure": 0.6,
            "service_accessibility": 0.5,
        },
        mechanism_table=_load_json(
            DATA_ROOT
            / "data_calibrated_mechanism_table_2026_07_06/uwm_data_calibrated_mechanism_table.json"
        ),
        spatial_spillover_kernel=_load_json(
            DATA_ROOT
            / "data_calibrated_spatial_spillover_kernel_2026_07_07/uwm_data_calibrated_spatial_spillover_kernel.json"
        ),
        air_quality_uncertainty_context=_load_json(
            DATA_ROOT
            / "scene_aligned_gridded_air_quality_holdout_2026_07_06/uwm_scene_aligned_gridded_air_quality_holdout.json"
        ),
    )


def test_real_data_graph_dqn_trains_neural_value_model_over_graph_mdp():
    report = train_livability_graph_dqn_agent(
        _env(),
        report_id="uwm-livability-real-data-graph-dqn-training-test",
        created_at="2026-07-07T16:15:00Z",
        seed=20260707,
        epochs=160,
        hidden_dim=32,
        learning_rate=0.01,
        discount_factor=0.9,
        holdout_stride=7,
    )

    assert report["schema"] == UWM_LIVABILITY_GRAPH_DRL_TRAINING_REPORT_SCHEMA
    assert report["drl_algorithm"]["algorithm"] == "graph_dqn_fitted_q_model_based_rl"
    assert report["drl_algorithm"]["is_deep_rl"] is True
    assert report["drl_algorithm"]["is_model_based"] is True
    assert report["drl_algorithm"]["is_model_free"] is False
    assert report["drl_algorithm"]["uses_graph_message_passing"] is True
    assert report["drl_algorithm"]["policy_or_value_network_trained"] is True

    architecture = report["network_architecture"]
    assert architecture["node_feature_names"] == GRAPH_NODE_FEATURE_NAMES
    assert "estimated_nearest_essential_travel_time_min" in architecture[
        "node_feature_names"
    ]
    assert "travel_time_inverse_norm" in architecture["node_feature_names"]
    assert architecture["node_feature_dim"] == len(GRAPH_NODE_FEATURE_NAMES)

    summary = report["training_summary"]
    assert summary["real_data_graph_node_count"] == 36
    assert summary["real_data_graph_edge_count"] == 96
    assert summary["real_data_available_action_count"] == 60
    assert summary["spatial_spillover_directional_edge_count"] == 227
    assert summary["training_sample_count"] >= 3500
    assert summary["holdout_count"] > 0

    holdout = report["holdout_metrics"]
    assert holdout["q_return_mae"] < holdout["train_mean_return_mae"]
    assert holdout["q_return_rmse"] < holdout["train_mean_return_rmse"]

    learned = report["learned_policy_evaluation"]
    baseline = report["baseline_evaluation"]
    assert learned["action_count"] == 2
    assert learned["graph_dqn_policy_cumulative_reward"] > baseline[
        "traditional_static_cumulative_reward"
    ]
    assert learned["advantage_over_traditional_static"] > 0
    assert report["supported_claim"] == (
        "graph_dqn_value_network_improves_same_scene_static_livability_baseline"
    )
    assert report["observed_policy_outcome_superiority_claim"] is False
    assert report["empirical_superiority_claim"] is False

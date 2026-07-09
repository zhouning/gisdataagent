import json
from pathlib import Path

import pytest

from data_agent.uwm.livability_graph_drl import train_livability_graph_dqn_agent
from data_agent.uwm.livability_graph_mdp_env import build_livability_graph_mdp_env
from data_agent.uwm.model_based_rl import build_admin_livability_graph_observation


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data/uwm_public_proxy/chongqing_central"
FULL_ADMIN_GRAPH_DRL_REPORT_PATH = (
    DATA_ROOT
    / "livability_graph_drl_training_full_admin_graph_2026_07_08/uwm_full_admin_graph_livability_graph_drl_training_report.json"
)
GEOGRAPHIC_SIMILARITY_KERNEL_PATH = (
    DATA_ROOT
    / "geographic_similarity_kernel_2026_07_08/uwm_geographic_similarity_kernel.json"
)


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _full_admin_env():
    observation = build_admin_livability_graph_observation(
        _load_json(
            DATA_ROOT
            / "admin_livability_target_full_admin_graph_2024_07_2026_07_08/uwm_admin_livability_target_full_admin_graph_panel.json"
        ),
        observation_id="admin-livability-full-admin-graph-drl-test",
        created_at="2026-07-08T12:20:00Z",
        admin_spatial_graph=_load_json(
            DATA_ROOT
            / "admin_spatial_graph_2026_07_05/uwm_admin_spatial_adjacency_graph.json"
        ),
        geographic_similarity_kernel=_load_json(GEOGRAPHIC_SIMILARITY_KERNEL_PATH),
    )
    return build_livability_graph_mdp_env(
        observation,
        action_types=[
            "increase_green_infrastructure",
            "traffic_emission_control",
            "add_community_service",
        ],
        scenario={
            "scenario_id": "full_admin_graph_drl_heat_pollution_service_stress",
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
            / "data_calibrated_mechanism_table_full_admin_graph_2026_07_08/uwm_full_admin_graph_data_calibrated_mechanism_table.json"
        ),
        air_quality_uncertainty_context=_load_json(
            DATA_ROOT
            / "scene_aligned_gridded_air_quality_holdout_2026_07_06/uwm_scene_aligned_gridded_air_quality_holdout.json"
        ),
    )


def _truncated_env():
    observation = build_admin_livability_graph_observation(
        _load_json(
            DATA_ROOT
            / "admin_livability_target_2024_07_2026_07_05/uwm_admin_livability_target_panel.json"
        ),
        observation_id="admin-livability-truncated-graph-drl-test",
        created_at="2026-07-08T12:20:00Z",
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
            "scenario_id": "truncated_graph_drl_guard_test",
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
    )


def test_full_admin_graph_dqn_trains_over_full_graph_with_explicit_action_sampling():
    report = train_livability_graph_dqn_agent(
        _full_admin_env(),
        report_id="uwm-full-admin-graph-dqn-training-test",
        created_at="2026-07-08T12:25:00Z",
        seed=20260708,
        epochs=4,
        hidden_dim=8,
        learning_rate=0.005,
        discount_factor=0.9,
        holdout_stride=5,
        experiment_scope="full_admin_graph",
        required_graph_node_count=1017,
        max_first_actions=6,
        max_second_actions_per_first=3,
        action_sampling_strategy="stratified_priority",
        policy_action_scope="sampled_training_candidate_pool",
    )

    summary = report["training_summary"]
    assert report["experiment_scope"] == "full_admin_graph"
    assert report["full_data_guard"] == {
        "required_scope": "full_admin_graph",
        "required_graph_node_count": 1017,
        "observed_graph_node_count": 1017,
        "passed": True,
    }
    assert summary["real_data_graph_node_count"] == 1017
    assert summary["real_data_graph_edge_count"] == 7932
    assert summary["real_data_available_action_count"] > 1000
    assert summary["action_sampling_strategy"] == "stratified_priority"
    assert summary["exhaustive_action_pair_training"] is False
    assert summary["sampled_first_action_count"] == 6
    assert summary["sampled_second_action_limit"] == 3
    assert summary["sampled_unique_action_count"] == 6
    assert summary["training_sample_count"] == 24
    assert summary["holdout_count"] > 0

    learned = report["learned_policy_evaluation"]
    assert learned["policy_action_scope"] == "sampled_training_candidate_pool"
    assert learned["action_count"] == 2
    assert len(learned["action_sequence"]) == 2
    assert report["observed_policy_outcome_superiority_claim"] is False
    assert report["empirical_superiority_claim"] is False


def test_full_admin_graph_dqn_rejects_truncated_graph_when_full_guard_required():
    with pytest.raises(ValueError, match="required_graph_node_count"):
        train_livability_graph_dqn_agent(
            _truncated_env(),
            report_id="uwm-full-admin-graph-dqn-training-guard-test",
            created_at="2026-07-08T12:25:00Z",
            seed=20260708,
            epochs=1,
            hidden_dim=4,
            learning_rate=0.005,
            discount_factor=0.9,
            holdout_stride=5,
            experiment_scope="full_admin_graph",
            required_graph_node_count=1017,
            max_first_actions=3,
            max_second_actions_per_first=1,
            action_sampling_strategy="stratified_priority",
        )


def test_full_admin_graph_dqn_training_report_artifact_is_full_scope():
    assert FULL_ADMIN_GRAPH_DRL_REPORT_PATH.exists()
    report = _load_json(FULL_ADMIN_GRAPH_DRL_REPORT_PATH)

    assert report["schema"] == "uwm.livability_graph_drl_training_report.v1"
    assert report["experiment_scope"] == "full_admin_graph"
    assert report["full_data_guard"]["passed"] is True
    assert report["full_data_guard"]["observed_graph_node_count"] == 1017
    assert report["training_summary"]["real_data_graph_node_count"] == 1017
    assert report["source_geographic_similarity_kernel_summary"][
        "similarity_edge_count"
    ] == 5085
    assert report["training_summary"]["real_data_graph_edge_count"] == 7932
    assert report["training_summary"]["real_data_available_action_count"] > 1000
    assert report["training_summary"]["exhaustive_action_pair_training"] is False
    assert report["training_summary"]["sampled_first_action_count"] >= 48
    assert report["training_summary"]["sampled_second_action_limit"] >= 8
    assert report["training_summary"]["training_sample_count"] >= 432
    assert (
        report["learned_policy_evaluation"]["policy_action_scope"]
        == "sampled_training_candidate_pool"
    )
    assert report["observed_policy_outcome_superiority_claim"] is False
    assert report["empirical_superiority_claim"] is False

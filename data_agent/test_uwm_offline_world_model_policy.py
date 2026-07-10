from data_agent.uwm.offline_world_model_policy import (
    FEATURE_NAMES,
    OFFLINE_WORLD_MODEL_POLICY_REPORT_SCHEMA,
    OFFLINE_WORLD_MODEL_ROLLOUT_PLANNER_REPORT_SCHEMA,
    plan_with_offline_world_model_rollouts,
    train_offline_world_model_policy,
)


def _search_report():
    graph_state = {
        "state_id": "fixture-state",
        "state_encoder": "graph_feature_encoder_v0",
        "nodes": [
            {
                "unit_id": "hot-service-gap",
                "features": {
                    "heat_risk": 0.9,
                    "air_pollution_exposure": 0.7,
                    "service_accessibility": 0.2,
                    "equity": 0.8,
                    "livability": 0.2,
                    "estimated_nearest_essential_travel_time_min": 24.0,
                    "road_segment_count": 2.0,
                    "road_length_km": 1.5,
                    "mean_road_speed_kmh": 28.0,
                    "capacity_norm": 0.1,
                    "essential_norm": 0.0,
                    "travel_time_inverse_norm": 0.05,
                    "service_gap": 0.8,
                },
            },
            {
                "unit_id": "moderate",
                "features": {
                    "heat_risk": 0.4,
                    "air_pollution_exposure": 0.3,
                    "service_accessibility": 0.8,
                    "equity": 0.3,
                    "livability": 0.7,
                    "estimated_nearest_essential_travel_time_min": 4.0,
                    "road_segment_count": 9.0,
                    "road_length_km": 12.0,
                    "mean_road_speed_kmh": 45.0,
                    "capacity_norm": 0.8,
                    "essential_norm": 0.7,
                    "travel_time_inverse_norm": 0.75,
                    "service_gap": 0.2,
                },
            },
        ],
        "edges": [
            {"source": "hot-service-gap", "target": "moderate", "weight": 1.0},
        ],
        "available_actions": [
            {
                "action_id": "add_community_service-hot-service-gap",
                "action_type": "add_community_service",
                "target_units": ["hot-service-gap"],
                "intensity": 1.0,
                "mask_reason": "service_accessibility_below_threshold",
            },
            {
                "action_id": "increase_green_infrastructure-hot-service-gap",
                "action_type": "increase_green_infrastructure",
                "target_units": ["hot-service-gap"],
                "intensity": 1.0,
                "mask_reason": "heat_risk_above_threshold",
            },
            {
                "action_id": "add_community_service-moderate",
                "action_type": "add_community_service",
                "target_units": ["moderate"],
                "intensity": 1.0,
                "mask_reason": "generic_action_allowed",
            },
        ],
        "graph_statistics": {
            "node_count": 2,
            "edge_count": 1,
            "available_action_count": 3,
        },
    }
    transitions = [
        _transition("add_community_service-hot-service-gap", "add_community_service", "hot-service-gap", 0.48, 0),
        _transition("increase_green_infrastructure-hot-service-gap", "increase_green_infrastructure", "hot-service-gap", 0.18, 0),
        _transition("add_community_service-moderate", "add_community_service", "moderate", 0.05, 0),
        _transition("add_community_service-hot-service-gap", "add_community_service", "hot-service-gap", 0.47, 1),
        _transition("increase_green_infrastructure-hot-service-gap", "increase_green_infrastructure", "hot-service-gap", 0.17, 1),
        _transition("add_community_service-moderate", "add_community_service", "moderate", 0.04, 1),
        _transition("add_community_service-hot-service-gap", "add_community_service", "hot-service-gap", 0.49, 2),
        _transition("increase_green_infrastructure-hot-service-gap", "increase_green_infrastructure", "hot-service-gap", 0.19, 2),
        _transition("add_community_service-moderate", "add_community_service", "moderate", 0.06, 2),
    ]
    return {
        "schema": "uwm.model_based_graph_search_report.v1",
        "graph_mdp_state": graph_state,
        "static_single_step_baseline": {
            "action_sequence": [
                {
                    "action_id": "static-increase_green_infrastructure-hot-service-gap",
                    "action_type": "increase_green_infrastructure",
                    "target_units": ["hot-service-gap"],
                }
            ],
            "cumulative_reward": 0.18,
        },
        "trajectory_dataset": {
            "schema": "uwm.graph_mdp_replay_dataset.v1",
            "transition_count": len(transitions),
            "transitions": transitions,
        },
    }


def test_train_offline_world_model_policy_learns_reward_and_dynamics_on_holdout():
    report = train_offline_world_model_policy(
        _search_report(),
        model_id="fixture-world-model-policy",
        created_at="2026-07-05T14:00:00+08:00",
        holdout_stride=4,
        ridge=0.001,
        uncertainty_penalty=0.25,
    )

    assert report["schema"] == OFFLINE_WORLD_MODEL_POLICY_REPORT_SCHEMA
    assert report["backend"] == "ridge_action_conditioned_world_model_policy_v0"
    assert report["training_summary"]["transition_count"] == 9
    assert report["holdout_metrics"]["reward_mae"] < report["baseline_metrics"]["train_mean_reward_mae"]
    assert report["holdout_metrics"]["dynamics_mae_by_target"]["livability_delta"] < 0.05
    assert report["world_model"]["target_names"] == [
        "reward",
        "heat_risk_delta",
        "air_pollution_exposure_delta",
        "service_accessibility_delta",
        "equity_delta",
        "livability_delta",
    ]
    assert report["world_model"]["feature_names"] == FEATURE_NAMES
    for feature_name in [
        "target_travel_time_min_norm",
        "target_road_segment_count_norm",
        "target_road_length_km_norm",
        "target_mean_road_speed_kmh_norm",
        "target_travel_time_inverse_norm",
        "target_service_gap",
    ]:
        assert feature_name in report["world_model"]["feature_names"]
        assert feature_name in report["world_model"]["coefficients"]["reward"]
    assert report["empirical_superiority_claim"] is False


def test_offline_world_model_policy_selects_action_with_replay_advantage_over_static_baseline():
    report = train_offline_world_model_policy(
        _search_report(),
        model_id="fixture-world-model-policy",
        created_at="2026-07-05T14:00:00+08:00",
        holdout_stride=4,
        ridge=0.001,
        uncertainty_penalty=0.25,
    )

    policy = report["conservative_policy"]

    assert policy["selected_action"]["action_id"] == "add_community_service-hot-service-gap"
    assert policy["static_single_step_action"]["action_id"] == "increase_green_infrastructure-hot-service-gap"
    assert policy["actual_replay_evaluation"]["comparable"] is True
    assert policy["actual_replay_evaluation"]["selected_action_mean_reward"] > policy["actual_replay_evaluation"]["static_action_mean_reward"]
    assert report["supported_claim"] == "offline_world_model_policy_improves_replay_static_baseline"
    assert report["claim_boundary"]["max_claim_level"] == "bounded_support"
    assert "observed_policy_outcome_holdout_required" in report["remaining_gates"]


def test_offline_world_model_rollout_planner_imagines_multi_step_state_updates():
    report = plan_with_offline_world_model_rollouts(
        _search_report(),
        model_id="fixture-world-model-rollout-planner",
        created_at="2026-07-05T15:00:00+08:00",
        horizon=2,
        beam_width=3,
        holdout_stride=4,
        ridge=0.001,
        uncertainty_penalty=0.25,
    )

    planner = report["learned_rollout_planner"]
    selected = planner["selected_sequence"]

    assert report["schema"] == OFFLINE_WORLD_MODEL_ROLLOUT_PLANNER_REPORT_SCHEMA
    assert report["world_model"]["model_class"] == "linear_ridge_action_conditioned_dynamics"
    assert report["holdout_metrics"]["reward_mae"] < report["baseline_metrics"]["train_mean_reward_mae"]
    assert planner["policy_backend"] == "multi_step_action_conditioned_learned_rollout_v0"
    assert selected["action_count"] == 2
    assert len(selected["action_sequence"]) == 2
    assert len({action["action_id"] for action in selected["action_sequence"]}) == 2
    assert selected["imagined_cumulative_conservative_reward"] > planner["one_step_policy_baseline"][
        "imagined_cumulative_conservative_reward"
    ]
    assert selected["imagined_cumulative_conservative_reward"] > planner["static_single_step_baseline"][
        "imagined_cumulative_conservative_reward"
    ]
    assert selected["imagined_steps"][0]["predicted_dynamics"]["service_accessibility_delta"] > 0
    assert selected["imagined_steps"][0]["post_state_features"]["hot-service-gap"]["service_accessibility"] > 0.2
    assert report["supported_claim"] == "learned_world_model_rollout_improves_imagined_static_and_one_step_baselines"
    assert report["empirical_superiority_claim"] is False
    assert "observed_policy_outcome_holdout_required" in report["remaining_gates"]


def _transition(action_id, action_type, target_unit, reward, step_index):
    livability_delta = reward * 0.8
    return {
        "tuple_keys": ["state", "action", "reward", "next_state_delta", "transition"],
        "state": {"state_id": "fixture-state", "state_encoder": "graph_feature_encoder_v0"},
        "action": {
            "action_id": action_id,
            "action_type": action_type,
            "target_units": [target_unit],
            "intensity": 1.0,
        },
        "reward": reward,
        "next_state_delta": {
            "changed_units": 1,
            "per_unit": {
                target_unit: {
                    "heat_risk_delta": -reward * 0.10,
                    "air_pollution_exposure_delta": -reward * 0.05,
                    "service_accessibility_delta": reward * 0.30,
                    "equity_delta": reward * 0.20,
                    "livability_delta": livability_delta,
                }
            },
        },
        "transition": {
            "step_index": step_index,
            "cumulative_reward": reward,
            "evidence_grade": "bounded_support",
        },
    }

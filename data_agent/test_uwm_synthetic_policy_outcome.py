from data_agent.uwm.offline_world_model_policy import plan_with_offline_world_model_rollouts
from data_agent.uwm.synthetic_policy_outcome import (
    SYNTHETIC_POLICY_OUTCOME_BENCHMARK_SCHEMA,
    build_synthetic_policy_outcome_benchmark,
)


def test_synthetic_policy_outcome_benchmark_compares_static_and_learned_rollout_without_empirical_claim():
    search_report = _search_report()
    learned_report = plan_with_offline_world_model_rollouts(
        search_report,
        model_id="fixture-world-model-rollout-planner",
        created_at="2026-07-05T15:00:00+08:00",
        horizon=2,
        beam_width=3,
        holdout_stride=4,
        ridge=0.001,
        uncertainty_penalty=0.25,
    )

    benchmark = build_synthetic_policy_outcome_benchmark(
        search_report,
        learned_report,
        benchmark_id="fixture-synthetic-policy-outcome",
        created_at="2026-07-05T15:20:00+08:00",
    )

    rows = {row["policy_id"]: row for row in benchmark["synthetic_policy_outcomes"]}

    assert benchmark["schema"] == SYNTHETIC_POLICY_OUTCOME_BENCHMARK_SCHEMA
    assert benchmark["synthetic_status"] == "synthetic"
    assert benchmark["quality_status"] == "synthetic_policy_outcome_not_observed"
    assert benchmark["empirical_superiority_claim"] is False
    assert benchmark["claim_boundary"]["max_claim_level"] == "exploratory_only"
    assert rows["static_single_step_heuristic"]["action_count"] == 1
    assert rows["graph_mdp_known_effect_best"]["action_count"] == 2
    assert rows["learned_world_model_rollout"]["action_count"] == 2
    assert (
        rows["learned_world_model_rollout"]["synthetic_reward"]
        > rows["static_single_step_heuristic"]["synthetic_reward"]
    )
    assert benchmark["comparisons"]["learned_rollout_advantage_over_static"] > 0
    assert "observed_policy_outcome_required" in benchmark["remaining_gates"]


def _search_report():
    service_hot = {
        "action_id": "add_community_service-hot-service-gap",
        "action_type": "add_community_service",
        "target_units": ["hot-service-gap"],
        "intensity": 1.0,
    }
    green_hot = {
        "action_id": "increase_green_infrastructure-hot-service-gap",
        "action_type": "increase_green_infrastructure",
        "target_units": ["hot-service-gap"],
        "intensity": 1.0,
    }
    service_moderate = {
        "action_id": "add_community_service-moderate",
        "action_type": "add_community_service",
        "target_units": ["moderate"],
        "intensity": 1.0,
    }
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
                },
            },
        ],
        "edges": [{"source": "hot-service-gap", "target": "moderate", "weight": 1.0}],
        "available_actions": [service_hot, green_hot, service_moderate],
        "graph_statistics": {"node_count": 2, "edge_count": 1, "available_action_count": 3},
        "claim_boundary": {"max_claim_level": "bounded_support"},
    }
    transitions = [
        _transition(service_hot, 0.48, 0),
        _transition(green_hot, 0.18, 0),
        _transition(service_moderate, 0.05, 0),
        _transition(service_hot, 0.47, 1),
        _transition(green_hot, 0.17, 1),
        _transition(service_moderate, 0.04, 1),
        _transition(service_hot, 0.49, 2),
        _transition(green_hot, 0.19, 2),
        _transition(service_moderate, 0.06, 2),
    ]
    return {
        "schema": "uwm.model_based_graph_search_report.v1",
        "graph_mdp_state": graph_state,
        "best_sequence": {
            "action_sequence": [service_hot, green_hot],
            "cumulative_reward": 0.66,
        },
        "static_single_step_baseline": {
            "action_sequence": [
                {
                    "action_id": "static-increase_green_infrastructure-hot-service-gap",
                    "action_type": "increase_green_infrastructure",
                    "target_units": ["hot-service-gap"],
                    "intensity": 1.0,
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


def _transition(action, reward, step_index):
    return {
        "tuple_keys": ["state", "action", "reward", "next_state_delta", "transition"],
        "state": {"state_id": "fixture-state", "state_encoder": "graph_feature_encoder_v0"},
        "action": action,
        "reward": reward,
        "next_state_delta": {
            "changed_units": 1,
            "per_unit": {
                action["target_units"][0]: {
                    "heat_risk_delta": -reward * 0.10,
                    "air_pollution_exposure_delta": -reward * 0.05,
                    "service_accessibility_delta": reward * 0.30,
                    "equity_delta": reward * 0.20,
                    "livability_delta": reward * 0.80,
                }
            },
        },
        "transition": {
            "step_index": step_index,
            "cumulative_reward": reward,
            "evidence_grade": "bounded_support",
        },
    }

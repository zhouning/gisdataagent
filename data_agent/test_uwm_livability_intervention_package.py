from data_agent.uwm.livability_intervention_package import (
    UWM_LIVABILITY_INTERVENTION_PACKAGE_SCHEMA,
    build_livability_intervention_package,
)


def test_livability_intervention_package_exposes_business_theory_result_shape():
    package = build_livability_intervention_package(
        search_report=_search_report(),
        learned_rollout_report=_learned_rollout_report(),
        synthetic_policy_outcome_benchmark=_synthetic_policy_outcome_benchmark(),
        tap_like_pm25_scene_manifest=_tap_like_manifest(),
        package_id="fixture-livability-intervention-package",
        created_at="2026-07-05T21:10:00Z",
    )

    assert package["schema"] == UWM_LIVABILITY_INTERVENTION_PACKAGE_SCHEMA
    assert package["synthetic_status"] == "synthetic"
    assert package["empirical_superiority_claim"] is False
    assert package["claim_boundary"]["max_claim_level"] == "exploratory_only"
    assert package["business_theory_alignment"]["result_shape"] == [
        "low_livability_area_identification",
        "mechanism_explanation",
        "intervention_suitability_map",
        "multi_step_action_sequence",
        "before_after_indicator_delta",
        "equity_conclusion",
        "evidence_boundary",
    ]
    assert package["low_livability_units"][0]["unit_id"] == "hot-service-gap"
    assert "service_accessibility_deficit" in package["low_livability_units"][0]["dominant_mechanisms"]
    assert package["mechanism_explanations"][0]["primary_mechanism"] == "service_accessibility_deficit"
    assert package["intervention_suitability"][0]["recommended_action_type"] == "add_community_service"
    assert package["multi_step_plan"]["action_count"] == 2
    assert package["multi_step_plan"]["action_sequence"][0]["action_id"] == "add_community_service-hot-service-gap"
    assert package["before_after_indicators"]["predicted_delta"]["service_accessibility_delta"] > 0
    assert package["before_after_indicators"]["directions"] == {
        "heat_risk_delta": "target_decrease",
        "air_pollution_exposure_delta": "target_decrease",
        "service_accessibility_delta": "target_increase",
        "equity_delta": "target_increase",
        "livability_delta": "target_increase",
    }
    assert package["equity_conclusion"]["status"] == "equity_improves"
    assert package["traditional_method_comparison"]["learned_rollout_advantage_over_static"] > 0
    assert package["supported_claim"] == "business_theory_aligned_learned_rollout_beats_static_proxy_baseline"
    assert "observed_policy_outcome_required" in package["remaining_gates"]


def _search_report():
    return {
        "schema": "uwm.model_based_graph_search_report.v1",
        "graph_mdp_state": {
            "state_id": "fixture-state",
            "nodes": [
                {
                    "unit_id": "hot-service-gap",
                    "features": {
                        "heat_risk": 0.8,
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
                        "equity": 0.4,
                        "livability": 0.7,
                    },
                },
            ],
            "available_actions": [
                {
                    "action_id": "add_community_service-hot-service-gap",
                    "action_type": "add_community_service",
                    "target_units": ["hot-service-gap"],
                    "mask_reason": "service_accessibility_below_threshold",
                },
                {
                    "action_id": "increase_green_infrastructure-hot-service-gap",
                    "action_type": "increase_green_infrastructure",
                    "target_units": ["hot-service-gap"],
                    "mask_reason": "heat_risk_above_threshold",
                },
            ],
            "claim_boundary": {"max_claim_level": "bounded_support"},
        },
        "static_single_step_baseline": {
            "method": "static_priority_single_step_heuristic",
            "action_sequence": [
                {
                    "action_id": "increase_green_infrastructure-hot-service-gap",
                    "action_type": "increase_green_infrastructure",
                    "target_units": ["hot-service-gap"],
                }
            ],
        },
    }


def _learned_rollout_report():
    return {
        "schema": "uwm.offline_world_model_rollout_planner_report.v1",
        "holdout_metrics": {"reward_mae": 0.01},
        "baseline_metrics": {"train_mean_reward_mae": 0.10},
        "learned_rollout_planner": {
            "selected_sequence": {
                "action_count": 2,
                "action_sequence": [
                    {
                        "action_id": "add_community_service-hot-service-gap",
                        "action_type": "add_community_service",
                        "target_units": ["hot-service-gap"],
                    },
                    {
                        "action_id": "increase_green_infrastructure-hot-service-gap",
                        "action_type": "increase_green_infrastructure",
                        "target_units": ["hot-service-gap"],
                    },
                ],
                "imagined_cumulative_conservative_reward": 0.12,
                "imagined_steps": [
                    {
                        "predicted_reward": 0.07,
                        "conservative_reward": 0.06,
                        "predicted_dynamics": {
                            "heat_risk_delta": -0.01,
                            "air_pollution_exposure_delta": -0.005,
                            "service_accessibility_delta": 0.12,
                            "equity_delta": 0.04,
                            "livability_delta": 0.06,
                        },
                    },
                    {
                        "predicted_reward": 0.05,
                        "conservative_reward": 0.04,
                        "predicted_dynamics": {
                            "heat_risk_delta": -0.08,
                            "air_pollution_exposure_delta": -0.02,
                            "service_accessibility_delta": 0.01,
                            "equity_delta": 0.02,
                            "livability_delta": 0.05,
                        },
                    },
                ],
            },
            "static_single_step_baseline": {"imagined_cumulative_conservative_reward": 0.03},
            "one_step_policy_baseline": {"imagined_cumulative_conservative_reward": 0.06},
            "imagined_advantage_over_static_single_step": 0.09,
            "imagined_advantage_over_one_step_policy": 0.06,
        },
        "claim_boundary": {"max_claim_level": "bounded_support"},
        "empirical_superiority_claim": False,
    }


def _synthetic_policy_outcome_benchmark():
    return {
        "schema": "uwm.synthetic_policy_outcome_benchmark.v1",
        "synthetic_status": "synthetic",
        "comparisons": {"learned_rollout_advantage_over_static": 0.11},
        "claim_boundary": {"max_claim_level": "exploratory_only"},
        "empirical_superiority_claim": False,
    }


def _tap_like_manifest():
    return {
        "schema": "uwm.synthetic_snapshot_manifest.v1",
        "dataset_id": "tap_like_pm25_scene_v2_2024_07",
        "synthetic_status": "semi_synthetic",
        "quality_status": "tap_like_pm25_scene_not_observed_holdout",
        "record_counts": {"records": 6048},
        "calibration_summary": {"max_abs_chap_anchor_error_ugm3": 0.0},
        "claim_boundary": {"max_claim_level": "exploratory_only"},
        "empirical_superiority_claim": False,
    }

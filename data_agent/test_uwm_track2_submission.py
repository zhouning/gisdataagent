from pathlib import Path

from data_agent.uwm.track2_submission import (
    AI_URBAN_SCIENTIST_STAGE_MAP,
    TRACK2_INITIAL_REVIEW_DEADLINE,
    build_track2_readiness_matrix,
    build_uwm_default_artifact_inventory,
    build_uwm_default_track2_readiness_matrix,
)


def test_track2_readiness_matrix_encodes_required_deliverables_and_deadline():
    artifacts = {
        "research_report": {"status": "missing", "path": "docs/reports/uwm_track2_initial_report.md"},
        "data_description": {"status": "partial", "path": "docs/reports/uwm_data_foundation_manifest.md"},
        "reproducible_code": {"status": "available", "path": "data_agent/uwm"},
        "ai_collaboration_log": {"status": "available", "path": "docs/reports/uwm_track2_research_log.md"},
    }

    matrix = build_track2_readiness_matrix(artifacts, current_date="2026-07-04")

    assert matrix["schema"] == "uwm.track2_submission_readiness.v1"
    assert matrix["competition"] == "Urban Cup 2026 Track 2 Vibe Research"
    assert matrix["initial_review_deadline"] == TRACK2_INITIAL_REVIEW_DEADLINE
    assert matrix["days_to_initial_review_deadline"] == 18
    assert matrix["ready_for_initial_submission"] is False
    assert "research_report" in matrix["missing_required_artifacts"]
    assert matrix["deliverables"]["research_report"]["required"] is True
    assert matrix["deliverables"]["data_description"]["status"] == "partial"
    assert set(matrix["ai_urban_scientist_alignment"]) == {
        "idea_generation",
        "data_seeking",
        "paper_planning",
        "paper_writing",
    }


def test_default_uwm_artifact_inventory_reflects_current_repository_files():
    inventory = build_uwm_default_artifact_inventory(Path("."))

    assert inventory["data_description"]["status"] == "available"
    assert inventory["reproducible_code"]["status"] == "available"
    assert inventory["ai_collaboration_log"]["status"] == "available"
    assert inventory["research_report"]["status"] in {"missing", "partial"}
    assert AI_URBAN_SCIENTIST_STAGE_MAP["data_seeking"]["uwm_usage"] == "data foundation manifest and MMFE ingestion"


def test_default_track2_readiness_matrix_loads_real_world_model_evidence_gate():
    matrix = build_uwm_default_track2_readiness_matrix(
        Path("."),
        current_date="2026-07-06",
    )

    assert matrix["schema"] == "uwm.track2_submission_readiness.v1"
    assert matrix["observed_validation_readiness"]["temporal_state_prediction_suite_ready"] is True
    readiness = matrix["world_model_evidence_readiness"]
    assert readiness["overall_claim_ceiling"] == "bounded_support"
    assert readiness["system_level_superiority_summary"] == (
        "bounded_final_endpoint_and_endpoint_aligned_planner_advantage_without_policy_outcome_superiority"
    )
    assert readiness["traditional_method_comparison_ready"] is True
    assert readiness["bounded_final_system_superiority_ready"] is True
    assert readiness["policy_outcome_superiority_ready"] is False
    assert readiness["architecture_evidence"]["simulator"]["external_temporal_transition_ready"] is True
    assert (
        readiness["architecture_evidence"]["renderer"][
            "multisource_livability_scene_ready"
        ]
        is True
    )
    assert (
        readiness["architecture_evidence"]["renderer"][
            "multisource_air_quality_mae_reduction"
        ]
        == 0.002903
    )
    assert (
        readiness["architecture_evidence"]["renderer"][
            "osm_admin_mobility_crosswalk_ready"
        ]
        is True
    )
    assert (
        readiness["architecture_evidence"]["renderer"][
            "osm_admin_mobility_crosswalk_projected_in_scene"
        ]
        is True
    )
    assert (
        readiness["architecture_evidence"]["renderer"][
            "osm_assigned_road_segment_count_in_scene"
        ]
        == 45449
    )
    assert (
        readiness["architecture_evidence"]["renderer"][
            "osm_service_accessibility_mae_reduction"
        ]
        == 1.140949
    )
    assert (
        readiness["architecture_evidence"]["renderer"][
            "building_floor_morphology_ready"
        ]
        is True
    )
    assert (
        readiness["architecture_evidence"]["renderer"][
            "building_floor_assigned_building_count"
        ]
        == 44887
    )
    assert (
        readiness["architecture_evidence"]["renderer"][
            "building_floor_total_floor_count"
        ]
        == 322665
    )
    assert (
        readiness["architecture_evidence"]["renderer"][
            "building_floor_max_floor"
        ]
        == 66
    )
    assert (
        readiness["architecture_evidence"]["renderer"][
            "building_floor_ready_endpoint_count"
        ]
        == 2
    )
    assert (
        readiness["architecture_evidence"]["renderer"][
            "building_floor_true_3d_claim"
        ]
        is False
    )
    final_evaluator = readiness["architecture_evidence"][
        "final_livability_endpoint_evaluator"
    ]
    assert final_evaluator["ready"] is True
    assert final_evaluator["endpoint_count"] == 3
    assert final_evaluator["ready_endpoint_count"] == 3
    assert final_evaluator["mean_relative_mae_reduction_vs_best_traditional"] == 0.115337
    assert (
        readiness["architecture_evidence"]["planner"][
            "risk_calibrated_planner_replay_ready"
        ]
        is True
    )
    assert (
        readiness["architecture_evidence"]["planner"][
            "endpoint_aligned_planner_evaluator_ready"
        ]
        is True
    )
    assert (
        readiness["architecture_evidence"]["planner"][
            "endpoint_aligned_advantage_over_static"
        ]
        == 0.0007457
    )
    assert (
        readiness["architecture_evidence"]["planner"][
            "spatial_spillover_planner_evaluator_ready"
        ]
        is True
    )
    assert (
        readiness["architecture_evidence"]["planner"][
            "neighbor_livability_delta_advantage"
        ]
        == 0.272680076
    )
    assert (
        readiness["architecture_evidence"]["planner"][
            "risk_calibrated_planner_advantage_over_static"
        ]
        == 0.012777213
    )
    final_decision = readiness["architecture_evidence"][
        "final_livability_decision_package"
    ]
    assert final_decision["ready"] is True
    assert final_decision["action_count"] == 2
    assert final_decision["target_unit_count"] == 2
    assert final_decision["endpoint_aligned_advantage_over_static"] == 0.0007457
    assert final_decision["risk_adjusted_advantage_over_static"] == 0.012777213
    assert final_decision["neighbor_livability_delta_advantage"] == 0.272680076
    assert final_decision["graph_drl_training_ready"] is True
    assert final_decision["graph_drl_algorithm"] == "graph_dqn_fitted_q_model_based_rl"
    assert final_decision["graph_drl_training_sample_count"] == 3600
    graph_drl = readiness["architecture_evidence"]["graph_drl_training"]
    assert graph_drl["ready"] is True
    assert graph_drl["algorithm"] == "graph_dqn_fitted_q_model_based_rl"
    assert graph_drl["is_deep_rl"] is True
    assert graph_drl["uses_graph_message_passing"] is True
    assert graph_drl["policy_or_value_network_trained"] is True
    assert graph_drl["training_sample_count"] == 3600
    assert graph_drl["q_return_mae"] == 0.000109541
    assert graph_drl["advantage_over_traditional_static"] == 0.005131954
    assert "observed_policy_outcome_required" in readiness["remaining_gates"]


def test_track2_readiness_includes_data_foundation_empirical_blockers():
    artifacts = {
        "research_report": {"status": "available", "path": "docs/reports/uwm_track2_initial_report.md"},
        "data_description": {"status": "available", "path": "docs/reports/uwm_data_foundation_manifest.md"},
        "reproducible_code": {"status": "available", "path": "data_agent/uwm"},
        "ai_collaboration_log": {"status": "available", "path": "docs/reports/uwm_track2_research_log.md"},
    }
    data_foundation_audit = {
        "missing_required_roles": [],
        "empirical_superiority_blockers": ["air_pollution_exposure", "population_vulnerability"],
        "public_acquisition_queue": [
            "download_or_mount_air_pollution_public_proxy",
            "download_or_mount_population_vulnerability_public_proxy",
        ],
        "claim_ceiling": "bounded_support",
    }

    matrix = build_track2_readiness_matrix(
        artifacts,
        current_date="2026-07-04",
        data_foundation_audit=data_foundation_audit,
    )

    assert matrix["ready_for_initial_submission"] is True
    assert matrix["data_foundation_readiness"]["claim_ceiling"] == "bounded_support"
    assert matrix["data_foundation_readiness"]["empirical_superiority_ready"] is False
    assert "air_pollution_exposure" in matrix["data_foundation_readiness"]["empirical_superiority_blockers"]
    assert "advance_data_driven_holdout_validation" in matrix["next_actions"]


def test_track2_readiness_integrates_observed_temporal_holdout_without_policy_overclaim():
    artifacts = {
        "research_report": {"status": "available", "path": "docs/reports/uwm_track2_initial_report.md"},
        "data_description": {"status": "available", "path": "docs/reports/uwm_data_foundation_manifest.md"},
        "reproducible_code": {"status": "available", "path": "data_agent/uwm"},
        "ai_collaboration_log": {"status": "available", "path": "docs/reports/uwm_track2_research_log.md"},
    }
    observed_temporal_benchmark = {
        "schema": "uwm.openaq_observed_temporal_benchmark.v1",
        "benchmark_id": "uwm-openaq-observed-temporal-benchmark-chongqing-2018-10",
        "pollutant_count": 6,
        "observation_count": 600,
        "holdout_count": 180,
        "overall_holdout_win_count": 150,
        "overall_holdout_win_rate": 0.833333,
        "traditional_baseline_suite": ["static_train_mean", "static_last_train_observation"],
        "temporal_order_negative_control_summary": {
            "pollutant_count": 6,
            "ordered_advantage_count": 6,
            "ordered_advantage_rate": 1.0,
            "mean_ordered_mae_advantage": 4.25,
            "all_pollutants_ordered_temporal_state_advantage": True,
        },
        "overall_sign_tests": {
            "static_train_mean": {
                "wins": 150,
                "losses": 20,
                "ties": 10,
                "effective_n": 170,
                "one_sided_p_value": 1e-12,
            },
            "static_last_train_observation": {
                "wins": 142,
                "losses": 30,
                "ties": 8,
                "effective_n": 172,
                "one_sided_p_value": 1e-10,
            },
        },
        "observed_temporal_state_advantage_over_static_baseline_suite": True,
        "per_pollutant_results": [
            {
                "pollutant": "pm25",
                "holdout_count": 30,
                "holdout_win_count": 29,
                "holdout_win_rate": 0.966667,
                "static_mean_baseline_mae": 12.895238,
                "uwm_dynamic_persistence_mae": 2.4,
                "best_traditional_static_baseline": {
                    "method": "static_last_train_observation",
                    "mae": 9.466667,
                },
                "temporal_order_negative_control": {
                    "ordered_mae_advantage": 4.0,
                    "ordered_temporal_state_advantage": True,
                },
                "traditional_static_baseline_suite": {
                    "static_last_train_observation": {
                        "dynamic_sign_test": {
                            "wins": 25,
                            "losses": 5,
                            "ties": 0,
                            "effective_n": 30,
                            "one_sided_p_value": 0.000162,
                        }
                    }
                },
                "beats_all_traditional_static_baselines": True,
                "dynamic_advantage_over_static_mean": True,
            }
        ],
        "observed_temporal_state_advantage_over_static_baseline": True,
        "supported_claim": "observed_temporal_state_prediction_advantage_over_static_baseline_suite",
        "claim_boundary": {
            "max_claim_level": "bounded_support",
            "reason": "OpenAQ observed holdout supports temporal state-prediction comparison only.",
        },
        "limitations": ["not_policy_intervention_outcome"],
        "empirical_superiority_claim": False,
    }

    matrix = build_track2_readiness_matrix(
        artifacts,
        current_date="2026-07-05",
        observed_temporal_benchmark=observed_temporal_benchmark,
    )

    observed = matrix["observed_validation_readiness"]
    assert observed["temporal_state_prediction_ready"] is True
    assert observed["claim_boundary"]["max_claim_level"] == "bounded_support"
    assert observed["overall_holdout_win_count"] == 150
    assert observed["holdout_count"] == 180
    assert observed["pm25_holdout_win_rate"] == 0.966667
    assert observed["traditional_baseline_suite"] == ["static_train_mean", "static_last_train_observation"]
    assert observed["temporal_state_prediction_suite_ready"] is True
    assert observed["temporal_state_prediction_suite_significant_at_0_05"] is True
    assert observed["temporal_order_negative_control_passed"] is True
    assert observed["temporal_order_negative_control_summary"]["ordered_advantage_count"] == 6
    assert observed["pm25_ordered_mae_advantage_over_shuffled"] == 4.0
    assert observed["overall_sign_tests"]["static_train_mean"]["one_sided_p_value"] == 1e-12
    assert observed["pm25_best_static_baseline_method"] == "static_last_train_observation"
    assert observed["pm25_best_static_baseline_mae"] == 9.466667
    assert observed["pm25_sign_test_vs_best_static_p_value"] == 0.000162
    assert observed["pm25_beats_all_traditional_static_baselines"] is True
    assert observed["policy_outcome_superiority_ready"] is False
    assert observed["empirical_superiority_claim"] is False
    assert "observed_policy_outcome_holdout_required" in observed["remaining_gates"]
    assert "advance_observed_policy_outcome_holdout_validation" in matrix["next_actions"]


def test_track2_readiness_integrates_world_model_evidence_gate_claim_ladder():
    artifacts = {
        "research_report": {"status": "available", "path": "docs/reports/uwm_track2_initial_report.md"},
        "data_description": {"status": "available", "path": "docs/reports/uwm_data_foundation_manifest.md"},
        "reproducible_code": {"status": "available", "path": "data_agent/uwm"},
        "ai_collaboration_log": {"status": "available", "path": "docs/reports/uwm_track2_research_log.md"},
    }
    data_foundation_evidence_gate = {
        "schema": "uwm.data_foundation_evidence_gate.v1",
        "observed_state_prediction_superiority_claim": True,
        "external_temporal_transition_superiority_claim": True,
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
        "supported_claims": [
            {
                "claim": "observed_temporal_state_prediction_advantage_over_static_baseline_suite",
                "scope": "observed_temporal_state_prediction_not_policy_outcome",
                "claim_level": "bounded_support",
                "policy_outcome_claim": False,
            },
            {
                "claim": "tap_external_temporal_dynamics_advantage_without_spatial_claim",
                "scope": "tap_external_temporal_transition_without_spatial_claim",
                "claim_level": "bounded_support",
                "policy_outcome_claim": False,
                "spatial_attribution_claim": False,
            },
            {
                "claim": "learned_world_model_rollout_improves_imagined_static_and_one_step_baselines",
                "scope": "simulator_replay_learned_dynamics_not_observed_policy_outcome",
                "claim_level": "bounded_support",
                "policy_outcome_claim": False,
            },
            {
                "claim": "business_theory_aligned_learned_rollout_beats_static_proxy_baseline",
                "scope": "business_theory_aligned_proxy_package_not_observed_policy_outcome",
                "claim_level": "exploratory_only",
                "policy_outcome_claim": False,
            },
        ],
        "evidence_slices": {
            "openaq_observed_temporal_state": {
                "source_artifact_exists": True,
                "scope": "observed_temporal_state_prediction_not_policy_outcome",
                "claim_level": "bounded_support",
                "overall_holdout_win_rate": 0.833333,
                "holdout_count": 180,
                "temporal_order_negative_control_passed": True,
            },
            "tap_external_temporal_transition": {
                "source_artifact_exists": True,
                "scope": "tap_external_temporal_transition_without_spatial_claim",
                "claim_level": "bounded_support",
                "series_count": 10000,
                "holdout_count": 40000,
                "best_transition_mae": 7.003808,
                "best_non_spatial_dynamic_mae": 7.011689,
                "paired_win_rate_vs_best_non_spatial_dynamic": 0.5077,
                "spatial_negative_control_passed": False,
                "temporal_order_negative_control_passed": True,
                "future_label_leakage_guard_passed": True,
            },
            "learned_world_model_rollout": {
                "source_artifact_exists": True,
                "scope": "simulator_replay_learned_dynamics_not_observed_policy_outcome",
                "claim_level": "bounded_support",
                "holdout_reward_mae": 0.000165324,
                "train_mean_reward_mae": 0.002418188,
                "imagined_advantage_over_static": 0.010279633,
                "imagined_advantage_over_one_step": 0.00951568,
            },
            "livability_intervention_package": {
                "source_artifact_exists": True,
                "scope": "business_theory_aligned_proxy_package_not_observed_policy_outcome",
                "claim_level": "exploratory_only",
                "synthetic_status": "synthetic",
                "remaining_gates": ["observed_policy_outcome_required"],
                "predicted_delta": {
                    "service_accessibility_delta": 0.965080014,
                    "equity_delta": 0.552991953,
                    "livability_delta": 0.786721588,
                },
            },
            "admin_spatial_adjacency_graph": {
                "source_artifact_exists": True,
                "scope": "prepared_admin_boundary_adjacency_graph_not_mobility_graph",
                "claim_level": "bounded_support",
                "node_count": 1017,
                "edge_count": 2847,
            },
            "local_planning_data_foundation": {
                "source_artifact_exists": True,
                "scope": "prepared_local_planning_data_foundation",
                "claim_level": "fragile",
            },
        },
        "claim_guard": {
            "synthetic_or_smoke_blocked_from_empirical_policy_claim": True,
            "blocked_dataset_ids": ["synthetic_air_quality_placeholder"],
        },
        "remaining_gates": [
            "observed_policy_outcome_required",
            "scene_aligned_station_calibrated_air_quality_holdout_required",
            "causal_policy_effect_validation_required",
            "external_observed_holdout_required",
            "synthetic_proxy_boundary_must_remain_visible",
        ],
    }

    matrix = build_track2_readiness_matrix(
        artifacts,
        current_date="2026-07-06",
        data_foundation_evidence_gate=data_foundation_evidence_gate,
    )

    readiness = matrix["world_model_evidence_readiness"]
    assert readiness["schema"] == "uwm.world_model_evidence_readiness.v1"
    assert readiness["overall_claim_ceiling"] == "bounded_support"
    assert readiness["system_level_superiority_summary"] == (
        "bounded_state_prediction_and_transition_advantage_without_policy_outcome_superiority"
    )
    assert readiness["bounded_final_system_superiority_ready"] is False
    assert readiness["traditional_method_comparison_ready"] is True
    assert readiness["policy_outcome_superiority_ready"] is False
    assert readiness["empirical_superiority_claim"] is False
    assert readiness["forbidden_claims"] == [
        "observed_policy_outcome_superiority",
        "spatial_attribution_for_tap_external_transition",
        "overall_empirical_policy_superiority",
    ]
    assert readiness["architecture_evidence"]["renderer"]["ready"] is True
    assert readiness["architecture_evidence"]["simulator"]["ready"] is True
    assert readiness["architecture_evidence"]["planner"]["ready"] is True
    assert readiness["architecture_evidence"]["policy_outcome_evaluator"]["ready"] is False
    assert readiness["claim_ladder"][0]["claim"] == "observed_temporal_state_prediction_advantage_over_static_baseline_suite"
    assert readiness["claim_ladder"][0]["allowed_in_report"] is True
    assert readiness["claim_ladder"][1]["claim"] == "tap_external_temporal_dynamics_advantage_without_spatial_claim"
    assert readiness["claim_ladder"][1]["allowed_in_report"] is True
    assert readiness["claim_ladder"][1]["spatial_attribution_claim"] is False
    assert readiness["claim_ladder"][-1]["claim"] == "business_theory_aligned_learned_rollout_beats_static_proxy_baseline"
    assert readiness["claim_ladder"][-1]["allowed_in_report"] is False
    assert "observed_policy_outcome_required" in readiness["remaining_gates"]
    assert "complete_world_model_evidence_readiness_section" in matrix["next_actions"]
    assert "collect_observed_policy_outcome_validation_data" in matrix["next_actions"]

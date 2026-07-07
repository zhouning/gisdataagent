from pathlib import Path

from data_agent.uwm.data_foundation_evidence_gate import (
    UWM_DATA_FOUNDATION_EVIDENCE_GATE_SCHEMA,
    build_uwm_data_foundation_evidence_gate,
)


ROOT = Path(__file__).resolve().parents[1]


def test_data_foundation_evidence_gate_uses_prepared_artifacts_without_smoke_claims():
    gate = build_uwm_data_foundation_evidence_gate(
        manifest_path=ROOT / "docs/reports/uwm_data_foundation_manifest.csv",
        openaq_temporal_benchmark_path=ROOT
        / "data/uwm_public_proxy/chongqing_central/openaq_temporal_benchmark_2018_10/uwm_openaq_observed_temporal_benchmark.json",
        tap_external_dynamics_path=ROOT
        / "data/uwm_public_proxy/chongqing_central/tap_pm25_external_dynamics_2026_07_06/tap_external_dynamics_report.json",
        learned_rollout_path=ROOT
        / "data/uwm_public_proxy/chongqing_central/model_based_rl_graph_search_2026_07_05/uwm_offline_world_model_rollout_planner_admin_livability_spatial_graph_proxy.json",
        livability_intervention_package_path=ROOT
        / "data/uwm_public_proxy/chongqing_central/model_based_rl_graph_search_2026_07_05/uwm_livability_intervention_package_admin_livability_spatial_graph.json",
        local_planning_inventory_path=ROOT
        / "data/uwm_public_proxy/chongqing_central/local_planning_zip_audit_2026_07_05/uwm_local_planning_zip_inventory.csv",
        admin_spatial_graph_path=ROOT
        / "data/uwm_public_proxy/chongqing_central/admin_spatial_graph_2026_07_05/uwm_admin_spatial_adjacency_graph.json",
        causal_policy_evidence_path=ROOT
        / "data/uwm_public_proxy/chongqing_central/causal_policy_evidence_2026_07_06/uwm_causal_policy_evidence_gate.json",
        external_observed_holdout_suite_path=ROOT
        / "data/uwm_public_proxy/chongqing_central/external_observed_holdout_suite_2026_07_06/uwm_external_observed_holdout_suite.json",
        station_aligned_air_quality_holdout_path=ROOT
        / "data/uwm_public_proxy/chongqing_central/station_aligned_air_quality_holdout_2026_07_06/uwm_station_aligned_air_quality_holdout.json",
        data_calibrated_mechanism_table_path=ROOT
        / "data/uwm_public_proxy/chongqing_central/data_calibrated_mechanism_table_2026_07_06/uwm_data_calibrated_mechanism_table.json",
        data_calibrated_planner_replay_path=ROOT
        / "data/uwm_public_proxy/chongqing_central/data_calibrated_planner_replay_2026_07_06/uwm_data_calibrated_model_based_graph_search.json",
        scene_aligned_gridded_air_quality_holdout_path=ROOT
        / "data/uwm_public_proxy/chongqing_central/scene_aligned_gridded_air_quality_holdout_2026_07_06/uwm_scene_aligned_gridded_air_quality_holdout.json",
        multisource_livability_scene_path=ROOT
        / "data/uwm_public_proxy/chongqing_central/multisource_livability_scene_2026_07_06/uwm_multisource_livability_scene.json",
        osm_admin_mobility_crosswalk_path=ROOT
        / "data/uwm_public_proxy/chongqing_central/osm_admin_mobility_crosswalk_2026_07_06/uwm_osm_admin_mobility_crosswalk.json",
        building_floor_morphology_path=ROOT
        / "data/uwm_public_proxy/chongqing_central/building_floor_morphology_2026_07_07/uwm_building_floor_morphology.json",
        livability_endpoint_suite_path=ROOT
        / "data/uwm_public_proxy/chongqing_central/livability_endpoint_suite_2026_07_07/uwm_livability_endpoint_suite.json",
        endpoint_aligned_planner_evaluator_path=ROOT
        / "data/uwm_public_proxy/chongqing_central/endpoint_aligned_planner_evaluator_2026_07_07/uwm_endpoint_aligned_planner_evaluator.json",
        spatial_spillover_planner_evaluator_path=ROOT
        / "data/uwm_public_proxy/chongqing_central/spatial_spillover_planner_evaluator_2026_07_07/uwm_spatial_spillover_planner_evaluator.json",
        livability_decision_package_path=ROOT
        / "data/uwm_public_proxy/chongqing_central/livability_decision_package_2026_07_07/uwm_livability_decision_package.json",
        livability_rl_training_report_path=ROOT
        / "data/uwm_public_proxy/chongqing_central/livability_rl_training_2026_07_07/uwm_livability_rl_training_report.json",
        livability_graph_drl_training_report_path=ROOT
        / "data/uwm_public_proxy/chongqing_central/livability_graph_drl_training_2026_07_07/uwm_livability_graph_drl_training_report.json",
        gate_id="uwm-data-foundation-evidence-gate-real-artifacts-test",
        created_at="2026-07-05T22:30:00Z",
    )

    assert gate["schema"] == UWM_DATA_FOUNDATION_EVIDENCE_GATE_SCHEMA
    assert gate["data_foundation_scope"]["manifest_row_count"] == 75
    assert gate["data_foundation_scope"]["accepted_synthetic_statuses"] == [
        "real",
        "public_proxy",
        "fitted_proxy",
        "semi_synthetic",
        "synthetic",
        "restricted_expected",
    ]
    assert gate["data_foundation_scope"]["synthetic_status_counts"] == {
        "real": 18,
        "public_proxy": 48,
        "fitted_proxy": 2,
        "semi_synthetic": 3,
        "synthetic": 3,
        "restricted_expected": 1,
    }

    observed = gate["evidence_slices"]["openaq_observed_temporal_state"]
    assert observed["source_artifact_exists"] is True
    assert observed["scope"] == "observed_temporal_state_prediction_not_policy_outcome"
    assert observed["observation_count"] == 600
    assert observed["holdout_count"] == 180
    assert observed["overall_holdout_win_count"] == 150
    assert observed["overall_holdout_win_rate"] == 0.833333
    assert observed["pollutant_count"] == 6
    assert observed["pm25_dynamic_mae"] == 2.4
    assert observed["pm25_best_static_mae"] == 9.466667
    assert observed["overall_sign_tests"]["static_train_mean"]["one_sided_p_value"] < 1e-20
    assert observed["temporal_order_negative_control_passed"] is True
    assert observed["claim_level"] == "bounded_support"

    tap_transition = gate["evidence_slices"]["tap_external_temporal_transition"]
    assert tap_transition["source_artifact_exists"] is True
    assert tap_transition["scope"] == "tap_external_temporal_transition_without_spatial_claim"
    assert tap_transition["series_count"] == 10000
    assert tap_transition["holdout_count"] == 40000
    assert tap_transition["best_spatial_method"] == "spatial_residual_delta_ridge"
    assert tap_transition["best_transition_mae"] == 7.003808
    assert tap_transition["best_non_spatial_dynamic_mae"] == 7.011689
    assert tap_transition["paired_win_rate_vs_best_non_spatial_dynamic"] == 0.5077
    assert tap_transition["temporal_order_negative_control_passed"] is True
    assert tap_transition["spatial_negative_control_passed"] is False
    assert tap_transition["spatial_attribution_claim"] is False
    assert tap_transition["claim_level"] == "bounded_support"

    rollout = gate["evidence_slices"]["learned_world_model_rollout"]
    assert rollout["source_artifact_exists"] is True
    assert rollout["scope"] == "simulator_replay_learned_dynamics_not_observed_policy_outcome"
    assert rollout["transition_count"] == 355
    assert rollout["holdout_reward_mae"] < rollout["train_mean_reward_mae"]
    assert rollout["imagined_advantage_over_static"] > 0
    assert rollout["claim_level"] == "bounded_support"

    intervention = gate["evidence_slices"]["livability_intervention_package"]
    assert intervention["source_artifact_exists"] is True
    assert intervention["scope"] == "business_theory_aligned_proxy_package_not_observed_policy_outcome"
    assert intervention["synthetic_status"] == "synthetic"
    assert intervention["claim_level"] == "exploratory_only"
    assert intervention["predicted_delta"]["service_accessibility_delta"] > 0
    assert intervention["predicted_delta"]["equity_delta"] > 0
    assert intervention["equity_status"] == "equity_improves"
    assert "tap_or_authoritative_air_quality_required" in intervention["reported_remaining_gates"]
    assert "tap_or_authoritative_air_quality_required" not in intervention["remaining_gates"]
    assert "observed_policy_outcome_required" in intervention["remaining_gates"]

    local_assets = gate["evidence_slices"]["local_planning_data_foundation"]
    assert local_assets["source_artifact_exists"] is True
    assert local_assets["asset_counts"]["gaode_poi_2024"]["feature_count"] == 1194351
    assert local_assets["asset_counts"]["chongqing_central_buildings_2021"]["feature_count"] == 107452
    assert local_assets["asset_counts"]["chongqing_osm_roads_2021"]["feature_count"] == 50366
    assert local_assets["asset_counts"]["chongqing_unicom_commuting_2023_local"]["row_count"] == 2120

    admin_graph = gate["evidence_slices"]["admin_spatial_adjacency_graph"]
    assert admin_graph["source_artifact_exists"] is True
    assert admin_graph["node_count"] == 1017
    assert admin_graph["edge_count"] == 2847
    assert admin_graph["isolated_node_count"] == 0

    mechanism = gate["evidence_slices"]["data_calibrated_mechanism_table"]
    assert mechanism["source_artifact_exists"] is True
    assert mechanism["data_calibrated_mechanism_ready"] is True
    assert mechanism["openaq_observation_count"] == 600
    assert mechanism["tap_holdout_count"] == 40000
    assert mechanism["station_aligned_observation_count"] == 100
    assert mechanism["noaa_scene_observation_count"] == 224
    assert mechanism["admin_livability_row_count"] == 36
    assert mechanism["observed_policy_outcome_superiority_claim"] is False

    calibrated_replay = gate["evidence_slices"]["data_calibrated_planner_replay"]
    assert calibrated_replay["source_artifact_exists"] is True
    assert calibrated_replay["data_calibrated_planner_replay_ready"] is True
    assert calibrated_replay["mechanism_table_ready"] is True
    assert calibrated_replay["mechanism_table_id"] == (
        "uwm-data-calibrated-mechanism-table-2026-07-06"
    )
    assert calibrated_replay["transition_count"] == 355
    assert calibrated_replay["best_sequence_reward"] == 0.017180838
    assert calibrated_replay["static_single_step_reward"] == 0.003837146
    assert calibrated_replay["advantage_over_static_single_step"] == 0.013343692
    assert calibrated_replay["risk_calibrated_planner_replay_ready"] is True
    assert calibrated_replay["air_quality_uncertainty_calibration_ready"] is True
    assert calibrated_replay["air_quality_uncertainty_source_benchmark_id"] == (
        "uwm-scene-aligned-gridded-air-quality-holdout-2026-07-06"
    )
    assert calibrated_replay["air_quality_uncertainty_confidence_level"] == 0.9
    assert calibrated_replay["air_quality_uncertainty_calibration_count"] == 108
    assert calibrated_replay["air_quality_uwm_interval_score"] == 5.559385
    assert calibrated_replay["air_quality_static_interval_score"] == 13.7
    assert calibrated_replay["pm25_scene_range_ugm3"] == 16.4
    assert calibrated_replay["normalized_uwm_interval_score"] == 0.33898689
    assert calibrated_replay["best_sequence_risk_adjusted_reward"] == 0.016111838
    assert calibrated_replay["static_single_step_risk_adjusted_reward"] == 0.003334625
    assert calibrated_replay["risk_adjusted_advantage_over_static_single_step"] == 0.012777213
    assert calibrated_replay["observed_policy_outcome_superiority_claim"] is False

    scene_gridded = gate["evidence_slices"]["scene_aligned_gridded_air_quality_holdout"]
    assert scene_gridded["source_artifact_exists"] is True
    assert scene_gridded["scene_aligned_gridded_air_quality_holdout_ready"] is True
    assert scene_gridded["scene_aligned_station_calibrated_air_quality_holdout_ready"] is False
    assert scene_gridded["admin_unit_count"] == 36
    assert scene_gridded["holdout_count"] == 144
    assert scene_gridded["best_uwm_method"] == "spatial_idw_message_reconstruction"
    assert scene_gridded["best_uwm_mae"] == 1.058085
    assert scene_gridded["best_static_baseline_method"] == "static_train_mean"
    assert scene_gridded["best_static_baseline_mae"] == 2.783102
    assert scene_gridded["best_uwm_mae_reduction"] == 1.725017
    assert scene_gridded["spatial_shuffle_negative_control_passed"] is True
    assert scene_gridded["uwm_uncertainty_calibration_ready"] is True
    assert scene_gridded["uncertainty_confidence_level"] == 0.9
    assert scene_gridded["uncertainty_calibration_count"] == 108
    assert scene_gridded["uwm_interval_coverage"] == 0.944444
    assert scene_gridded["uwm_interval_score"] == 5.559385
    assert scene_gridded["static_interval_score"] == 13.7
    assert scene_gridded["uwm_interval_score_reduction"] == 8.140615
    assert scene_gridded["observed_policy_outcome_superiority_claim"] is False
    assert scene_gridded["empirical_superiority_claim"] is False

    multisource_scene = gate["evidence_slices"]["multisource_livability_scene"]
    assert multisource_scene["source_artifact_exists"] is True
    assert multisource_scene["multisource_livability_scene_ready"] is True
    assert multisource_scene["admin_unit_count"] == 36
    assert multisource_scene["data_source_count"] == 10
    assert multisource_scene["matched_source_count"] >= 7
    assert multisource_scene["osm_admin_mobility_crosswalk_projected"] is True
    assert multisource_scene["osm_crosswalk_matched_admin_units"] == 36
    assert multisource_scene["osm_assigned_road_segment_count_in_scene"] == 45449
    assert multisource_scene["air_quality_multisource_mae"] == 0.949891
    assert multisource_scene["air_quality_best_single_source_mae"] == 0.952794
    assert multisource_scene["air_quality_mae_reduction_vs_best_single_source"] == 0.002903
    assert multisource_scene["observed_policy_outcome_superiority_claim"] is False

    osm_mobility = gate["evidence_slices"]["osm_admin_mobility_crosswalk"]
    assert osm_mobility["source_artifact_exists"] is True
    assert osm_mobility["osm_admin_mobility_crosswalk_ready"] is True
    assert osm_mobility["admin_unit_count"] == 36
    assert osm_mobility["assigned_road_segment_count"] == 45449
    assert osm_mobility["service_accessibility_mobility_mae"] == 12.887057
    assert osm_mobility["service_accessibility_best_static_mae"] == 14.028006
    assert osm_mobility["service_accessibility_mae_reduction"] == 1.140949
    assert osm_mobility["observed_policy_outcome_superiority_claim"] is False

    building_morphology = gate["evidence_slices"]["building_floor_morphology"]
    assert building_morphology["source_artifact_exists"] is True
    assert building_morphology["building_floor_morphology_ready"] is True
    assert building_morphology["scope"] == (
        "building_floor_25d_morphology_not_full_3d_city_model"
    )
    assert building_morphology["admin_unit_count"] == 36
    assert building_morphology["source_building_record_count"] == 107452
    assert building_morphology["assigned_building_count"] == 44887
    assert building_morphology["total_floor_count"] == 322665
    assert building_morphology["max_floor"] == 66
    assert building_morphology["ready_endpoint_count"] == 2
    assert building_morphology["endpoint_count"] == 2
    assert building_morphology["true_3d_claim"] is False
    assert building_morphology["observed_policy_outcome_superiority_claim"] is False

    endpoint_suite = gate["evidence_slices"]["livability_endpoint_suite"]
    assert endpoint_suite["source_artifact_exists"] is True
    assert endpoint_suite["livability_endpoint_suite_ready"] is True
    assert endpoint_suite["endpoint_count"] == 3
    assert endpoint_suite["ready_endpoint_count"] == 3
    assert endpoint_suite["mean_relative_mae_reduction_vs_best_traditional"] == 0.115337
    assert endpoint_suite["min_relative_mae_reduction_vs_best_traditional"] == 0.003047
    assert endpoint_suite["observed_policy_outcome_superiority_claim"] is False

    endpoint_planner = gate["evidence_slices"]["endpoint_aligned_planner_evaluator"]
    assert endpoint_planner["source_artifact_exists"] is True
    assert endpoint_planner["endpoint_aligned_planner_evaluator_ready"] is True
    assert endpoint_planner["endpoint_count"] == 3
    assert endpoint_planner["planner_endpoint_aligned_score"] == 0.001407208
    assert endpoint_planner["static_endpoint_aligned_score"] == 0.000661508
    assert endpoint_planner["endpoint_aligned_advantage_over_static"] == 0.0007457
    assert endpoint_planner["endpoint_aligned_advantage_ratio"] == 2.127273
    assert endpoint_planner["observed_policy_outcome_superiority_claim"] is False

    spillover_planner = gate["evidence_slices"]["spatial_spillover_planner_evaluator"]
    assert spillover_planner["source_artifact_exists"] is True
    assert spillover_planner["spatial_spillover_planner_evaluator_ready"] is True
    assert spillover_planner["planner_neighbor_benefited_unit_count"] == 11
    assert spillover_planner["static_neighbor_benefited_unit_count"] == 5
    assert spillover_planner["neighbor_livability_delta_advantage"] == 0.272680076
    assert spillover_planner["neighbor_livability_delta_advantage_ratio"] == 2.2
    assert spillover_planner["observed_policy_outcome_superiority_claim"] is False

    decision_package = gate["evidence_slices"]["livability_decision_package"]
    assert decision_package["source_artifact_exists"] is True
    assert decision_package["livability_decision_package_ready"] is True
    assert decision_package["action_count"] == 2
    assert decision_package["target_unit_count"] == 2
    assert decision_package["endpoint_aligned_advantage_over_static"] == 0.0007457
    assert decision_package["risk_adjusted_advantage_over_static"] == 0.012777213
    assert decision_package["neighbor_livability_delta_advantage"] == 0.272680076
    assert decision_package["planner_benefited_unit_count"] == 13
    assert decision_package["static_benefited_unit_count"] == 6
    assert decision_package["graph_drl_training_ready"] is True
    assert decision_package["graph_drl_algorithm"] == "graph_dqn_fitted_q_model_based_rl"
    assert decision_package["graph_drl_training_sample_count"] == 3600
    assert decision_package["graph_policy_or_value_network_trained"] is True
    assert decision_package["graph_drl_q_return_mae"] == 0.000109541
    assert decision_package["graph_drl_advantage_over_traditional_static"] > 0
    assert decision_package["observed_policy_outcome_superiority_claim"] is False

    graph_drl = gate["evidence_slices"]["livability_graph_drl_training"]
    assert graph_drl["source_artifact_exists"] is True
    assert graph_drl["livability_graph_drl_training_ready"] is True
    assert graph_drl["algorithm"] == "graph_dqn_fitted_q_model_based_rl"
    assert graph_drl["is_deep_rl"] is True
    assert graph_drl["uses_graph_message_passing"] is True
    assert graph_drl["policy_or_value_network_trained"] is True
    assert graph_drl["training_sample_count"] == 3600
    assert graph_drl["q_return_mae"] < graph_drl["train_mean_return_mae"]
    assert graph_drl["advantage_over_traditional_static"] > 0
    assert graph_drl["observed_policy_outcome_superiority_claim"] is False

    assert gate["observed_state_prediction_superiority_claim"] is True
    assert gate["external_temporal_transition_superiority_claim"] is True
    assert gate["observed_policy_outcome_superiority_claim"] is False
    assert "observed_policy_outcome_required" in gate["remaining_gates"]
    assert "tap_or_authoritative_air_quality_required" not in gate["remaining_gates"]
    assert "scene_aligned_station_calibrated_air_quality_holdout_required" in gate["remaining_gates"]
    assert gate["claim_guard"]["synthetic_or_smoke_blocked_from_empirical_policy_claim"] is True
    assert "synthetic_air_quality_placeholder" in gate["claim_guard"]["blocked_dataset_ids"]
    assert "uwm_livability_intervention_package_admin_livability_spatial_graph" in gate["claim_guard"][
        "blocked_dataset_ids"
    ]
    assert gate["data_foundation_scope"]["source_type_counts"]["planning_sample"] == 15
    assert gate["empirical_superiority_claim"] is False
    claims = {claim["claim"] for claim in gate["supported_claims"]}
    assert "tap_external_temporal_dynamics_advantage_without_spatial_claim" in claims
    assert "data_calibrated_simulator_mechanism_replaces_hardcoded_coefficients" in claims
    assert "data_calibrated_planner_replay_advantage_over_static_heuristic" in claims
    assert "risk_calibrated_planner_replay_advantage_over_static_heuristic" in claims
    assert "scene_aligned_gridded_pm25_spatial_message_advantage_over_static_baselines" in claims
    assert (
        "scene_aligned_gridded_pm25_conformal_uncertainty_advantage_over_static_baseline"
        in claims
    )
    assert (
        "multisource_livability_scene_air_quality_head_beats_single_source_baselines"
        in claims
    )
    assert (
        "osm_admin_mobility_crosswalk_service_accessibility_head_beats_static_baselines"
        in claims
    )
    assert (
        "building_floor_25d_morphology_service_endpoint_head_beats_2d_baselines"
        in claims
    )
    assert (
        "uwm_final_livability_endpoint_suite_beats_traditional_baselines"
        in claims
    )
    assert (
        "endpoint_aligned_planner_replay_advantage_over_static_heuristic"
        in claims
    )
    assert (
        "spatial_spillover_planner_replay_advantage_over_static_heuristic"
        in claims
    )
    assert (
        "uwm_livability_decision_package_beats_static_heuristic_on_validated_endpoints_spillover_and_risk"
        in claims
    )
    assert (
        "trained_model_based_q_agent_improves_same_scene_static_livability_baseline"
        in claims
    )
    assert (
        "graph_dqn_value_network_improves_same_scene_static_livability_baseline"
        in claims
    )

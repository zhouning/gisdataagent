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
        full_admin_service_accessibility_surface_path=ROOT
        / "data/uwm_public_proxy/chongqing_central/full_admin_service_accessibility_surface_2026_07_08/uwm_full_admin_service_accessibility_surface.json",
        full_admin_service_surface_quality_audit_path=ROOT
        / "data/uwm_public_proxy/chongqing_central/full_admin_service_surface_quality_audit_2026_07_08/uwm_full_admin_service_surface_quality_audit.json",
        geographic_similarity_kernel_path=ROOT
        / "data/uwm_public_proxy/chongqing_central/geographic_similarity_kernel_2026_07_08/uwm_geographic_similarity_kernel.json",
        full_admin_mobility_graph_path=ROOT
        / "data/uwm_public_proxy/chongqing_central/full_admin_mobility_graph_2026_07_10/full_admin_mobility_graph.json",
        full_admin_action_inventory_path=ROOT
        / "data/uwm_public_proxy/chongqing_central/full_admin_action_inventory_2026_07_08/uwm_full_admin_action_inventory.json",
        production_action_catalog_path=ROOT
        / "data/uwm_public_proxy/chongqing_central/production_action_catalog_2026_07_08/uwm_production_action_catalog.json",
        production_governance_data_contract_path=ROOT
        / "data/uwm_public_proxy/chongqing_central/production_governance_data_contract_2026_07_08/uwm_production_governance_data_contract.json",
        production_governance_data_adapter_readiness_path=ROOT
        / "data/uwm_public_proxy/chongqing_central/production_governance_data_adapter_readiness_2026_07_08/uwm_production_governance_data_adapter_readiness.json",
        production_governance_input_templates_path=ROOT
        / "data/uwm_public_proxy/chongqing_central/production_governance_input_templates_2026_07_08/uwm_production_governance_input_templates.json",
        production_governance_linkage_audit_path=ROOT
        / "data/uwm_public_proxy/chongqing_central/production_governance_linkage_audit_2026_07_08/uwm_production_governance_linkage_audit.json",
        production_governance_planner_binding_gate_path=ROOT
        / "data/uwm_public_proxy/chongqing_central/production_governance_planner_binding_gate_2026_07_08/uwm_production_governance_planner_binding_gate.json",
        spatial_causal_question_registry_path=ROOT
        / "data/uwm_public_proxy/chongqing_central/spatial_causal_question_registry_2026_07_09/uwm_spatial_causal_question_registry.json",
        full_admin_graph_planner_replay_path=ROOT
        / "data/uwm_public_proxy/chongqing_central/data_calibrated_planner_replay_full_admin_graph_2026_07_08/uwm_full_admin_graph_model_based_graph_search.json",
        full_admin_graph_drl_training_report_path=ROOT
        / "data/uwm_public_proxy/chongqing_central/livability_graph_drl_training_full_admin_graph_2026_07_08/uwm_full_admin_graph_livability_graph_drl_training_report.json",
        full_admin_learned_world_model_rollout_path=ROOT
        / "data/uwm_public_proxy/chongqing_central/learned_world_model_rollout_full_admin_graph_2026_07_08/uwm_full_admin_graph_learned_world_model_rollout.json",
        full_admin_livability_decision_package_path=ROOT
        / "data/uwm_public_proxy/chongqing_central/full_admin_livability_decision_package_2026_07_08/uwm_full_admin_livability_decision_package.json",
        core_action_conditioned_dynamics_benchmark_path=ROOT
        / "data/uwm_public_proxy/chongqing_central/core_action_conditioned_dynamics_benchmark_2026_07_09/uwm_core_action_conditioned_dynamics_benchmark.json",
        core_world_model_policy_improvement_benchmark_path=ROOT
        / "data/uwm_public_proxy/chongqing_central/core_world_model_policy_improvement_benchmark_2026_07_09/uwm_core_world_model_policy_improvement_benchmark.json",
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

    full_service_surface = gate["evidence_slices"][
        "full_admin_service_accessibility_surface"
    ]
    assert full_service_surface["source_artifact_exists"] is True
    assert full_service_surface[
        "full_admin_service_accessibility_surface_ready"
    ] is True
    assert full_service_surface["admin_unit_count"] == 1017
    assert full_service_surface["source_admin_unit_count"] == 1017
    assert full_service_surface["source_poi_point_count"] == 1194351
    assert full_service_surface["source_road_count"] == 50366
    assert full_service_surface["service_missing_admin_count"] == 0
    assert full_service_surface["admin_units_with_accessibility_score"] == 1017
    assert full_service_surface["admin_units_with_road_context"] > 900
    assert full_service_surface["total_service_point_count"] > 1000000
    assert full_service_surface["total_essential_service_count"] > 10000
    assert full_service_surface["observed_policy_outcome_superiority_claim"] is False
    assert full_service_surface["empirical_superiority_claim"] is False

    full_service_quality = gate["evidence_slices"][
        "full_admin_service_surface_quality_audit"
    ]
    assert full_service_quality["source_artifact_exists"] is True
    assert full_service_quality[
        "full_admin_service_surface_quality_audit_ready"
    ] is True
    assert full_service_quality["admin_unit_count"] == 1017
    assert full_service_quality["endpoint_count"] == 2
    assert full_service_quality["ready_endpoint_count"] == 2
    assert full_service_quality["essential_service_model_mae"] == 16.728755
    assert full_service_quality["essential_service_best_baseline_mae"] == 57.472199
    assert full_service_quality["travel_time_model_mae"] == 2.17547
    assert full_service_quality["travel_time_best_baseline_mae"] == 2.192174
    assert full_service_quality["target_rotation_negative_controls_passed"] is True
    assert full_service_quality["observed_trip_time_claim"] is False
    assert full_service_quality["observed_policy_outcome_superiority_claim"] is False

    geographic_similarity = gate["evidence_slices"]["geographic_similarity_kernel"]
    assert geographic_similarity["source_artifact_exists"] is True
    assert geographic_similarity["geographic_similarity_kernel_ready"] is True
    assert geographic_similarity["panel_unit_count"] == 1017
    assert geographic_similarity["similarity_edge_count"] == 5085
    assert geographic_similarity["non_adjacent_similarity_edge_count"] == 4835
    assert geographic_similarity["rotated_target_similarity_control_passed"] is True
    assert geographic_similarity["uses_coordinates_as_similarity_features"] is False
    assert geographic_similarity["observed_policy_outcome_superiority_claim"] is False

    full_admin_mobility = gate["evidence_slices"]["full_admin_mobility_graph"]
    assert full_admin_mobility["source_artifact_exists"] is True
    assert full_admin_mobility["full_admin_mobility_graph_ready"] is True
    assert full_admin_mobility["claim_level"] == "bounded_support"
    assert full_admin_mobility["node_count"] == 1017
    assert full_admin_mobility["edge_count"] == 5085
    assert full_admin_mobility["mobility_similarity_edge_count"] == 5085
    assert full_admin_mobility["travel_time_min_mean"] > 0.0
    assert full_admin_mobility["road_segment_count_sum"] > 50000
    assert full_admin_mobility["unicom_directed_edge_count"] == 1067
    assert full_admin_mobility["osm_highway_edge_count"] == 45468
    assert full_admin_mobility["osm_crosswalk_assigned_road_segment_count"] == 45449
    assert full_admin_mobility["observed_od_flow_claim"] is False
    assert full_admin_mobility["observed_trip_time_claim"] is False
    assert full_admin_mobility["observed_policy_outcome_superiority_claim"] is False

    full_admin_actions = gate["evidence_slices"]["full_admin_action_inventory"]
    assert full_admin_actions["source_artifact_exists"] is True
    assert full_admin_actions["full_admin_action_inventory_ready"] is True
    assert full_admin_actions["schema"] == "uwm.full_admin_action_inventory.v1"
    assert full_admin_actions["experiment_scope"] == "full_admin_graph"
    assert full_admin_actions["graph_node_count"] == 1017
    assert full_admin_actions["graph_edge_count"] == 7932
    assert full_admin_actions["available_action_count"] == 1137
    assert full_admin_actions["candidate_action_mask_trace_count"] == 3051
    assert full_admin_actions["action_type_counts"] == {
        "increase_green_infrastructure": 81,
        "traffic_emission_control": 77,
        "add_community_service": 979,
    }
    assert full_admin_actions["mask_reason_counts"] == {
        "heat_risk_above_threshold": 81,
        "air_pollution_exposure_above_threshold": 77,
        "service_accessibility_below_threshold": 979,
    }
    assert full_admin_actions["spatial_causal_contract_binding_ready"] is True
    assert full_admin_actions["spatial_causal_feasible_action_count"] == 1137
    assert full_admin_actions["spatial_causal_attached_action_count"] == 1137
    assert full_admin_actions["spatial_causal_missing_contract_action_count"] == 0
    assert (
        full_admin_actions[
            "spatial_causal_underidentified_policy_effect_action_count"
        ]
        == 1137
    )
    assert full_admin_actions["spatial_causal_policy_outcome_claim_action_count"] == 0
    assert set(full_admin_actions["action_type_definitions"]) == {
        "increase_green_infrastructure",
        "traffic_emission_control",
        "add_community_service",
    }
    assert (
        full_admin_actions["action_type_definitions"]["increase_green_infrastructure"][
            "state_trigger"
        ]
        == "heat_risk >= 0.7"
    )
    assert (
        full_admin_actions["action_type_definitions"]["traffic_emission_control"][
            "state_trigger"
        ]
        == "air_pollution_exposure >= 0.6"
    )
    assert (
        full_admin_actions["action_type_definitions"]["add_community_service"][
            "state_trigger"
        ]
        == "service_accessibility <= 0.5"
    )
    assert full_admin_actions["sample_action_ids"] == [
        "increase_green_infrastructure-涪陵区|蔺市镇|498",
        "traffic_emission_control-涪陵区|蔺市镇|498",
        "add_community_service-涪陵区|蔺市镇|498",
    ]
    assert full_admin_actions["observed_policy_outcome_superiority_claim"] is False
    assert full_admin_actions["empirical_superiority_claim"] is False

    production_action_catalog = gate["evidence_slices"]["production_action_catalog"]
    assert production_action_catalog["source_artifact_exists"] is True
    assert production_action_catalog["production_action_catalog_ready"] is True
    assert production_action_catalog["schema"] == "uwm.production_action_catalog.v1"
    assert production_action_catalog["experiment_scope"] == "full_admin_graph"
    assert production_action_catalog["production_action_type_count"] == 57
    assert production_action_catalog["currently_bound_action_type_count"] == 3
    assert production_action_catalog["currently_bound_feasible_action_count"] == 1137
    assert production_action_catalog["current_candidate_binding_count"] == 1137
    assert production_action_catalog["planner_production_action_ready"] is False
    assert production_action_catalog["constraint_cost_model_ready"] is False
    assert production_action_catalog["policy_project_history_ready"] is False
    assert production_action_catalog["observed_policy_outcome_panel_ready"] is False
    assert production_action_catalog["observed_policy_outcome_superiority_claim"] is False
    assert production_action_catalog["empirical_superiority_claim"] is False

    governance_contract = gate["evidence_slices"][
        "production_governance_data_contract"
    ]
    assert governance_contract["source_artifact_exists"] is True
    assert governance_contract["production_governance_data_contract_ready"] is True
    assert governance_contract["schema"] == (
        "uwm.production_governance_data_contract.v1"
    )
    assert governance_contract["experiment_scope"] == "full_admin_graph"
    assert governance_contract["production_action_type_count"] == 57
    assert governance_contract["currently_bound_feasible_action_count"] == 1137
    assert governance_contract["required_governance_table_count"] == 5
    assert governance_contract["ready_governance_table_count"] == 0
    assert governance_contract["planning_sample_source_count"] == 15
    assert governance_contract["planner_governance_binding_ready"] is False
    assert governance_contract["policy_project_history_ready"] is False
    assert governance_contract["constraint_cost_model_ready"] is False
    assert governance_contract["observed_outcome_panel_ready"] is False
    assert governance_contract["observed_policy_outcome_superiority_claim"] is False
    assert governance_contract["empirical_superiority_claim"] is False

    governance_adapter = gate["evidence_slices"][
        "production_governance_data_adapter_readiness"
    ]
    assert governance_adapter["source_artifact_exists"] is True
    assert governance_adapter["production_governance_data_adapter_readiness_ready"] is True
    assert governance_adapter["schema"] == (
        "uwm.production_governance_data_adapter_readiness.v1"
    )
    assert governance_adapter["experiment_scope"] == "full_admin_graph"
    assert governance_adapter["expected_table_count"] == 5
    assert governance_adapter["ready_table_count"] == 0
    assert governance_adapter["missing_source_table_count"] == 5
    assert governance_adapter["accepted_authoritative_row_count"] == 0
    assert governance_adapter["all_required_tables_ready"] is False
    assert governance_adapter["planner_governance_binding_ready"] is False
    assert governance_adapter["observed_policy_outcome_superiority_claim"] is False
    assert governance_adapter["empirical_superiority_claim"] is False

    governance_templates = gate["evidence_slices"][
        "production_governance_input_templates"
    ]
    assert governance_templates["source_artifact_exists"] is True
    assert governance_templates["production_governance_input_templates_ready"] is True
    assert governance_templates["schema"] == (
        "uwm.production_governance_input_templates.v1"
    )
    assert governance_templates["experiment_scope"] == "full_admin_graph"
    assert governance_templates["template_count"] == 5
    assert governance_templates["required_field_count"] == 54
    assert governance_templates["adapter_ready_table_count"] == 0
    assert governance_templates["adapter_missing_source_table_count"] == 5
    assert governance_templates["template_dir_is_adapter_input_dir"] is False
    assert governance_templates["authoritative_input_claim"] is False
    assert governance_templates["observed_policy_outcome_superiority_claim"] is False
    assert governance_templates["empirical_superiority_claim"] is False

    governance_linkage = gate["evidence_slices"][
        "production_governance_linkage_audit"
    ]
    assert governance_linkage["source_artifact_exists"] is True
    assert governance_linkage["production_governance_linkage_audit_ready"] is True
    assert governance_linkage["schema"] == (
        "uwm.production_governance_linkage_audit.v1"
    )
    assert governance_linkage["experiment_scope"] == "full_admin_graph"
    assert governance_linkage["expected_table_count"] == 5
    assert governance_linkage["present_table_count"] == 0
    assert governance_linkage["missing_table_count"] == 5
    assert governance_linkage["linked_project_count"] == 0
    assert governance_linkage["unlinked_project_count"] == 0
    assert governance_linkage["all_required_tables_present"] is False
    assert governance_linkage["governance_linkage_ready"] is False
    assert governance_linkage["planner_governance_binding_ready"] is False
    assert governance_linkage["observed_policy_outcome_superiority_claim"] is False
    assert governance_linkage["empirical_superiority_claim"] is False

    governance_binding_gate = gate["evidence_slices"][
        "production_governance_planner_binding_gate"
    ]
    assert governance_binding_gate["source_artifact_exists"] is True
    assert governance_binding_gate[
        "production_governance_planner_binding_gate_ready"
    ] is True
    assert governance_binding_gate["schema"] == (
        "uwm.production_governance_planner_binding_gate.v1"
    )
    assert governance_binding_gate["experiment_scope"] == "full_admin_graph"
    assert governance_binding_gate["binding_gate_ready"] is True
    assert governance_binding_gate["authoritative_governance_data_closure_ready"] is False
    assert governance_binding_gate["planner_governance_binding_ready"] is False
    assert governance_binding_gate["required_gate_count"] == 9
    assert governance_binding_gate["passed_gate_count"] == 2
    assert governance_binding_gate["blocking_gate_count"] == 7
    assert governance_binding_gate["missing_table_count"] == 5
    assert governance_binding_gate["accepted_authoritative_row_count"] == 0
    assert governance_binding_gate["linked_project_count"] == 0
    assert governance_binding_gate["observed_policy_outcome_superiority_claim"] is False
    assert governance_binding_gate["empirical_superiority_claim"] is False

    spatial_causal_registry = gate["evidence_slices"][
        "spatial_causal_question_registry"
    ]
    assert spatial_causal_registry["source_artifact_exists"] is True
    assert spatial_causal_registry["spatial_causal_question_registry_ready"] is True
    assert spatial_causal_registry["schema"] == (
        "uwm.spatial_causal_question_registry.v1"
    )
    assert spatial_causal_registry["experiment_scope"] == "full_admin_graph"
    assert spatial_causal_registry["active_causal_question_count"] == 3
    assert spatial_causal_registry["currently_bound_feasible_action_count"] == 1137
    assert spatial_causal_registry["authoritative_required_table_count"] == 5
    assert spatial_causal_registry["ready_authoritative_table_count"] == 0
    assert spatial_causal_registry["identified_policy_effect_question_count"] == 0
    assert spatial_causal_registry["underidentified_policy_effect_question_count"] == 3
    assert spatial_causal_registry["algorithmic_causal_diagnostic_ready"] is True
    assert spatial_causal_registry["observed_outcome_panel_ready"] is False
    assert spatial_causal_registry["causal_effect_calibration_ready"] is False
    assert spatial_causal_registry["planner_governance_binding_ready"] is False
    assert spatial_causal_registry["observed_policy_outcome_superiority_claim"] is False
    assert spatial_causal_registry["empirical_superiority_claim"] is False
    assert spatial_causal_registry["claim_level"] == "spatial_causal_question_contract_only"
    assert set(spatial_causal_registry["active_action_types"]) == {
        "increase_green_infrastructure",
        "traffic_emission_control",
        "add_community_service",
    }

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

    full_admin_replay = gate["evidence_slices"]["full_admin_graph_planner_replay"]
    assert full_admin_replay["full_admin_graph_planner_replay_ready"] is True
    assert full_admin_replay["experiment_scope"] == "full_admin_graph"
    assert full_admin_replay["graph_node_count"] == 1017
    assert full_admin_replay["graph_edge_count"] == 7932
    assert full_admin_replay["geographic_similarity_edge_count"] == 5085
    assert full_admin_replay["non_adjacent_similarity_edge_count"] == 4835
    assert full_admin_replay["available_action_count"] == 1137
    assert full_admin_replay["transition_count"] == 6817
    assert full_admin_replay["advantage_over_static_single_step"] > 0
    assert full_admin_replay["air_quality_uncertainty_calibration_ready"] is True
    assert full_admin_replay["risk_calibrated_planner_replay_ready"] is True
    assert full_admin_replay["risk_adjusted_advantage_over_static_single_step"] > 0
    assert full_admin_replay["observed_policy_outcome_superiority_claim"] is False

    full_admin_drl = gate["evidence_slices"]["full_admin_graph_drl_training"]
    assert full_admin_drl["full_admin_graph_drl_training_ready"] is True
    assert full_admin_drl["experiment_scope"] == "full_admin_graph"
    assert full_admin_drl["graph_node_count"] == 1017
    assert full_admin_drl["graph_edge_count"] == 7932
    assert full_admin_drl["geographic_similarity_edge_count"] == 5085
    assert full_admin_drl["available_action_count"] == 1137
    assert full_admin_drl["training_sample_count"] == 1248
    assert full_admin_drl["sampled_first_action_count"] == 96
    assert full_admin_drl["sampled_second_action_limit"] == 12
    assert full_admin_drl["q_return_mae"] < full_admin_drl["train_mean_return_mae"]
    assert full_admin_drl["advantage_over_traditional_static"] > 0
    assert full_admin_drl["observed_policy_outcome_superiority_claim"] is False

    full_admin_learned = gate["evidence_slices"][
        "full_admin_learned_world_model_rollout"
    ]
    assert full_admin_learned[
        "full_admin_learned_world_model_rollout_ready"
    ] is True
    assert full_admin_learned["experiment_scope"] == "full_admin_graph"
    assert full_admin_learned["graph_node_count"] == 1017
    assert full_admin_learned["graph_edge_count"] == 7932
    assert full_admin_learned["available_action_count"] == 1137
    assert full_admin_learned["transition_count"] == 6817
    assert full_admin_learned["reward_mae"] < full_admin_learned[
        "train_mean_reward_mae"
    ]
    assert full_admin_learned["imagined_advantage_over_static_single_step"] > 0
    assert full_admin_learned["imagined_advantage_over_one_step_policy"] > 0
    assert full_admin_learned["observed_policy_outcome_superiority_claim"] is False

    core_dynamics = gate["evidence_slices"]["core_action_conditioned_dynamics_benchmark"]
    assert core_dynamics["source_artifact_exists"] is True
    assert core_dynamics["core_action_conditioned_dynamics_ready"] is True
    assert core_dynamics["experiment_scope"] == "full_admin_graph"
    assert core_dynamics["graph_node_count"] == 1017
    assert core_dynamics["graph_edge_count"] == 7932
    assert core_dynamics["available_action_count"] == 1137
    assert core_dynamics["transition_count"] == 6817
    assert core_dynamics["holdout_count"] == 973
    assert core_dynamics["action_conditioning_gate_passed"] is True
    assert core_dynamics["observed_policy_outcome_superiority_claim"] is False

    core_policy = gate["evidence_slices"][
        "core_world_model_policy_improvement_benchmark"
    ]
    assert core_policy["source_artifact_exists"] is True
    assert core_policy["core_world_model_policy_improvement_ready"] is True
    assert core_policy["experiment_scope"] == "full_admin_graph"
    assert core_policy["graph_node_count"] == 1017
    assert core_policy["graph_edge_count"] == 7932
    assert core_policy["available_action_count"] == 1137
    assert core_policy["transition_count"] == 6817
    assert core_policy["holdout_count"] == 973
    assert core_policy["policy_improvement_gate_passed"] is True
    assert core_policy["policy_advantage_over_static"] > 0
    assert core_policy["policy_advantage_over_one_step"] > 0
    assert core_policy["observed_policy_outcome_superiority_claim"] is False

    production_world_model = gate["production_world_model_readiness"]
    assert production_world_model["bounded_research_world_model_ready"] is True
    assert production_world_model["production_ready"] is False
    assert production_world_model["production_readiness_claim"] is False
    assert production_world_model["base_simulator_backend"] == (
        "mechanistic_urban_livability_v0"
    )
    assert production_world_model[
        "mechanistic_rollout_backend_allowed_for_bounded_research_only"
    ] is True
    assert production_world_model["core_action_conditioned_dynamics_ready"] is True
    assert production_world_model["core_world_model_policy_improvement_ready"] is True
    assert production_world_model["bounded_mobility_projection_graph_ready"] is True
    assert production_world_model["observed_mobility_or_travel_time_graph_ready"] is False
    assert production_world_model["observed_policy_outcome_ready"] is False
    assert production_world_model["scene_aligned_station_calibrated_air_quality_holdout_ready"] is False
    assert production_world_model["planner_governance_binding_ready"] is False
    assert "observed_mobility_or_travel_time_graph_required" in production_world_model[
        "blocking_gates"
    ]
    assert "observed_policy_outcome_holdout_required" in production_world_model[
        "blocking_gates"
    ]

    full_admin_decision = gate["evidence_slices"][
        "full_admin_livability_decision_package"
    ]
    assert full_admin_decision["source_artifact_exists"] is True
    assert full_admin_decision[
        "full_admin_livability_decision_package_ready"
    ] is True
    assert full_admin_decision["experiment_scope"] == "full_admin_graph"
    assert full_admin_decision["graph_node_count"] == 1017
    assert full_admin_decision["graph_edge_count"] == 7932
    assert full_admin_decision["available_action_count"] == 1137
    assert full_admin_decision["transition_count"] == 6817
    assert full_admin_decision["planner_governance_binding_ready"] is False
    assert full_admin_decision["spatial_causal_contract_binding_ready"] is True
    assert full_admin_decision["spatial_causal_attached_action_count"] == 6
    assert full_admin_decision["spatial_causal_missing_contract_action_count"] == 0
    assert (
        full_admin_decision[
            "spatial_causal_underidentified_policy_effect_action_count"
        ]
        == 6
    )
    assert full_admin_decision["spatial_causal_policy_outcome_claim_action_count"] == 0
    assert full_admin_decision["observed_policy_outcome_superiority_claim"] is False
    assert full_admin_decision["empirical_superiority_claim"] is False
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
    assert "observed_mobility_or_travel_time_graph_required" in gate["remaining_gates"]
    assert "planner_governance_binding_required" in gate["remaining_gates"]
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
    assert (
        "full_admin_service_accessibility_surface_covers_all_admin_units_from_local_poi_and_road_assets"
        in claims
    )
    assert (
        "full_admin_service_surface_proxy_quality_beats_static_and_negative_controls"
        in claims
    )
    assert "tap_external_temporal_dynamics_advantage_without_spatial_claim" in claims
    assert "data_calibrated_simulator_mechanism_replaces_hardcoded_coefficients" in claims
    assert "data_calibrated_planner_replay_advantage_over_static_heuristic" in claims
    assert "risk_calibrated_planner_replay_advantage_over_static_heuristic" in claims
    assert "full_admin_graph_planner_replay_advantage_over_static_heuristic" in claims
    assert (
        "full_admin_graph_risk_calibrated_planner_replay_advantage_over_static_heuristic"
        in claims
    )
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
    assert (
        "full_admin_graph_dqn_value_network_improves_same_scene_static_livability_baseline"
        in claims
    )
    assert (
        "full_admin_graph_learned_world_model_rollout_improves_imagined_static_and_one_step_baselines"
        in claims
    )
    assert (
        "full_admin_graph_feasible_action_inventory_enumerates_real_data_graph_mdp_actions"
        in claims
    )
    assert (
        "production_action_catalog_contract_binds_current_full_admin_actions_and_blocks_unverified_targets"
        in claims
    )
    assert (
        "production_governance_data_contract_defines_non_smoke_policy_constraint_outcome_requirements"
        in claims
    )
    assert (
        "production_governance_data_adapter_readiness_audits_authoritative_table_availability_without_fake_rows"
        in claims
    )
    assert (
        "production_governance_input_templates_define_authoritative_table_headers_without_fake_rows"
        in claims
    )
    assert (
        "production_governance_linkage_audit_checks_cross_table_policy_constraint_outcome_closure"
        in claims
    )
    assert (
        "production_governance_planner_binding_gate_blocks_search_until_authoritative_data_closure"
        in claims
    )
    assert (
        "spatial_causal_question_contracts_define_do_queries_and_block_policy_overclaims"
        in claims
    )

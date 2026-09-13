import json
from pathlib import Path

from data_agent.uwm.data_foundation_evidence_gate import (
    build_uwm_data_foundation_evidence_gate,
)
from data_agent.uwm.full_admin_livability_decision_package import (
    UWM_FULL_ADMIN_LIVABILITY_DECISION_PACKAGE_SCHEMA,
    build_uwm_full_admin_livability_decision_package,
)
from data_agent.uwm.livability_graph_drl import GRAPH_NODE_FEATURE_NAMES
from data_agent.uwm.livability_data_catalog import (
    build_uwm_livability_data_catalog,
)
from data_agent.uwm.offline_world_model_policy import FEATURE_NAMES


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data/uwm_public_proxy/chongqing_central"
ARTIFACT_PATH = (
    DATA_ROOT
    / "full_admin_livability_decision_package_2026_07_08/uwm_full_admin_livability_decision_package.json"
)


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _build_package() -> dict:
    return build_uwm_full_admin_livability_decision_package(
        package_id="uwm-full-admin-livability-decision-package-test",
        created_at="2026-07-08T18:30:00Z",
        full_admin_graph_planner_replay=_read_json(
            DATA_ROOT
            / "data_calibrated_planner_replay_full_admin_graph_2026_07_08/uwm_full_admin_graph_model_based_graph_search.json"
        ),
        full_admin_graph_drl_training_report=_read_json(
            DATA_ROOT
            / "livability_graph_drl_training_full_admin_graph_2026_07_08/uwm_full_admin_graph_livability_graph_drl_training_report.json"
        ),
        full_admin_learned_world_model_rollout=_read_json(
            DATA_ROOT
            / "learned_world_model_rollout_full_admin_graph_2026_07_08/uwm_full_admin_graph_learned_world_model_rollout.json"
        ),
        geographic_similarity_kernel=_read_json(
            DATA_ROOT
            / "geographic_similarity_kernel_2026_07_08/uwm_geographic_similarity_kernel.json"
        ),
        full_admin_service_accessibility_surface=_read_json(
            DATA_ROOT
            / "full_admin_service_accessibility_surface_2026_07_08/uwm_full_admin_service_accessibility_surface.json"
        ),
        full_admin_service_surface_quality_audit=_read_json(
            DATA_ROOT
            / "full_admin_service_surface_quality_audit_2026_07_08/uwm_full_admin_service_surface_quality_audit.json"
        ),
        full_admin_mobility_graph=_read_json(
            DATA_ROOT
            / "full_admin_mobility_graph_2026_07_10/full_admin_mobility_graph.json"
        ),
        production_governance_planner_binding_gate=_read_json(
            DATA_ROOT
            / "production_governance_planner_binding_gate_2026_07_08/uwm_production_governance_planner_binding_gate.json"
        ),
        spatial_causal_question_registry=_read_json(
            DATA_ROOT
            / "spatial_causal_question_registry_2026_07_09/uwm_spatial_causal_question_registry.json"
        ),
    )


def test_full_admin_livability_decision_package_collects_real_full_scope_evidence():
    package = _build_package()

    assert package["schema"] == UWM_FULL_ADMIN_LIVABILITY_DECISION_PACKAGE_SCHEMA
    assert package["experiment_scope"] == "full_admin_graph"
    assert package["full_admin_decision_package_ready"] is True
    assert package["supported_claim"] == (
        "full_admin_livability_decision_package_supports_world_model_advantage_over_static_baselines"
    )

    guard = package["full_data_guard"]
    assert guard["passed"] is True
    assert guard["graph_node_count"] == 1017
    assert guard["graph_edge_count"] == 7932
    assert guard["admin_boundary_edge_count"] == 2847
    assert guard["geographic_similarity_edge_count"] == 5085
    assert guard["non_adjacent_similarity_edge_count"] == 4835
    assert guard["available_action_count"] == 1137
    assert guard["transition_count"] == 6817
    assert guard["service_surface_admin_unit_count"] == 1017
    assert guard["service_surface_missing_admin_count"] == 0
    assert guard["source_poi_point_count"] == 1194351
    assert guard["source_road_count"] == 50366

    planner = package["planner_replay_evidence"]
    assert planner["planner_replay_ready"] is True
    assert planner["best_sequence_reward"] == -0.005905423
    assert planner["static_single_step_reward"] == -0.00734186
    assert planner["advantage_over_static_single_step"] == 0.001436437
    assert planner["risk_adjusted_advantage_over_static_single_step"] == 0.0013756
    assert planner["target_units"] == [
        "九龙坡区|中梁山街道|91",
        "大渡口区|八桥镇|964",
    ]

    graph_dqn = package["graph_dqn_training_evidence"]
    assert graph_dqn["graph_dqn_training_ready"] is True
    assert graph_dqn["training_sample_count"] == 1248
    assert graph_dqn["sampled_first_action_count"] == 96
    assert graph_dqn["sampled_second_action_limit"] == 12
    assert graph_dqn["node_feature_names"] == GRAPH_NODE_FEATURE_NAMES
    assert "estimated_nearest_essential_travel_time_min" in graph_dqn[
        "node_feature_names"
    ]
    assert "travel_time_inverse_norm" in graph_dqn["node_feature_names"]
    assert graph_dqn["q_return_mae"] < graph_dqn["train_mean_return_mae"]
    assert graph_dqn["train_mean_return_mae"] == 0.000994236
    assert graph_dqn["advantage_over_traditional_static"] > 0.0
    assert graph_dqn["target_units"] == [
        "江北区|观音桥街道|653",
        "沙坪坝区|覃家岗街道|973",
    ]

    learned = package["learned_world_model_rollout_evidence"]
    assert learned["learned_world_model_rollout_ready"] is True
    assert learned["world_model_feature_names"] == FEATURE_NAMES
    assert "target_travel_time_min_norm" in learned["world_model_feature_names"]
    assert "target_travel_time_inverse_norm" in learned["world_model_feature_names"]
    assert learned["reward_mae"] < learned["train_mean_reward_mae"]
    assert learned["train_mean_reward_mae"] == 0.00222562
    assert learned["imagined_advantage_over_static_single_step"] > 0.0
    assert learned["imagined_advantage_over_one_step_policy"] > 0.0
    assert learned["target_units"] == [
        "沙坪坝区|石井坡街道|793",
        "九龙坡区|中梁山街道|91",
    ]

    similarity = package["geographic_similarity_evidence"]
    assert similarity["geographic_similarity_kernel_ready"] is True
    assert similarity["panel_unit_count"] == 1017
    assert similarity["similarity_edge_count"] == 5085
    assert similarity["non_adjacent_similarity_edge_count"] == 4835
    assert similarity["uses_coordinates_as_similarity_features"] is False
    assert similarity["rotated_target_similarity_control_passed"] is True

    service = package["service_accessibility_evidence"]
    assert service["service_accessibility_surface_ready"] is True
    assert service["service_surface_quality_audit_ready"] is True
    assert service["admin_unit_count"] == 1017
    assert service["essential_service_model_mae"] == 16.728755
    assert service["essential_service_best_baseline_mae"] == 57.472199
    assert service["travel_time_model_mae"] == 2.17547
    assert service["travel_time_best_baseline_mae"] == 2.192174
    assert service["target_rotation_negative_controls_passed"] is True

    mobility = package["mobility_graph_evidence"]
    assert mobility["full_admin_mobility_graph_ready"] is True
    assert mobility["node_count"] == 1017
    assert mobility["edge_count"] == 5085
    assert mobility["mobility_similarity_edge_count"] == 5085
    assert mobility["travel_time_min_mean"] > 0.0
    assert mobility["unicom_directed_edge_count"] == 1067
    assert mobility["osm_highway_edge_count"] == 45468
    assert mobility["osm_crosswalk_assigned_road_segment_count"] == 45449
    assert mobility["observed_od_flow_claim"] is False
    assert mobility["observed_trip_time_claim"] is False
    assert mobility["observed_policy_outcome_superiority_claim"] is False

    governance = package["production_governance_binding_evidence"]
    assert governance["production_governance_binding_gate_ready"] is True
    assert governance["authoritative_governance_data_closure_ready"] is False
    assert governance["planner_governance_binding_ready"] is False
    assert governance["production_planner_binding_blocked"] is True
    assert governance["required_gate_count"] == 9
    assert governance["passed_gate_count"] == 2
    assert governance["blocking_gate_count"] == 7
    assert governance["missing_table_count"] == 5
    assert governance["accepted_authoritative_row_count"] == 0
    assert governance["linked_project_count"] == 0
    assert governance["observed_policy_outcome_superiority_claim"] is False

    causal_binding = package["spatial_causal_contract_binding"]
    assert causal_binding["binding_ready"] is True
    assert causal_binding["registry_ready"] is True
    assert causal_binding["active_causal_question_count"] == 3
    assert causal_binding["attached_action_count"] == 6
    assert causal_binding["missing_contract_action_count"] == 0
    assert causal_binding["underidentified_policy_effect_action_count"] == 6
    assert causal_binding["identified_policy_effect_action_count"] == 0
    assert causal_binding["policy_outcome_claim_allowed_action_count"] == 0

    for sequence_key in [
        "planner_recommended_sequence",
        "graph_dqn_recommended_sequence",
        "learned_rollout_recommended_sequence",
    ]:
        sequence = package["final_outputs"][sequence_key]
        for action in sequence["action_sequence"]:
            assert action["causal_question_id"] == "uwm-cq-green-heat-livability"
            assert action["causal_query"] == (
                "P(heat_risk, livability | do(increase_green_infrastructure), spatial_context)"
            )
            assert action["primary_outcome"] == "heat_risk"
            assert action["identification_status"] == (
                "underidentified_for_observed_policy_effect"
            )
            assert action["required_authoritative_tables"] == [
                "policy_project_history",
                "action_constraint_cost_model",
                "observed_outcome_validation_panel",
                "causal_effect_calibration_panel",
                "human_governance_review_log",
            ]
            assert action["policy_outcome_claim_allowed"] is False

    comparison = package["comparison_against_traditional_static_baselines"]
    assert comparison["all_world_model_advantages_positive"] is True
    assert comparison["planner_advantage_over_static"] == 0.001436437
    assert comparison["planner_risk_adjusted_advantage_over_static"] == 0.0013756
    assert comparison["graph_dqn_advantage_over_static"] == graph_dqn[
        "advantage_over_traditional_static"
    ]
    assert comparison["learned_rollout_advantage_over_static"] == learned[
        "imagined_advantage_over_static_single_step"
    ]
    assert comparison["learned_rollout_advantage_over_one_step_policy"] == learned[
        "imagined_advantage_over_one_step_policy"
    ]

    outputs = package["final_outputs"]
    assert outputs["planner_recommended_sequence"]["target_units"] == planner[
        "target_units"
    ]
    assert outputs["graph_dqn_recommended_sequence"]["target_units"] == graph_dqn[
        "target_units"
    ]
    assert outputs["learned_rollout_recommended_sequence"]["target_units"] == learned[
        "target_units"
    ]
    priority_units = {unit["unit_id"] for unit in outputs["priority_admin_units"]}
    expected_priority_units = set(planner["target_units"])
    expected_priority_units.update(graph_dqn["target_units"])
    expected_priority_units.update(learned["target_units"])
    assert expected_priority_units.issubset(priority_units)
    assert "full_admin_graph_model_based_planner_replay" in outputs["decision_basis"]
    assert "full_admin_graph_trained_graph_dqn_value_network" in outputs[
        "decision_basis"
    ]
    assert "full_admin_graph_learned_world_model_rollout" in outputs[
        "decision_basis"
    ]
    assert "full_admin_geographic_similarity_kernel" in outputs["decision_basis"]
    assert "full_admin_mobility_travel_time_similarity_projection" in outputs[
        "decision_basis"
    ]

    assert package["claim_boundary"]["max_claim_level"] == "bounded_support"
    assert package["planner_governance_binding_ready"] is False
    assert package["observed_policy_outcome_superiority_claim"] is False
    assert package["empirical_superiority_claim"] is False

    causal_binding = package["spatial_causal_contract_binding"]
    assert causal_binding["binding_ready"] is True
    assert causal_binding["attached_action_count"] == 6
    assert causal_binding["missing_contract_action_count"] == 0
    for sequence_key in [
        "planner_recommended_sequence",
        "graph_dqn_recommended_sequence",
        "learned_rollout_recommended_sequence",
    ]:
        for action in package["final_outputs"][sequence_key]["action_sequence"]:
            assert action["causal_question_id"]
            assert "do(" in action["causal_query"]
            assert action["primary_outcome"]
            assert action["identification_status"]
            assert action["required_authoritative_tables"]
            assert action["policy_outcome_claim_allowed"] is False
    assert "production_governance_planner_binding_gate_required" in package[
        "remaining_gates"
    ]


def test_full_admin_livability_decision_package_artifact_is_full_scope_and_claim_safe():
    package = _read_json(ARTIFACT_PATH)

    assert package["schema"] == UWM_FULL_ADMIN_LIVABILITY_DECISION_PACKAGE_SCHEMA
    assert package["full_admin_decision_package_ready"] is True
    assert package["full_data_guard"]["passed"] is True
    assert package["full_data_guard"]["graph_node_count"] == 1017
    assert package["full_data_guard"]["graph_edge_count"] == 7932
    assert package["full_data_guard"]["transition_count"] == 6817
    assert package["mobility_graph_evidence"]["full_admin_mobility_graph_ready"] is True
    assert package["mobility_graph_evidence"]["node_count"] == 1017
    assert package["mobility_graph_evidence"]["edge_count"] == 5085
    assert package["mobility_graph_evidence"]["observed_trip_time_claim"] is False
    assert package["comparison_against_traditional_static_baselines"][
        "all_world_model_advantages_positive"
    ] is True
    assert package["production_governance_binding_evidence"][
        "planner_governance_binding_ready"
    ] is False
    assert package["production_governance_binding_evidence"][
        "blocking_gate_count"
    ] == 7
    assert package["planner_governance_binding_ready"] is False
    assert package["observed_policy_outcome_superiority_claim"] is False
    assert package["empirical_superiority_claim"] is False


def test_catalog_tracks_full_admin_livability_decision_package_asset_and_lineage():
    catalog = build_uwm_livability_data_catalog(
        data_root=DATA_ROOT,
        catalog_id="uwm-livability-data-catalog-full-admin-decision-test",
        created_at="2026-07-08T18:40:00Z",
    )

    assets_by_id = {asset["asset_id"]: asset for asset in catalog["assets"]}
    asset = assets_by_id["full_admin_livability_decision_package"]
    assert asset["exists"] is True
    assert asset["schema"] == UWM_FULL_ADMIN_LIVABILITY_DECISION_PACKAGE_SCHEMA
    assert asset["experiment_scope"] == "full_admin_graph"
    assert asset["full_admin_decision_package_ready"] is True
    assert asset["graph_node_count"] == 1017
    assert asset["graph_edge_count"] == 7932
    assert asset["available_action_count"] == 1137
    assert asset["transition_count"] == 6817
    assert asset["geographic_similarity_edge_count"] == 5085
    assert asset["planner_governance_binding_ready"] is False
    assert asset["production_governance_binding_blocking_gate_count"] == 7
    assert asset["observed_policy_outcome_superiority_claim"] is False

    assert (
        catalog["full_data_readiness"][
            "full_admin_livability_decision_package_completed"
        ]
        is True
    )
    assert (
        catalog["full_data_readiness"][
            "full_admin_decision_package_world_model_advantages_positive"
        ]
        is True
    )

    edges = {
        (edge["from"], edge["to"], edge["relation"])
        for edge in catalog["lineage_edges"]
    }
    assert (
        "full_admin_graph_planner_replay",
        "full_admin_livability_decision_package",
        "full_admin_decision_planner_replay_input",
    ) in edges
    assert (
        "full_admin_graph_drl_training_report",
        "full_admin_livability_decision_package",
        "full_admin_decision_graph_dqn_input",
    ) in edges
    assert (
        "full_admin_learned_world_model_rollout",
        "full_admin_livability_decision_package",
        "full_admin_decision_learned_rollout_input",
    ) in edges
    assert (
        "geographic_similarity_kernel",
        "full_admin_livability_decision_package",
        "full_admin_decision_similarity_kernel_input",
    ) in edges
    assert (
        "production_governance_planner_binding_gate",
        "full_admin_livability_decision_package",
        "full_admin_decision_production_governance_binding_gate_input",
    ) in edges


def test_evidence_gate_tracks_full_admin_livability_decision_package(tmp_path: Path):
    package_path = tmp_path / "uwm_full_admin_livability_decision_package.json"
    package_path.write_text(
        json.dumps(_build_package(), ensure_ascii=False),
        encoding="utf-8",
    )

    gate = build_uwm_data_foundation_evidence_gate(
        manifest_path=ROOT / "docs/reports/uwm_data_foundation_manifest.csv",
        openaq_temporal_benchmark_path=DATA_ROOT
        / "openaq_temporal_benchmark_2018_10/uwm_openaq_observed_temporal_benchmark.json",
        tap_external_dynamics_path=DATA_ROOT
        / "tap_pm25_external_dynamics_2026_07_06/tap_external_dynamics_report.json",
        learned_rollout_path=DATA_ROOT
        / "model_based_rl_graph_search_2026_07_05/uwm_offline_world_model_rollout_planner_admin_livability_spatial_graph_proxy.json",
        livability_intervention_package_path=DATA_ROOT
        / "model_based_rl_graph_search_2026_07_05/uwm_livability_intervention_package_admin_livability_spatial_graph.json",
        local_planning_inventory_path=DATA_ROOT
        / "local_planning_zip_audit_2026_07_05/uwm_local_planning_zip_inventory.csv",
        admin_spatial_graph_path=DATA_ROOT
        / "admin_spatial_graph_2026_07_05/uwm_admin_spatial_adjacency_graph.json",
        full_admin_livability_decision_package_path=package_path,
        gate_id="uwm-data-foundation-evidence-gate-full-admin-decision-test",
        created_at="2026-07-08T18:45:00Z",
    )

    decision_slice = gate["evidence_slices"]["full_admin_livability_decision_package"]
    assert decision_slice["source_artifact_exists"] is True
    assert decision_slice["full_admin_livability_decision_package_ready"] is True
    assert decision_slice["experiment_scope"] == "full_admin_graph"
    assert decision_slice["graph_node_count"] == 1017
    assert decision_slice["graph_edge_count"] == 7932
    assert decision_slice["geographic_similarity_edge_count"] == 5085
    assert decision_slice["available_action_count"] == 1137
    assert decision_slice["transition_count"] == 6817
    assert decision_slice["planner_advantage_over_static"] == 0.001436437
    assert decision_slice["planner_risk_adjusted_advantage_over_static"] == 0.0013756
    assert decision_slice["graph_dqn_advantage_over_static"] > 0.0
    assert decision_slice["learned_rollout_advantage_over_static"] > 0.0
    assert decision_slice["all_world_model_advantages_positive"] is True
    assert decision_slice["planner_governance_binding_ready"] is False
    assert decision_slice["production_governance_binding_blocking_gate_count"] == 7
    assert decision_slice["observed_policy_outcome_superiority_claim"] is False
    assert decision_slice["empirical_superiority_claim"] is False

    claims = {claim["claim"] for claim in gate["supported_claims"]}
    assert (
        "full_admin_livability_decision_package_supports_world_model_advantage_over_static_baselines"
        in claims
    )

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
        learned_rollout_path=ROOT
        / "data/uwm_public_proxy/chongqing_central/model_based_rl_graph_search_2026_07_05/uwm_offline_world_model_rollout_planner_admin_livability_spatial_graph_proxy.json",
        livability_intervention_package_path=ROOT
        / "data/uwm_public_proxy/chongqing_central/model_based_rl_graph_search_2026_07_05/uwm_livability_intervention_package_admin_livability_spatial_graph.json",
        local_planning_inventory_path=ROOT
        / "data/uwm_public_proxy/chongqing_central/local_planning_zip_audit_2026_07_05/uwm_local_planning_zip_inventory.csv",
        admin_spatial_graph_path=ROOT
        / "data/uwm_public_proxy/chongqing_central/admin_spatial_graph_2026_07_05/uwm_admin_spatial_adjacency_graph.json",
        gate_id="uwm-data-foundation-evidence-gate-real-artifacts-test",
        created_at="2026-07-05T22:30:00Z",
    )

    assert gate["schema"] == UWM_DATA_FOUNDATION_EVIDENCE_GATE_SCHEMA
    assert gate["data_foundation_scope"]["manifest_row_count"] == 65
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
        "public_proxy": 38,
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

    assert gate["observed_state_prediction_superiority_claim"] is True
    assert gate["observed_policy_outcome_superiority_claim"] is False
    assert "observed_policy_outcome_required" in gate["remaining_gates"]
    assert gate["claim_guard"]["synthetic_or_smoke_blocked_from_empirical_policy_claim"] is True
    assert "synthetic_air_quality_placeholder" in gate["claim_guard"]["blocked_dataset_ids"]
    assert "uwm_livability_intervention_package_admin_livability_spatial_graph" in gate["claim_guard"][
        "blocked_dataset_ids"
    ]
    assert gate["data_foundation_scope"]["source_type_counts"]["planning_sample"] == 15
    assert gate["empirical_superiority_claim"] is False

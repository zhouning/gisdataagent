from pathlib import Path

from data_agent.uwm.data_foundation_evidence_gate import (
    build_uwm_data_foundation_evidence_gate,
)
from data_agent.uwm.world_model_evidence_readiness import (
    build_world_model_evidence_readiness,
)


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data/uwm_public_proxy/chongqing_central"


def _build_gate() -> dict:
    return build_uwm_data_foundation_evidence_gate(
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
        causal_policy_evidence_path=DATA_ROOT
        / "causal_policy_evidence_2026_07_06/uwm_causal_policy_evidence_gate.json",
        external_observed_holdout_suite_path=DATA_ROOT
        / "external_observed_holdout_suite_2026_07_06/uwm_external_observed_holdout_suite.json",
        station_aligned_air_quality_holdout_path=DATA_ROOT
        / "station_aligned_air_quality_holdout_2026_07_06/uwm_station_aligned_air_quality_holdout.json",
        data_calibrated_mechanism_table_path=DATA_ROOT
        / "data_calibrated_mechanism_table_2026_07_06/uwm_data_calibrated_mechanism_table.json",
        data_calibrated_planner_replay_path=DATA_ROOT
        / "data_calibrated_planner_replay_2026_07_06/uwm_data_calibrated_model_based_graph_search.json",
        scene_aligned_gridded_air_quality_holdout_path=DATA_ROOT
        / "scene_aligned_gridded_air_quality_holdout_2026_07_06/uwm_scene_aligned_gridded_air_quality_holdout.json",
        multisource_livability_scene_path=DATA_ROOT
        / "multisource_livability_scene_2026_07_06/uwm_multisource_livability_scene.json",
        osm_admin_mobility_crosswalk_path=DATA_ROOT
        / "osm_admin_mobility_crosswalk_2026_07_06/uwm_osm_admin_mobility_crosswalk.json",
        livability_endpoint_suite_path=DATA_ROOT
        / "livability_endpoint_suite_2026_07_07/uwm_livability_endpoint_suite.json",
        endpoint_aligned_planner_evaluator_path=DATA_ROOT
        / "endpoint_aligned_planner_evaluator_2026_07_07/uwm_endpoint_aligned_planner_evaluator.json",
        gate_id="uwm-data-foundation-evidence-gate-overall-system-test",
        created_at="2026-07-07T10:35:00Z",
    )


def test_overall_bounded_final_system_superiority_claim_is_gate_checked():
    gate = _build_gate()

    assert gate["bounded_final_system_superiority_claim"] is True
    assert gate["observed_policy_outcome_superiority_claim"] is False
    assert gate["empirical_superiority_claim"] is False
    assert "uwm_bounded_final_endpoint_and_planner_advantage_over_traditional_methods" in {
        claim["claim"] for claim in gate["supported_claims"]
    }

    readiness = build_world_model_evidence_readiness(gate)
    assert readiness["bounded_final_system_superiority_ready"] is True
    assert readiness["system_level_superiority_summary"] == (
        "bounded_final_endpoint_and_endpoint_aligned_planner_advantage_without_policy_outcome_superiority"
    )
    assert readiness["policy_outcome_superiority_ready"] is False
    assert readiness["empirical_superiority_claim"] is False
    assert "overall_empirical_policy_superiority" in readiness["forbidden_claims"]

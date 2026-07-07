"""Build UWM data-foundation evidence gate from prepared project artifacts."""

from __future__ import annotations

import json
from pathlib import Path

from data_agent.uwm.data_foundation_evidence_gate import build_uwm_data_foundation_evidence_gate


REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = REPO_ROOT / "data/uwm_public_proxy/chongqing_central/data_foundation_evidence_gate_2026_07_05"
OUTPUT_PATH = OUTPUT_DIR / "uwm_data_foundation_evidence_gate.json"
CAUSAL_POLICY_EVIDENCE_PATH = (
    REPO_ROOT
    / "data/uwm_public_proxy/chongqing_central/causal_policy_evidence_2026_07_06/uwm_causal_policy_evidence_gate.json"
)
EXTERNAL_OBSERVED_HOLDOUT_SUITE_PATH = (
    REPO_ROOT
    / "data/uwm_public_proxy/chongqing_central/external_observed_holdout_suite_2026_07_06/uwm_external_observed_holdout_suite.json"
)
STATION_ALIGNED_AIR_QUALITY_HOLDOUT_PATH = (
    REPO_ROOT
    / "data/uwm_public_proxy/chongqing_central/station_aligned_air_quality_holdout_2026_07_06/uwm_station_aligned_air_quality_holdout.json"
)
DATA_CALIBRATED_MECHANISM_TABLE_PATH = (
    REPO_ROOT
    / "data/uwm_public_proxy/chongqing_central/data_calibrated_mechanism_table_2026_07_06/uwm_data_calibrated_mechanism_table.json"
)
DATA_CALIBRATED_PLANNER_REPLAY_PATH = (
    REPO_ROOT
    / "data/uwm_public_proxy/chongqing_central/data_calibrated_planner_replay_2026_07_06/uwm_data_calibrated_model_based_graph_search.json"
)
SCENE_ALIGNED_GRIDDED_AIR_QUALITY_HOLDOUT_PATH = (
    REPO_ROOT
    / "data/uwm_public_proxy/chongqing_central/scene_aligned_gridded_air_quality_holdout_2026_07_06/uwm_scene_aligned_gridded_air_quality_holdout.json"
)
MULTISOURCE_LIVABILITY_SCENE_PATH = (
    REPO_ROOT
    / "data/uwm_public_proxy/chongqing_central/multisource_livability_scene_2026_07_06/uwm_multisource_livability_scene.json"
)
OSM_ADMIN_MOBILITY_CROSSWALK_PATH = (
    REPO_ROOT
    / "data/uwm_public_proxy/chongqing_central/osm_admin_mobility_crosswalk_2026_07_06/uwm_osm_admin_mobility_crosswalk.json"
)
BUILDING_FLOOR_MORPHOLOGY_PATH = (
    REPO_ROOT
    / "data/uwm_public_proxy/chongqing_central/building_floor_morphology_2026_07_07/uwm_building_floor_morphology.json"
)
LIVABILITY_ENDPOINT_SUITE_PATH = (
    REPO_ROOT
    / "data/uwm_public_proxy/chongqing_central/livability_endpoint_suite_2026_07_07/uwm_livability_endpoint_suite.json"
)
ENDPOINT_ALIGNED_PLANNER_EVALUATOR_PATH = (
    REPO_ROOT
    / "data/uwm_public_proxy/chongqing_central/endpoint_aligned_planner_evaluator_2026_07_07/uwm_endpoint_aligned_planner_evaluator.json"
)
SPATIAL_SPILLOVER_PLANNER_EVALUATOR_PATH = (
    REPO_ROOT
    / "data/uwm_public_proxy/chongqing_central/spatial_spillover_planner_evaluator_2026_07_07/uwm_spatial_spillover_planner_evaluator.json"
)
LIVABILITY_DECISION_PACKAGE_PATH = (
    REPO_ROOT
    / "data/uwm_public_proxy/chongqing_central/livability_decision_package_2026_07_07/uwm_livability_decision_package.json"
)
LIVABILITY_RL_TRAINING_REPORT_PATH = (
    REPO_ROOT
    / "data/uwm_public_proxy/chongqing_central/livability_rl_training_2026_07_07/uwm_livability_rl_training_report.json"
)
LIVABILITY_GRAPH_DRL_TRAINING_REPORT_PATH = (
    REPO_ROOT
    / "data/uwm_public_proxy/chongqing_central/livability_graph_drl_training_2026_07_07/uwm_livability_graph_drl_training_report.json"
)


def main() -> None:
    gate = build_uwm_data_foundation_evidence_gate(
        manifest_path=REPO_ROOT / "docs/reports/uwm_data_foundation_manifest.csv",
        openaq_temporal_benchmark_path=REPO_ROOT
        / "data/uwm_public_proxy/chongqing_central/openaq_temporal_benchmark_2018_10/uwm_openaq_observed_temporal_benchmark.json",
        tap_external_dynamics_path=REPO_ROOT
        / "data/uwm_public_proxy/chongqing_central/tap_pm25_external_dynamics_2026_07_06/tap_external_dynamics_report.json",
        learned_rollout_path=REPO_ROOT
        / "data/uwm_public_proxy/chongqing_central/model_based_rl_graph_search_2026_07_05/uwm_offline_world_model_rollout_planner_admin_livability_spatial_graph_proxy.json",
        livability_intervention_package_path=REPO_ROOT
        / "data/uwm_public_proxy/chongqing_central/model_based_rl_graph_search_2026_07_05/uwm_livability_intervention_package_admin_livability_spatial_graph.json",
        local_planning_inventory_path=REPO_ROOT
        / "data/uwm_public_proxy/chongqing_central/local_planning_zip_audit_2026_07_05/uwm_local_planning_zip_inventory.csv",
        admin_spatial_graph_path=REPO_ROOT
        / "data/uwm_public_proxy/chongqing_central/admin_spatial_graph_2026_07_05/uwm_admin_spatial_adjacency_graph.json",
        causal_policy_evidence_path=(
            CAUSAL_POLICY_EVIDENCE_PATH if CAUSAL_POLICY_EVIDENCE_PATH.exists() else None
        ),
        external_observed_holdout_suite_path=(
            EXTERNAL_OBSERVED_HOLDOUT_SUITE_PATH
            if EXTERNAL_OBSERVED_HOLDOUT_SUITE_PATH.exists()
            else None
        ),
        station_aligned_air_quality_holdout_path=(
            STATION_ALIGNED_AIR_QUALITY_HOLDOUT_PATH
            if STATION_ALIGNED_AIR_QUALITY_HOLDOUT_PATH.exists()
            else None
        ),
        data_calibrated_mechanism_table_path=(
            DATA_CALIBRATED_MECHANISM_TABLE_PATH
            if DATA_CALIBRATED_MECHANISM_TABLE_PATH.exists()
            else None
        ),
        data_calibrated_planner_replay_path=(
            DATA_CALIBRATED_PLANNER_REPLAY_PATH
            if DATA_CALIBRATED_PLANNER_REPLAY_PATH.exists()
            else None
        ),
        scene_aligned_gridded_air_quality_holdout_path=(
            SCENE_ALIGNED_GRIDDED_AIR_QUALITY_HOLDOUT_PATH
            if SCENE_ALIGNED_GRIDDED_AIR_QUALITY_HOLDOUT_PATH.exists()
            else None
        ),
        multisource_livability_scene_path=(
            MULTISOURCE_LIVABILITY_SCENE_PATH
            if MULTISOURCE_LIVABILITY_SCENE_PATH.exists()
            else None
        ),
        osm_admin_mobility_crosswalk_path=(
            OSM_ADMIN_MOBILITY_CROSSWALK_PATH
            if OSM_ADMIN_MOBILITY_CROSSWALK_PATH.exists()
            else None
        ),
        building_floor_morphology_path=(
            BUILDING_FLOOR_MORPHOLOGY_PATH
            if BUILDING_FLOOR_MORPHOLOGY_PATH.exists()
            else None
        ),
        livability_endpoint_suite_path=(
            LIVABILITY_ENDPOINT_SUITE_PATH
            if LIVABILITY_ENDPOINT_SUITE_PATH.exists()
            else None
        ),
        endpoint_aligned_planner_evaluator_path=(
            ENDPOINT_ALIGNED_PLANNER_EVALUATOR_PATH
            if ENDPOINT_ALIGNED_PLANNER_EVALUATOR_PATH.exists()
            else None
        ),
        spatial_spillover_planner_evaluator_path=(
            SPATIAL_SPILLOVER_PLANNER_EVALUATOR_PATH
            if SPATIAL_SPILLOVER_PLANNER_EVALUATOR_PATH.exists()
            else None
        ),
        livability_decision_package_path=(
            LIVABILITY_DECISION_PACKAGE_PATH
            if LIVABILITY_DECISION_PACKAGE_PATH.exists()
            else None
        ),
        livability_rl_training_report_path=(
            LIVABILITY_RL_TRAINING_REPORT_PATH
            if LIVABILITY_RL_TRAINING_REPORT_PATH.exists()
            else None
        ),
        livability_graph_drl_training_report_path=(
            LIVABILITY_GRAPH_DRL_TRAINING_REPORT_PATH
            if LIVABILITY_GRAPH_DRL_TRAINING_REPORT_PATH.exists()
            else None
        ),
        gate_id="uwm-data-foundation-evidence-gate-2026-07-06",
        created_at="2026-07-06T14:25:00Z",
    )
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as handle:
        json.dump(gate, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(
        json.dumps(
            {
                "path": str(OUTPUT_PATH.relative_to(REPO_ROOT)),
                "manifest_row_count": gate["data_foundation_scope"]["manifest_row_count"],
                "observed_state_prediction_superiority_claim": gate[
                    "observed_state_prediction_superiority_claim"
                ],
                "observed_policy_outcome_superiority_claim": gate[
                    "observed_policy_outcome_superiority_claim"
                ],
                "bounded_final_system_superiority_claim": gate[
                    "bounded_final_system_superiority_claim"
                ],
                "openaq_holdout_win_rate": gate["evidence_slices"][
                    "openaq_observed_temporal_state"
                ]["overall_holdout_win_rate"],
                "tap_external_transition_claim": gate["external_temporal_transition_superiority_claim"],
                "tap_external_transition_mae": gate["evidence_slices"][
                    "tap_external_temporal_transition"
                ]["best_transition_mae"],
                "causal_policy_diagnostic_ready": gate["evidence_slices"][
                    "causal_policy_effect_validation"
                ]["algorithmic_causal_diagnostic_ready"],
                "external_observed_holdout_ready": gate["evidence_slices"][
                    "external_observed_holdout_suite"
                ]["external_observed_holdout_ready"],
                "historical_station_aligned_holdout_ready": gate["evidence_slices"][
                    "station_aligned_air_quality_holdout"
                ]["historical_station_aligned_holdout_ready"],
                "data_calibrated_mechanism_ready": gate["evidence_slices"][
                    "data_calibrated_mechanism_table"
                ]["data_calibrated_mechanism_ready"],
                "data_calibrated_planner_replay_ready": gate["evidence_slices"][
                    "data_calibrated_planner_replay"
                ]["data_calibrated_planner_replay_ready"],
                "risk_calibrated_planner_replay_ready": gate["evidence_slices"][
                    "data_calibrated_planner_replay"
                ]["risk_calibrated_planner_replay_ready"],
                "risk_adjusted_planner_replay_advantage": gate["evidence_slices"][
                    "data_calibrated_planner_replay"
                ]["risk_adjusted_advantage_over_static_single_step"],
                "scene_aligned_gridded_air_quality_holdout_ready": gate[
                    "evidence_slices"
                ]["scene_aligned_gridded_air_quality_holdout"][
                    "scene_aligned_gridded_air_quality_holdout_ready"
                ],
                "scene_aligned_gridded_uncertainty_ready": gate["evidence_slices"][
                    "scene_aligned_gridded_air_quality_holdout"
                ]["uwm_uncertainty_calibration_ready"],
                "scene_aligned_gridded_uwm_interval_score": gate["evidence_slices"][
                    "scene_aligned_gridded_air_quality_holdout"
                ]["uwm_interval_score"],
                "scene_aligned_gridded_static_interval_score": gate["evidence_slices"][
                    "scene_aligned_gridded_air_quality_holdout"
                ]["static_interval_score"],
                "multisource_livability_scene_ready": gate["evidence_slices"][
                    "multisource_livability_scene"
                ]["multisource_livability_scene_ready"],
                "multisource_air_quality_mae": gate["evidence_slices"][
                    "multisource_livability_scene"
                ]["air_quality_multisource_mae"],
                "multisource_osm_admin_mobility_crosswalk_projected": gate[
                    "evidence_slices"
                ]["multisource_livability_scene"][
                    "osm_admin_mobility_crosswalk_projected"
                ],
                "multisource_osm_assigned_road_segment_count_in_scene": gate[
                    "evidence_slices"
                ]["multisource_livability_scene"][
                    "osm_assigned_road_segment_count_in_scene"
                ],
                "multisource_air_quality_best_single_source_mae": gate[
                    "evidence_slices"
                ]["multisource_livability_scene"][
                    "air_quality_best_single_source_mae"
                ],
                "osm_admin_mobility_crosswalk_ready": gate["evidence_slices"][
                    "osm_admin_mobility_crosswalk"
                ]["osm_admin_mobility_crosswalk_ready"],
                "osm_service_accessibility_mae": gate["evidence_slices"][
                    "osm_admin_mobility_crosswalk"
                ]["service_accessibility_mobility_mae"],
                "osm_service_accessibility_best_static_mae": gate["evidence_slices"][
                    "osm_admin_mobility_crosswalk"
                ]["service_accessibility_best_static_mae"],
                "building_floor_morphology_ready": gate["evidence_slices"][
                    "building_floor_morphology"
                ]["building_floor_morphology_ready"],
                "building_floor_assigned_building_count": gate["evidence_slices"][
                    "building_floor_morphology"
                ]["assigned_building_count"],
                "building_floor_total_floor_count": gate["evidence_slices"][
                    "building_floor_morphology"
                ]["total_floor_count"],
                "building_floor_max_floor": gate["evidence_slices"][
                    "building_floor_morphology"
                ]["max_floor"],
                "building_floor_true_3d_claim": gate["evidence_slices"][
                    "building_floor_morphology"
                ]["true_3d_claim"],
                "livability_endpoint_suite_ready": gate["evidence_slices"][
                    "livability_endpoint_suite"
                ]["livability_endpoint_suite_ready"],
                "livability_endpoint_ready_count": gate["evidence_slices"][
                    "livability_endpoint_suite"
                ]["ready_endpoint_count"],
                "livability_endpoint_mean_relative_mae_reduction": gate[
                    "evidence_slices"
                ]["livability_endpoint_suite"][
                    "mean_relative_mae_reduction_vs_best_traditional"
                ],
                "endpoint_aligned_planner_evaluator_ready": gate["evidence_slices"][
                    "endpoint_aligned_planner_evaluator"
                ]["endpoint_aligned_planner_evaluator_ready"],
                "endpoint_aligned_planner_advantage": gate["evidence_slices"][
                    "endpoint_aligned_planner_evaluator"
                ]["endpoint_aligned_advantage_over_static"],
                "spatial_spillover_planner_evaluator_ready": gate["evidence_slices"][
                    "spatial_spillover_planner_evaluator"
                ]["spatial_spillover_planner_evaluator_ready"],
                "spatial_spillover_neighbor_delta_advantage": gate["evidence_slices"][
                    "spatial_spillover_planner_evaluator"
                ]["neighbor_livability_delta_advantage"],
                "livability_decision_package_ready": gate["evidence_slices"][
                    "livability_decision_package"
                ]["livability_decision_package_ready"],
                "livability_decision_action_count": gate["evidence_slices"][
                    "livability_decision_package"
                ]["action_count"],
                "livability_decision_endpoint_advantage": gate["evidence_slices"][
                    "livability_decision_package"
                ]["endpoint_aligned_advantage_over_static"],
                "livability_decision_best_single_action_advantage": gate[
                    "evidence_slices"
                ]["livability_decision_package"][
                    "advantage_vs_best_single_action"
                ],
                "livability_decision_single_action_empirical_p_value": gate[
                    "evidence_slices"
                ]["livability_decision_package"][
                    "empirical_p_value_vs_single_action_baselines"
                ],
                "livability_decision_endpoint_weight_sensitivity_min_advantage": gate[
                    "evidence_slices"
                ]["livability_decision_package"][
                    "endpoint_weight_sensitivity_min_advantage"
                ],
                "livability_decision_risk_adjusted_advantage": gate[
                    "evidence_slices"
                ]["livability_decision_package"][
                    "risk_adjusted_advantage_over_static"
                ],
                "livability_rl_training_ready": gate["evidence_slices"][
                    "livability_rl_training"
                ]["livability_rl_training_ready"],
                "livability_rl_training_algorithm": gate["evidence_slices"][
                    "livability_rl_training"
                ]["algorithm"],
                "livability_rl_training_advantage": gate["evidence_slices"][
                    "livability_rl_training"
                ]["advantage_over_traditional_static"],
                "livability_graph_drl_training_ready": gate["evidence_slices"][
                    "livability_graph_drl_training"
                ]["livability_graph_drl_training_ready"],
                "livability_graph_drl_algorithm": gate["evidence_slices"][
                    "livability_graph_drl_training"
                ]["algorithm"],
                "livability_graph_drl_advantage": gate["evidence_slices"][
                    "livability_graph_drl_training"
                ]["advantage_over_traditional_static"],
                "remaining_gates": gate["remaining_gates"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

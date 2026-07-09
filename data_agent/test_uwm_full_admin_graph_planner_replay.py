import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = (
    ROOT
    / "data/uwm_public_proxy/chongqing_central/data_calibrated_planner_replay_full_admin_graph_2026_07_08/uwm_full_admin_graph_model_based_graph_search.json"
)


def test_full_admin_graph_planner_replay_uses_all_admin_nodes():
    assert REPORT_PATH.exists()
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    assert report["schema"] == "uwm.model_based_graph_search_report.v1"
    assert report["experiment_scope"] == "full_admin_graph"
    assert report["source_admin_livability_panel_summary"]["joined_admin_count"] == 1017
    assert report["source_admin_spatial_graph_summary"]["node_count"] == 1017
    assert report["source_geographic_similarity_kernel_summary"]["similarity_edge_count"] == 5085
    assert (
        report["source_geographic_similarity_kernel_summary"][
            "non_adjacent_similarity_edge_count"
        ]
        == 4835
    )
    assert report["graph_mdp_state"]["graph_statistics"]["node_count"] == 1017
    assert report["graph_mdp_state"]["graph_statistics"]["edge_count"] == 7932
    assert report["graph_mdp_state"]["graph_statistics"]["available_action_count"] > 60
    edge_types = {
        edge["edge_type"] for edge in report["graph_mdp_state"]["edges"]
    }
    assert "admin_boundary_adjacency" in edge_types
    assert "geographic_configuration_similarity" in edge_types
    assert report["search_config"]["transition_storage"] == "compact"
    assert report["trajectory_dataset"]["transition_count"] > 0

    first_transition = report["trajectory_dataset"]["transitions"][0]
    assert "next_state_delta_summary" in first_transition
    assert "next_state_delta" not in first_transition
    assert report["observed_policy_outcome_superiority_claim"] is False
    assert report["empirical_superiority_claim"] is False


def test_full_admin_graph_planner_replay_is_scene_pm25_risk_calibrated():
    assert REPORT_PATH.exists()
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    air_quality = report["air_quality_uncertainty_calibration_summary"]
    risk = report["risk_adjusted_planner_evaluation"]

    assert air_quality["uwm_uncertainty_calibration_ready"] is True
    assert air_quality["source_benchmark_id"] == (
        "uwm-scene-aligned-gridded-air-quality-holdout-2026-07-06"
    )
    assert air_quality["scene_aligned_station_calibrated_air_quality_holdout_ready"] is False
    assert air_quality["observed_policy_outcome_superiority_claim"] is False
    assert risk["risk_calibrated_planner_replay_ready"] is True
    assert risk["risk_adjusted_advantage_over_static_single_step"] > 0
    assert risk["observed_policy_outcome_superiority_claim"] is False

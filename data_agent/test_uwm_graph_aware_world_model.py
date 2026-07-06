import json
from pathlib import Path

from data_agent.uwm.graph_aware_world_model import (
    GRAPH_AWARE_WORLD_MODEL_REPORT_SCHEMA,
    train_graph_aware_world_model,
)


ROOT = Path(__file__).resolve().parents[1]
SEARCH_REPORT_PATH = ROOT / (
    "data/uwm_public_proxy/chongqing_central/model_based_rl_graph_search_2026_07_05/"
    "uwm_model_based_graph_search_admin_livability_spatial_graph_proxy.json"
)


def test_graph_aware_world_model_beats_target_only_baseline_on_prepared_spatial_graph_replay():
    search_report = json.loads(SEARCH_REPORT_PATH.read_text(encoding="utf-8"))

    report = train_graph_aware_world_model(
        search_report,
        model_id="admin-livability-spatial-graph-aware-world-model-2026-07-05",
        created_at="2026-07-05T23:10:00Z",
        holdout_stride=5,
        ridge=0.001,
    )

    assert report["schema"] == GRAPH_AWARE_WORLD_MODEL_REPORT_SCHEMA
    assert report["backend"] == "ridge_graph_aware_action_conditioned_dynamics_v0"
    assert report["training_summary"]["transition_count"] == 355
    assert report["source_graph_summary"]["node_count"] == 36
    assert report["source_graph_summary"]["edge_count"] == 96
    assert "neighbor_mean_heat_risk" in report["world_model"]["feature_names"]
    assert "neighbor_mean_service_gap" in report["world_model"]["feature_names"]
    assert "target_neighbor_livability_gap_contrast" in report["world_model"]["feature_names"]

    assert report["holdout_metrics"]["reward_mae"] < report["baseline_metrics"]["target_only_reward_mae"]
    assert report["holdout_metrics"]["reward_mae"] < report["baseline_metrics"]["train_mean_reward_mae"]
    assert report["holdout_metrics"]["reward_win_count_vs_target_only"] > 0
    assert report["holdout_metrics"]["reward_win_rate_vs_target_only"] > 0.5
    assert report["holdout_metrics"]["dynamics_mean_mae"] < report["baseline_metrics"]["target_only_dynamics_mean_mae"]
    assert report["supported_claim"] == "graph_aware_world_model_beats_target_only_and_train_mean_baselines"
    assert report["claim_boundary"]["max_claim_level"] == "bounded_support"
    assert report["empirical_superiority_claim"] is False
    assert "observed_policy_outcome_required" in report["remaining_gates"]

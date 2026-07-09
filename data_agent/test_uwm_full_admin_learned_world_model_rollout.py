import json
from pathlib import Path

from data_agent.uwm.offline_world_model_policy import (
    OFFLINE_WORLD_MODEL_ROLLOUT_PLANNER_REPORT_SCHEMA,
    plan_with_offline_world_model_rollouts,
)


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data/uwm_public_proxy/chongqing_central"
FULL_ADMIN_PLANNER_REPLAY_PATH = (
    DATA_ROOT
    / "data_calibrated_planner_replay_full_admin_graph_2026_07_08/uwm_full_admin_graph_model_based_graph_search.json"
)
FULL_ADMIN_LEARNED_ROLLOUT_PATH = (
    DATA_ROOT
    / "learned_world_model_rollout_full_admin_graph_2026_07_08/uwm_full_admin_graph_learned_world_model_rollout.json"
)


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_full_admin_compact_replay_trains_learned_rollout_from_aggregate_dynamics():
    learned = plan_with_offline_world_model_rollouts(
        _load_json(FULL_ADMIN_PLANNER_REPLAY_PATH),
        model_id="full-admin-learned-rollout-compact-replay-test",
        created_at="2026-07-08T13:10:00Z",
        horizon=2,
        beam_width=5,
        holdout_stride=7,
        ridge=0.001,
        uncertainty_penalty=0.5,
    )

    assert learned["schema"] == OFFLINE_WORLD_MODEL_ROLLOUT_PLANNER_REPORT_SCHEMA
    assert learned["training_summary"]["transition_count"] == 6817
    assert learned["holdout_metrics"]["reward_mae"] < learned["baseline_metrics"][
        "train_mean_reward_mae"
    ]
    for target_name in [
        "heat_risk_delta",
        "air_pollution_exposure_delta",
        "service_accessibility_delta",
        "equity_delta",
        "livability_delta",
    ]:
        assert learned["holdout_metrics"]["dynamics_mae_by_target"][
            target_name
        ] < learned["baseline_metrics"]["train_mean_mae_by_target"][target_name]
    assert learned["learned_rollout_planner"][
        "imagined_advantage_over_static_single_step"
    ] > 0
    assert learned["learned_rollout_planner"][
        "imagined_advantage_over_one_step_policy"
    ] > 0
    assert learned["observed_policy_outcome_superiority_claim"] is False
    assert learned["empirical_superiority_claim"] is False


def test_full_admin_learned_rollout_artifact_is_full_scope_and_claim_gated():
    assert FULL_ADMIN_LEARNED_ROLLOUT_PATH.exists()
    report = _load_json(FULL_ADMIN_LEARNED_ROLLOUT_PATH)

    assert report["schema"] == OFFLINE_WORLD_MODEL_ROLLOUT_PLANNER_REPORT_SCHEMA
    assert report["experiment_scope"] == "full_admin_graph"
    assert report["full_data_guard"]["passed"] is True
    assert report["full_data_guard"]["observed_graph_node_count"] == 1017
    assert report["training_summary"]["transition_count"] == 6817
    assert report["training_summary"]["source_graph_node_count"] == 1017
    assert report["training_summary"]["source_graph_edge_count"] == 7932
    assert report["training_summary"]["source_available_action_count"] == 1137
    assert report["holdout_metrics"]["reward_mae"] < report["baseline_metrics"][
        "train_mean_reward_mae"
    ]
    assert report["learned_rollout_planner"][
        "imagined_advantage_over_static_single_step"
    ] > 0
    assert report["supported_claim"] == (
        "full_admin_graph_learned_world_model_rollout_improves_imagined_static_and_one_step_baselines"
    )
    assert report["observed_policy_outcome_superiority_claim"] is False
    assert report["empirical_superiority_claim"] is False

"""Build data-calibrated UWM Graph-MDP planner replay artifacts."""

from __future__ import annotations

import json
from pathlib import Path

from data_agent.uwm.model_based_rl import (
    build_admin_livability_graph_observation,
    plan_with_model_based_graph_search,
)
from data_agent.uwm.offline_world_model_policy import plan_with_offline_world_model_rollouts


REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = (
    REPO_ROOT
    / "data/uwm_public_proxy/chongqing_central/data_calibrated_planner_replay_2026_07_06"
)
GRAPH_SEARCH_PATH = OUTPUT_DIR / "uwm_data_calibrated_model_based_graph_search.json"
LEARNED_ROLLOUT_PATH = OUTPUT_DIR / "uwm_data_calibrated_offline_world_model_rollout_planner.json"
MANIFEST_PATH = OUTPUT_DIR / "snapshot_manifest.json"

ADMIN_GRAPH_PATH = (
    REPO_ROOT
    / "data/uwm_public_proxy/chongqing_central/admin_spatial_graph_2026_07_05/uwm_admin_spatial_adjacency_graph.json"
)
ADMIN_PANEL_PATH = (
    REPO_ROOT
    / "data/uwm_public_proxy/chongqing_central/admin_livability_target_2024_07_2026_07_05/uwm_admin_livability_target_panel.json"
)
MECHANISM_TABLE_PATH = (
    REPO_ROOT
    / "data/uwm_public_proxy/chongqing_central/data_calibrated_mechanism_table_2026_07_06/uwm_data_calibrated_mechanism_table.json"
)
SCENE_ALIGNED_GRIDDED_AIR_QUALITY_HOLDOUT_PATH = (
    REPO_ROOT
    / "data/uwm_public_proxy/chongqing_central/scene_aligned_gridded_air_quality_holdout_2026_07_06/uwm_scene_aligned_gridded_air_quality_holdout.json"
)


def main() -> None:
    graph = _load_json(ADMIN_GRAPH_PATH)
    panel = _load_json(ADMIN_PANEL_PATH)
    mechanism_table = _load_json(MECHANISM_TABLE_PATH)
    scene_aligned_gridded_air_quality_holdout = _load_json(
        SCENE_ALIGNED_GRIDDED_AIR_QUALITY_HOLDOUT_PATH
    )
    observation = build_admin_livability_graph_observation(
        panel,
        observation_id="admin-livability-data-calibrated-graph-mdp-2026-07-06",
        created_at="2026-07-06T19:20:00Z",
        max_units=36,
        admin_spatial_graph=graph,
    )
    report = plan_with_model_based_graph_search(
        observation,
        action_types=[
            "increase_green_infrastructure",
            "traffic_emission_control",
            "add_community_service",
        ],
        scenario={
            "scenario_id": "data_calibrated_heat_pollution_service_stress",
            "heat_stress_multiplier": 1.2,
            "air_pollution_stress_multiplier": 1.15,
            "vulnerability_multiplier": 1.1,
        },
        horizon=2,
        beam_width=5,
        thresholds={
            "heat_risk": 0.7,
            "air_pollution_exposure": 0.6,
            "service_accessibility": 0.5,
        },
        mechanism_table=mechanism_table,
        air_quality_uncertainty_context=scene_aligned_gridded_air_quality_holdout,
    )
    report["source_admin_spatial_graph_path"] = str(ADMIN_GRAPH_PATH.relative_to(REPO_ROOT))
    report["source_admin_livability_panel_path"] = str(ADMIN_PANEL_PATH.relative_to(REPO_ROOT))
    report["source_data_calibrated_mechanism_table_path"] = str(
        MECHANISM_TABLE_PATH.relative_to(REPO_ROOT)
    )
    report["source_scene_aligned_gridded_air_quality_holdout_path"] = str(
        SCENE_ALIGNED_GRIDDED_AIR_QUALITY_HOLDOUT_PATH.relative_to(REPO_ROOT)
    )

    learned_rollout = plan_with_offline_world_model_rollouts(
        report,
        model_id="data-calibrated-admin-livability-learned-rollout-2026-07-06",
        created_at="2026-07-06T19:25:00Z",
        horizon=2,
        beam_width=5,
        holdout_stride=5,
        ridge=0.001,
        uncertainty_penalty=0.5,
    )
    learned_rollout["source_data_calibrated_graph_search_path"] = str(
        GRAPH_SEARCH_PATH.relative_to(REPO_ROOT)
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _write_json(GRAPH_SEARCH_PATH, report)
    _write_json(LEARNED_ROLLOUT_PATH, learned_rollout)
    snapshot = {
        "snapshot_id": "uwm_data_calibrated_planner_replay_2026_07_06",
        "created_at": "2026-07-06T19:25:00Z",
        "graph_search_path": str(GRAPH_SEARCH_PATH.relative_to(REPO_ROOT)),
        "learned_rollout_path": str(LEARNED_ROLLOUT_PATH.relative_to(REPO_ROOT)),
        "source_admin_spatial_graph_path": str(ADMIN_GRAPH_PATH.relative_to(REPO_ROOT)),
        "source_admin_livability_panel_path": str(ADMIN_PANEL_PATH.relative_to(REPO_ROOT)),
        "source_data_calibrated_mechanism_table_path": str(
            MECHANISM_TABLE_PATH.relative_to(REPO_ROOT)
        ),
        "source_scene_aligned_gridded_air_quality_holdout_path": str(
            SCENE_ALIGNED_GRIDDED_AIR_QUALITY_HOLDOUT_PATH.relative_to(REPO_ROOT)
        ),
        "data_calibrated_planner_replay_ready": report["supported_claim"]
        == "data_calibrated_model_based_graph_search_advantage_over_static_heuristic",
        "advantage_over_static_single_step": report["advantage_over_static_single_step"],
        "air_quality_uncertainty_calibration_ready": report[
            "air_quality_uncertainty_calibration_summary"
        ]["uwm_uncertainty_calibration_ready"],
        "risk_calibrated_planner_replay_ready": report[
            "risk_adjusted_planner_evaluation"
        ]["risk_calibrated_planner_replay_ready"],
        "risk_adjusted_advantage_over_static_single_step": report[
            "risk_adjusted_planner_evaluation"
        ]["risk_adjusted_advantage_over_static_single_step"],
        "learned_rollout_supported_claim": learned_rollout["supported_claim"],
        "observed_policy_outcome_superiority_claim": False,
    }
    _write_json(MANIFEST_PATH, snapshot)
    print(
        json.dumps(
            {
                "graph_search_path": str(GRAPH_SEARCH_PATH.relative_to(REPO_ROOT)),
                "learned_rollout_path": str(LEARNED_ROLLOUT_PATH.relative_to(REPO_ROOT)),
                "mechanism_table_id": report["mechanism_table_summary"][
                    "mechanism_table_id"
                ],
                "best_sequence_reward": report["best_sequence"]["cumulative_reward"],
                "static_single_step_reward": report["static_single_step_baseline"][
                    "cumulative_reward"
                ],
                "advantage_over_static_single_step": report[
                    "advantage_over_static_single_step"
                ],
                "air_quality_uncertainty_calibration_ready": report[
                    "air_quality_uncertainty_calibration_summary"
                ]["uwm_uncertainty_calibration_ready"],
                "air_quality_uwm_interval_score": report[
                    "air_quality_uncertainty_calibration_summary"
                ]["uwm_interval_score"],
                "risk_adjusted_advantage_over_static_single_step": report[
                    "risk_adjusted_planner_evaluation"
                ]["risk_adjusted_advantage_over_static_single_step"],
                "risk_calibrated_supported_claim": report[
                    "risk_adjusted_planner_evaluation"
                ]["supported_claim"],
                "supported_claim": report["supported_claim"],
                "learned_rollout_reward_mae": learned_rollout["holdout_metrics"][
                    "reward_mae"
                ],
                "learned_rollout_baseline_mae": learned_rollout["baseline_metrics"][
                    "train_mean_reward_mae"
                ],
                "learned_rollout_supported_claim": learned_rollout["supported_claim"],
                "observed_policy_outcome_superiority_claim": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


if __name__ == "__main__":
    main()

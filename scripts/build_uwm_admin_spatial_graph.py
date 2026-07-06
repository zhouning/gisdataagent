"""Build UWM admin spatial graph artifacts from local Chongqing boundaries."""

from __future__ import annotations

import json
from pathlib import Path

from data_agent.uwm.admin_spatial_graph import build_admin_spatial_adjacency_graph
from data_agent.uwm.model_based_rl import (
    build_admin_livability_graph_observation,
    plan_with_model_based_graph_search,
)
from data_agent.uwm.graph_aware_world_model import train_graph_aware_world_model
from data_agent.uwm.livability_intervention_package import build_livability_intervention_package
from data_agent.uwm.offline_value_model import train_offline_graph_value_model
from data_agent.uwm.offline_world_model_policy import train_offline_world_model_policy
from data_agent.uwm.offline_world_model_policy import plan_with_offline_world_model_rollouts
from data_agent.uwm.synthetic_policy_outcome import build_synthetic_policy_outcome_benchmark


REPO_ROOT = Path(__file__).resolve().parents[1]
ADMIN_GEOJSON = (
    REPO_ROOT
    / "data/uwm_public_proxy/chongqing_central/admin_units/chongqing_township_admin_units.geojson"
)
ADMIN_GRAPH_DIR = REPO_ROOT / "data/uwm_public_proxy/chongqing_central/admin_spatial_graph_2026_07_05"
ADMIN_GRAPH_PATH = ADMIN_GRAPH_DIR / "uwm_admin_spatial_adjacency_graph.json"
LIVABILITY_PANEL = (
    REPO_ROOT
    / "data/uwm_public_proxy/chongqing_central/admin_livability_target_2024_07_2026_07_05/uwm_admin_livability_target_panel.json"
)
GRAPH_SEARCH_DIR = (
    REPO_ROOT
    / "data/uwm_public_proxy/chongqing_central/model_based_rl_graph_search_2026_07_05"
)
SPATIAL_GRAPH_SEARCH_PATH = (
    GRAPH_SEARCH_DIR / "uwm_model_based_graph_search_admin_livability_spatial_graph_proxy.json"
)
OFFLINE_VALUE_MODEL_PATH = (
    GRAPH_SEARCH_DIR / "uwm_offline_value_model_admin_livability_spatial_graph_proxy.json"
)
OFFLINE_WORLD_MODEL_POLICY_PATH = (
    GRAPH_SEARCH_DIR / "uwm_offline_world_model_policy_admin_livability_spatial_graph_proxy.json"
)
OFFLINE_WORLD_MODEL_ROLLOUT_PLANNER_PATH = (
    GRAPH_SEARCH_DIR / "uwm_offline_world_model_rollout_planner_admin_livability_spatial_graph_proxy.json"
)
GRAPH_AWARE_WORLD_MODEL_PATH = (
    GRAPH_SEARCH_DIR / "uwm_graph_aware_world_model_admin_livability_spatial_graph_proxy.json"
)
SYNTHETIC_POLICY_OUTCOME_PATH = (
    GRAPH_SEARCH_DIR / "uwm_synthetic_policy_outcome_benchmark_admin_livability_spatial_graph.json"
)
TAP_LIKE_PM25_SCENE_MANIFEST = (
    REPO_ROOT
    / "data/uwm_public_proxy/chongqing_central/tap_like_pm25_scene_v2_2024_07_01_07/snapshot_manifest.json"
)
LIVABILITY_INTERVENTION_PACKAGE_PATH = (
    GRAPH_SEARCH_DIR / "uwm_livability_intervention_package_admin_livability_spatial_graph.json"
)


def main() -> None:
    admin_geojson = _load_json(ADMIN_GEOJSON)
    graph = build_admin_spatial_adjacency_graph(
        admin_features=list(admin_geojson.get("features") or []),
        graph_id="chongqing-admin-spatial-adjacency-2026-07-05",
        created_at="2026-07-05T08:30:00+00:00",
        source_dataset_id="chongqing_township_admin_units_local",
    )
    ADMIN_GRAPH_DIR.mkdir(parents=True, exist_ok=True)
    _write_json(ADMIN_GRAPH_PATH, graph)

    panel = _load_json(LIVABILITY_PANEL)
    observation = build_admin_livability_graph_observation(
        panel,
        observation_id="admin-livability-spatial-graph-mdp-obs-2026-07-05",
        created_at="2026-07-05T08:35:00+00:00",
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
            "scenario_id": "heat_pollution_service_stress",
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
    )
    report["source_admin_spatial_graph_path"] = str(ADMIN_GRAPH_PATH.relative_to(REPO_ROOT))
    report["source_admin_spatial_graph_summary"] = graph["summary"]
    GRAPH_SEARCH_DIR.mkdir(parents=True, exist_ok=True)
    _write_json(SPATIAL_GRAPH_SEARCH_PATH, report)

    value_report = train_offline_graph_value_model(
        report,
        model_id="admin-livability-spatial-graph-ridge-value-2026-07-05",
        created_at="2026-07-05T09:20:00+00:00",
        holdout_stride=5,
        ridge=0.001,
    )
    value_report["source_graph_search_path"] = str(SPATIAL_GRAPH_SEARCH_PATH.relative_to(REPO_ROOT))
    _write_json(OFFLINE_VALUE_MODEL_PATH, value_report)

    world_model_policy_report = train_offline_world_model_policy(
        report,
        model_id="admin-livability-spatial-graph-ridge-world-model-policy-2026-07-05",
        created_at="2026-07-05T09:35:00+00:00",
        holdout_stride=5,
        ridge=0.001,
        uncertainty_penalty=0.5,
    )
    world_model_policy_report["source_graph_search_path"] = str(SPATIAL_GRAPH_SEARCH_PATH.relative_to(REPO_ROOT))
    _write_json(OFFLINE_WORLD_MODEL_POLICY_PATH, world_model_policy_report)

    rollout_planner_report = plan_with_offline_world_model_rollouts(
        report,
        model_id="admin-livability-spatial-graph-learned-rollout-planner-2026-07-05",
        created_at="2026-07-05T09:45:00+00:00",
        horizon=2,
        beam_width=5,
        holdout_stride=5,
        ridge=0.001,
        uncertainty_penalty=0.5,
    )
    rollout_planner_report["source_graph_search_path"] = str(SPATIAL_GRAPH_SEARCH_PATH.relative_to(REPO_ROOT))
    _write_json(OFFLINE_WORLD_MODEL_ROLLOUT_PLANNER_PATH, rollout_planner_report)

    graph_aware_world_model_report = train_graph_aware_world_model(
        report,
        model_id="admin-livability-spatial-graph-aware-world-model-2026-07-05",
        created_at="2026-07-05T10:00:00+00:00",
        holdout_stride=5,
        ridge=0.001,
    )
    graph_aware_world_model_report["source_graph_search_path"] = str(
        SPATIAL_GRAPH_SEARCH_PATH.relative_to(REPO_ROOT)
    )
    _write_json(GRAPH_AWARE_WORLD_MODEL_PATH, graph_aware_world_model_report)

    synthetic_policy_outcome_report = build_synthetic_policy_outcome_benchmark(
        report,
        rollout_planner_report,
        benchmark_id="admin-livability-spatial-graph-synthetic-policy-outcome-2026-07-05",
        created_at="2026-07-05T09:55:00+00:00",
    )
    synthetic_policy_outcome_report["source_graph_search_path"] = str(
        SPATIAL_GRAPH_SEARCH_PATH.relative_to(REPO_ROOT)
    )
    synthetic_policy_outcome_report["source_learned_rollout_path"] = str(
        OFFLINE_WORLD_MODEL_ROLLOUT_PLANNER_PATH.relative_to(REPO_ROOT)
    )
    _write_json(SYNTHETIC_POLICY_OUTCOME_PATH, synthetic_policy_outcome_report)

    tap_like_pm25_scene_manifest = (
        _load_json(TAP_LIKE_PM25_SCENE_MANIFEST)
        if TAP_LIKE_PM25_SCENE_MANIFEST.exists()
        else {}
    )
    livability_intervention_package = build_livability_intervention_package(
        search_report=report,
        learned_rollout_report=rollout_planner_report,
        synthetic_policy_outcome_benchmark=synthetic_policy_outcome_report,
        tap_like_pm25_scene_manifest=tap_like_pm25_scene_manifest,
        package_id="admin-livability-spatial-graph-intervention-package-2026-07-05",
        created_at="2026-07-05T10:05:00+00:00",
    )
    livability_intervention_package["source_graph_search_path"] = str(
        SPATIAL_GRAPH_SEARCH_PATH.relative_to(REPO_ROOT)
    )
    livability_intervention_package["source_learned_rollout_path"] = str(
        OFFLINE_WORLD_MODEL_ROLLOUT_PLANNER_PATH.relative_to(REPO_ROOT)
    )
    livability_intervention_package["source_synthetic_policy_outcome_path"] = str(
        SYNTHETIC_POLICY_OUTCOME_PATH.relative_to(REPO_ROOT)
    )
    livability_intervention_package["source_tap_like_pm25_scene_manifest_path"] = (
        str(TAP_LIKE_PM25_SCENE_MANIFEST.relative_to(REPO_ROOT))
        if TAP_LIKE_PM25_SCENE_MANIFEST.exists()
        else None
    )
    _write_json(LIVABILITY_INTERVENTION_PACKAGE_PATH, livability_intervention_package)

    print(
        json.dumps(
            {
                "admin_graph_path": str(ADMIN_GRAPH_PATH.relative_to(REPO_ROOT)),
                "admin_graph_summary": graph["summary"],
                "graph_search_path": str(SPATIAL_GRAPH_SEARCH_PATH.relative_to(REPO_ROOT)),
                "selected_unit_count": report["graph_mdp_state"]["graph_statistics"]["node_count"],
                "selected_spatial_edge_count": report["graph_mdp_state"]["graph_statistics"]["edge_count"],
                "replay_transition_count": report["trajectory_dataset"]["transition_count"],
                "best_sequence_reward": report["best_sequence"]["cumulative_reward"],
                "static_single_step_reward": report["static_single_step_baseline"]["cumulative_reward"],
                "advantage": report["advantage_over_static_single_step"],
                "empirical_superiority_claim": report["empirical_superiority_claim"],
                "supported_claim": report["supported_claim"],
                "offline_value_model_path": str(OFFLINE_VALUE_MODEL_PATH.relative_to(REPO_ROOT)),
                "offline_value_model_holdout_mae": value_report["holdout_metrics"]["mae"],
                "offline_value_model_baseline_mae": value_report["baseline_metrics"]["train_mean_mae"],
                "offline_value_model_supported_claim": value_report["supported_claim"],
                "offline_world_model_policy_path": str(OFFLINE_WORLD_MODEL_POLICY_PATH.relative_to(REPO_ROOT)),
                "offline_world_model_policy_reward_mae": world_model_policy_report["holdout_metrics"]["reward_mae"],
                "offline_world_model_policy_baseline_mae": world_model_policy_report["baseline_metrics"]["train_mean_reward_mae"],
                "offline_world_model_policy_replay_advantage": world_model_policy_report["conservative_policy"][
                    "actual_replay_evaluation"
                ]["replay_reward_advantage"],
                "offline_world_model_policy_supported_claim": world_model_policy_report["supported_claim"],
                "offline_world_model_rollout_planner_path": str(
                    OFFLINE_WORLD_MODEL_ROLLOUT_PLANNER_PATH.relative_to(REPO_ROOT)
                ),
                "offline_world_model_rollout_planner_reward_mae": rollout_planner_report["holdout_metrics"][
                    "reward_mae"
                ],
                "offline_world_model_rollout_planner_baseline_mae": rollout_planner_report["baseline_metrics"][
                    "train_mean_reward_mae"
                ],
                "offline_world_model_rollout_planner_imagined_advantage_over_static": rollout_planner_report[
                    "learned_rollout_planner"
                ]["imagined_advantage_over_static_single_step"],
                "offline_world_model_rollout_planner_imagined_advantage_over_one_step": rollout_planner_report[
                    "learned_rollout_planner"
                ]["imagined_advantage_over_one_step_policy"],
                "offline_world_model_rollout_planner_supported_claim": rollout_planner_report["supported_claim"],
                "graph_aware_world_model_path": str(GRAPH_AWARE_WORLD_MODEL_PATH.relative_to(REPO_ROOT)),
                "graph_aware_world_model_reward_mae": graph_aware_world_model_report["holdout_metrics"][
                    "reward_mae"
                ],
                "graph_aware_world_model_target_only_reward_mae": graph_aware_world_model_report[
                    "baseline_metrics"
                ]["target_only_reward_mae"],
                "graph_aware_world_model_train_mean_reward_mae": graph_aware_world_model_report[
                    "baseline_metrics"
                ]["train_mean_reward_mae"],
                "graph_aware_world_model_reward_win_rate_vs_target_only": graph_aware_world_model_report[
                    "holdout_metrics"
                ]["reward_win_rate_vs_target_only"],
                "graph_aware_world_model_supported_claim": graph_aware_world_model_report["supported_claim"],
                "synthetic_policy_outcome_path": str(SYNTHETIC_POLICY_OUTCOME_PATH.relative_to(REPO_ROOT)),
                "synthetic_policy_outcome_learned_advantage_over_static": synthetic_policy_outcome_report[
                    "comparisons"
                ]["learned_rollout_advantage_over_static"],
                "synthetic_policy_outcome_claim_boundary": synthetic_policy_outcome_report["claim_boundary"][
                    "max_claim_level"
                ],
                "livability_intervention_package_path": str(
                    LIVABILITY_INTERVENTION_PACKAGE_PATH.relative_to(REPO_ROOT)
                ),
                "livability_intervention_package_supported_claim": livability_intervention_package[
                    "supported_claim"
                ],
                "livability_intervention_package_claim_boundary": livability_intervention_package[
                    "claim_boundary"
                ]["max_claim_level"],
                "livability_intervention_package_low_unit_count": len(
                    livability_intervention_package["low_livability_units"]
                ),
                "livability_intervention_package_first_action": (
                    livability_intervention_package["multi_step_plan"]["action_sequence"][0]["action_id"]
                    if livability_intervention_package["multi_step_plan"]["action_sequence"]
                    else None
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: Path, payload: dict) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


if __name__ == "__main__":
    main()

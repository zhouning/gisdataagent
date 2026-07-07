"""Build UWM livability model-based RL training report from real local data."""

from __future__ import annotations

import json
from pathlib import Path

from data_agent.uwm.livability_graph_mdp_env import build_livability_graph_mdp_env
from data_agent.uwm.livability_rl_training import train_livability_model_based_q_agent
from data_agent.uwm.model_based_rl import build_admin_livability_graph_observation


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = REPO_ROOT / "data/uwm_public_proxy/chongqing_central"
OUTPUT_DIR = DATA_ROOT / "livability_rl_training_2026_07_07"
OUTPUT_PATH = OUTPUT_DIR / "uwm_livability_rl_training_report.json"
MANIFEST_PATH = OUTPUT_DIR / "snapshot_manifest.json"
ADMIN_GRAPH_PATH = (
    DATA_ROOT
    / "admin_spatial_graph_2026_07_05/uwm_admin_spatial_adjacency_graph.json"
)
ADMIN_PANEL_PATH = (
    DATA_ROOT
    / "admin_livability_target_2024_07_2026_07_05/uwm_admin_livability_target_panel.json"
)
MECHANISM_TABLE_PATH = (
    DATA_ROOT
    / "data_calibrated_mechanism_table_2026_07_06/uwm_data_calibrated_mechanism_table.json"
)
SPATIAL_KERNEL_PATH = (
    DATA_ROOT
    / "data_calibrated_spatial_spillover_kernel_2026_07_07/uwm_data_calibrated_spatial_spillover_kernel.json"
)
SCENE_AIR_QUALITY_HOLDOUT_PATH = (
    DATA_ROOT
    / "scene_aligned_gridded_air_quality_holdout_2026_07_06/uwm_scene_aligned_gridded_air_quality_holdout.json"
)


def main() -> None:
    graph = _read_json(ADMIN_GRAPH_PATH)
    panel = _read_json(ADMIN_PANEL_PATH)
    observation = build_admin_livability_graph_observation(
        panel,
        observation_id="admin-livability-real-data-graph-mdp-rl-training",
        created_at="2026-07-07T15:00:00Z",
        max_units=36,
        admin_spatial_graph=graph,
    )
    env = build_livability_graph_mdp_env(
        observation,
        action_types=[
            "increase_green_infrastructure",
            "traffic_emission_control",
            "add_community_service",
        ],
        scenario={
            "scenario_id": "real_data_graph_mdp_rl_heat_pollution_service_stress",
            "heat_stress_multiplier": 1.2,
            "air_pollution_stress_multiplier": 1.15,
            "vulnerability_multiplier": 1.1,
        },
        horizon=2,
        thresholds={
            "heat_risk": 0.7,
            "air_pollution_exposure": 0.6,
            "service_accessibility": 0.5,
        },
        mechanism_table=_read_json(MECHANISM_TABLE_PATH),
        spatial_spillover_kernel=_read_json(SPATIAL_KERNEL_PATH),
        air_quality_uncertainty_context=_read_json(SCENE_AIR_QUALITY_HOLDOUT_PATH),
    )
    report = train_livability_model_based_q_agent(
        env,
        report_id="uwm-livability-real-data-model-based-q-training-2026-07-07",
        created_at="2026-07-07T15:05:00Z",
        episodes=160,
        seed=20260707,
        learning_rate=0.35,
        discount_factor=0.9,
        epsilon_start=0.75,
        epsilon_end=0.05,
        planning_updates_per_step=8,
    )
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _write_json(OUTPUT_PATH, report)
    manifest = {
        "snapshot_id": "uwm_livability_rl_training_2026_07_07",
        "created_at": "2026-07-07T15:05:00Z",
        "report_path": str(OUTPUT_PATH.relative_to(REPO_ROOT)),
        "source_admin_graph_path": str(ADMIN_GRAPH_PATH.relative_to(REPO_ROOT)),
        "source_admin_livability_panel_path": str(
            ADMIN_PANEL_PATH.relative_to(REPO_ROOT)
        ),
        "source_mechanism_table_path": str(
            MECHANISM_TABLE_PATH.relative_to(REPO_ROOT)
        ),
        "source_spatial_spillover_kernel_path": str(
            SPATIAL_KERNEL_PATH.relative_to(REPO_ROOT)
        ),
        "source_air_quality_holdout_path": str(
            SCENE_AIR_QUALITY_HOLDOUT_PATH.relative_to(REPO_ROOT)
        ),
        "algorithm": report["rl_algorithm"]["algorithm"],
        "episode_count": report["training_summary"]["episode_count"],
        "real_data_graph_node_count": report["training_summary"][
            "real_data_graph_node_count"
        ],
        "real_data_available_action_count": report["training_summary"][
            "real_data_available_action_count"
        ],
        "advantage_over_traditional_static": report["learned_policy_evaluation"][
            "advantage_over_traditional_static"
        ],
        "supported_claim": report["supported_claim"],
        "observed_policy_outcome_superiority_claim": False,
    }
    _write_json(MANIFEST_PATH, manifest)
    print(
        json.dumps(
            {
                "report_path": str(OUTPUT_PATH.relative_to(REPO_ROOT)),
                "algorithm": report["rl_algorithm"]["algorithm"],
                "episode_count": report["training_summary"]["episode_count"],
                "last_20_mean_reward": report["training_curve"][
                    "last_20_mean_reward"
                ],
                "first_20_mean_reward": report["training_curve"][
                    "first_20_mean_reward"
                ],
                "learned_policy_cumulative_reward": report[
                    "learned_policy_evaluation"
                ]["learned_policy_cumulative_reward"],
                "traditional_static_cumulative_reward": report[
                    "baseline_evaluation"
                ]["traditional_static_cumulative_reward"],
                "advantage_over_traditional_static": report[
                    "learned_policy_evaluation"
                ]["advantage_over_traditional_static"],
                "supported_claim": report["supported_claim"],
                "observed_policy_outcome_superiority_claim": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _read_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


if __name__ == "__main__":
    main()

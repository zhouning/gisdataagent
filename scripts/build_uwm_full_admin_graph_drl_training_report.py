"""Build full-admin UWM livability GraphDQN training evidence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from data_agent.uwm.livability_graph_drl import train_livability_graph_dqn_agent
from data_agent.uwm.livability_graph_mdp_env import build_livability_graph_mdp_env
from data_agent.uwm.model_based_rl import build_admin_livability_graph_observation


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = REPO_ROOT / "data/uwm_public_proxy/chongqing_central"
OUTPUT_DIR = DATA_ROOT / "livability_graph_drl_training_full_admin_graph_2026_07_08"
OUTPUT_PATH = OUTPUT_DIR / "uwm_full_admin_graph_livability_graph_drl_training_report.json"
MANIFEST_PATH = OUTPUT_DIR / "snapshot_manifest.json"
FULL_PANEL_PATH = (
    DATA_ROOT
    / "admin_livability_target_full_admin_graph_2024_07_2026_07_08/uwm_admin_livability_target_full_admin_graph_panel.json"
)
ADMIN_GRAPH_PATH = (
    DATA_ROOT / "admin_spatial_graph_2026_07_05/uwm_admin_spatial_adjacency_graph.json"
)
GEOGRAPHIC_SIMILARITY_KERNEL_PATH = (
    DATA_ROOT
    / "geographic_similarity_kernel_2026_07_08/uwm_geographic_similarity_kernel.json"
)
MECHANISM_TABLE_PATH = (
    DATA_ROOT
    / "data_calibrated_mechanism_table_full_admin_graph_2026_07_08/uwm_full_admin_graph_data_calibrated_mechanism_table.json"
)
SCENE_AIR_QUALITY_HOLDOUT_PATH = (
    DATA_ROOT
    / "scene_aligned_gridded_air_quality_holdout_2026_07_06/uwm_scene_aligned_gridded_air_quality_holdout.json"
)


def main() -> None:
    panel = _read_json(FULL_PANEL_PATH)
    admin_graph = _read_json(ADMIN_GRAPH_PATH)
    geographic_similarity_kernel = _read_json(GEOGRAPHIC_SIMILARITY_KERNEL_PATH)
    mechanism_table = _read_json(MECHANISM_TABLE_PATH)
    air_quality_holdout = _read_json(SCENE_AIR_QUALITY_HOLDOUT_PATH)
    _validate_full_inputs(panel, admin_graph)

    observation = build_admin_livability_graph_observation(
        panel,
        observation_id="admin-livability-full-admin-graph-drl-obs-2026-07-08",
        created_at="2026-07-08T12:35:00Z",
        admin_spatial_graph=admin_graph,
        geographic_similarity_kernel=geographic_similarity_kernel,
    )
    rendered_node_count = len(observation.get("spatial_units") or [])
    if rendered_node_count != panel["joined_admin_count"]:
        raise SystemExit(
            "renderer dropped admin units in full_admin_graph GraphDQN mode: "
            f"{rendered_node_count} != {panel['joined_admin_count']}"
        )

    env = build_livability_graph_mdp_env(
        observation,
        action_types=[
            "increase_green_infrastructure",
            "traffic_emission_control",
            "add_community_service",
        ],
        scenario={
            "scenario_id": "full_admin_graph_drl_heat_pollution_service_stress",
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
        mechanism_table=mechanism_table,
        air_quality_uncertainty_context=air_quality_holdout,
    )
    report = train_livability_graph_dqn_agent(
        env,
        report_id="uwm-full-admin-graph-livability-graph-dqn-training-2026-07-08",
        created_at="2026-07-08T12:40:00Z",
        seed=20260708,
        epochs=80,
        hidden_dim=24,
        learning_rate=0.006,
        discount_factor=0.9,
        holdout_stride=7,
        experiment_scope="full_admin_graph",
        required_graph_node_count=1017,
        max_first_actions=96,
        max_second_actions_per_first=12,
        action_sampling_strategy="stratified_priority",
        policy_action_scope="sampled_training_candidate_pool",
    )
    report["source_admin_livability_panel_path"] = str(
        FULL_PANEL_PATH.relative_to(REPO_ROOT)
    )
    report["source_admin_livability_panel_summary"] = {
        "panel_id": panel.get("panel_id"),
        "joined_admin_count": panel.get("joined_admin_count"),
        "source_admin_count": panel.get("source_admin_count"),
        "service_matched_admin_count": panel.get("service_matched_admin_count"),
        "service_missing_admin_count": panel.get("service_missing_admin_count"),
        "claim_boundary": panel.get("claim_boundary"),
    }
    report["source_admin_spatial_graph_path"] = str(
        ADMIN_GRAPH_PATH.relative_to(REPO_ROOT)
    )
    report["source_admin_spatial_graph_summary"] = admin_graph.get("summary") or {}
    report["source_geographic_similarity_kernel_path"] = str(
        GEOGRAPHIC_SIMILARITY_KERNEL_PATH.relative_to(REPO_ROOT)
    )
    report["source_geographic_similarity_kernel_summary"] = (
        geographic_similarity_kernel.get("summary") or {}
    )
    report["source_mechanism_table_path"] = str(
        MECHANISM_TABLE_PATH.relative_to(REPO_ROOT)
    )
    report["source_air_quality_holdout_path"] = str(
        SCENE_AIR_QUALITY_HOLDOUT_PATH.relative_to(REPO_ROOT)
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _write_json(OUTPUT_PATH, report)
    _write_json(
        MANIFEST_PATH,
        {
            "snapshot_id": "uwm_full_admin_graph_livability_graph_drl_training_2026_07_08",
            "created_at": report["created_at"],
            "schema": "uwm.snapshot_manifest.v1",
            "output_path": str(OUTPUT_PATH.relative_to(REPO_ROOT)),
            "experiment_scope": report["experiment_scope"],
            "source_artifacts": {
                "admin_livability_panel": report["source_admin_livability_panel_path"],
                "admin_spatial_graph": report["source_admin_spatial_graph_path"],
                "geographic_similarity_kernel": report[
                    "source_geographic_similarity_kernel_path"
                ],
                "mechanism_table": report["source_mechanism_table_path"],
                "air_quality_holdout": report["source_air_quality_holdout_path"],
            },
            "full_data_guard": report["full_data_guard"],
            "training_summary": report["training_summary"],
            "holdout_metrics": report["holdout_metrics"],
            "learned_policy_evaluation": report["learned_policy_evaluation"],
            "baseline_evaluation": report["baseline_evaluation"],
            "supported_claim": report["supported_claim"],
            "observed_policy_outcome_superiority_claim": report[
                "observed_policy_outcome_superiority_claim"
            ],
            "empirical_superiority_claim": report["empirical_superiority_claim"],
            "remaining_gates": report["remaining_gates"],
        },
    )
    print(
        json.dumps(
            {
                "report_path": str(OUTPUT_PATH.relative_to(REPO_ROOT)),
                "experiment_scope": report["experiment_scope"],
                "full_data_guard": report["full_data_guard"],
                "real_data_graph_node_count": report["training_summary"][
                    "real_data_graph_node_count"
                ],
                "real_data_available_action_count": report["training_summary"][
                    "real_data_available_action_count"
                ],
                "training_sample_count": report["training_summary"][
                    "training_sample_count"
                ],
                "q_return_mae": report["holdout_metrics"]["q_return_mae"],
                "train_mean_return_mae": report["holdout_metrics"][
                    "train_mean_return_mae"
                ],
                "graph_dqn_policy_cumulative_reward": report[
                    "learned_policy_evaluation"
                ]["graph_dqn_policy_cumulative_reward"],
                "traditional_static_cumulative_reward": report[
                    "baseline_evaluation"
                ]["traditional_static_cumulative_reward"],
                "advantage_over_traditional_static": report[
                    "learned_policy_evaluation"
                ]["advantage_over_traditional_static"],
                "supported_claim": report["supported_claim"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _validate_full_inputs(panel: dict[str, Any], admin_graph: dict[str, Any]) -> None:
    graph_node_count = (admin_graph.get("summary") or {}).get("node_count")
    if panel.get("experiment_scope") != "full_admin_graph":
        raise SystemExit("panel experiment_scope must be full_admin_graph")
    if panel.get("joined_admin_count") != graph_node_count:
        raise SystemExit(
            "full panel joined_admin_count must equal admin graph node_count: "
            f"{panel.get('joined_admin_count')} != {graph_node_count}"
        )


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()

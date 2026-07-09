"""Build full-admin Graph-MDP planner replay for UWM livability."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from data_agent.uwm.model_based_rl import (
    build_admin_livability_graph_observation,
    plan_with_model_based_graph_search,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = REPO_ROOT / "data/uwm_public_proxy/chongqing_central"
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
OUTPUT_DIR = DATA_ROOT / "data_calibrated_planner_replay_full_admin_graph_2026_07_08"
REPORT_PATH = OUTPUT_DIR / "uwm_full_admin_graph_model_based_graph_search.json"
MANIFEST_PATH = OUTPUT_DIR / "snapshot_manifest.json"


def main() -> None:
    panel = _read_json(FULL_PANEL_PATH)
    admin_graph = _read_json(ADMIN_GRAPH_PATH)
    geographic_similarity_kernel = _read_json(GEOGRAPHIC_SIMILARITY_KERNEL_PATH)
    mechanism_table = _read_json(MECHANISM_TABLE_PATH)
    air_quality_holdout = _read_json(SCENE_AIR_QUALITY_HOLDOUT_PATH)
    _validate_full_inputs(panel, admin_graph)

    observation = build_admin_livability_graph_observation(
        panel,
        observation_id="admin-livability-full-admin-graph-mdp-obs-2026-07-08",
        created_at="2026-07-08T11:00:00+00:00",
        admin_spatial_graph=admin_graph,
        geographic_similarity_kernel=geographic_similarity_kernel,
    )
    if len(observation["spatial_units"]) != panel["joined_admin_count"]:
        raise SystemExit("renderer dropped admin units in full_admin_graph mode")

    report = plan_with_model_based_graph_search(
        observation,
        action_types=[
            "increase_green_infrastructure",
            "traffic_emission_control",
            "add_community_service",
        ],
        scenario={
            "scenario_id": "full_admin_graph_heat_pollution_service_stress",
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
        air_quality_uncertainty_context=air_quality_holdout,
        transition_storage="compact",
    )
    report["experiment_scope"] = "full_admin_graph"
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
    report["full_data_guard"] = {
        "required_scope": "full_admin_graph",
        "source_panel_joined_admin_count": panel["joined_admin_count"],
        "source_graph_node_count": (admin_graph.get("summary") or {}).get("node_count"),
        "rendered_node_count": report["graph_mdp_state"]["graph_statistics"][
            "node_count"
        ],
        "source_admin_boundary_edge_count": (admin_graph.get("summary") or {}).get(
            "edge_count"
        ),
        "source_geographic_similarity_edge_count": (
            geographic_similarity_kernel.get("summary") or {}
        ).get("similarity_edge_count"),
        "rendered_graph_edge_count": report["graph_mdp_state"]["graph_statistics"][
            "edge_count"
        ],
        "passed": (
            panel["joined_admin_count"]
            == (admin_graph.get("summary") or {}).get("node_count")
            == report["graph_mdp_state"]["graph_statistics"]["node_count"]
            and report["graph_mdp_state"]["graph_statistics"]["edge_count"]
            == (admin_graph.get("summary") or {}).get("edge_count")
            + (geographic_similarity_kernel.get("summary") or {}).get(
                "similarity_edge_count"
            )
        ),
    }
    if report["full_data_guard"]["passed"] is not True:
        raise SystemExit(f"full data guard failed: {report['full_data_guard']}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _write_json(REPORT_PATH, report)
    _write_json(
        MANIFEST_PATH,
        {
            "snapshot_id": "uwm_full_admin_graph_planner_replay_2026_07_08",
            "created_at": "2026-07-08T11:00:00+00:00",
            "schema": "uwm.snapshot_manifest.v1",
            "output_path": str(REPORT_PATH.relative_to(REPO_ROOT)),
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
            "graph_statistics": report["graph_mdp_state"]["graph_statistics"],
            "search_config": report["search_config"],
            "advantage_over_static_single_step": report[
                "advantage_over_static_single_step"
            ],
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
                "path": str(REPORT_PATH.relative_to(REPO_ROOT)),
                "node_count": report["graph_mdp_state"]["graph_statistics"][
                    "node_count"
                ],
                "available_action_count": report["graph_mdp_state"][
                    "graph_statistics"
                ]["available_action_count"],
                "edge_count": report["graph_mdp_state"]["graph_statistics"][
                    "edge_count"
                ],
                "transition_count": report["trajectory_dataset"][
                    "transition_count"
                ],
                "advantage_over_static_single_step": report[
                    "advantage_over_static_single_step"
                ],
                "full_data_guard": report["full_data_guard"],
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

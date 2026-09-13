"""Build full-admin feasible action inventory for UWM livability."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from data_agent.uwm.full_admin_action_inventory import build_full_admin_action_inventory
from data_agent.uwm.livability_graph_mdp_env import build_livability_graph_mdp_env
from data_agent.uwm.model_based_rl import build_admin_livability_graph_observation


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = REPO_ROOT / "data/uwm_public_proxy/chongqing_central"
OUTPUT_DIR = DATA_ROOT / "full_admin_action_inventory_2026_07_08"
OUTPUT_PATH = OUTPUT_DIR / "uwm_full_admin_action_inventory.json"
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
SPATIAL_CAUSAL_QUESTION_REGISTRY_PATH = (
    DATA_ROOT
    / "spatial_causal_question_registry_2026_07_09/uwm_spatial_causal_question_registry.json"
)


def main() -> None:
    panel = _read_json(FULL_PANEL_PATH)
    admin_graph = _read_json(ADMIN_GRAPH_PATH)
    geographic_similarity_kernel = _read_json(GEOGRAPHIC_SIMILARITY_KERNEL_PATH)
    _validate_full_inputs(panel, admin_graph)
    observation = build_admin_livability_graph_observation(
        panel,
        observation_id="admin-livability-full-admin-action-inventory-obs-2026-07-08",
        created_at="2026-07-08T21:00:00Z",
        admin_spatial_graph=admin_graph,
        geographic_similarity_kernel=geographic_similarity_kernel,
    )
    env = build_livability_graph_mdp_env(
        observation,
        action_types=[
            "increase_green_infrastructure",
            "traffic_emission_control",
            "add_community_service",
        ],
        scenario={
            "scenario_id": "full_admin_action_inventory_heat_pollution_service_stress",
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
        air_quality_uncertainty_context=_read_json(SCENE_AIR_QUALITY_HOLDOUT_PATH),
    )
    source_artifacts = {
        "admin_livability_panel": str(FULL_PANEL_PATH.relative_to(REPO_ROOT)),
        "admin_spatial_graph": str(ADMIN_GRAPH_PATH.relative_to(REPO_ROOT)),
        "geographic_similarity_kernel": str(
            GEOGRAPHIC_SIMILARITY_KERNEL_PATH.relative_to(REPO_ROOT)
        ),
        "mechanism_table": str(MECHANISM_TABLE_PATH.relative_to(REPO_ROOT)),
        "air_quality_holdout": str(
            SCENE_AIR_QUALITY_HOLDOUT_PATH.relative_to(REPO_ROOT)
        ),
        "spatial_causal_question_registry": str(
            SPATIAL_CAUSAL_QUESTION_REGISTRY_PATH.relative_to(REPO_ROOT)
        ),
    }
    inventory = build_full_admin_action_inventory(
        env,
        inventory_id="uwm-full-admin-action-inventory-2026-07-08",
        created_at="2026-07-08T21:00:00Z",
        source_artifacts=source_artifacts,
        spatial_causal_question_registry=_read_json(
            SPATIAL_CAUSAL_QUESTION_REGISTRY_PATH
        ),
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _write_json(OUTPUT_PATH, inventory)
    _write_json(
        MANIFEST_PATH,
        {
            "schema": "uwm.snapshot_manifest.v1",
            "snapshot_id": "uwm_full_admin_action_inventory_2026_07_08",
            "created_at": inventory["created_at"],
            "output_path": str(OUTPUT_PATH.relative_to(REPO_ROOT)),
            "experiment_scope": inventory["experiment_scope"],
            "source_artifacts": source_artifacts,
            "full_data_guard": inventory["full_data_guard"],
            "summary": inventory["summary"],
            "spatial_causal_contract_binding": inventory[
                "spatial_causal_contract_binding"
            ],
            "supported_claim": inventory["supported_claim"],
            "observed_policy_outcome_superiority_claim": False,
            "empirical_superiority_claim": False,
        },
    )
    print(
        json.dumps(
            {
                "path": str(OUTPUT_PATH.relative_to(REPO_ROOT)),
                "full_admin_action_inventory_ready": inventory["full_data_guard"][
                    "passed"
                ],
                "graph_node_count": inventory["summary"]["graph_node_count"],
                "graph_edge_count": inventory["summary"]["graph_edge_count"],
                "available_action_count": inventory["summary"][
                    "available_action_count"
                ],
                "action_type_counts": inventory["summary"]["action_type_counts"],
                "mask_reason_counts": inventory["summary"]["mask_reason_counts"],
                "spatial_causal_contract_binding_ready": inventory[
                    "spatial_causal_contract_binding"
                ]["binding_ready"],
                "spatial_causal_attached_action_count": inventory[
                    "spatial_causal_contract_binding"
                ]["attached_action_count"],
                "spatial_causal_missing_contract_action_count": inventory[
                    "spatial_causal_contract_binding"
                ]["missing_contract_action_count"],
                "observed_policy_outcome_superiority_claim": False,
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

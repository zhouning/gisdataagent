"""Build the full-admin UWM world-model superiority dossier."""

from __future__ import annotations

import json
from pathlib import Path

from data_agent.uwm.full_admin_world_model_superiority_dossier import (
    build_uwm_full_admin_world_model_superiority_dossier,
    validate_uwm_full_admin_world_model_superiority_dossier,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = REPO_ROOT / "data/uwm_public_proxy/chongqing_central"
OUTPUT_DIR = DATA_ROOT / "full_admin_world_model_superiority_dossier_2026_07_09"
OUTPUT_PATH = OUTPUT_DIR / "uwm_full_admin_world_model_superiority_dossier.json"
MANIFEST_PATH = OUTPUT_DIR / "snapshot_manifest.json"

SOURCE_PATHS = {
    "full_admin_graph_planner_replay": DATA_ROOT
    / "data_calibrated_planner_replay_full_admin_graph_2026_07_08/uwm_full_admin_graph_model_based_graph_search.json",
    "full_admin_graph_drl_training_report": DATA_ROOT
    / "livability_graph_drl_training_full_admin_graph_2026_07_08/uwm_full_admin_graph_livability_graph_drl_training_report.json",
    "full_admin_learned_world_model_rollout": DATA_ROOT
    / "learned_world_model_rollout_full_admin_graph_2026_07_08/uwm_full_admin_graph_learned_world_model_rollout.json",
    "full_admin_energy_regularized_planner_report": DATA_ROOT
    / "energy_regularized_planner_full_admin_graph_2026_07_08/uwm_full_admin_graph_energy_regularized_planner_report.json",
    "full_admin_livability_decision_package": DATA_ROOT
    / "full_admin_livability_decision_package_2026_07_08/uwm_full_admin_livability_decision_package.json",
    "livability_endpoint_suite": DATA_ROOT
    / "livability_endpoint_suite_2026_07_07/uwm_livability_endpoint_suite.json",
    "full_admin_service_accessibility_surface": DATA_ROOT
    / "full_admin_service_accessibility_surface_2026_07_08/uwm_full_admin_service_accessibility_surface.json",
    "geographic_similarity_kernel": DATA_ROOT
    / "geographic_similarity_kernel_2026_07_08/uwm_geographic_similarity_kernel.json",
    "spatial_causal_question_registry": DATA_ROOT
    / "spatial_causal_question_registry_2026_07_09/uwm_spatial_causal_question_registry.json",
    "production_governance_planner_binding_gate": DATA_ROOT
    / "production_governance_planner_binding_gate_2026_07_08/uwm_production_governance_planner_binding_gate.json",
}


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    sources = {name: _read_json(path) for name, path in SOURCE_PATHS.items()}
    source_artifact_paths = {
        name: str(path.relative_to(REPO_ROOT)) for name, path in SOURCE_PATHS.items()
    }
    dossier = build_uwm_full_admin_world_model_superiority_dossier(
        dossier_id="uwm-full-admin-world-model-superiority-dossier-2026-07-09",
        created_at="2026-07-09T13:00:00Z",
        source_artifact_paths=source_artifact_paths,
        **sources,
    )
    validation = validate_uwm_full_admin_world_model_superiority_dossier(dossier)
    if validation["valid"] is not True:
        raise SystemExit(f"invalid UWM superiority dossier: {validation['errors']}")
    _write_json(OUTPUT_PATH, dossier)
    manifest = {
        "schema": "uwm.snapshot_manifest.v1",
        "snapshot_id": "uwm_full_admin_world_model_superiority_dossier_2026_07_09",
        "created_at": "2026-07-09T13:00:00Z",
        "artifact_path": str(OUTPUT_PATH.relative_to(REPO_ROOT)),
        "source_artifact_paths": source_artifact_paths,
        "supported_claim": dossier["supported_claim"],
        "claim_boundary": dossier["claim_boundary"],
        "full_admin_scope_guard": dossier["full_admin_scope_guard"],
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
    }
    _write_json(MANIFEST_PATH, manifest)
    print(
        json.dumps(
            {
                "path": str(OUTPUT_PATH.relative_to(REPO_ROOT)),
                "supported_claim": dossier["supported_claim"],
                "graph_node_count": dossier["full_admin_scope_guard"][
                    "graph_node_count"
                ],
                "available_action_count": dossier["full_admin_scope_guard"][
                    "available_action_count"
                ],
                "transition_count": dossier["full_admin_scope_guard"][
                    "transition_count"
                ],
                "planner_attached_action_count": dossier[
                    "causal_and_governance_gate"
                ]["planner_attached_action_count"],
                "observed_policy_outcome_superiority_claim": False,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()

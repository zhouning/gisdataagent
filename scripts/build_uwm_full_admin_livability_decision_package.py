"""Build the full-admin UWM livability decision package."""

from __future__ import annotations

import json
from pathlib import Path

from data_agent.uwm.full_admin_livability_decision_package import (
    build_uwm_full_admin_livability_decision_package,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = REPO_ROOT / "data/uwm_public_proxy/chongqing_central"
OUTPUT_DIR = DATA_ROOT / "full_admin_livability_decision_package_2026_07_08"
OUTPUT_PATH = OUTPUT_DIR / "uwm_full_admin_livability_decision_package.json"
MANIFEST_PATH = OUTPUT_DIR / "snapshot_manifest.json"

FULL_ADMIN_GRAPH_PLANNER_REPLAY_PATH = (
    DATA_ROOT
    / "data_calibrated_planner_replay_full_admin_graph_2026_07_08/uwm_full_admin_graph_model_based_graph_search.json"
)
FULL_ADMIN_GRAPH_DRL_TRAINING_REPORT_PATH = (
    DATA_ROOT
    / "livability_graph_drl_training_full_admin_graph_2026_07_08/uwm_full_admin_graph_livability_graph_drl_training_report.json"
)
FULL_ADMIN_LEARNED_WORLD_MODEL_ROLLOUT_PATH = (
    DATA_ROOT
    / "learned_world_model_rollout_full_admin_graph_2026_07_08/uwm_full_admin_graph_learned_world_model_rollout.json"
)
GEOGRAPHIC_SIMILARITY_KERNEL_PATH = (
    DATA_ROOT
    / "geographic_similarity_kernel_2026_07_08/uwm_geographic_similarity_kernel.json"
)
FULL_ADMIN_SERVICE_ACCESSIBILITY_SURFACE_PATH = (
    DATA_ROOT
    / "full_admin_service_accessibility_surface_2026_07_08/uwm_full_admin_service_accessibility_surface.json"
)
FULL_ADMIN_SERVICE_SURFACE_QUALITY_AUDIT_PATH = (
    DATA_ROOT
    / "full_admin_service_surface_quality_audit_2026_07_08/uwm_full_admin_service_surface_quality_audit.json"
)
PRODUCTION_GOVERNANCE_PLANNER_BINDING_GATE_PATH = (
    DATA_ROOT
    / "production_governance_planner_binding_gate_2026_07_08/uwm_production_governance_planner_binding_gate.json"
)
SPATIAL_CAUSAL_QUESTION_REGISTRY_PATH = (
    DATA_ROOT
    / "spatial_causal_question_registry_2026_07_09/uwm_spatial_causal_question_registry.json"
)


def main() -> None:
    package = build_uwm_full_admin_livability_decision_package(
        package_id="uwm-full-admin-livability-decision-package-2026-07-08",
        created_at="2026-07-08T18:30:00Z",
        full_admin_graph_planner_replay=_read_json(
            FULL_ADMIN_GRAPH_PLANNER_REPLAY_PATH
        ),
        full_admin_graph_drl_training_report=_read_json(
            FULL_ADMIN_GRAPH_DRL_TRAINING_REPORT_PATH
        ),
        full_admin_learned_world_model_rollout=_read_json(
            FULL_ADMIN_LEARNED_WORLD_MODEL_ROLLOUT_PATH
        ),
        geographic_similarity_kernel=_read_json(GEOGRAPHIC_SIMILARITY_KERNEL_PATH),
        full_admin_service_accessibility_surface=_read_json(
            FULL_ADMIN_SERVICE_ACCESSIBILITY_SURFACE_PATH
        ),
        full_admin_service_surface_quality_audit=_read_json(
            FULL_ADMIN_SERVICE_SURFACE_QUALITY_AUDIT_PATH
        ),
        production_governance_planner_binding_gate=_read_json(
            PRODUCTION_GOVERNANCE_PLANNER_BINDING_GATE_PATH
        ),
        spatial_causal_question_registry=_read_json(
            SPATIAL_CAUSAL_QUESTION_REGISTRY_PATH
        ),
    )
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _write_json(OUTPUT_PATH, package)
    manifest = {
        "snapshot_id": "uwm_full_admin_livability_decision_package_2026_07_08",
        "created_at": "2026-07-08T18:30:00Z",
        "package_path": str(OUTPUT_PATH.relative_to(REPO_ROOT)),
        "source_full_admin_graph_planner_replay_path": str(
            FULL_ADMIN_GRAPH_PLANNER_REPLAY_PATH.relative_to(REPO_ROOT)
        ),
        "source_full_admin_graph_drl_training_report_path": str(
            FULL_ADMIN_GRAPH_DRL_TRAINING_REPORT_PATH.relative_to(REPO_ROOT)
        ),
        "source_full_admin_learned_world_model_rollout_path": str(
            FULL_ADMIN_LEARNED_WORLD_MODEL_ROLLOUT_PATH.relative_to(REPO_ROOT)
        ),
        "source_geographic_similarity_kernel_path": str(
            GEOGRAPHIC_SIMILARITY_KERNEL_PATH.relative_to(REPO_ROOT)
        ),
        "source_full_admin_service_accessibility_surface_path": str(
            FULL_ADMIN_SERVICE_ACCESSIBILITY_SURFACE_PATH.relative_to(REPO_ROOT)
        ),
        "source_full_admin_service_surface_quality_audit_path": str(
            FULL_ADMIN_SERVICE_SURFACE_QUALITY_AUDIT_PATH.relative_to(REPO_ROOT)
        ),
        "source_production_governance_planner_binding_gate_path": str(
            PRODUCTION_GOVERNANCE_PLANNER_BINDING_GATE_PATH.relative_to(REPO_ROOT)
        ),
        "source_spatial_causal_question_registry_path": str(
            SPATIAL_CAUSAL_QUESTION_REGISTRY_PATH.relative_to(REPO_ROOT)
        ),
        "full_admin_decision_package_ready": package[
            "full_admin_decision_package_ready"
        ],
        "graph_node_count": package["full_data_guard"]["graph_node_count"],
        "graph_edge_count": package["full_data_guard"]["graph_edge_count"],
        "geographic_similarity_edge_count": package["full_data_guard"][
            "geographic_similarity_edge_count"
        ],
        "available_action_count": package["full_data_guard"][
            "available_action_count"
        ],
        "transition_count": package["full_data_guard"]["transition_count"],
        "planner_governance_binding_ready": package[
            "planner_governance_binding_ready"
        ],
        "production_governance_binding_blocking_gate_count": package[
            "production_governance_binding_evidence"
        ]["blocking_gate_count"],
        "spatial_causal_contract_binding_ready": package[
            "spatial_causal_contract_binding"
        ]["binding_ready"],
        "spatial_causal_attached_action_count": package[
            "spatial_causal_contract_binding"
        ]["attached_action_count"],
        "spatial_causal_missing_contract_action_count": package[
            "spatial_causal_contract_binding"
        ]["missing_contract_action_count"],
        "supported_claim": package["supported_claim"],
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
    }
    _write_json(MANIFEST_PATH, manifest)
    comparison = package["comparison_against_traditional_static_baselines"]
    print(
        json.dumps(
            {
                "package_path": str(OUTPUT_PATH.relative_to(REPO_ROOT)),
                "full_admin_decision_package_ready": package[
                    "full_admin_decision_package_ready"
                ],
                "graph_node_count": package["full_data_guard"]["graph_node_count"],
                "graph_edge_count": package["full_data_guard"]["graph_edge_count"],
                "geographic_similarity_edge_count": package["full_data_guard"][
                    "geographic_similarity_edge_count"
                ],
                "available_action_count": package["full_data_guard"][
                    "available_action_count"
                ],
                "transition_count": package["full_data_guard"]["transition_count"],
                "planner_advantage_over_static": comparison[
                    "planner_advantage_over_static"
                ],
                "planner_risk_adjusted_advantage_over_static": comparison[
                    "planner_risk_adjusted_advantage_over_static"
                ],
                "graph_dqn_advantage_over_static": comparison[
                    "graph_dqn_advantage_over_static"
                ],
                "learned_rollout_advantage_over_static": comparison[
                    "learned_rollout_advantage_over_static"
                ],
                "planner_governance_binding_ready": package[
                    "planner_governance_binding_ready"
                ],
                "production_governance_binding_blocking_gate_count": package[
                    "production_governance_binding_evidence"
                ]["blocking_gate_count"],
                "spatial_causal_contract_binding_ready": package[
                    "spatial_causal_contract_binding"
                ]["binding_ready"],
                "spatial_causal_attached_action_count": package[
                    "spatial_causal_contract_binding"
                ]["attached_action_count"],
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

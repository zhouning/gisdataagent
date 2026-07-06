"""Build UWM data-foundation evidence gate from prepared project artifacts."""

from __future__ import annotations

import json
from pathlib import Path

from data_agent.uwm.data_foundation_evidence_gate import build_uwm_data_foundation_evidence_gate


REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = REPO_ROOT / "data/uwm_public_proxy/chongqing_central/data_foundation_evidence_gate_2026_07_05"
OUTPUT_PATH = OUTPUT_DIR / "uwm_data_foundation_evidence_gate.json"


def main() -> None:
    gate = build_uwm_data_foundation_evidence_gate(
        manifest_path=REPO_ROOT / "docs/reports/uwm_data_foundation_manifest.csv",
        openaq_temporal_benchmark_path=REPO_ROOT
        / "data/uwm_public_proxy/chongqing_central/openaq_temporal_benchmark_2018_10/uwm_openaq_observed_temporal_benchmark.json",
        tap_external_dynamics_path=REPO_ROOT
        / "data/uwm_public_proxy/chongqing_central/tap_pm25_external_dynamics_2026_07_06/tap_external_dynamics_report.json",
        learned_rollout_path=REPO_ROOT
        / "data/uwm_public_proxy/chongqing_central/model_based_rl_graph_search_2026_07_05/uwm_offline_world_model_rollout_planner_admin_livability_spatial_graph_proxy.json",
        livability_intervention_package_path=REPO_ROOT
        / "data/uwm_public_proxy/chongqing_central/model_based_rl_graph_search_2026_07_05/uwm_livability_intervention_package_admin_livability_spatial_graph.json",
        local_planning_inventory_path=REPO_ROOT
        / "data/uwm_public_proxy/chongqing_central/local_planning_zip_audit_2026_07_05/uwm_local_planning_zip_inventory.csv",
        admin_spatial_graph_path=REPO_ROOT
        / "data/uwm_public_proxy/chongqing_central/admin_spatial_graph_2026_07_05/uwm_admin_spatial_adjacency_graph.json",
        gate_id="uwm-data-foundation-evidence-gate-2026-07-05",
        created_at="2026-07-05T22:45:00Z",
    )
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as handle:
        json.dump(gate, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(
        json.dumps(
            {
                "path": str(OUTPUT_PATH.relative_to(REPO_ROOT)),
                "manifest_row_count": gate["data_foundation_scope"]["manifest_row_count"],
                "observed_state_prediction_superiority_claim": gate[
                    "observed_state_prediction_superiority_claim"
                ],
                "observed_policy_outcome_superiority_claim": gate[
                    "observed_policy_outcome_superiority_claim"
                ],
                "openaq_holdout_win_rate": gate["evidence_slices"][
                    "openaq_observed_temporal_state"
                ]["overall_holdout_win_rate"],
                "tap_external_transition_claim": gate["external_temporal_transition_superiority_claim"],
                "tap_external_transition_mae": gate["evidence_slices"][
                    "tap_external_temporal_transition"
                ]["best_transition_mae"],
                "remaining_gates": gate["remaining_gates"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

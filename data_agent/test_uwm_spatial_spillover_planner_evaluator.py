import json
from pathlib import Path

from data_agent.uwm.data_foundation_evidence_gate import (
    build_uwm_data_foundation_evidence_gate,
)
from data_agent.uwm.spatial_spillover_planner_evaluator import (
    UWM_SPATIAL_SPILLOVER_PLANNER_EVALUATOR_SCHEMA,
    build_uwm_spatial_spillover_planner_evaluator,
)
from data_agent.uwm.world_model_evidence_readiness import (
    build_world_model_evidence_readiness,
)


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data/uwm_public_proxy/chongqing_central"


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _build_evaluator() -> dict:
    return build_uwm_spatial_spillover_planner_evaluator(
        evaluator_id="uwm-spatial-spillover-planner-evaluator-real-data-test",
        created_at="2026-07-07T11:00:00Z",
        data_calibrated_planner_replay=_read_json(
            DATA_ROOT
            / "data_calibrated_planner_replay_2026_07_06/uwm_data_calibrated_model_based_graph_search.json"
        ),
        admin_spatial_graph=_read_json(
            DATA_ROOT
            / "admin_spatial_graph_2026_07_05/uwm_admin_spatial_adjacency_graph.json"
        ),
    )


def test_spatial_spillover_planner_evaluator_beats_static_on_real_graph():
    evaluator = _build_evaluator()

    assert evaluator["schema"] == UWM_SPATIAL_SPILLOVER_PLANNER_EVALUATOR_SCHEMA
    assert evaluator["evaluation_method"] == "first_order_admin_neighbor_spillover"
    assert evaluator["planner_target_unit_count"] == 2
    assert evaluator["static_target_unit_count"] == 1
    assert evaluator["planner_neighbor_benefited_unit_count"] == 11
    assert evaluator["static_neighbor_benefited_unit_count"] == 5
    assert evaluator["neighbor_benefited_unit_count_advantage"] == 6
    assert evaluator["planner_neighbor_livability_delta_sum"] == 0.499913472
    assert evaluator["static_neighbor_livability_delta_sum"] == 0.227233396
    assert evaluator["neighbor_livability_delta_advantage"] == 0.272680076
    assert evaluator["neighbor_livability_delta_advantage_ratio"] == 2.2
    assert evaluator["supported_claim"] == (
        "spatial_spillover_planner_replay_advantage_over_static_heuristic"
    )
    assert evaluator["observed_policy_outcome_superiority_claim"] is False


def test_evidence_gate_tracks_spatial_spillover_planner_evaluator(tmp_path: Path):
    evaluator = _build_evaluator()
    evaluator_path = tmp_path / "uwm_spatial_spillover_planner_evaluator.json"
    evaluator_path.write_text(
        json.dumps(evaluator, ensure_ascii=False),
        encoding="utf-8",
    )

    gate = build_uwm_data_foundation_evidence_gate(
        manifest_path=ROOT / "docs/reports/uwm_data_foundation_manifest.csv",
        openaq_temporal_benchmark_path=DATA_ROOT
        / "openaq_temporal_benchmark_2018_10/uwm_openaq_observed_temporal_benchmark.json",
        tap_external_dynamics_path=DATA_ROOT
        / "tap_pm25_external_dynamics_2026_07_06/tap_external_dynamics_report.json",
        learned_rollout_path=DATA_ROOT
        / "model_based_rl_graph_search_2026_07_05/uwm_offline_world_model_rollout_planner_admin_livability_spatial_graph_proxy.json",
        livability_intervention_package_path=DATA_ROOT
        / "model_based_rl_graph_search_2026_07_05/uwm_livability_intervention_package_admin_livability_spatial_graph.json",
        local_planning_inventory_path=DATA_ROOT
        / "local_planning_zip_audit_2026_07_05/uwm_local_planning_zip_inventory.csv",
        admin_spatial_graph_path=DATA_ROOT
        / "admin_spatial_graph_2026_07_05/uwm_admin_spatial_adjacency_graph.json",
        spatial_spillover_planner_evaluator_path=evaluator_path,
        gate_id="uwm-data-foundation-evidence-gate-spillover-planner-test",
        created_at="2026-07-07T11:10:00Z",
    )

    spillover_slice = gate["evidence_slices"]["spatial_spillover_planner_evaluator"]
    assert spillover_slice["source_artifact_exists"] is True
    assert spillover_slice["spatial_spillover_planner_evaluator_ready"] is True
    assert spillover_slice["planner_neighbor_benefited_unit_count"] == 11
    assert spillover_slice["static_neighbor_benefited_unit_count"] == 5
    assert spillover_slice["neighbor_livability_delta_advantage"] == 0.272680076
    assert "spatial_spillover_planner_replay_advantage_over_static_heuristic" in {
        claim["claim"] for claim in gate["supported_claims"]
    }

    readiness = build_world_model_evidence_readiness(gate)
    planner = readiness["architecture_evidence"]["planner"]
    assert planner["spatial_spillover_planner_evaluator_ready"] is True
    assert planner["neighbor_livability_delta_advantage"] == 0.272680076
    assert readiness["policy_outcome_superiority_ready"] is False

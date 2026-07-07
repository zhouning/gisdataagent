import json
from pathlib import Path

from data_agent.uwm.data_foundation_evidence_gate import (
    build_uwm_data_foundation_evidence_gate,
)
from data_agent.uwm.endpoint_aligned_planner_evaluator import (
    UWM_ENDPOINT_ALIGNED_PLANNER_EVALUATOR_SCHEMA,
    build_uwm_endpoint_aligned_planner_evaluator,
)
from data_agent.uwm.world_model_evidence_readiness import (
    build_world_model_evidence_readiness,
)


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data/uwm_public_proxy/chongqing_central"


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _build_evaluator() -> dict:
    return build_uwm_endpoint_aligned_planner_evaluator(
        evaluator_id="uwm-endpoint-aligned-planner-evaluator-real-data-test",
        created_at="2026-07-07T10:00:00Z",
        data_calibrated_planner_replay=_read_json(
            DATA_ROOT
            / "data_calibrated_planner_replay_2026_07_06/uwm_data_calibrated_model_based_graph_search.json"
        ),
        livability_endpoint_suite=_read_json(
            DATA_ROOT
            / "livability_endpoint_suite_2026_07_07/uwm_livability_endpoint_suite.json"
        ),
    )


def test_endpoint_aligned_planner_evaluator_beats_static_on_real_replay():
    evaluator = _build_evaluator()

    assert evaluator["schema"] == UWM_ENDPOINT_ALIGNED_PLANNER_EVALUATOR_SCHEMA
    assert evaluator["evaluation_method"] == (
        "endpoint_validation_weighted_rollout_delta"
    )
    assert evaluator["endpoint_count"] == 3
    assert evaluator["planner_sequence_action_count"] == 2
    assert evaluator["static_sequence_action_count"] == 1
    assert evaluator["planner_endpoint_aligned_score"] == 0.001407208
    assert evaluator["static_endpoint_aligned_score"] == 0.000661508
    assert evaluator["endpoint_aligned_advantage_over_static"] == 0.0007457
    assert evaluator["endpoint_aligned_advantage_ratio"] == 2.127273
    assert evaluator["endpoint_weights"] == {
        "air_quality_pm25": 0.003047,
        "service_point_accessibility": 0.128622,
        "essential_service_accessibility": 0.214343,
    }
    assert evaluator["supported_claim"] == (
        "endpoint_aligned_planner_replay_advantage_over_static_heuristic"
    )
    assert evaluator["observed_policy_outcome_superiority_claim"] is False


def test_evidence_gate_tracks_endpoint_aligned_planner_evaluator(tmp_path: Path):
    evaluator = _build_evaluator()
    evaluator_path = tmp_path / "uwm_endpoint_aligned_planner_evaluator.json"
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
        endpoint_aligned_planner_evaluator_path=evaluator_path,
        gate_id="uwm-data-foundation-evidence-gate-endpoint-planner-test",
        created_at="2026-07-07T10:10:00Z",
    )

    planner_slice = gate["evidence_slices"]["endpoint_aligned_planner_evaluator"]
    assert planner_slice["source_artifact_exists"] is True
    assert planner_slice["endpoint_aligned_planner_evaluator_ready"] is True
    assert planner_slice["endpoint_count"] == 3
    assert planner_slice["planner_endpoint_aligned_score"] == 0.001407208
    assert planner_slice["static_endpoint_aligned_score"] == 0.000661508
    assert planner_slice["endpoint_aligned_advantage_over_static"] == 0.0007457
    assert planner_slice["observed_policy_outcome_superiority_claim"] is False
    assert "endpoint_aligned_planner_replay_advantage_over_static_heuristic" in {
        claim["claim"] for claim in gate["supported_claims"]
    }

    readiness = build_world_model_evidence_readiness(gate)
    planner = readiness["architecture_evidence"]["planner"]
    assert planner["endpoint_aligned_planner_evaluator_ready"] is True
    assert planner["endpoint_aligned_advantage_over_static"] == 0.0007457
    assert readiness["policy_outcome_superiority_ready"] is False

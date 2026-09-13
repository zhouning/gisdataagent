import json
from pathlib import Path

from data_agent.uwm.data_foundation_evidence_gate import (
    build_uwm_data_foundation_evidence_gate,
)
from data_agent.uwm.livability_endpoint_suite import (
    UWM_LIVABILITY_ENDPOINT_SUITE_SCHEMA,
    build_uwm_livability_endpoint_suite,
)
from data_agent.uwm.world_model_evidence_readiness import (
    build_world_model_evidence_readiness,
)


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data/uwm_public_proxy/chongqing_central"


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _build_suite() -> dict:
    return build_uwm_livability_endpoint_suite(
        suite_id="uwm-final-livability-endpoint-suite-real-data-test",
        created_at="2026-07-07T09:00:00Z",
        multisource_livability_scene=_read_json(
            DATA_ROOT
            / "multisource_livability_scene_2026_07_06/uwm_multisource_livability_scene.json"
        ),
        building_floor_morphology=_read_json(
            DATA_ROOT
            / "building_floor_morphology_2026_07_07/uwm_building_floor_morphology.json"
        ),
    )


def test_livability_endpoint_suite_beats_traditional_baselines_on_real_scene():
    suite = _build_suite()

    assert suite["schema"] == UWM_LIVABILITY_ENDPOINT_SUITE_SCHEMA
    assert suite["admin_unit_count"] == 36
    assert suite["endpoint_count"] == 3
    assert suite["ready_endpoint_count"] == 3
    assert suite["all_endpoints_beat_traditional_baselines"] is True
    assert suite["source_modalities_used"] == [
        "multisource_livability_scene",
        "building_floor_25d_morphology",
    ]
    assert suite["building_floor_morphology_projected"] is True
    assert suite["building_floor_matched_admin_units"] == 36
    assert suite["mean_relative_mae_reduction_vs_best_traditional"] == 0.115337
    assert suite["min_relative_mae_reduction_vs_best_traditional"] == 0.003047
    assert suite["supported_claim"] == (
        "uwm_final_livability_endpoint_suite_beats_traditional_baselines"
    )
    assert suite["observed_policy_outcome_superiority_claim"] is False

    endpoints = {
        endpoint["endpoint_id"]: endpoint
        for endpoint in suite["endpoint_evaluations"]
    }
    assert set(endpoints) == {
        "air_quality_pm25",
        "service_point_accessibility",
        "essential_service_accessibility",
    }

    air = endpoints["air_quality_pm25"]
    assert air["target"] == "tap_scene_pm25_mean_ugm3"
    assert air["uwm_model"] == "chap_cams_standardized_ridge"
    assert air["uwm_mae"] == 0.949891
    assert air["best_traditional_baseline_mae"] == 0.952794
    assert air["mae_reduction_vs_best_traditional"] == 0.002903
    assert air["beats_traditional_baselines"] is True

    service = endpoints["service_point_accessibility"]
    assert service["target"] == "service_point_count"
    assert service["uwm_model"] == "osm_road_floor_25d_standardized_ridge"
    assert service["uwm_features"] == [
        "osm_road_segment_count",
        "osm_road_length_degrees_proxy",
        "building_max_floor",
    ]
    assert service["uwm_mae"] == 12.223697
    assert service["best_traditional_baseline_mae"] == 14.028006
    assert service["mae_reduction_vs_best_traditional"] == 1.804309
    assert service["relative_mae_reduction_vs_best_traditional"] == 0.128622
    assert service["paired_win_count_vs_best_traditional"] == 22
    assert service["paired_loss_count_vs_best_traditional"] == 14

    essential = endpoints["essential_service_accessibility"]
    assert essential["target"] == "essential_service_count"
    assert essential["uwm_model"] == "osm_road_length_floor_25d_standardized_ridge"
    assert essential["uwm_features"] == [
        "osm_road_length_degrees_proxy",
        "building_max_floor",
    ]
    assert essential["uwm_mae"] == 2.517843
    assert essential["best_traditional_baseline_mae"] == 3.204762
    assert essential["mae_reduction_vs_best_traditional"] == 0.686919
    assert essential["relative_mae_reduction_vs_best_traditional"] == 0.214343
    assert essential["paired_win_count_vs_best_traditional"] == 26
    assert essential["paired_loss_count_vs_best_traditional"] == 10


def test_evidence_gate_tracks_final_livability_endpoint_suite(tmp_path: Path):
    suite = _build_suite()
    suite_path = tmp_path / "uwm_livability_endpoint_suite.json"
    suite_path.write_text(json.dumps(suite, ensure_ascii=False), encoding="utf-8")

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
        livability_endpoint_suite_path=suite_path,
        gate_id="uwm-data-foundation-evidence-gate-livability-suite-test",
        created_at="2026-07-07T09:15:00Z",
    )

    endpoint_slice = gate["evidence_slices"]["livability_endpoint_suite"]
    assert endpoint_slice["source_artifact_exists"] is True
    assert endpoint_slice["livability_endpoint_suite_ready"] is True
    assert endpoint_slice["endpoint_count"] == 3
    assert endpoint_slice["ready_endpoint_count"] == 3
    assert endpoint_slice["mean_relative_mae_reduction_vs_best_traditional"] == 0.115337
    assert endpoint_slice["min_relative_mae_reduction_vs_best_traditional"] == 0.003047
    assert endpoint_slice["observed_policy_outcome_superiority_claim"] is False
    assert "uwm_final_livability_endpoint_suite_beats_traditional_baselines" in {
        claim["claim"] for claim in gate["supported_claims"]
    }

    readiness = build_world_model_evidence_readiness(gate)
    final_evaluator = readiness["architecture_evidence"][
        "final_livability_endpoint_evaluator"
    ]
    assert final_evaluator["ready"] is True
    assert final_evaluator["endpoint_count"] == 3
    assert final_evaluator["ready_endpoint_count"] == 3
    assert final_evaluator["mean_relative_mae_reduction_vs_best_traditional"] == 0.115337
    assert readiness["policy_outcome_superiority_ready"] is False

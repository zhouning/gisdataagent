import csv
import json
from pathlib import Path

from data_agent.uwm.multisource_livability_scene import (
    UWM_MULTISOURCE_LIVABILITY_SCENE_SCHEMA,
    build_uwm_multisource_livability_scene,
)
from data_agent.uwm.data_foundation_evidence_gate import (
    build_uwm_data_foundation_evidence_gate,
)
from data_agent.uwm.world_model_evidence_readiness import (
    build_world_model_evidence_readiness,
)


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data/uwm_public_proxy/chongqing_central"


def _read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _build_scene() -> dict:
    return build_uwm_multisource_livability_scene(
        scene_id="uwm-multisource-livability-scene-real-data-test",
        created_at="2026-07-06T23:10:00Z",
        admin_livability_rows=_read_csv(
            DATA_ROOT
            / "admin_livability_target_complete_bbox_2024_07_2026_07_05/uwm_admin_livability_target_complete_bbox_panel.csv"
        ),
        admin_exposure_equity_rows=_read_csv(
            DATA_ROOT
            / "admin_exposure_equity_2024_07_01_07/uwm_admin_exposure_equity_panel.csv"
        ),
        service_accessibility_rows=_read_csv(
            DATA_ROOT
            / "admin_service_accessibility_complete_bbox_2026_07_05/uwm_admin_service_accessibility_complete_bbox_panel.csv"
        ),
        ghsl_admin_rows=_read_csv(
            DATA_ROOT / "ghsl_admin_alignment/ghsl_admin_zonal_proxy.csv"
        ),
        gee_admin_environment=_read_json(
            DATA_ROOT
            / "gee_admin_environment_2024_07_01_07/gee_admin_environment_proxy.json"
        ),
        scene_aligned_gridded_air_quality_holdout=_read_json(
            DATA_ROOT
            / "scene_aligned_gridded_air_quality_holdout_2026_07_06/uwm_scene_aligned_gridded_air_quality_holdout.json"
        ),
        admin_spatial_graph=_read_json(
            DATA_ROOT
            / "admin_spatial_graph_2026_07_05/uwm_admin_spatial_adjacency_graph.json"
        ),
        unicom_latent_mobility_graph=_read_json(
            DATA_ROOT
            / "fitted_gap_filling_2026_07_05/unicom_latent_mobility_graph.json"
        ),
        osm_mobility_network=_read_json(
            DATA_ROOT
            / "osm_complete_bbox_2026_07_05/mobility/osm_mobility_network_proxy.json"
        ),
        osm_admin_mobility_crosswalk=_read_json(
            DATA_ROOT
            / "osm_admin_mobility_crosswalk_2026_07_06/uwm_osm_admin_mobility_crosswalk.json"
        ),
    )


def test_multisource_livability_scene_renders_real_admin_unit_state_without_smoke():
    scene = _build_scene()

    assert scene["schema"] == UWM_MULTISOURCE_LIVABILITY_SCENE_SCHEMA
    assert scene["admin_unit_count"] == 36
    assert scene["source_coverage"]["admin_exposure_equity"]["matched_admin_units"] == 36
    assert scene["source_coverage"]["ghsl_admin_alignment"]["matched_admin_units"] == 36
    assert scene["source_coverage"]["service_accessibility"]["matched_admin_units"] == 36
    assert scene["source_coverage"]["gee_admin_environment"]["matched_admin_units"] == 36
    assert scene["source_coverage"]["scene_aligned_gridded_pm25"]["matched_admin_units"] == 36
    assert scene["source_coverage"]["admin_spatial_graph"]["source_node_count"] == 1017
    assert scene["source_coverage"]["unicom_latent_mobility_graph"]["edge_count"] == 1067

    used = set(scene["data_sources_used"])
    assert {
        "admin_livability_target_complete_bbox",
        "admin_exposure_equity",
        "admin_service_accessibility_complete_bbox",
        "ghsl_admin_alignment",
        "gee_admin_environment",
        "scene_aligned_gridded_air_quality_holdout",
        "admin_spatial_adjacency_graph",
        "unicom_latent_mobility_graph",
        "osm_mobility_network_proxy",
        "osm_admin_mobility_crosswalk",
    }.issubset(used)
    assert scene["source_coverage"]["osm_admin_mobility_crosswalk"][
        "matched_admin_units"
    ] == 36
    assert scene["source_coverage"]["osm_admin_mobility_crosswalk"][
        "assigned_road_segment_count"
    ] == 45449
    assert scene["source_coverage"]["osm_admin_mobility_crosswalk"][
        "unit_projection"
    ] == "admin_unit_state_vector"

    first = scene["admin_unit_states"][0]
    assert first["admin_unit_id"]
    assert first["state_vector"]["tap_scene_pm25_mean_ugm3"] > 0
    assert first["state_vector"]["ghsl_population_proxy_sum"] >= 0
    assert first["state_vector"]["service_gap_norm"] >= 0
    assert first["state_vector"]["livability_need_score"] >= 0
    assert first["state_vector"]["admin_graph_degree"] >= 0
    assert "osm_road_segment_count" in first["state_vector"]
    assert "osm_road_length_degrees_proxy" in first["state_vector"]
    assert first["source_join_trace"]["osm_assignment_rule"] == (
        "segment_midpoint_inside_admin_bbox_choose_smallest_bbox_area"
    )
    assert first["source_join_trace"]["join_key"] == "county_township"
    assert sum(
        row["state_vector"]["osm_road_segment_count"]
        for row in scene["admin_unit_states"]
    ) == 45449


def test_multisource_scene_air_quality_head_beats_single_source_baselines_on_real_holdout():
    scene = _build_scene()
    evaluation = scene["holdout_evaluation"][
        "air_quality_multisource_leave_one_admin_out"
    ]

    assert evaluation["target"] == "tap_scene_pm25_mean_ugm3"
    assert evaluation["model"] == "chap_cams_standardized_ridge"
    assert evaluation["holdout_admin_unit_count"] == 36
    assert evaluation["multisource_mae"] == 0.949891
    assert evaluation["single_source_baselines"]["chap_monthly_anchor_ridge"] == 0.952794
    assert evaluation["single_source_baselines"]["gee_cams_pm25_ridge"] == 1.010687
    assert evaluation["single_source_baselines"]["city_mean"] == 1.009252
    assert evaluation["mae_reduction_vs_best_single_source"] == 0.002903
    assert evaluation["paired_win_count_vs_chap"] == 20
    assert evaluation["paired_loss_count_vs_chap"] == 16
    assert evaluation["beats_all_single_source_baselines"] is True
    assert evaluation["spatial_interaction_negative_control_passed"] is False
    assert scene["supported_claim"] == (
        "multisource_livability_scene_air_quality_head_beats_single_source_baselines"
    )
    assert scene["observed_policy_outcome_superiority_claim"] is False


def test_data_foundation_gate_tracks_multisource_livability_scene(tmp_path: Path):
    scene = _build_scene()
    scene_path = tmp_path / "uwm_multisource_livability_scene.json"
    scene_path.write_text(json.dumps(scene, ensure_ascii=False), encoding="utf-8")

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
        multisource_livability_scene_path=scene_path,
        gate_id="uwm-data-foundation-evidence-gate-multisource-scene-test",
        created_at="2026-07-06T23:20:00Z",
    )

    scene_slice = gate["evidence_slices"]["multisource_livability_scene"]
    assert scene_slice["multisource_livability_scene_ready"] is True
    assert scene_slice["admin_unit_count"] == 36
    assert scene_slice["matched_source_count"] >= 7
    assert scene_slice["osm_admin_mobility_crosswalk_projected"] is True
    assert scene_slice["osm_crosswalk_matched_admin_units"] == 36
    assert scene_slice["osm_assigned_road_segment_count_in_scene"] == 45449
    assert scene_slice["air_quality_multisource_mae"] == 0.949891
    assert scene_slice["air_quality_best_single_source_mae"] == 0.952794
    assert scene_slice["air_quality_mae_reduction_vs_best_single_source"] == 0.002903
    assert scene_slice["observed_policy_outcome_superiority_claim"] is False
    assert "multisource_livability_scene_air_quality_head_beats_single_source_baselines" in {
        claim["claim"] for claim in gate["supported_claims"]
    }

    readiness = build_world_model_evidence_readiness(gate)
    renderer = readiness["architecture_evidence"]["renderer"]
    assert renderer["multisource_livability_scene_ready"] is True
    assert renderer["multisource_admin_unit_count"] == 36
    assert renderer["osm_admin_mobility_crosswalk_projected_in_scene"] is True
    assert renderer["osm_assigned_road_segment_count_in_scene"] == 45449
    assert readiness["empirical_superiority_claim"] is False

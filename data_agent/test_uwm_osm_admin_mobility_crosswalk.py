import csv
import json
from pathlib import Path

from data_agent.uwm.osm_admin_mobility_crosswalk import (
    UWM_OSM_ADMIN_MOBILITY_CROSSWALK_SCHEMA,
    build_uwm_osm_admin_mobility_crosswalk,
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


def _build_crosswalk() -> dict:
    return build_uwm_osm_admin_mobility_crosswalk(
        crosswalk_id="uwm-osm-admin-mobility-crosswalk-real-data-test",
        created_at="2026-07-06T23:50:00Z",
        admin_livability_rows=_read_csv(
            DATA_ROOT
            / "admin_livability_target_complete_bbox_2024_07_2026_07_05/uwm_admin_livability_target_complete_bbox_panel.csv"
        ),
        service_accessibility_rows=_read_csv(
            DATA_ROOT
            / "admin_service_accessibility_complete_bbox_2026_07_05/uwm_admin_service_accessibility_complete_bbox_panel.csv"
        ),
        ghsl_admin_rows=_read_csv(
            DATA_ROOT / "ghsl_admin_alignment/ghsl_admin_zonal_proxy.csv"
        ),
        admin_spatial_graph=_read_json(
            DATA_ROOT
            / "admin_spatial_graph_2026_07_05/uwm_admin_spatial_adjacency_graph.json"
        ),
        osm_mobility_network=_read_json(
            DATA_ROOT
            / "osm_complete_bbox_2026_07_05/mobility/osm_mobility_network_proxy.json"
        ),
        osm_overpass_raw=_read_json(
            DATA_ROOT
            / "osm_complete_bbox_2026_07_05/mobility/osm_mobility_network_overpass_raw.json"
        ),
    )


def test_osm_admin_mobility_crosswalk_assigns_real_road_segments_to_admin_units():
    crosswalk = _build_crosswalk()

    assert crosswalk["schema"] == UWM_OSM_ADMIN_MOBILITY_CROSSWALK_SCHEMA
    assert crosswalk["admin_unit_count"] == 36
    assert crosswalk["osm_raw_node_count"] == 42058
    assert crosswalk["osm_highway_way_count"] == 6762
    assert crosswalk["assigned_road_segment_count"] == 45449
    assert crosswalk["unassigned_road_segment_count"] == 19
    assert crosswalk["assignment_rule"] == (
        "segment_midpoint_inside_admin_bbox_choose_smallest_bbox_area"
    )

    first = crosswalk["admin_mobility_rows"][0]
    assert first["admin_unit_id"]
    assert first["road_segment_count"] >= 0
    assert first["road_length_degrees_proxy"] >= 0
    assert first["bbox_area_degrees2"] > 0


def test_osm_admin_mobility_head_beats_static_service_accessibility_baselines():
    crosswalk = _build_crosswalk()
    evaluation = crosswalk["holdout_evaluation"][
        "service_accessibility_leave_one_admin_out"
    ]

    assert evaluation["target"] == "osm_service_point_count"
    assert evaluation["model"] == "osm_road_segment_count_standardized_ridge"
    assert evaluation["holdout_admin_unit_count"] == 36
    assert evaluation["mobility_crosswalk_mae"] == 12.887057
    assert evaluation["traditional_static_baselines"]["city_mean"] == 14.152381
    assert evaluation["traditional_static_baselines"]["ghsl_population_proxy"] == 14.760068
    assert evaluation["traditional_static_baselines"]["ghsl_built_surface_proxy"] == 14.028006
    assert evaluation["mae_reduction_vs_best_traditional_static"] == 1.140949
    assert evaluation["paired_win_count_vs_best_traditional"] == 20
    assert evaluation["paired_loss_count_vs_best_traditional"] == 16
    assert evaluation["beats_all_traditional_static_baselines"] is True
    assert crosswalk["supported_claim"] == (
        "osm_admin_mobility_crosswalk_service_accessibility_head_beats_static_baselines"
    )
    assert crosswalk["observed_policy_outcome_superiority_claim"] is False


def test_data_foundation_gate_tracks_osm_admin_mobility_crosswalk(tmp_path: Path):
    crosswalk = _build_crosswalk()
    crosswalk_path = tmp_path / "uwm_osm_admin_mobility_crosswalk.json"
    crosswalk_path.write_text(json.dumps(crosswalk, ensure_ascii=False), encoding="utf-8")

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
        osm_admin_mobility_crosswalk_path=crosswalk_path,
        gate_id="uwm-data-foundation-evidence-gate-osm-admin-mobility-test",
        created_at="2026-07-06T23:55:00Z",
    )

    mobility = gate["evidence_slices"]["osm_admin_mobility_crosswalk"]
    assert mobility["osm_admin_mobility_crosswalk_ready"] is True
    assert mobility["assigned_road_segment_count"] == 45449
    assert mobility["service_accessibility_mobility_mae"] == 12.887057
    assert mobility["service_accessibility_best_static_mae"] == 14.028006
    assert mobility["service_accessibility_mae_reduction"] == 1.140949
    assert mobility["observed_policy_outcome_superiority_claim"] is False
    assert "osm_admin_mobility_crosswalk_service_accessibility_head_beats_static_baselines" in {
        claim["claim"] for claim in gate["supported_claims"]
    }

    readiness = build_world_model_evidence_readiness(gate)
    renderer = readiness["architecture_evidence"]["renderer"]
    assert renderer["osm_admin_mobility_crosswalk_ready"] is True
    assert renderer["osm_service_accessibility_mae_reduction"] == 1.140949

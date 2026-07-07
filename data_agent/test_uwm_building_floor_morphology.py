import csv
from pathlib import Path

from data_agent.uwm.building_floor_morphology import (
    UWM_BUILDING_FLOOR_MORPHOLOGY_SCHEMA,
    build_uwm_building_floor_morphology,
)


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data/uwm_public_proxy/chongqing_central"
BUILDING_SHP_PATH = (
    ROOT
    / ".tmp/twm_standard_1128/自然资源一张图数据库标准1128/规划院提供数据样例及Demo系统功能演示建议/01数据样例/04重庆市中心城区建筑物轮廓数据2021年/中心城区建筑数据带层高.shp"
)


def _read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _build_morphology() -> dict:
    import json

    return build_uwm_building_floor_morphology(
        morphology_id="uwm-building-floor-morphology-real-data-test",
        created_at="2026-07-07T12:00:00Z",
        building_shp_path=BUILDING_SHP_PATH,
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
        admin_spatial_graph=json.loads(
            (
                DATA_ROOT
                / "admin_spatial_graph_2026_07_05/uwm_admin_spatial_adjacency_graph.json"
            ).read_text(encoding="utf-8")
        ),
    )


def test_building_floor_morphology_projects_real_25d_buildings_to_admin_units():
    morphology = _build_morphology()

    assert morphology["schema"] == UWM_BUILDING_FLOOR_MORPHOLOGY_SCHEMA
    assert morphology["source_building_record_count"] == 107452
    assert morphology["assigned_building_count"] == 44887
    assert morphology["unassigned_building_count"] == 62565
    assert morphology["admin_unit_count"] == 36
    assert morphology["source_coverage"]["matched_admin_units"] == 36
    assert morphology["total_floor_count"] == 322665
    assert morphology["max_floor"] == 66

    first = morphology["admin_morphology_rows"][0]
    assert first["admin_unit_id"]
    assert "building_count" in first
    assert "floor_count_sum" in first
    assert "max_floor" in first
    assert first["assignment_rule"] == (
        "building_bbox_center_inside_admin_bbox_choose_smallest_bbox_area"
    )


def test_building_floor_morphology_beats_2d_baselines_on_service_endpoints():
    morphology = _build_morphology()
    evaluations = {
        item["endpoint_id"]: item
        for item in morphology["holdout_evaluation"]["morphology_endpoint_leave_one_admin_out"]
    }

    service = evaluations["service_point_accessibility"]
    assert service["target"] == "service_point_count"
    assert service["morphology_model"] == "building_max_floor_standardized_ridge"
    assert service["morphology_mae"] == 13.647302
    assert service["best_2d_baseline_mae"] == 14.028006
    assert service["mae_reduction_vs_best_2d_baseline"] == 0.380704
    assert service["beats_2d_baselines"] is True

    essential = evaluations["essential_service_accessibility"]
    assert essential["target"] == "essential_service_count"
    assert essential["morphology_mae"] == 2.855141
    assert essential["best_2d_baseline_mae"] == 3.204762
    assert essential["mae_reduction_vs_best_2d_baseline"] == 0.349621
    assert essential["beats_2d_baselines"] is True

    assert morphology["supported_claim"] == (
        "building_floor_25d_morphology_service_endpoint_head_beats_2d_baselines"
    )
    assert morphology["true_3d_claim"] is False

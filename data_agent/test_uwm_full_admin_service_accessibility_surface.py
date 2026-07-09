import json
from pathlib import Path

import geopandas as gpd
from shapely.geometry import LineString, Point, Polygon

from data_agent.uwm.full_admin_service_accessibility_surface import (
    UWM_FULL_ADMIN_SERVICE_ACCESSIBILITY_SURFACE_SCHEMA,
    build_full_admin_service_accessibility_surface,
    validate_full_admin_service_accessibility_surface,
)


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data/uwm_public_proxy/chongqing_central"
SURFACE_PATH = (
    DATA_ROOT
    / "full_admin_service_accessibility_surface_2026_07_08/uwm_full_admin_service_accessibility_surface.json"
)


def _admin_units() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        [
            {
                "admin_unit_id": "A|one|0",
                "county": "A",
                "township": "one",
                "geometry": Polygon(
                    [
                        (106.50, 29.50),
                        (106.55, 29.50),
                        (106.55, 29.55),
                        (106.50, 29.55),
                    ]
                ),
            },
            {
                "admin_unit_id": "B|two|1",
                "county": "B",
                "township": "two",
                "geometry": Polygon(
                    [
                        (106.55, 29.50),
                        (106.60, 29.50),
                        (106.60, 29.55),
                        (106.55, 29.55),
                    ]
                ),
            },
        ],
        crs="EPSG:4326",
    )


def _poi_points() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        [
            {"ID": 1, "名称": "A医院", "类型": "医疗保健服务;综合医院;综合医院", "geometry": Point(106.52, 29.52)},
            {"ID": 2, "名称": "A学校", "类型": "科教文化服务;学校;小学", "geometry": Point(106.53, 29.53)},
            {"ID": 3, "名称": "B餐厅", "类型": "餐饮服务;中餐厅;中餐厅", "geometry": Point(106.57, 29.52)},
        ],
        crs="EPSG:4326",
    )


def _roads() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        [
            {
                "osm_id": "r1",
                "fclass": "primary",
                "maxspeed": 60,
                "geometry": LineString([(106.50, 29.51), (106.55, 29.51)]),
            },
            {
                "osm_id": "r2",
                "fclass": "residential",
                "maxspeed": 30,
                "geometry": LineString([(106.56, 29.51), (106.59, 29.51)]),
            },
        ],
        crs="EPSG:4326",
    )


def test_full_admin_service_surface_builds_complete_rows_from_real_geometries():
    surface = build_full_admin_service_accessibility_surface(
        admin_units=_admin_units(),
        poi_points=_poi_points(),
        roads=_roads(),
        surface_id="full-admin-service-surface-unit-test",
        created_at="2026-07-08T15:00:00Z",
        source_refs={
            "admin_units": "unit-admin.geojson",
            "poi_points": "unit-poi.gdb",
            "roads": "unit-roads.shp",
        },
    )

    validation = validate_full_admin_service_accessibility_surface(surface)
    assert validation["valid"], validation["errors"]
    assert surface["schema"] == UWM_FULL_ADMIN_SERVICE_ACCESSIBILITY_SURFACE_SCHEMA
    assert surface["admin_unit_count"] == 2
    assert surface["source_feature_counts"] == {
        "admin_units": 2,
        "poi_points": 3,
        "roads": 2,
    }
    assert surface["coverage"]["service_missing_admin_count"] == 0
    assert surface["coverage"]["admin_units_with_accessibility_score"] == 2

    rows = {row["admin_unit_id"]: row for row in surface["admin_service_rows"]}
    assert rows["A|one|0"]["service_point_count"] == 2
    assert rows["A|one|0"]["essential_service_count"] == 2
    assert rows["A|one|0"]["healthcare_count"] == 1
    assert rows["A|one|0"]["education_count"] == 1
    assert rows["A|one|0"]["estimated_nearest_essential_travel_time_min"] > 0
    assert rows["A|one|0"]["service_accessibility_score"] > rows["B|two|1"]["service_accessibility_score"]
    assert rows["B|two|1"]["service_point_count"] == 1
    assert rows["B|two|1"]["essential_service_count"] == 0
    assert rows["B|two|1"]["service_coverage_status"] == "covered_by_full_local_surface"
    assert rows["B|two|1"]["sample_gap_flag"] == ""
    assert rows["B|two|1"]["interpretable_as_true_service_absence"] is False
    assert surface["observed_policy_outcome_superiority_claim"] is False


def test_full_admin_service_surface_artifact_uses_full_local_assets():
    assert SURFACE_PATH.exists()

    surface = json.loads(SURFACE_PATH.read_text(encoding="utf-8"))
    validation = validate_full_admin_service_accessibility_surface(surface)
    assert validation["valid"], validation["errors"]

    assert surface["schema"] == UWM_FULL_ADMIN_SERVICE_ACCESSIBILITY_SURFACE_SCHEMA
    assert surface["experiment_scope"] == "full_admin_graph"
    assert surface["admin_unit_count"] == 1017
    assert surface["source_feature_counts"]["admin_units"] == 1017
    assert surface["source_feature_counts"]["poi_points"] == 1194351
    assert surface["source_feature_counts"]["roads"] == 50366
    assert surface["coverage"]["service_missing_admin_count"] == 0
    assert surface["coverage"]["admin_units_with_accessibility_score"] == 1017
    assert surface["coverage"]["admin_units_with_road_context"] > 900
    assert surface["total_service_point_count"] > 1000000
    assert surface["total_essential_service_count"] > 10000
    assert surface["supported_claim"] == (
        "full_admin_service_accessibility_surface_covers_all_admin_units_from_local_poi_and_road_assets"
    )
    assert surface["observed_policy_outcome_superiority_claim"] is False
    assert surface["empirical_superiority_claim"] is False

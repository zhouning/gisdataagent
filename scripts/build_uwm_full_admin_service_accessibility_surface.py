"""Build full-admin service accessibility surface from local POI and road assets."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import pyogrio

from data_agent.uwm.full_admin_service_accessibility_surface import (
    build_full_admin_service_accessibility_surface,
    validate_full_admin_service_accessibility_surface,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = REPO_ROOT / "data/uwm_public_proxy/chongqing_central"
LOCAL_SAMPLE_ROOT = (
    REPO_ROOT
    / ".tmp/twm_standard_1128/自然资源一张图数据库标准1128/规划院提供数据样例及Demo系统功能演示建议/01数据样例"
)
ADMIN_UNITS_PATH = DATA_ROOT / "admin_units/chongqing_township_admin_units.geojson"
GAODE_POI_PATH = LOCAL_SAMPLE_ROOT / "09高德地图POI数据/高德地图POI数据2024年.gdb"
GAODE_POI_LAYER = "高德地图POI数据2024年"
OSM_ROADS_PATH = LOCAL_SAMPLE_ROOT / "02重庆市OSM道路数据2021年/OSM_roads.shp"
OUTPUT_DIR = DATA_ROOT / "full_admin_service_accessibility_surface_2026_07_08"
OUTPUT_JSON = OUTPUT_DIR / "uwm_full_admin_service_accessibility_surface.json"
OUTPUT_CSV = OUTPUT_DIR / "uwm_full_admin_service_accessibility_surface.csv"
MANIFEST_PATH = OUTPUT_DIR / "snapshot_manifest.json"


def main() -> None:
    admin_info = pyogrio.read_info(ADMIN_UNITS_PATH)
    poi_info = pyogrio.read_info(GAODE_POI_PATH, layer=GAODE_POI_LAYER)
    road_info = pyogrio.read_info(OSM_ROADS_PATH)

    admin_units = pyogrio.read_dataframe(ADMIN_UNITS_PATH)
    poi_points = pyogrio.read_dataframe(
        GAODE_POI_PATH,
        layer=GAODE_POI_LAYER,
        columns=["类型"],
    )
    roads = pyogrio.read_dataframe(
        OSM_ROADS_PATH,
        columns=["fclass", "maxspeed"],
    )

    surface = build_full_admin_service_accessibility_surface(
        admin_units=admin_units,
        poi_points=poi_points,
        roads=roads,
        surface_id="uwm-full-admin-service-accessibility-surface-2026-07-08",
        created_at="2026-07-08T15:30:00Z",
        source_refs={
            "admin_units": str(ADMIN_UNITS_PATH.relative_to(REPO_ROOT)),
            "poi_points": str(GAODE_POI_PATH.relative_to(REPO_ROOT)),
            "poi_layer": GAODE_POI_LAYER,
            "roads": str(OSM_ROADS_PATH.relative_to(REPO_ROOT)),
        },
        source_feature_counts={
            "admin_units": int(admin_info["features"]),
            "poi_points": int(poi_info["features"]),
            "roads": int(road_info["features"]),
        },
    )
    validation = validate_full_admin_service_accessibility_surface(surface)
    if not validation["valid"]:
        raise SystemExit(
            f"invalid full-admin service accessibility surface: {validation['errors']}"
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _write_json(OUTPUT_JSON, surface)
    _write_csv(OUTPUT_CSV, surface["admin_service_rows"])
    _write_json(
        MANIFEST_PATH,
        {
            "snapshot_id": "uwm_full_admin_service_accessibility_surface_2026_07_08",
            "schema": "uwm.snapshot_manifest.v1",
            "created_at": surface["created_at"],
            "output_path": str(OUTPUT_JSON.relative_to(REPO_ROOT)),
            "csv_path": str(OUTPUT_CSV.relative_to(REPO_ROOT)),
            "experiment_scope": surface["experiment_scope"],
            "source_refs": surface["source_refs"],
            "source_feature_counts": surface["source_feature_counts"],
            "admin_unit_count": surface["admin_unit_count"],
            "coverage": surface["coverage"],
            "supported_claim": surface["supported_claim"],
            "claim_boundary": surface["claim_boundary"],
            "limitations": surface["limitations"],
            "observed_policy_outcome_superiority_claim": surface[
                "observed_policy_outcome_superiority_claim"
            ],
            "empirical_superiority_claim": surface["empirical_superiority_claim"],
        },
    )
    print(
        json.dumps(
            {
                "path": str(OUTPUT_JSON.relative_to(REPO_ROOT)),
                "admin_unit_count": surface["admin_unit_count"],
                "source_feature_counts": surface["source_feature_counts"],
                "service_missing_admin_count": surface["coverage"][
                    "service_missing_admin_count"
                ],
                "admin_units_with_service_points": surface["coverage"][
                    "admin_units_with_service_points"
                ],
                "admin_units_with_road_context": surface["coverage"][
                    "admin_units_with_road_context"
                ],
                "total_service_point_count": surface["total_service_point_count"],
                "total_essential_service_count": surface[
                    "total_essential_service_count"
                ],
                "supported_claim": surface["supported_claim"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "admin_unit_id",
        "county",
        "township",
        "service_point_count",
        "essential_service_count",
        "healthcare_count",
        "education_count",
        "food_retail_count",
        "finance_count",
        "mobility_transport_count",
        "civic_public_count",
        "recreation_count",
        "lodging_count",
        "other_service_count",
        "nearest_essential_service_distance_m",
        "estimated_nearest_essential_travel_time_min",
        "road_segment_count",
        "road_length_km",
        "mean_road_speed_kmh",
        "service_capacity_proxy",
        "service_accessibility_score",
        "service_gap_score",
        "service_coverage_status",
        "sample_gap_flag",
        "service_void_flag",
        "interpretable_as_true_service_absence",
        "capacity_norm",
        "essential_norm",
        "travel_time_inverse_norm",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            components = row.get("score_components") or {}
            writer.writerow(
                {
                    **{
                        key: row.get(key)
                        for key in fieldnames
                        if key not in {
                            "capacity_norm",
                            "essential_norm",
                            "travel_time_inverse_norm",
                        }
                    },
                    "capacity_norm": components.get("capacity_norm"),
                    "essential_norm": components.get("essential_norm"),
                    "travel_time_inverse_norm": components.get(
                        "travel_time_inverse_norm"
                    ),
                }
            )


if __name__ == "__main__":
    main()

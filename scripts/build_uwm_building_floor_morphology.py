"""Build UWM 2.5D building-floor morphology artifact."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from data_agent.uwm.building_floor_morphology import (
    build_uwm_building_floor_morphology,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = REPO_ROOT / "data/uwm_public_proxy/chongqing_central"
OUTPUT_DIR = DATA_ROOT / "building_floor_morphology_2026_07_07"
OUTPUT_PATH = OUTPUT_DIR / "uwm_building_floor_morphology.json"
MANIFEST_PATH = OUTPUT_DIR / "snapshot_manifest.json"
BUILDING_SHP_PATH = (
    REPO_ROOT
    / ".tmp/twm_standard_1128/自然资源一张图数据库标准1128/规划院提供数据样例及Demo系统功能演示建议/01数据样例/04重庆市中心城区建筑物轮廓数据2021年/中心城区建筑数据带层高.shp"
)
ADMIN_LIVABILITY_PATH = (
    DATA_ROOT
    / "admin_livability_target_complete_bbox_2024_07_2026_07_05/uwm_admin_livability_target_complete_bbox_panel.csv"
)
SERVICE_ACCESSIBILITY_PATH = (
    DATA_ROOT
    / "admin_service_accessibility_complete_bbox_2026_07_05/uwm_admin_service_accessibility_complete_bbox_panel.csv"
)
GHSL_ADMIN_PATH = DATA_ROOT / "ghsl_admin_alignment/ghsl_admin_zonal_proxy.csv"
ADMIN_SPATIAL_GRAPH_PATH = (
    DATA_ROOT / "admin_spatial_graph_2026_07_05/uwm_admin_spatial_adjacency_graph.json"
)


def main() -> None:
    morphology = build_uwm_building_floor_morphology(
        morphology_id="uwm-building-floor-morphology-2026-07-07",
        created_at="2026-07-07T12:20:00Z",
        building_shp_path=BUILDING_SHP_PATH,
        admin_livability_rows=_read_csv(ADMIN_LIVABILITY_PATH),
        service_accessibility_rows=_read_csv(SERVICE_ACCESSIBILITY_PATH),
        ghsl_admin_rows=_read_csv(GHSL_ADMIN_PATH),
        admin_spatial_graph=_read_json(ADMIN_SPATIAL_GRAPH_PATH),
    )
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _write_json(OUTPUT_PATH, morphology)
    manifest = {
        "snapshot_id": "uwm_building_floor_morphology_2026_07_07",
        "created_at": "2026-07-07T12:20:00Z",
        "morphology_path": str(OUTPUT_PATH.relative_to(REPO_ROOT)),
        "source_building_shp_path": str(BUILDING_SHP_PATH),
        "source_building_record_count": morphology["source_building_record_count"],
        "assigned_building_count": morphology["assigned_building_count"],
        "admin_unit_count": morphology["admin_unit_count"],
        "total_floor_count": morphology["total_floor_count"],
        "max_floor": morphology["max_floor"],
        "supported_claim": morphology["supported_claim"],
        "true_3d_claim": False,
    }
    _write_json(MANIFEST_PATH, manifest)
    print(
        json.dumps(
            {
                "morphology_path": str(OUTPUT_PATH.relative_to(REPO_ROOT)),
                "source_building_record_count": morphology[
                    "source_building_record_count"
                ],
                "assigned_building_count": morphology["assigned_building_count"],
                "admin_unit_count": morphology["admin_unit_count"],
                "total_floor_count": morphology["total_floor_count"],
                "max_floor": morphology["max_floor"],
                "supported_claim": morphology["supported_claim"],
                "true_3d_claim": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


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

"""Build UWM OSM road-to-admin mobility crosswalk from local artifacts."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from data_agent.uwm.osm_admin_mobility_crosswalk import (
    build_uwm_osm_admin_mobility_crosswalk,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = REPO_ROOT / "data/uwm_public_proxy/chongqing_central"
OUTPUT_DIR = DATA_ROOT / "osm_admin_mobility_crosswalk_2026_07_06"
OUTPUT_PATH = OUTPUT_DIR / "uwm_osm_admin_mobility_crosswalk.json"
MANIFEST_PATH = OUTPUT_DIR / "snapshot_manifest.json"

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
    DATA_ROOT
    / "admin_spatial_graph_2026_07_05/uwm_admin_spatial_adjacency_graph.json"
)
OSM_MOBILITY_NETWORK_PATH = (
    DATA_ROOT / "osm_complete_bbox_2026_07_05/mobility/osm_mobility_network_proxy.json"
)
OSM_OVERPASS_RAW_PATH = (
    DATA_ROOT
    / "osm_complete_bbox_2026_07_05/mobility/osm_mobility_network_overpass_raw.json"
)


def main() -> None:
    crosswalk = build_uwm_osm_admin_mobility_crosswalk(
        crosswalk_id="uwm-osm-admin-mobility-crosswalk-2026-07-06",
        created_at="2026-07-06T23:58:00Z",
        admin_livability_rows=_read_csv(ADMIN_LIVABILITY_PATH),
        service_accessibility_rows=_read_csv(SERVICE_ACCESSIBILITY_PATH),
        ghsl_admin_rows=_read_csv(GHSL_ADMIN_PATH),
        admin_spatial_graph=_read_json(ADMIN_SPATIAL_GRAPH_PATH),
        osm_mobility_network=_read_json(OSM_MOBILITY_NETWORK_PATH),
        osm_overpass_raw=_read_json(OSM_OVERPASS_RAW_PATH),
    )
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _write_json(OUTPUT_PATH, crosswalk)
    evaluation = crosswalk["holdout_evaluation"][
        "service_accessibility_leave_one_admin_out"
    ]
    manifest = {
        "snapshot_id": "uwm_osm_admin_mobility_crosswalk_2026_07_06",
        "created_at": "2026-07-06T23:58:00Z",
        "crosswalk_path": str(OUTPUT_PATH.relative_to(REPO_ROOT)),
        "admin_unit_count": crosswalk["admin_unit_count"],
        "assigned_road_segment_count": crosswalk["assigned_road_segment_count"],
        "mobility_crosswalk_mae": evaluation["mobility_crosswalk_mae"],
        "best_traditional_static_mae": evaluation["best_traditional_static_mae"],
        "mae_reduction_vs_best_traditional_static": evaluation[
            "mae_reduction_vs_best_traditional_static"
        ],
        "supported_claim": crosswalk["supported_claim"],
        "observed_policy_outcome_superiority_claim": False,
    }
    _write_json(MANIFEST_PATH, manifest)
    print(
        json.dumps(
            {
                "crosswalk_path": str(OUTPUT_PATH.relative_to(REPO_ROOT)),
                "admin_unit_count": crosswalk["admin_unit_count"],
                "assigned_road_segment_count": crosswalk[
                    "assigned_road_segment_count"
                ],
                "mobility_crosswalk_mae": evaluation["mobility_crosswalk_mae"],
                "best_traditional_static_mae": evaluation[
                    "best_traditional_static_mae"
                ],
                "mae_reduction_vs_best_traditional_static": evaluation[
                    "mae_reduction_vs_best_traditional_static"
                ],
                "supported_claim": crosswalk["supported_claim"],
                "observed_policy_outcome_superiority_claim": False,
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

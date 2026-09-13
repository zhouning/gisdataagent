"""Build UWM multisource livability scene from prepared local artifacts."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from data_agent.uwm.multisource_livability_scene import (
    build_uwm_multisource_livability_scene,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = REPO_ROOT / "data/uwm_public_proxy/chongqing_central"
OUTPUT_DIR = DATA_ROOT / "multisource_livability_scene_2026_07_06"
OUTPUT_PATH = OUTPUT_DIR / "uwm_multisource_livability_scene.json"
MANIFEST_PATH = OUTPUT_DIR / "snapshot_manifest.json"

ADMIN_LIVABILITY_PATH = (
    DATA_ROOT
    / "admin_livability_target_complete_bbox_2024_07_2026_07_05/uwm_admin_livability_target_complete_bbox_panel.csv"
)
ADMIN_EXPOSURE_EQUITY_PATH = (
    DATA_ROOT
    / "admin_exposure_equity_2024_07_01_07/uwm_admin_exposure_equity_panel.csv"
)
SERVICE_ACCESSIBILITY_PATH = (
    DATA_ROOT
    / "admin_service_accessibility_complete_bbox_2026_07_05/uwm_admin_service_accessibility_complete_bbox_panel.csv"
)
GHSL_ADMIN_PATH = DATA_ROOT / "ghsl_admin_alignment/ghsl_admin_zonal_proxy.csv"
GEE_ADMIN_ENVIRONMENT_PATH = (
    DATA_ROOT
    / "gee_admin_environment_2024_07_01_07/gee_admin_environment_proxy.json"
)
SCENE_ALIGNED_GRIDDED_AIR_QUALITY_PATH = (
    DATA_ROOT
    / "scene_aligned_gridded_air_quality_holdout_2026_07_06/uwm_scene_aligned_gridded_air_quality_holdout.json"
)
ADMIN_SPATIAL_GRAPH_PATH = (
    DATA_ROOT
    / "admin_spatial_graph_2026_07_05/uwm_admin_spatial_adjacency_graph.json"
)
UNICOM_LATENT_MOBILITY_PATH = (
    DATA_ROOT / "fitted_gap_filling_2026_07_05/unicom_latent_mobility_graph.json"
)
OSM_MOBILITY_NETWORK_PATH = (
    DATA_ROOT / "osm_complete_bbox_2026_07_05/mobility/osm_mobility_network_proxy.json"
)
OSM_ADMIN_MOBILITY_CROSSWALK_PATH = (
    DATA_ROOT
    / "osm_admin_mobility_crosswalk_2026_07_06/uwm_osm_admin_mobility_crosswalk.json"
)


def main() -> None:
    scene = build_uwm_multisource_livability_scene(
        scene_id="uwm-multisource-livability-scene-2026-07-06",
        created_at="2026-07-06T23:30:00Z",
        admin_livability_rows=_read_csv(ADMIN_LIVABILITY_PATH),
        admin_exposure_equity_rows=_read_csv(ADMIN_EXPOSURE_EQUITY_PATH),
        service_accessibility_rows=_read_csv(SERVICE_ACCESSIBILITY_PATH),
        ghsl_admin_rows=_read_csv(GHSL_ADMIN_PATH),
        gee_admin_environment=_read_json(GEE_ADMIN_ENVIRONMENT_PATH),
        scene_aligned_gridded_air_quality_holdout=_read_json(
            SCENE_ALIGNED_GRIDDED_AIR_QUALITY_PATH
        ),
        admin_spatial_graph=_read_json(ADMIN_SPATIAL_GRAPH_PATH),
        unicom_latent_mobility_graph=_read_json(UNICOM_LATENT_MOBILITY_PATH),
        osm_mobility_network=_read_json(OSM_MOBILITY_NETWORK_PATH),
        osm_admin_mobility_crosswalk=_read_json(OSM_ADMIN_MOBILITY_CROSSWALK_PATH),
    )
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _write_json(OUTPUT_PATH, scene)
    evaluation = scene["holdout_evaluation"][
        "air_quality_multisource_leave_one_admin_out"
    ]
    manifest = {
        "snapshot_id": "uwm_multisource_livability_scene_2026_07_06",
        "created_at": "2026-07-06T23:30:00Z",
        "scene_path": str(OUTPUT_PATH.relative_to(REPO_ROOT)),
        "admin_unit_count": scene["admin_unit_count"],
        "data_sources_used": scene["data_sources_used"],
        "osm_admin_mobility_crosswalk_projected": scene["source_coverage"][
            "osm_admin_mobility_crosswalk"
        ]["unit_projection"]
        == "admin_unit_state_vector",
        "osm_assigned_road_segment_count_in_scene": scene["source_coverage"][
            "osm_admin_mobility_crosswalk"
        ]["assigned_road_segment_count"],
        "multisource_air_quality_mae": evaluation["multisource_mae"],
        "best_single_source_mae": evaluation["best_single_source_mae"],
        "mae_reduction_vs_best_single_source": evaluation[
            "mae_reduction_vs_best_single_source"
        ],
        "supported_claim": scene["supported_claim"],
        "observed_policy_outcome_superiority_claim": False,
    }
    _write_json(MANIFEST_PATH, manifest)
    print(
        json.dumps(
            {
                "scene_path": str(OUTPUT_PATH.relative_to(REPO_ROOT)),
                "admin_unit_count": scene["admin_unit_count"],
                "data_source_count": len(scene["data_sources_used"]),
                "osm_admin_mobility_crosswalk_projected": scene["source_coverage"][
                    "osm_admin_mobility_crosswalk"
                ]["unit_projection"]
                == "admin_unit_state_vector",
                "osm_assigned_road_segment_count_in_scene": scene["source_coverage"][
                    "osm_admin_mobility_crosswalk"
                ]["assigned_road_segment_count"],
                "multisource_air_quality_mae": evaluation["multisource_mae"],
                "best_single_source_mae": evaluation["best_single_source_mae"],
                "mae_reduction_vs_best_single_source": evaluation[
                    "mae_reduction_vs_best_single_source"
                ],
                "supported_claim": scene["supported_claim"],
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

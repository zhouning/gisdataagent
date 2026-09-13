"""Build the full-admin UWM mobility graph artifact."""

from __future__ import annotations

import json
from pathlib import Path

from data_agent.uwm.full_admin_mobility_graph import (
    validate_full_admin_mobility_graph,
    write_full_admin_mobility_graph_snapshot,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = REPO_ROOT / "data/uwm_public_proxy/chongqing_central"
OUTPUT_DIR = DATA_ROOT / "full_admin_mobility_graph_2026_07_10"

FULL_ADMIN_SERVICE_ACCESSIBILITY_SURFACE_PATH = (
    DATA_ROOT
    / "full_admin_service_accessibility_surface_2026_07_08/uwm_full_admin_service_accessibility_surface.json"
)
GEOGRAPHIC_SIMILARITY_KERNEL_PATH = (
    DATA_ROOT
    / "geographic_similarity_kernel_2026_07_08/uwm_geographic_similarity_kernel.json"
)
UNICOM_LATENT_MOBILITY_GRAPH_PATH = (
    DATA_ROOT / "fitted_gap_filling_2026_07_05/unicom_latent_mobility_graph.json"
)
OSM_MOBILITY_NETWORK_PATH = (
    DATA_ROOT
    / "osm_complete_bbox_2026_07_05/mobility/osm_mobility_network_proxy.json"
)
OSM_ADMIN_MOBILITY_CROSSWALK_PATH = (
    DATA_ROOT
    / "osm_admin_mobility_crosswalk_2026_07_06/uwm_osm_admin_mobility_crosswalk.json"
)


def main() -> None:
    manifest = write_full_admin_mobility_graph_snapshot(
        output_dir=OUTPUT_DIR,
        graph_id="uwm-full-admin-mobility-graph-2026-07-10",
        created_at="2026-07-10T09:30:00Z",
        full_admin_service_accessibility_surface=_read_json(
            FULL_ADMIN_SERVICE_ACCESSIBILITY_SURFACE_PATH
        ),
        geographic_similarity_kernel=_read_json(GEOGRAPHIC_SIMILARITY_KERNEL_PATH),
        unicom_latent_mobility_graph=_read_json(UNICOM_LATENT_MOBILITY_GRAPH_PATH),
        osm_mobility_network=_read_json(OSM_MOBILITY_NETWORK_PATH),
        osm_admin_mobility_crosswalk=_read_json(OSM_ADMIN_MOBILITY_CROSSWALK_PATH),
    )
    graph_path = OUTPUT_DIR / manifest["files"]["graph"]
    graph = _read_json(graph_path)
    validation = validate_full_admin_mobility_graph(graph)
    if validation["valid"] is not True:
        raise SystemExit(f"invalid full-admin mobility graph: {validation['errors']}")

    manifest["source_artifact_paths"] = {
        "full_admin_service_accessibility_surface": str(
            FULL_ADMIN_SERVICE_ACCESSIBILITY_SURFACE_PATH.relative_to(REPO_ROOT)
        ),
        "geographic_similarity_kernel": str(
            GEOGRAPHIC_SIMILARITY_KERNEL_PATH.relative_to(REPO_ROOT)
        ),
        "unicom_latent_mobility_graph": str(
            UNICOM_LATENT_MOBILITY_GRAPH_PATH.relative_to(REPO_ROOT)
        ),
        "osm_mobility_network": str(OSM_MOBILITY_NETWORK_PATH.relative_to(REPO_ROOT)),
        "osm_admin_mobility_crosswalk": str(
            OSM_ADMIN_MOBILITY_CROSSWALK_PATH.relative_to(REPO_ROOT)
        ),
    }
    _write_json(OUTPUT_DIR / "snapshot_manifest.json", manifest)
    print(
        json.dumps(
            {
                "graph_path": str(graph_path.relative_to(REPO_ROOT)),
                "full_admin_mobility_graph_ready": graph[
                    "full_admin_mobility_graph_ready"
                ],
                "node_count": graph["node_count"],
                "edge_count": graph["edge_count"],
                "travel_time_min_mean": graph["summary"]["travel_time_min_mean"],
                "unicom_directed_edge_count": graph["summary"][
                    "mobility_activity_context"
                ]["unicom_directed_edge_count"],
                "osm_highway_edge_count": graph["summary"][
                    "mobility_activity_context"
                ]["osm_highway_edge_count"],
                "supported_claim": graph["supported_claim"],
                "observed_policy_outcome_superiority_claim": False,
                "empirical_superiority_claim": False,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()

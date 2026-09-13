import json
from pathlib import Path

from data_agent.uwm.full_admin_mobility_graph import (
    UWM_FULL_ADMIN_MOBILITY_GRAPH_SCHEMA,
    build_full_admin_mobility_graph,
    validate_full_admin_mobility_graph,
)


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data/uwm_public_proxy/chongqing_central"
SURFACE_PATH = (
    DATA_ROOT
    / "full_admin_service_accessibility_surface_2026_07_08/uwm_full_admin_service_accessibility_surface.json"
)
KERNEL_PATH = (
    DATA_ROOT
    / "geographic_similarity_kernel_2026_07_08/uwm_geographic_similarity_kernel.json"
)
UNICOM_PATH = (
    DATA_ROOT / "fitted_gap_filling_2026_07_05/unicom_latent_mobility_graph.json"
)
OSM_NETWORK_PATH = (
    DATA_ROOT
    / "osm_complete_bbox_2026_07_05/mobility/osm_mobility_network_proxy.json"
)
OSM_CROSSWALK_PATH = (
    DATA_ROOT
    / "osm_admin_mobility_crosswalk_2026_07_06/uwm_osm_admin_mobility_crosswalk.json"
)
ARTIFACT_PATH = (
    DATA_ROOT
    / "full_admin_mobility_graph_2026_07_10/full_admin_mobility_graph.json"
)


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _build_graph() -> dict:
    return build_full_admin_mobility_graph(
        graph_id="uwm-full-admin-mobility-graph-test",
        created_at="2026-07-10T09:30:00Z",
        full_admin_service_accessibility_surface=_read_json(SURFACE_PATH),
        geographic_similarity_kernel=_read_json(KERNEL_PATH),
        unicom_latent_mobility_graph=_read_json(UNICOM_PATH),
        osm_mobility_network=_read_json(OSM_NETWORK_PATH),
        osm_admin_mobility_crosswalk=_read_json(OSM_CROSSWALK_PATH),
    )


def _assert_full_admin_mobility_graph(graph: dict) -> None:
    assert graph["schema"] == UWM_FULL_ADMIN_MOBILITY_GRAPH_SCHEMA
    assert graph["experiment_scope"] == "full_admin_graph"
    assert graph["full_admin_mobility_graph_ready"] is True
    assert graph["supported_claim"] == (
        "full_admin_mobility_graph_travel_time_similarity_projection_ready"
    )
    assert graph["claim_boundary"]["max_claim_level"] == "bounded_support"
    assert graph["node_count"] == 1017
    assert graph["edge_count"] == 5085

    summary = graph["summary"]
    assert summary["node_count"] == 1017
    assert summary["edge_count"] == 5085
    assert summary["mobility_similarity_edge_count"] == 5085
    assert summary["travel_time_min_mean"] > 0.0
    assert summary["travel_time_min_max"] > summary["travel_time_min_mean"]
    assert summary["road_segment_count_sum"] > 50000
    assert summary["road_length_km_sum"] > 50000.0

    context = summary["mobility_activity_context"]
    assert context["unicom_directed_edge_count"] == 1067
    assert context["unicom_total_expanded_population"] == 29634.796667
    assert context["osm_highway_edge_count"] == 45468
    assert context["osm_crosswalk_assigned_road_segment_count"] == 45449

    first_node = graph["mobility_nodes"][0]
    for field in [
        "estimated_nearest_essential_travel_time_min",
        "road_segment_count",
        "road_length_km",
        "mean_road_speed_kmh",
        "travel_time_inverse_norm",
    ]:
        assert field in first_node

    first_edge = graph["mobility_edges"][0]
    assert first_edge["edge_type"] == "mobility_accessibility_similarity"
    assert "travel_time_difference_min" in first_edge
    assert "road_segment_difference" in first_edge
    assert "road_length_difference_km" in first_edge
    assert "road_speed_difference_kmh" in first_edge

    assert graph["negative_controls"]["rotated_target_similarity_control_passed"] is True
    assert graph["observed_policy_outcome_superiority_claim"] is False
    assert graph["empirical_superiority_claim"] is False
    assert "mobility_graph_is_similarity_projection_not_true_od_geometry" in graph[
        "limitations"
    ]
    assert validate_full_admin_mobility_graph(graph) == {"valid": True, "errors": []}


def test_full_admin_mobility_graph_builds_from_real_full_data_sources():
    _assert_full_admin_mobility_graph(_build_graph())


def test_full_admin_mobility_graph_artifact_is_full_scope_and_claim_safe():
    assert ARTIFACT_PATH.exists()
    _assert_full_admin_mobility_graph(_read_json(ARTIFACT_PATH))

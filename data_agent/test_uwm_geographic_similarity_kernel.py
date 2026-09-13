from pathlib import Path

from data_agent.uwm.geographic_similarity_kernel import (
    build_uwm_geographic_similarity_kernel,
    validate_uwm_geographic_similarity_kernel,
)


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data/uwm_public_proxy/chongqing_central"
FULL_ADMIN_PANEL_PATH = (
    DATA_ROOT
    / "admin_livability_target_full_admin_graph_2024_07_2026_07_08/uwm_admin_livability_target_full_admin_graph_panel.json"
)
ADMIN_GRAPH_PATH = (
    DATA_ROOT
    / "admin_spatial_graph_2026_07_05/uwm_admin_spatial_adjacency_graph.json"
)
GEOGRAPHIC_SIMILARITY_KERNEL_PATH = (
    DATA_ROOT
    / "geographic_similarity_kernel_2026_07_08/uwm_geographic_similarity_kernel.json"
)


def test_geographic_similarity_kernel_builds_full_admin_configuration_edges():
    kernel = build_uwm_geographic_similarity_kernel(
        admin_livability_panel=_read_json(FULL_ADMIN_PANEL_PATH),
        admin_spatial_graph=_read_json(ADMIN_GRAPH_PATH),
        kernel_id="uwm-geographic-similarity-kernel-test",
        created_at="2026-07-08T15:00:00Z",
        top_k=3,
    )

    assert validate_uwm_geographic_similarity_kernel(kernel) == {
        "valid": True,
        "errors": [],
    }
    assert kernel["schema"] == "uwm.geographic_similarity_kernel.v1"
    assert kernel["geographic_similarity_kernel_ready"] is True
    assert kernel["summary"]["panel_unit_count"] == 1017
    assert kernel["summary"]["graph_node_count"] == 1017
    assert kernel["summary"]["kernel_source_unit_count"] == 1017
    assert kernel["summary"]["similarity_edge_count"] == 3051
    assert kernel["summary"]["non_adjacent_similarity_edge_count"] > 0
    assert kernel["configuration_features"]["uses_full_admin_livability_panel"] is True
    assert kernel["configuration_features"]["uses_service_road_exposure_need_features"] is True
    assert kernel["negative_controls"]["rotated_target_similarity_control_passed"] is True
    assert kernel["supported_claim"] == "geographic_similarity_configuration_kernel_ready"
    assert kernel["observed_policy_outcome_superiority_claim"] is False


def test_geographic_similarity_kernel_artifact_uses_full_admin_panel():
    kernel = _read_json(GEOGRAPHIC_SIMILARITY_KERNEL_PATH)

    assert validate_uwm_geographic_similarity_kernel(kernel) == {
        "valid": True,
        "errors": [],
    }
    assert kernel["geographic_similarity_kernel_ready"] is True
    assert kernel["summary"]["panel_unit_count"] == 1017
    assert kernel["summary"]["kernel_source_unit_count"] == 1017
    assert kernel["summary"]["top_k"] == 5
    assert kernel["summary"]["similarity_edge_count"] == 5085
    assert kernel["summary"]["non_adjacent_similarity_edge_count"] > 0
    assert kernel["configuration_features"]["uses_coordinates_as_similarity_features"] is False
    assert kernel["negative_controls"]["rotated_target_similarity_control_passed"] is True
    assert kernel["observed_policy_outcome_superiority_claim"] is False


def test_geographic_similarity_kernel_distinguishes_similarity_from_boundary_adjacency():
    panel = {
        "schema": "uwm.admin_livability_target_panel.v1",
        "admin_livability_target_rows": [
            _panel_row("A|one|1", "A", need=0.9, exposure=0.8, service=0.2, roads=20),
            _panel_row("B|two|2", "B", need=0.88, exposure=0.79, service=0.22, roads=21),
            _panel_row("C|three|3", "C", need=0.2, exposure=0.1, service=0.9, roads=90),
        ],
        "claim_boundary": {"max_claim_level": "bounded_support"},
    }
    graph = {
        "schema": "uwm.admin_spatial_adjacency_graph.v1",
        "nodes": [
            {"unit_id": "A|one|1", "county": "A", "degree": 1},
            {"unit_id": "B|two|2", "county": "B", "degree": 0},
            {"unit_id": "C|three|3", "county": "C", "degree": 1},
        ],
        "edges": [
            {
                "edge_type": "admin_boundary_adjacency",
                "source": "A|one|1",
                "target": "C|three|3",
                "weight": 1.0,
                "shared_boundary_length_degrees": 0.2,
            }
        ],
        "summary": {"node_count": 3, "edge_count": 1},
    }

    kernel = build_uwm_geographic_similarity_kernel(
        admin_livability_panel=panel,
        admin_spatial_graph=graph,
        kernel_id="uwm-geographic-similarity-kernel-small-test",
        created_at="2026-07-08T15:05:00Z",
        top_k=1,
    )

    a_edges = kernel["neighbors"]["A|one|1"]
    assert a_edges[0]["target_unit_id"] == "B|two|2"
    assert a_edges[0]["edge_type"] == "geographic_configuration_similarity"
    assert a_edges[0]["boundary_adjacent"] is False
    assert a_edges[0]["configuration_similarity"] > 0.9


def _panel_row(
    unit_id: str,
    county: str,
    *,
    need: float,
    exposure: float,
    service: float,
    roads: float,
) -> dict:
    return {
        "admin_unit_id": unit_id,
        "county": county,
        "township": unit_id.split("|")[1],
        "exposure_priority_score": exposure,
        "service_point_count": service * 100.0,
        "essential_service_count": service * 10.0,
        "service_accessibility_score": service,
        "service_gap_score": 1.0 - service,
        "nearest_essential_service_distance_m": (1.0 - service) * 1000.0,
        "estimated_nearest_essential_travel_time_min": (1.0 - service) * 8.0,
        "road_segment_count": roads,
        "road_length_km": roads * 0.8,
        "mean_road_speed_kmh": 40.0 + roads * 0.1,
        "healthcare_count": service * 2.0,
        "education_count": service * 3.0,
        "food_retail_count": service * 20.0,
        "finance_count": service * 2.0,
        "mobility_transport_count": service * 4.0,
        "civic_public_count": service * 5.0,
        "recreation_count": service * 2.0,
        "lodging_count": service,
        "other_service_count": service * 20.0,
        "service_capacity_proxy": service * 110.0,
        "livability_need_score": need,
        "score_components": {
            "exposure_norm": exposure,
            "service_gap_norm": 1.0 - service,
            "essential_gap_norm": 1.0 - service,
        },
    }


def _read_json(path: Path) -> dict:
    import json

    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload if isinstance(payload, dict) else {}

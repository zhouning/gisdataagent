from copy import deepcopy

import pytest

from data_agent.uwm.environmental_kernel.state import build_environmental_state


def state_input():
    return {
        "scene_id": "chongqing-scene-1",
        "snapshot_time": "2026-07-11T00:00:00Z",
        "geography_version": "grid-v1",
        "evidence_bundle_id": "evidence-1",
        "source_dataset_ids": ["weather-b", "air-a"],
        "external_forcing": {"forcing_id": "forcing-1"},
        "spatial_nodes": [
            {
                "node_id": "grid-b",
                "node_type": "grid",
                "geometry_ref": "geom-b",
                "geometry_area_m2": 200.0,
                "pm25_ugm3": None,
                "pm25_support_level": "unavailable",
                "temperature_c": 30.0,
                "temperature_support_level": "observed_context",
                "vegetation_fraction": 0.25,
                "vegetation_fraction_support_level": "observed_context",
            },
            {
                "node_id": "grid-a",
                "node_type": "grid",
                "geometry_ref": "geom-a",
                "geometry_area_m2": 100.0,
                "pm25_ugm3": 18.0,
                "pm25_support_level": "observed_calibrated",
                "temperature_c": None,
                "temperature_support_level": "unavailable",
                "vegetation_fraction": 0.4,
                "vegetation_fraction_support_level": "observed_context",
            },
            {
                "node_id": "admin-1",
                "node_type": "admin",
                "geometry_ref": "admin-geom",
            },
        ],
        "spatial_edges": [
            {
                "edge_id": "within-b",
                "source_node_id": "grid-b",
                "target_node_id": "admin-1",
                "relation_type": "grid_within_admin",
                "support_level": "observed_context",
            },
            {
                "edge_id": "adjacent-a-b",
                "source_node_id": "grid-a",
                "target_node_id": "grid-b",
                "relation_type": "grid_adjacent_grid",
                "support_level": "observed_context",
            },
            {
                "edge_id": "within-a",
                "source_node_id": "grid-a",
                "target_node_id": "admin-1",
                "relation_type": "grid_within_admin",
                "support_level": "observed_context",
            },
        ],
        "kernel_versions": {"state": "0.1.0"},
    }


def test_state_is_canonical_and_digest_is_order_independent():
    first = build_environmental_state(state_input())
    reordered = deepcopy(state_input())
    reordered["spatial_nodes"].reverse()
    reordered["spatial_edges"].reverse()
    reordered["source_dataset_ids"].reverse()
    second = build_environmental_state(reordered)

    assert [row["node_id"] for row in first["spatial_nodes"]] == ["admin-1", "grid-a", "grid-b"]
    assert [row["edge_id"] for row in first["spatial_edges"]] == ["adjacent-a-b", "within-a", "within-b"]
    assert first["source_dataset_ids"] == ["air-a", "weather-b"]
    assert first["snapshot_digest"] == second["snapshot_digest"]


def test_state_preserves_unavailable_values_as_null_and_lists_missing_fields():
    state = build_environmental_state(state_input())
    rows = {row["node_id"]: row for row in state["spatial_nodes"]}

    assert rows["grid-b"]["pm25_ugm3"] is None
    assert "pm25_ugm3" in rows["grid-b"]["missing_fields"]
    assert rows["grid-a"]["temperature_c"] is None
    assert "temperature_c" in rows["grid-a"]["missing_fields"]


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda payload: payload["spatial_nodes"].append(deepcopy(payload["spatial_nodes"][0])), "duplicate_node_id"),
        (lambda payload: payload["spatial_edges"][0].update(source_node_id="missing"), "dangling_edge_endpoint"),
        (lambda payload: payload["spatial_nodes"][0].update(vegetation_fraction=1.2), "vegetation_fraction_out_of_range"),
        (lambda payload: payload["spatial_edges"][0].update(relation_type="name_similarity_crosswalk"), "unsupported_relation_type"),
    ],
)
def test_state_rejects_invalid_graphs(mutation, message):
    payload = state_input()
    mutation(payload)

    with pytest.raises(ValueError, match=message):
        build_environmental_state(payload)

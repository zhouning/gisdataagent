from copy import deepcopy

import pytest

from data_agent.uwm.geospatial_kernel.state_graph import (
    GEOSPATIAL_STATE_GRAPH_SCHEMA,
    build_state_graph,
    validate_state_graph,
)


def _nodes() -> list[dict]:
    return [
        {
            "node_id": "parcel-1",
            "node_type": "parcel",
            "state_time": "t0_current",
            "current_land_use_class": "residential",
            "planned_land_use_class": "public_service",
            "candidate_land_use_class": None,
            "source_land_use_code": "0701",
            "evidence_refs": ["source:parcel-1"],
            "observability": "observed",
        },
        {
            "node_id": "resource-1",
            "node_type": "planning_resource",
            "state_time": "t0_current",
            "source_name": "规划资源一",
            "evidence_refs": ["source:resource-1"],
            "observability": "observed",
        },
        {
            "node_id": "facility-1",
            "node_type": "facility",
            "state_time": "t0_current",
            "source_name": "设施一",
            "evidence_refs": ["source:facility-1"],
            "observability": "observed",
        },
        {
            "node_id": "village-1",
            "node_type": "village_context",
            "state_time": "t0_current",
            "evidence_refs": ["source:village-1"],
            "observability": "derived",
        },
        {
            "node_id": "admin-1",
            "node_type": "admin_context",
            "state_time": "t0_current",
            "evidence_refs": ["source:admin-1"],
            "observability": "derived",
        },
    ]


def _edges() -> list[dict]:
    return [
        {
            "edge_id": "edge-3",
            "source_node_id": "parcel-1",
            "target_node_id": "facility-1",
            "relation_type": "parcel_near_facility",
            "evidence_refs": ["geometry:distance"],
            "support_level": "deterministic_geometry",
        },
        {
            "edge_id": "edge-1",
            "source_node_id": "parcel-1",
            "target_node_id": "resource-1",
            "relation_type": "parcel_contains_resource",
            "evidence_refs": ["geometry:intersection"],
            "support_level": "deterministic_geometry",
        },
        {
            "edge_id": "edge-2",
            "source_node_id": "parcel-1",
            "target_node_id": "village-1",
            "relation_type": "parcel_within_village",
            "evidence_refs": ["geometry:containment"],
            "support_level": "deterministic_geometry",
        },
        {
            "edge_id": "edge-4",
            "source_node_id": "village-1",
            "target_node_id": "admin-1",
            "relation_type": "village_within_admin",
            "evidence_refs": ["authority:admin-hierarchy"],
            "support_level": "authoritative_rule",
        },
    ]


def test_state_graph_is_canonical_and_input_order_independent():
    nodes = _nodes()
    edges = _edges()

    graph = build_state_graph(nodes=nodes, edges=edges, kernel_version="0.1.0")
    reordered = build_state_graph(
        nodes=list(reversed(nodes)), edges=list(reversed(edges)), kernel_version="0.1.0"
    )

    assert graph["schema"] == GEOSPATIAL_STATE_GRAPH_SCHEMA
    assert [row["node_id"] for row in graph["nodes"]] == sorted(
        row["node_id"] for row in nodes
    )
    assert [row["edge_id"] for row in graph["edges"]] == sorted(
        row["edge_id"] for row in edges
    )
    assert graph["snapshot_digest"] == reordered["snapshot_digest"]
    assert validate_state_graph(graph) == {"valid": True, "errors": []}


def test_state_graph_does_not_mutate_inputs():
    nodes = _nodes()
    edges = _edges()
    original_nodes = deepcopy(nodes)
    original_edges = deepcopy(edges)

    graph = build_state_graph(nodes=nodes, edges=edges, kernel_version="0.1.0")
    graph["nodes"][0]["observability"] = "changed"

    assert nodes == original_nodes
    assert edges == original_edges


@pytest.mark.parametrize(
    ("mutator", "error"),
    [
        (lambda nodes, edges: nodes.append(deepcopy(nodes[0])), "duplicate_node_id:parcel-1"),
        (lambda nodes, edges: edges.append(deepcopy(edges[0])), "duplicate_edge_id:edge-3"),
        (
            lambda nodes, edges: edges[0].update({"target_node_id": "missing-node"}),
            "dangling_edge_target:edge-3:missing-node",
        ),
        (
            lambda nodes, edges: nodes[0].update({"node_type": "unknown"}),
            "invalid_node_type:parcel-1",
        ),
    ],
)
def test_state_graph_rejects_invalid_structure(mutator, error):
    nodes = _nodes()
    edges = _edges()
    mutator(nodes, edges)

    with pytest.raises(ValueError, match=error):
        build_state_graph(nodes=nodes, edges=edges, kernel_version="0.1.0")


def test_state_graph_requires_distinct_parcel_land_use_fields():
    nodes = _nodes()
    nodes[0].pop("planned_land_use_class")
    nodes[0]["land_use_class"] = "residential"

    with pytest.raises(ValueError, match="parcel_land_use_fields_missing:parcel-1"):
        build_state_graph(nodes=nodes, edges=_edges(), kernel_version="0.1.0")


def test_validation_detects_digest_tampering():
    graph = build_state_graph(nodes=_nodes(), edges=_edges(), kernel_version="0.1.0")
    graph["nodes"][0]["observability"] = "unavailable"

    validation = validate_state_graph(graph)

    assert not validation["valid"]
    assert "snapshot_digest_mismatch" in validation["errors"]

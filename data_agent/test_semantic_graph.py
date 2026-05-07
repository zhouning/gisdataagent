"""Tests for the metadata graph G=(V,E) abstraction."""
import os

import pytest
import networkx as nx
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from data_agent.semantic_graph import (
    SemanticGraph,
    NodeKind,
    EdgeKind,
    build_semantic_graph,
)


def test_node_and_edge_kinds_exposed():
    assert set(NodeKind) == {
        NodeKind.GEO_ENTITY, NodeKind.DIMENSION, NodeKind.MEASURE,
        NodeKind.INTENT, NodeKind.PREDICATE, NodeKind.CONSTRAINT,
    }
    assert set(EdgeKind) == {
        EdgeKind.HAS_GEOMETRY, EdgeKind.FK, EdgeKind.TOPOLOGICAL,
        EdgeKind.METRIC, EdgeKind.KNN, EdgeKind.INTENT_ROUTES,
        EdgeKind.SAFETY_CONSTRAINT, EdgeKind.UNIT_RULE,
    }


def test_geo_entity_node_carries_srid_and_geom_type():
    g = SemanticGraph()
    g.add_geo_entity(
        table="cq_osm_roads_2021", geom_col="geometry",
        srid=4326, geom_type="MULTILINESTRING",
    )
    node = g.graph.nodes["cq_osm_roads_2021"]
    assert node["kind"] == NodeKind.GEO_ENTITY
    assert node["srid"] == 4326
    assert node["geom_type"] == "MULTILINESTRING"
    assert node["geom_col"] == "geometry"


def test_intent_routes_edge_to_predicate_class():
    g = SemanticGraph()
    g.add_intent("spatial_measurement")
    g.add_predicate("ST_Length", predicate_class="metric")
    g.add_intent_route("spatial_measurement", "ST_Length")
    edges = list(g.graph.out_edges("spatial_measurement", data=True))
    assert len(edges) == 1
    assert edges[0][2]["kind"] == EdgeKind.INTENT_ROUTES


def test_safety_constraint_edge_encodes_srid_rule():
    g = SemanticGraph()
    g.add_geo_entity("cq_osm_roads_2021", "geometry", 4326, "MULTILINESTRING")
    g.add_predicate("ST_Length", predicate_class="metric")
    g.add_unit_rule(
        predicate="ST_Length",
        srid_range=(4326, 4326),
        required_cast="geography",
        yields_unit="metre",
    )
    edges = [e for e in g.graph.edges(data=True)
             if e[2]["kind"] == EdgeKind.UNIT_RULE]
    assert len(edges) == 1
    assert edges[0][2]["required_cast"] == "geography"


def test_graph_to_mermaid_is_deterministic():
    g = SemanticGraph()
    g.add_geo_entity("cq_osm_roads_2021", "geometry", 4326, "MULTILINESTRING")
    g.add_intent("spatial_measurement")
    g.add_predicate("ST_Length", predicate_class="metric")
    g.add_intent_route("spatial_measurement", "ST_Length")
    m1 = g.to_mermaid()
    m2 = g.to_mermaid()
    assert m1 == m2
    assert "cq_osm_roads_2021" in m1
    assert ("spatial_measurement --> ST_Length" in m1
            or "spatial_measurement-->ST_Length" in m1)


def test_build_from_live_pg_covers_all_cq_tables():
    g = build_semantic_graph(schema="public", table_prefix="cq_")
    geo_nodes = [n for n, d in g.graph.nodes(data=True)
                 if d.get("kind") == NodeKind.GEO_ENTITY]
    # 18 cq_* rows in geometry_columns (verified 2026-05-07); 7 are
    # zero-SRID grid tables that are correctly skipped, leaving 11.
    assert len(geo_nodes) >= 11
    assert g.graph.nodes["cq_osm_roads_2021"]["srid"] == 4326
    assert g.graph.nodes["cq_land_use_dltb"]["srid"] == 4326
    assert g.graph.nodes["cq_dltb"]["srid"] == 4610

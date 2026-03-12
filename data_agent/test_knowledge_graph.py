"""Tests for the Geographic Knowledge Graph module (v7.0).

Covers: graph construction from GeoDataFrames, entity type detection,
adjacency/containment detection, layer merging, neighbor/path/type queries,
JSON export, stats computation, and toolset registration.
"""

import json
import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point, Polygon, box


# ---------------------------------------------------------------------------
# Helpers: create test fixtures
# ---------------------------------------------------------------------------

def _make_adjacent_polygons(tmp_dir: str, name: str = "parcels.geojson") -> str:
    """Create 3 adjacent unit-square polygons sharing edges."""
    polys = [
        Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]),
        Polygon([(1, 0), (2, 0), (2, 1), (1, 1)]),
        Polygon([(0, 1), (1, 1), (1, 2), (0, 2)]),
    ]
    gdf = gpd.GeoDataFrame({
        "OBJECTID": [1, 2, 3],
        "DLBM": ["0101", "0201", "0301"],
        "AREA": [100.5, 200.3, 150.7],
    }, geometry=polys, crs="EPSG:4326")
    path = os.path.join(tmp_dir, name)
    gdf.to_file(path, driver="GeoJSON")
    return path


def _make_contained_polygons(tmp_dir: str, name: str = "contained.geojson") -> str:
    """Create a large polygon containing a smaller one."""
    polys = [
        Polygon([(0, 0), (10, 0), (10, 10), (0, 10)]),   # large
        Polygon([(2, 2), (4, 2), (4, 4), (2, 4)]),         # small inside large
    ]
    gdf = gpd.GeoDataFrame({
        "FID": [1, 2],
        "TYPE": ["outer", "inner"],
    }, geometry=polys, crs="EPSG:4326")
    path = os.path.join(tmp_dir, name)
    gdf.to_file(path, driver="GeoJSON")
    return path


def _make_points(tmp_dir: str, name: str = "pois.geojson") -> str:
    """Create a point layer (POI type)."""
    points = [Point(0.5, 0.5), Point(1.5, 0.5), Point(0.5, 1.5)]
    gdf = gpd.GeoDataFrame({
        "POI_ID": [10, 20, 30],
        "NAME": ["School", "Hospital", "Park"],
    }, geometry=points, crs="EPSG:4326")
    path = os.path.join(tmp_dir, name)
    gdf.to_file(path, driver="GeoJSON")
    return path


def _make_disconnected_polygons(tmp_dir: str, name: str = "disconnected.geojson") -> str:
    """Create two polygons far apart (no spatial relationship)."""
    polys = [
        Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]),
        Polygon([(100, 100), (101, 100), (101, 101), (100, 101)]),
    ]
    gdf = gpd.GeoDataFrame({
        "ID": [1, 2],
        "VALUE": [10, 20],
    }, geometry=polys, crs="EPSG:4326")
    path = os.path.join(tmp_dir, name)
    gdf.to_file(path, driver="GeoJSON")
    return path


# ---------------------------------------------------------------------------
# TestGeoKnowledgeGraph
# ---------------------------------------------------------------------------

class TestGeoKnowledgeGraph(unittest.TestCase):
    """Tests for the GeoKnowledgeGraph class."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_build_from_geodataframe_basic(self):
        """3 adjacent polygons produce 3 nodes."""
        from data_agent.knowledge_graph import GeoKnowledgeGraph
        gdf = gpd.read_file(_make_adjacent_polygons(self.tmp))
        graph = GeoKnowledgeGraph()
        stats = graph.build_from_geodataframe(gdf)
        self.assertEqual(stats.node_count, 3)

    def test_build_detects_entity_type(self):
        """GDF with 'DLBM' column detected as entity_type 'parcel'."""
        from data_agent.knowledge_graph import GeoKnowledgeGraph
        gdf = gpd.read_file(_make_adjacent_polygons(self.tmp))
        graph = GeoKnowledgeGraph()
        stats = graph.build_from_geodataframe(gdf, entity_type="auto")
        self.assertIn("parcel", stats.entity_types)

    def test_adjacency_detection(self):
        """Two touching squares produce adjacent_to edges."""
        from data_agent.knowledge_graph import GeoKnowledgeGraph
        # Build 2 squares sharing an edge at x=1
        polys = [
            Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]),
            Polygon([(1, 0), (2, 0), (2, 1), (1, 1)]),
        ]
        gdf = gpd.GeoDataFrame(
            {"ID": [1, 2]}, geometry=polys, crs="EPSG:4326",
        )
        graph = GeoKnowledgeGraph()
        graph.build_from_geodataframe(gdf, id_column="ID")
        # Should have bidirectional adjacent_to edges
        self.assertTrue(graph.graph.has_edge("1", "2"))
        self.assertTrue(graph.graph.has_edge("2", "1"))
        self.assertEqual(graph.graph.edges["1", "2"]["type"], "adjacent_to")

    def test_containment_detection(self):
        """Small polygon inside large polygon produces contains/within edges."""
        from data_agent.knowledge_graph import GeoKnowledgeGraph
        gdf = gpd.read_file(_make_contained_polygons(self.tmp))
        graph = GeoKnowledgeGraph()
        graph.build_from_geodataframe(gdf, id_column="FID")
        # Large (1) contains Small (2)
        has_contains = graph.graph.has_edge("1", "2") and \
            graph.graph.edges["1", "2"].get("type") == "contains"
        has_within = graph.graph.has_edge("2", "1") and \
            graph.graph.edges["2", "1"].get("type") == "within"
        self.assertTrue(has_contains, "Expected 'contains' edge from 1 to 2")
        self.assertTrue(has_within, "Expected 'within' edge from 2 to 1")

    def test_no_self_loops(self):
        """Graph should not contain any self-loop edges."""
        from data_agent.knowledge_graph import GeoKnowledgeGraph
        gdf = gpd.read_file(_make_adjacent_polygons(self.tmp))
        graph = GeoKnowledgeGraph()
        graph.build_from_geodataframe(gdf)
        for nid in graph.graph.nodes():
            self.assertFalse(
                graph.graph.has_edge(nid, nid),
                f"Self-loop found on node {nid}",
            )

    def test_merge_layer(self):
        """Merge a second layer; verify cross-layer relationships detected."""
        from data_agent.knowledge_graph import GeoKnowledgeGraph
        gdf1 = gpd.read_file(_make_adjacent_polygons(self.tmp))
        graph = GeoKnowledgeGraph()
        graph.build_from_geodataframe(gdf1, entity_type="parcel")

        # Create points inside the polygons
        points = [Point(0.5, 0.5), Point(1.5, 0.5)]
        gdf2 = gpd.GeoDataFrame(
            {"POI_ID": [10, 20]}, geometry=points, crs="EPSG:4326",
        )
        stats = graph.merge_layer(gdf2, entity_type="poi", id_column="POI_ID")
        # Should have original 3 nodes + 2 new poi nodes
        self.assertEqual(stats.node_count, 5)
        # POI nodes should be prefixed
        self.assertIn("poi_10", graph.graph.nodes())
        self.assertIn("poi_20", graph.graph.nodes())
        # Points inside polygons should have contains/within edges
        self.assertGreaterEqual(stats.edge_count, 1)

    def test_query_neighbors_basic(self):
        """Query depth=1 neighbors returns direct neighbors."""
        from data_agent.knowledge_graph import GeoKnowledgeGraph
        polys = [
            Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]),
            Polygon([(1, 0), (2, 0), (2, 1), (1, 1)]),
            Polygon([(2, 0), (3, 0), (3, 1), (2, 1)]),
        ]
        gdf = gpd.GeoDataFrame(
            {"ID": ["A", "B", "C"]}, geometry=polys, crs="EPSG:4326",
        )
        graph = GeoKnowledgeGraph()
        graph.build_from_geodataframe(gdf, id_column="ID")
        result = graph.query_neighbors("A", depth=1)
        neighbor_ids = [n["id"] for n in result["neighbors"]]
        self.assertIn("B", neighbor_ids)
        # C is not adjacent to A (doesn't share a boundary)
        self.assertNotIn("C", neighbor_ids)

    def test_query_neighbors_depth_2(self):
        """Query depth=2 reaches nodes 2 hops away."""
        from data_agent.knowledge_graph import GeoKnowledgeGraph
        polys = [
            Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]),
            Polygon([(1, 0), (2, 0), (2, 1), (1, 1)]),
            Polygon([(2, 0), (3, 0), (3, 1), (2, 1)]),
        ]
        gdf = gpd.GeoDataFrame(
            {"ID": ["A", "B", "C"]}, geometry=polys, crs="EPSG:4326",
        )
        graph = GeoKnowledgeGraph()
        graph.build_from_geodataframe(gdf, id_column="ID")
        result = graph.query_neighbors("A", depth=2)
        neighbor_ids = [n["id"] for n in result["neighbors"]]
        # depth=2 should reach C via A→B→C
        self.assertIn("B", neighbor_ids)
        self.assertIn("C", neighbor_ids)

    def test_query_neighbors_filtered(self):
        """Filter by relationship_type returns only matching edges."""
        from data_agent.knowledge_graph import GeoKnowledgeGraph
        gdf = gpd.read_file(_make_contained_polygons(self.tmp))
        graph = GeoKnowledgeGraph()
        graph.build_from_geodataframe(gdf, id_column="FID")
        # Query from large (1) with filter "contains"
        result = graph.query_neighbors("1", relationship_type="contains")
        self.assertTrue(len(result["neighbors"]) > 0)
        for n in result["neighbors"]:
            self.assertEqual(n["relationship"], "contains")

    def test_query_path(self):
        """Find shortest path between two connected nodes."""
        from data_agent.knowledge_graph import GeoKnowledgeGraph
        polys = [
            Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]),
            Polygon([(1, 0), (2, 0), (2, 1), (1, 1)]),
            Polygon([(2, 0), (3, 0), (3, 1), (2, 1)]),
        ]
        gdf = gpd.GeoDataFrame(
            {"ID": ["A", "B", "C"]}, geometry=polys, crs="EPSG:4326",
        )
        graph = GeoKnowledgeGraph()
        graph.build_from_geodataframe(gdf, id_column="ID")
        result = graph.query_path("A", "C")
        self.assertGreater(result["length"], 0)
        self.assertEqual(result["path"][0], "A")
        self.assertEqual(result["path"][-1], "C")

    def test_query_path_no_connection(self):
        """Disconnected nodes return length -1."""
        from data_agent.knowledge_graph import GeoKnowledgeGraph
        gdf = gpd.read_file(_make_disconnected_polygons(self.tmp))
        graph = GeoKnowledgeGraph()
        graph.build_from_geodataframe(
            gdf, id_column="ID", detect_adjacency=True, detect_containment=False,
        )
        result = graph.query_path("1", "2")
        self.assertEqual(result["length"], -1)
        self.assertEqual(result["path"], [])

    def test_query_by_type(self):
        """Filter nodes by entity_type."""
        from data_agent.knowledge_graph import GeoKnowledgeGraph
        gdf1 = gpd.read_file(_make_adjacent_polygons(self.tmp))
        graph = GeoKnowledgeGraph()
        graph.build_from_geodataframe(gdf1, entity_type="parcel")

        points = [Point(5, 5)]
        gdf2 = gpd.GeoDataFrame({"PID": [99]}, geometry=points, crs="EPSG:4326")
        graph.merge_layer(gdf2, entity_type="poi", id_column="PID")

        parcels = graph.query_by_type("parcel")
        pois = graph.query_by_type("poi")
        self.assertEqual(len(parcels), 3)
        self.assertEqual(len(pois), 1)

    def test_export_to_json(self):
        """Export produces valid JSON with nodes and links."""
        from data_agent.knowledge_graph import GeoKnowledgeGraph
        polys = [
            Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]),
            Polygon([(1, 0), (2, 0), (2, 1), (1, 1)]),
        ]
        gdf = gpd.GeoDataFrame(
            {"ID": [1, 2]}, geometry=polys, crs="EPSG:4326",
        )
        graph = GeoKnowledgeGraph()
        graph.build_from_geodataframe(gdf)
        data = graph.export_to_json()
        self.assertIn("nodes", data)
        # networkx >=3.2 uses "edges", older versions use "links"
        self.assertTrue(
            "links" in data or "edges" in data,
            "Expected 'links' or 'edges' key in node_link_data output",
        )
        # _geom_wkt should be stripped
        for node in data["nodes"]:
            self.assertNotIn("_geom_wkt", node)

    def test_empty_gdf(self):
        """Empty GeoDataFrame produces empty graph."""
        from data_agent.knowledge_graph import GeoKnowledgeGraph
        gdf = gpd.GeoDataFrame(columns=["geometry"], geometry="geometry")
        graph = GeoKnowledgeGraph()
        stats = graph.build_from_geodataframe(gdf)
        self.assertEqual(stats.node_count, 0)
        self.assertEqual(stats.edge_count, 0)

    def test_auto_detect_id_column(self):
        """Prefers 'OBJECTID' over other columns."""
        from data_agent.knowledge_graph import GeoKnowledgeGraph
        polys = [Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])]
        gdf = gpd.GeoDataFrame({
            "NAME": ["test"],
            "OBJECTID": [42],
            "VALUE": [100],
        }, geometry=polys, crs="EPSG:4326")
        graph = GeoKnowledgeGraph()
        detected = graph._detect_id_column(gdf)
        self.assertEqual(detected, "OBJECTID")

    def test_get_stats(self):
        """Verify all stats fields are populated after build."""
        from data_agent.knowledge_graph import GeoKnowledgeGraph
        gdf = gpd.read_file(_make_adjacent_polygons(self.tmp))
        graph = GeoKnowledgeGraph()
        graph.build_from_geodataframe(gdf)
        stats = graph.get_stats()
        self.assertGreater(stats.node_count, 0)
        self.assertIsInstance(stats.entity_types, dict)
        self.assertIsInstance(stats.relationship_types, dict)
        self.assertGreaterEqual(stats.connected_components, 1)
        self.assertIsInstance(stats.density, float)


# ---------------------------------------------------------------------------
# TestKnowledgeGraphToolset
# ---------------------------------------------------------------------------

class TestKnowledgeGraphToolset(unittest.TestCase):
    """Tests for the KnowledgeGraphToolset class."""

    def test_toolset_has_3_tools(self):
        """KnowledgeGraphToolset exposes exactly 3 tools."""
        import asyncio
        from data_agent.toolsets.knowledge_graph_tools import KnowledgeGraphToolset

        toolset = KnowledgeGraphToolset()
        loop = asyncio.new_event_loop()
        try:
            tools = loop.run_until_complete(toolset.get_tools())
        finally:
            loop.close()
        self.assertEqual(len(tools), 3)
        names = sorted([t.name for t in tools])
        self.assertIn("build_knowledge_graph", names)
        self.assertIn("query_knowledge_graph", names)
        self.assertIn("export_knowledge_graph", names)


if __name__ == "__main__":
    unittest.main()

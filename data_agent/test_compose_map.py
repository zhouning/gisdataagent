"""Tests for compose_map multi-layer map tool."""
import json
import os
import sys
import tempfile
import unittest

import geopandas as gpd
import numpy as np
from shapely.geometry import Point, Polygon

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def _make_point_shp(tmp_dir, name="pts.shp", n=20):
    """Create a simple point shapefile for testing."""
    pts = [Point(116.4 + np.random.uniform(-0.05, 0.05),
                 39.9 + np.random.uniform(-0.05, 0.05)) for _ in range(n)]
    gdf = gpd.GeoDataFrame({"name": [f"P{i}" for i in range(n)],
                             "value": np.random.randint(1, 100, n)},
                            geometry=pts, crs="EPSG:4326")
    path = os.path.join(tmp_dir, name)
    gdf.to_file(path)
    return path


def _make_polygon_shp(tmp_dir, name="polys.shp", n=5):
    """Create a simple polygon shapefile for testing."""
    polys = []
    for i in range(n):
        x = 116.35 + i * 0.02
        y = 39.88
        polys.append(Polygon([(x, y), (x + 0.02, y), (x + 0.02, y + 0.02), (x, y + 0.02)]))
    gdf = gpd.GeoDataFrame({"area_ha": np.random.uniform(10, 100, n),
                             "category": [f"C{i}" for i in range(n)]},
                            geometry=polys, crs="EPSG:4326")
    path = os.path.join(tmp_dir, name)
    gdf.to_file(path)
    return path


class TestComposeMap(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp_dir = tempfile.mkdtemp()
        cls.pt_path = _make_point_shp(cls.tmp_dir)
        cls.poly_path = _make_polygon_shp(cls.tmp_dir)

    def test_two_layer_point_polygon(self):
        from data_agent.toolsets.visualization_tools import compose_map
        layers = [
            {"data_path": self.pt_path, "name": "Points", "type": "point", "color": "#e74c3c"},
            {"data_path": self.poly_path, "name": "Polygons", "type": "polygon", "color": "#3498db", "opacity": 0.3},
        ]
        result = compose_map(json.dumps(layers))
        self.assertIn("composed_map", result)
        self.assertIn(".html", result)
        self.assertTrue(os.path.exists(result.split(": ")[1].split("\n")[0]))

    def test_choropleth_layer(self):
        from data_agent.toolsets.visualization_tools import compose_map
        layers = [
            {"data_path": self.poly_path, "name": "Choropleth", "type": "choropleth",
             "value_column": "area_ha", "color_scheme": "Blues"},
        ]
        result = compose_map(json.dumps(layers))
        self.assertIn("composed_map", result)
        self.assertNotIn("Error", result)

    def test_heatmap_point_overlay(self):
        from data_agent.toolsets.visualization_tools import compose_map
        layers = [
            {"data_path": self.pt_path, "name": "Heatmap", "type": "heatmap"},
            {"data_path": self.pt_path, "name": "Markers", "type": "point", "color": "#000"},
        ]
        result = compose_map(json.dumps(layers))
        self.assertIn("composed_map", result)
        self.assertIn("2 个图层", result)

    def test_invalid_json(self):
        from data_agent.toolsets.visualization_tools import compose_map
        result = compose_map("not valid json {{{")
        self.assertIn("Error", result)
        self.assertIn("解析失败", result)

    def test_empty_layers(self):
        from data_agent.toolsets.visualization_tools import compose_map
        result = compose_map("[]")
        self.assertIn("Error", result)
        self.assertIn("非空", result)

    def test_missing_value_column_choropleth(self):
        from data_agent.toolsets.visualization_tools import compose_map
        layers = [
            {"data_path": self.poly_path, "name": "Bad", "type": "choropleth",
             "value_column": "nonexistent_field"},
        ]
        result = compose_map(json.dumps(layers))
        self.assertIn("Error", result)
        self.assertIn("不存在", result)

    def test_mixed_three_layers(self):
        from data_agent.toolsets.visualization_tools import compose_map
        layers = [
            {"data_path": self.poly_path, "name": "Areas", "type": "polygon"},
            {"data_path": self.pt_path, "name": "Bubbles", "type": "bubble",
             "value_column": "value", "max_radius": 20},
            {"data_path": self.pt_path, "name": "Heat", "type": "heatmap",
             "weight_field": "value"},
        ]
        result = compose_map(json.dumps(layers))
        self.assertIn("composed_map", result)
        self.assertIn("3 个图层", result)


if __name__ == "__main__":
    unittest.main()

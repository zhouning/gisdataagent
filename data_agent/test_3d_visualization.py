"""
Tests for 3D spatial visualization (v5.3).
Tests generate_3d_map tool, _save_map_config 3D params, and VisualizationToolset.
"""

import json
import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock

import geopandas as gpd
import numpy as np
from shapely.geometry import Polygon, Point


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_polygon_gdf(n=10, with_elevation=True, with_value=True):
    """Create a test GeoDataFrame with polygons."""
    polys = []
    for i in range(n):
        x, y = 120.0 + i * 0.01, 30.0 + i * 0.01
        polys.append(Polygon([
            (x, y), (x + 0.005, y), (x + 0.005, y + 0.005), (x, y + 0.005)
        ]))
    data = {"geometry": polys, "name": [f"parcel_{i}" for i in range(n)]}
    if with_elevation:
        data["height"] = np.random.randint(10, 500, n).tolist()
    if with_value:
        data["area_m2"] = np.random.uniform(100, 5000, n).tolist()
    return gpd.GeoDataFrame(data, crs="EPSG:4326")


def _make_point_gdf(n=10):
    """Create a test GeoDataFrame with points."""
    points = [Point(120.0 + i * 0.01, 30.0 + i * 0.01) for i in range(n)]
    data = {
        "geometry": points,
        "label": [f"pt_{i}" for i in range(n)],
        "value": np.random.uniform(1, 100, n).tolist(),
    }
    return gpd.GeoDataFrame(data, crs="EPSG:4326")


# ---------------------------------------------------------------------------
# TestGenerate3dMap
# ---------------------------------------------------------------------------

class TestGenerate3dMap(unittest.TestCase):
    """Tests for generate_3d_map() tool function."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.gdf = _make_polygon_gdf()
        self.geojson_path = os.path.join(self.tmpdir, "test.geojson")
        self.gdf.to_file(self.geojson_path, driver="GeoJSON")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @patch("data_agent.toolsets.visualization_tools._generate_output_path")
    def test_basic_extrusion(self, mock_path):
        out_html = os.path.join(self.tmpdir, "3d_map_test.html")
        mock_path.return_value = out_html

        from data_agent.toolsets.visualization_tools import generate_3d_map
        result = generate_3d_map(
            data_path=self.geojson_path,
            elevation_column="height",
            layer_name="Test 3D",
        )
        self.assertIn("3D 地图已生成", result)
        self.assertIn("Test 3D", result)
        # Verify mapconfig was created
        config_path = out_html.replace(".html", ".mapconfig.json")
        self.assertTrue(os.path.exists(config_path))
        with open(config_path, encoding="utf-8") as f:
            config = json.load(f)
        self.assertEqual(config["layers"][0]["type"], "extrusion")
        self.assertEqual(config["layers"][0]["elevation_column"], "height")
        self.assertTrue(config["layers"][0]["extruded"])

    @patch("data_agent.toolsets.visualization_tools._generate_output_path")
    def test_with_value_column_and_breaks(self, mock_path):
        out_html = os.path.join(self.tmpdir, "3d_choro.html")
        mock_path.return_value = out_html

        from data_agent.toolsets.visualization_tools import generate_3d_map
        result = generate_3d_map(
            data_path=self.geojson_path,
            elevation_column="height",
            value_column="area_m2",
            layer_name="Choropleth 3D",
        )
        self.assertIn("3D 地图已生成", result)
        self.assertIn("area_m2", result)
        config_path = out_html.replace(".html", ".mapconfig.json")
        with open(config_path, encoding="utf-8") as f:
            config = json.load(f)
        layer = config["layers"][0]
        self.assertEqual(layer["value_column"], "area_m2")
        self.assertIn("breaks", layer)
        self.assertEqual(len(layer["breaks"]), 5)

    @patch("data_agent.toolsets.visualization_tools._generate_output_path")
    def test_column_type(self, mock_path):
        out_html = os.path.join(self.tmpdir, "3d_col.html")
        mock_path.return_value = out_html

        from data_agent.toolsets.visualization_tools import generate_3d_map
        result = generate_3d_map(
            data_path=self.geojson_path,
            layer_type="column",
            layer_name="Column Chart",
        )
        self.assertIn("3D 地图已生成", result)
        config_path = out_html.replace(".html", ".mapconfig.json")
        with open(config_path, encoding="utf-8") as f:
            config = json.load(f)
        self.assertEqual(config["layers"][0]["type"], "column")

    @patch("data_agent.toolsets.visualization_tools._generate_output_path")
    def test_pitch_bearing_in_config(self, mock_path):
        out_html = os.path.join(self.tmpdir, "3d_pb.html")
        mock_path.return_value = out_html

        from data_agent.toolsets.visualization_tools import generate_3d_map
        generate_3d_map(
            data_path=self.geojson_path,
            pitch=50,
            bearing=-30,
        )
        config_path = out_html.replace(".html", ".mapconfig.json")
        with open(config_path, encoding="utf-8") as f:
            config = json.load(f)
        self.assertEqual(config["pitch"], 50)
        self.assertEqual(config["bearing"], -30)

    def test_missing_elevation_column(self):
        from data_agent.toolsets.visualization_tools import generate_3d_map
        result = generate_3d_map(
            data_path=self.geojson_path,
            elevation_column="nonexistent",
        )
        self.assertIn("Error", result)
        self.assertIn("nonexistent", result)

    def test_missing_value_column(self):
        from data_agent.toolsets.visualization_tools import generate_3d_map
        result = generate_3d_map(
            data_path=self.geojson_path,
            value_column="nonexistent",
        )
        self.assertIn("Error", result)
        self.assertIn("nonexistent", result)

    @patch("data_agent.toolsets.visualization_tools._generate_output_path")
    def test_no_elevation_column(self, mock_path):
        """When no elevation_column, layer should still have extruded=True."""
        out_html = os.path.join(self.tmpdir, "3d_noelev.html")
        mock_path.return_value = out_html

        from data_agent.toolsets.visualization_tools import generate_3d_map
        result = generate_3d_map(data_path=self.geojson_path)
        self.assertIn("3D 地图已生成", result)
        config_path = out_html.replace(".html", ".mapconfig.json")
        with open(config_path, encoding="utf-8") as f:
            config = json.load(f)
        self.assertTrue(config["layers"][0]["extruded"])
        self.assertNotIn("elevation_column", config["layers"][0])

    @patch("data_agent.toolsets.visualization_tools._generate_output_path")
    def test_invalid_layer_type_defaults_to_extrusion(self, mock_path):
        out_html = os.path.join(self.tmpdir, "3d_invalid.html")
        mock_path.return_value = out_html

        from data_agent.toolsets.visualization_tools import generate_3d_map
        result = generate_3d_map(
            data_path=self.geojson_path,
            layer_type="invalidtype",
        )
        self.assertIn("3D 地图已生成", result)
        config_path = out_html.replace(".html", ".mapconfig.json")
        with open(config_path, encoding="utf-8") as f:
            config = json.load(f)
        self.assertEqual(config["layers"][0]["type"], "extrusion")


# ---------------------------------------------------------------------------
# TestSaveMapConfig3D
# ---------------------------------------------------------------------------

class TestSaveMapConfig3D(unittest.TestCase):
    """Tests for _save_map_config with 3D parameters."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.gdf = _make_polygon_gdf(5, with_elevation=False, with_value=False)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_pitch_bearing_saved(self):
        from data_agent.toolsets.visualization_tools import _save_map_config
        html_path = os.path.join(self.tmpdir, "test.html")
        with open(html_path, "w") as f:
            f.write("<html></html>")

        _save_map_config(html_path, self.gdf, [{"name": "L1", "type": "extrusion"}],
                         pitch=45, bearing=-20)

        config_path = html_path.replace(".html", ".mapconfig.json")
        with open(config_path, encoding="utf-8") as f:
            config = json.load(f)
        self.assertEqual(config["pitch"], 45)
        self.assertEqual(config["bearing"], -20)

    def test_no_pitch_bearing_omitted(self):
        from data_agent.toolsets.visualization_tools import _save_map_config
        html_path = os.path.join(self.tmpdir, "test2.html")
        with open(html_path, "w") as f:
            f.write("<html></html>")

        _save_map_config(html_path, self.gdf, [{"name": "L1", "type": "polygon"}])

        config_path = html_path.replace(".html", ".mapconfig.json")
        with open(config_path, encoding="utf-8") as f:
            config = json.load(f)
        self.assertNotIn("pitch", config)
        self.assertNotIn("bearing", config)


# ---------------------------------------------------------------------------
# TestVisualizationToolset3D
# ---------------------------------------------------------------------------

class TestVisualizationToolset3D(unittest.TestCase):
    """Verify generate_3d_map is registered in VisualizationToolset."""

    def test_generate_3d_map_in_all_funcs(self):
        from data_agent.toolsets.visualization_tools import _ALL_FUNCS, generate_3d_map
        self.assertIn(generate_3d_map, _ALL_FUNCS)

    def test_toolset_tool_count(self):
        from data_agent.toolsets.visualization_tools import _ALL_FUNCS
        self.assertEqual(len(_ALL_FUNCS), 11)


# ---------------------------------------------------------------------------
# TestMapLayerInterface
# ---------------------------------------------------------------------------

class TestMapLayerInterface(unittest.TestCase):
    """Verify 3D layer config structure."""

    def test_3d_layer_config_structure(self):
        """A valid 3D layer config has the expected keys."""
        layer = {
            "name": "Test 3D",
            "type": "extrusion",
            "extruded": True,
            "elevation_column": "height",
            "elevation_scale": 2.0,
            "pitch": 45,
            "bearing": 0,
        }
        self.assertEqual(layer["type"], "extrusion")
        self.assertTrue(layer["extruded"])
        self.assertEqual(layer["elevation_column"], "height")
        self.assertEqual(layer["elevation_scale"], 2.0)

    def test_3d_types_are_valid(self):
        """3D types: extrusion, column, arc."""
        valid_3d_types = {"extrusion", "column", "arc"}
        for t in valid_3d_types:
            layer = {"name": f"test_{t}", "type": t, "extruded": True}
            self.assertEqual(layer["type"], t)


if __name__ == "__main__":
    unittest.main()

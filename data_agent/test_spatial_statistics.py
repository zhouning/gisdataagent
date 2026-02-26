"""Tests for spatial statistics tools (F11)."""
import asyncio
import json
import os
import tempfile
import unittest

import geopandas as gpd
import numpy as np
from shapely.geometry import box


def _make_grid(seed=42, crs="EPSG:3857"):
    """Create a 10x10 grid with spatially clustered values for testing."""
    np.random.seed(seed)
    polys = []
    values = []
    for i in range(10):
        for j in range(10):
            polys.append(box(i, j, i + 1, j + 1))
            # High values top-right, low bottom-left → positive autocorrelation
            values.append(float(i + j) + np.random.normal(0, 0.3))
    return gpd.GeoDataFrame({"value": values, "geometry": polys}, crs=crs)


class TestSpatialAutocorrelation(unittest.TestCase):
    """Test global Moran's I computation."""

    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp()
        cls.shp_path = os.path.join(cls.tmpdir, "test_grid.shp")
        _make_grid().to_file(cls.shp_path)

    def test_basic_queen(self):
        from data_agent.spatial_statistics import spatial_autocorrelation
        result = spatial_autocorrelation(self.shp_path, "value", weights_type="queen")
        self.assertNotIn("Error", result)
        data = json.loads(result)
        self.assertIn("moran_I", data)
        self.assertGreater(data["moran_I"], 0)
        self.assertIn("p_value", data)
        self.assertIn("significance", data)

    def test_knn_weights(self):
        from data_agent.spatial_statistics import spatial_autocorrelation
        result = spatial_autocorrelation(self.shp_path, "value", weights_type="knn", k=4)
        self.assertNotIn("Error", result)
        data = json.loads(result)
        self.assertIn("moran_I", data)

    def test_invalid_column(self):
        from data_agent.spatial_statistics import spatial_autocorrelation
        result = spatial_autocorrelation(self.shp_path, "nonexistent")
        self.assertIn("Error", result)

    def test_invalid_file(self):
        from data_agent.spatial_statistics import spatial_autocorrelation
        result = spatial_autocorrelation("/fake/path.shp", "value")
        self.assertIn("Error", result)

    def test_invalid_weights_type(self):
        from data_agent.spatial_statistics import spatial_autocorrelation
        result = spatial_autocorrelation(self.shp_path, "value", weights_type="invalid")
        self.assertIn("Error", result)


class TestLocalMoran(unittest.TestCase):
    """Test LISA computation."""

    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp()
        cls.shp_path = os.path.join(cls.tmpdir, "test_lisa.shp")
        _make_grid().to_file(cls.shp_path)

    def test_basic_lisa(self):
        from data_agent.spatial_statistics import local_moran
        result = local_moran(self.shp_path, "value")
        self.assertIsInstance(result, dict)
        self.assertIn("output_path", result)
        self.assertIn("visualization", result)
        self.assertTrue(os.path.exists(result["output_path"]))
        self.assertTrue(os.path.exists(result["visualization"]))
        self.assertTrue(result["visualization"].endswith(".png"))

    def test_lisa_cluster_labels(self):
        from data_agent.spatial_statistics import local_moran
        result = local_moran(self.shp_path, "value")
        gdf_result = gpd.read_file(result["output_path"])
        valid_labels = {"HH", "HL", "LH", "LL", "NS"}
        self.assertIn("lisa_cls", gdf_result.columns)
        self.assertTrue(set(gdf_result["lisa_cls"].unique()).issubset(valid_labels))

    def test_invalid_column(self):
        from data_agent.spatial_statistics import local_moran
        result = local_moran(self.shp_path, "nonexistent")
        self.assertIn("Error", result)


class TestHotspotAnalysis(unittest.TestCase):
    """Test Getis-Ord Gi* computation."""

    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp()
        cls.shp_path = os.path.join(cls.tmpdir, "test_hotspot.shp")
        _make_grid().to_file(cls.shp_path)

    def test_basic_hotspot(self):
        from data_agent.spatial_statistics import hotspot_analysis
        result = hotspot_analysis(self.shp_path, "value")
        self.assertIsInstance(result, dict)
        self.assertIn("output_path", result)
        self.assertIn("visualization", result)
        self.assertTrue(os.path.exists(result["output_path"]))
        self.assertTrue(os.path.exists(result["visualization"]))
        self.assertTrue(result["visualization"].endswith(".png"))

    def test_hotspot_labels(self):
        from data_agent.spatial_statistics import hotspot_analysis
        result = hotspot_analysis(self.shp_path, "value")
        gdf_result = gpd.read_file(result["output_path"])
        self.assertIn("hotspot", gdf_result.columns)
        valid_labels = {"Hot Spot", "Cold Spot", "Not Significant"}
        self.assertTrue(set(gdf_result["hotspot"].unique()).issubset(valid_labels))

    def test_invalid_column(self):
        from data_agent.spatial_statistics import hotspot_analysis
        result = hotspot_analysis(self.shp_path, "nonexistent")
        self.assertIn("Error", result)


class TestSpatialStatisticsToolset(unittest.TestCase):
    """Test toolset class."""

    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_tool_count(self):
        from data_agent.toolsets.spatial_statistics_tools import SpatialStatisticsToolset
        ts = SpatialStatisticsToolset()
        tools = self._run(ts.get_tools())
        self.assertEqual(len(tools), 3)

    def test_tool_names(self):
        from data_agent.toolsets.spatial_statistics_tools import SpatialStatisticsToolset
        ts = SpatialStatisticsToolset()
        tools = self._run(ts.get_tools())
        names = {t.name for t in tools}
        self.assertEqual(names, {"spatial_autocorrelation", "local_moran", "hotspot_analysis"})

    def test_filter(self):
        from data_agent.toolsets.spatial_statistics_tools import SpatialStatisticsToolset
        ts = SpatialStatisticsToolset(tool_filter=["hotspot_analysis"])
        tools = self._run(ts.get_tools())
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0].name, "hotspot_analysis")


class TestCRSHandling(unittest.TestCase):
    """Test geographic CRS auto-reprojection."""

    def test_geographic_crs_reprojection(self):
        """Verify tools work with WGS84 data (auto-reproject to metric)."""
        polys = [box(116 + i * 0.01, 39 + j * 0.01,
                     116 + (i + 1) * 0.01, 39 + (j + 1) * 0.01)
                 for i in range(5) for j in range(5)]
        values = [float(i) for i in range(25)]
        gdf = gpd.GeoDataFrame(
            {"value": values, "geometry": polys}, crs="EPSG:4326"
        )
        tmpdir = tempfile.mkdtemp()
        shp_path = os.path.join(tmpdir, "wgs84_test.shp")
        gdf.to_file(shp_path)

        from data_agent.spatial_statistics import spatial_autocorrelation
        result = spatial_autocorrelation(shp_path, "value")
        self.assertNotIn("Error", result)


class TestCodeExporterEntries(unittest.TestCase):
    """Verify code_exporter has entries for all spatial statistics tools."""

    def test_all_ss_tools_in_import_map(self):
        from data_agent.code_exporter import TOOL_IMPORT_MAP
        ss_tools = ["spatial_autocorrelation", "local_moran", "hotspot_analysis"]
        for tool in ss_tools:
            self.assertIn(tool, TOOL_IMPORT_MAP, f"{tool} missing from TOOL_IMPORT_MAP")

    def test_import_statements_valid(self):
        from data_agent.code_exporter import TOOL_IMPORT_MAP
        for tool in ["spatial_autocorrelation", "local_moran", "hotspot_analysis"]:
            imp = TOOL_IMPORT_MAP[tool]
            self.assertIn("from data_agent.spatial_statistics import", imp)


if __name__ == "__main__":
    unittest.main()

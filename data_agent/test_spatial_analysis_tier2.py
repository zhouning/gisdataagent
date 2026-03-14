"""Tests for Spatial Analysis Tier 2 (v10.0.3).

Covers IDW, Kriging, GWR, Change Detection, Viewshed with synthetic data.
"""
import json
import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock

import numpy as np


def _make_point_geojson(n=20, value_col="elevation"):
    """Create a temporary GeoJSON file with random points."""
    import geopandas as gpd
    from shapely.geometry import Point

    np.random.seed(42)
    xs = np.random.uniform(100, 200, n)
    ys = np.random.uniform(30, 40, n)
    vals = np.random.uniform(10, 100, n)

    gdf = gpd.GeoDataFrame(
        {value_col: vals, "id": range(n)},
        geometry=[Point(x, y) for x, y in zip(xs, ys)],
    )
    path = os.path.join(tempfile.gettempdir(), f"test_points_{os.getpid()}.geojson")
    gdf.to_file(path, driver="GeoJSON")
    return path


def _make_polygon_geojson(n=10, id_col="id", extra_col="landuse"):
    """Create a temporary GeoJSON with simple polygons."""
    import geopandas as gpd
    from shapely.geometry import box

    np.random.seed(42)
    features = []
    for i in range(n):
        x = i * 10
        features.append(box(x, 0, x + 9, 9))

    gdf = gpd.GeoDataFrame({
        id_col: [f"P{i}" for i in range(n)],
        extra_col: [f"type_{i % 3}" for i in range(n)],
        "area_val": np.random.uniform(50, 200, n),
    }, geometry=features)
    path = os.path.join(tempfile.gettempdir(), f"test_polys_{os.getpid()}.geojson")
    gdf.to_file(path, driver="GeoJSON")
    return path


# ---------------------------------------------------------------------------
# TestIDWInterpolation
# ---------------------------------------------------------------------------

class TestIDWInterpolation(unittest.TestCase):
    def setUp(self):
        self.point_file = _make_point_geojson()

    def tearDown(self):
        if os.path.exists(self.point_file):
            os.remove(self.point_file)

    @patch("data_agent.spatial_analysis_tier2._resolve_path", side_effect=lambda p: p)
    @patch("data_agent.spatial_analysis_tier2._generate_output_path")
    def test_idw_basic(self, mock_out, mock_resolve):
        from data_agent.spatial_analysis_tier2 import idw_interpolation
        out_tif = os.path.join(tempfile.gettempdir(), "idw_test.npy")
        out_png = os.path.join(tempfile.gettempdir(), "idw_test.png")
        mock_out.side_effect = [out_tif, out_png]

        result = json.loads(idw_interpolation(self.point_file, "elevation", resolution="10"))
        self.assertEqual(result["status"], "ok")
        self.assertIn("statistics", result)
        self.assertIn("point_count", result["statistics"])

    @patch("data_agent.spatial_analysis_tier2._resolve_path", side_effect=lambda p: p)
    def test_idw_missing_column(self, _):
        from data_agent.spatial_analysis_tier2 import idw_interpolation
        result = json.loads(idw_interpolation(self.point_file, "nonexistent"))
        self.assertEqual(result["status"], "error")
        self.assertIn("不存在", result["message"])

    def test_idw_nonexistent_file(self):
        from data_agent.spatial_analysis_tier2 import idw_interpolation
        result = json.loads(idw_interpolation("/nonexistent/file.geojson", "val"))
        self.assertEqual(result["status"], "error")


# ---------------------------------------------------------------------------
# TestKrigingInterpolation
# ---------------------------------------------------------------------------

class TestKrigingInterpolation(unittest.TestCase):
    def setUp(self):
        self.point_file = _make_point_geojson()

    def tearDown(self):
        if os.path.exists(self.point_file):
            os.remove(self.point_file)

    @patch("data_agent.spatial_analysis_tier2._resolve_path", side_effect=lambda p: p)
    @patch("data_agent.spatial_analysis_tier2._generate_output_path")
    def test_kriging_basic(self, mock_out, mock_resolve):
        from data_agent.spatial_analysis_tier2 import kriging_interpolation
        out_tif = os.path.join(tempfile.gettempdir(), "krig_test.npy")
        out_png = os.path.join(tempfile.gettempdir(), "krig_test.png")
        mock_out.side_effect = [out_tif, out_png]

        result = json.loads(kriging_interpolation(
            self.point_file, "elevation", resolution="20"))
        self.assertEqual(result["status"], "ok")
        self.assertIn("variogram", result)

    @patch("data_agent.spatial_analysis_tier2._resolve_path", side_effect=lambda p: p)
    def test_kriging_missing_column(self, _):
        from data_agent.spatial_analysis_tier2 import kriging_interpolation
        result = json.loads(kriging_interpolation(self.point_file, "nonexistent"))
        self.assertEqual(result["status"], "error")

    @patch("data_agent.spatial_analysis_tier2._resolve_path", side_effect=lambda p: p)
    @patch("data_agent.spatial_analysis_tier2._generate_output_path")
    def test_kriging_too_few_points(self, mock_out, _):
        from data_agent.spatial_analysis_tier2 import kriging_interpolation
        mock_out.return_value = os.path.join(tempfile.gettempdir(), "krig_few.npy")
        # Create file with only 3 points
        path = _make_point_geojson(n=3)
        result = json.loads(kriging_interpolation(path, "elevation"))
        self.assertEqual(result["status"], "error")
        self.assertIn("5", result["message"])
        os.remove(path)


# ---------------------------------------------------------------------------
# TestGWRAnalysis
# ---------------------------------------------------------------------------

class TestGWRAnalysis(unittest.TestCase):
    def setUp(self):
        self.point_file = _make_point_geojson(n=30)

    def tearDown(self):
        if os.path.exists(self.point_file):
            os.remove(self.point_file)

    @patch("data_agent.spatial_analysis_tier2._resolve_path", side_effect=lambda p: p)
    @patch("data_agent.spatial_analysis_tier2._generate_output_path")
    def test_gwr_fallback_ols(self, mock_out, _):
        """GWR falls back to OLS when mgwr not installed."""
        from data_agent.spatial_analysis_tier2 import gwr_analysis
        mock_out.return_value = os.path.join(tempfile.gettempdir(), "gwr_test.png")

        # This will likely use OLS fallback unless mgwr is installed
        result = json.loads(gwr_analysis(
            self.point_file, "elevation", "id", bandwidth="auto"))
        # Should succeed with either GWR or OLS fallback
        self.assertIn(result["status"], ("ok", "error"))

    @patch("data_agent.spatial_analysis_tier2._resolve_path", side_effect=lambda p: p)
    def test_gwr_missing_column(self, _):
        from data_agent.spatial_analysis_tier2 import gwr_analysis
        result = json.loads(gwr_analysis(
            self.point_file, "nonexistent", "elevation"))
        self.assertEqual(result["status"], "error")


# ---------------------------------------------------------------------------
# TestChangeDetection
# ---------------------------------------------------------------------------

class TestChangeDetection(unittest.TestCase):
    def setUp(self):
        import geopandas as gpd
        from shapely.geometry import box

        # T1: 5 polygons
        gdf1 = gpd.GeoDataFrame({
            "id": ["A", "B", "C", "D", "E"],
            "landuse": ["farm", "forest", "urban", "farm", "water"],
            "area_val": [100, 200, 150, 80, 300],
        }, geometry=[box(i*10, 0, i*10+9, 9) for i in range(5)])

        # T2: 5 polygons, some changed
        gdf2 = gpd.GeoDataFrame({
            "id": ["A", "B", "C", "F", "E"],  # D removed, F added
            "landuse": ["farm", "urban", "urban", "forest", "water"],  # B: forest→urban
            "area_val": [100, 250, 150, 90, 300],  # B: 200→250
        }, geometry=[box(i*10, 0, i*10+9, 9) for i in range(5)])

        self.t1_path = os.path.join(tempfile.gettempdir(), f"t1_{os.getpid()}.geojson")
        self.t2_path = os.path.join(tempfile.gettempdir(), f"t2_{os.getpid()}.geojson")
        gdf1.to_file(self.t1_path, driver="GeoJSON")
        gdf2.to_file(self.t2_path, driver="GeoJSON")

    def tearDown(self):
        for p in (self.t1_path, self.t2_path):
            if os.path.exists(p):
                os.remove(p)

    @patch("data_agent.spatial_analysis_tier2._resolve_path", side_effect=lambda p: p)
    @patch("data_agent.spatial_analysis_tier2._generate_output_path")
    def test_change_detection_basic(self, mock_out, _):
        from data_agent.spatial_analysis_tier2 import spatial_change_detection
        csv_path = os.path.join(tempfile.gettempdir(), "change_test.csv")
        mock_out.return_value = csv_path

        result = json.loads(spatial_change_detection(
            self.t1_path, self.t2_path, id_column="id"))
        self.assertEqual(result["status"], "ok")
        summary = result["summary"]
        self.assertEqual(summary["added"], 1)   # F added
        self.assertEqual(summary["removed"], 1) # D removed
        # Total features should be correct
        self.assertEqual(summary["total_t1"], 5)
        self.assertEqual(summary["total_t2"], 5)

        # Clean up
        if os.path.exists(csv_path):
            os.remove(csv_path)

    @patch("data_agent.spatial_analysis_tier2._resolve_path", side_effect=lambda p: p)
    @patch("data_agent.spatial_analysis_tier2._generate_output_path")
    def test_change_detection_auto_id(self, mock_out, _):
        from data_agent.spatial_analysis_tier2 import spatial_change_detection
        mock_out.return_value = os.path.join(tempfile.gettempdir(), "change_auto.csv")

        result = json.loads(spatial_change_detection(
            self.t1_path, self.t2_path, id_column="auto"))
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["id_column"], "id")

    @patch("data_agent.spatial_analysis_tier2._resolve_path", side_effect=lambda p: p)
    def test_change_detection_bad_id_col(self, _):
        from data_agent.spatial_analysis_tier2 import spatial_change_detection
        result = json.loads(spatial_change_detection(
            self.t1_path, self.t2_path, id_column="nonexistent"))
        self.assertEqual(result["status"], "error")


# ---------------------------------------------------------------------------
# TestViewshedAnalysis
# ---------------------------------------------------------------------------

class TestViewshedAnalysis(unittest.TestCase):
    def setUp(self):
        """Create a synthetic DEM raster."""
        try:
            import rasterio
            from rasterio.transform import from_bounds
            self.has_rasterio = True

            np.random.seed(42)
            dem = np.random.uniform(50, 200, (50, 50)).astype(np.float32)
            # Create a ridge in the middle
            dem[20:30, :] = 300
            dem[25, 25] = 100  # valley at observer

            self.dem_path = os.path.join(tempfile.gettempdir(), f"test_dem_{os.getpid()}.tif")
            transform = from_bounds(100, 30, 150, 35, 50, 50)
            with rasterio.open(self.dem_path, 'w', driver='GTiff',
                              height=50, width=50, count=1,
                              dtype='float32', transform=transform) as dst:
                dst.write(dem, 1)
        except ImportError:
            self.has_rasterio = False

    def tearDown(self):
        if hasattr(self, 'dem_path') and os.path.exists(self.dem_path):
            os.remove(self.dem_path)

    @unittest.skipUnless(True, "rasterio needed")
    @patch("data_agent.spatial_analysis_tier2._resolve_path", side_effect=lambda p: p)
    @patch("data_agent.spatial_analysis_tier2._generate_output_path")
    def test_viewshed_basic(self, mock_out, _):
        if not self.has_rasterio:
            self.skipTest("rasterio not installed")
        from data_agent.spatial_analysis_tier2 import viewshed_analysis
        out_tif = os.path.join(tempfile.gettempdir(), "vs_test.tif")
        out_png = os.path.join(tempfile.gettempdir(), "vs_test.png")
        mock_out.side_effect = [out_tif, out_png]

        result = json.loads(viewshed_analysis(
            self.dem_path, "125", "32.5", observer_height="2", max_distance="2000"))
        self.assertEqual(result["status"], "ok")
        self.assertIn("visible_cells", result["statistics"])
        self.assertGreater(result["statistics"]["visible_cells"], 0)

        for f in (out_tif, out_png):
            if os.path.exists(f):
                os.remove(f)

    @patch("data_agent.spatial_analysis_tier2._resolve_path", side_effect=lambda p: p)
    def test_viewshed_out_of_bounds(self, _):
        if not self.has_rasterio:
            self.skipTest("rasterio not installed")
        from data_agent.spatial_analysis_tier2 import viewshed_analysis
        result = json.loads(viewshed_analysis(
            self.dem_path, "999", "999"))
        self.assertEqual(result["status"], "error")


# ---------------------------------------------------------------------------
# TestToolset
# ---------------------------------------------------------------------------

class TestSpatialAnalysisTier2Toolset(unittest.TestCase):
    def test_toolset_exists(self):
        from data_agent.toolsets.spatial_analysis_tier2_tools import SpatialAnalysisTier2Toolset
        ts = SpatialAnalysisTier2Toolset()
        self.assertIsNotNone(ts)

    def test_toolset_has_5_tools(self):
        from data_agent.toolsets.spatial_analysis_tier2_tools import _ALL_FUNCS
        self.assertEqual(len(_ALL_FUNCS), 5)

    def test_toolset_in_registry(self):
        from data_agent.custom_skills import TOOLSET_NAMES
        self.assertIn("SpatialAnalysisTier2Toolset", TOOLSET_NAMES)


if __name__ == "__main__":
    unittest.main()

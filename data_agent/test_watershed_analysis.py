"""Tests for Watershed Analysis (v12.1).

Covers DEM preprocessing, flow accumulation, stream extraction,
watershed delineation with synthetic DEM data.
"""
import json
import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock

import numpy as np


def _make_synthetic_dem(rows=100, cols=100):
    """Create a synthetic DEM with a valley for testing.

    The DEM has a gradient sloping from NW corner (high) to SE corner (low)
    with a valley channel running diagonally.
    """
    y, x = np.mgrid[0:rows, 0:cols]
    # Base slope: high NW, low SE
    dem = (rows - y) * 2.0 + (cols - x) * 2.0
    # Add valley channel (diagonal)
    channel_mask = np.abs(y - x) < 3
    dem[channel_mask] -= 20
    # Add some noise
    np.random.seed(42)
    dem += np.random.normal(0, 0.5, dem.shape)
    return dem.astype(np.float32)


def _save_synthetic_dem(dem, path):
    """Save synthetic DEM as GeoTIFF."""
    import rasterio
    from rasterio.transform import from_bounds
    transform = from_bounds(100.0, 30.0, 101.0, 31.0, dem.shape[1], dem.shape[0])
    with rasterio.open(path, 'w', driver='GTiff', height=dem.shape[0],
                      width=dem.shape[1], count=1, dtype='float32',
                      transform=transform, crs='EPSG:4326') as dst:
        dst.write(dem, 1)


class TestWatershedConstants(unittest.TestCase):
    def test_module_imports(self):
        from data_agent.watershed_analysis import (
            extract_watershed, extract_stream_network, compute_flow_accumulation
        )
        self.assertTrue(callable(extract_watershed))
        self.assertTrue(callable(extract_stream_network))
        self.assertTrue(callable(compute_flow_accumulation))


class TestExtractWatershed(unittest.TestCase):
    def setUp(self):
        self.dem_path = os.path.join(tempfile.gettempdir(), f"test_dem_ws_{os.getpid()}.tif")
        try:
            dem = _make_synthetic_dem()
            _save_synthetic_dem(dem, self.dem_path)
            self.has_rasterio = True
        except ImportError:
            self.has_rasterio = False

    def tearDown(self):
        if os.path.exists(self.dem_path):
            os.remove(self.dem_path)

    @patch("data_agent.watershed_analysis._resolve_path", side_effect=lambda p: p)
    @patch("data_agent.watershed_analysis._generate_output_path")
    def test_extract_watershed_auto_pour_point(self, mock_out, _):
        if not self.has_rasterio:
            self.skipTest("rasterio not installed")
        from data_agent.watershed_analysis import extract_watershed

        # Generate unique output paths
        outputs = [os.path.join(tempfile.gettempdir(), f"ws_out_{i}_{os.getpid()}.tmp") for i in range(4)]
        mock_out.side_effect = outputs

        result = json.loads(extract_watershed(self.dem_path, threshold="50"))
        self.assertEqual(result["status"], "ok")
        self.assertIn("statistics", result)
        self.assertIn("pour_point", result["statistics"])
        self.assertGreater(result["statistics"]["watershed_cells"], 0)

        # Clean up
        for f in outputs:
            if os.path.exists(f):
                os.remove(f)

    def test_nonexistent_dem(self):
        from data_agent.watershed_analysis import extract_watershed
        result = json.loads(extract_watershed("/nonexistent/dem.tif"))
        self.assertEqual(result["status"], "error")

    def test_auto_dem_no_boundary(self):
        from data_agent.watershed_analysis import extract_watershed
        result = json.loads(extract_watershed("auto"))
        self.assertEqual(result["status"], "error")
        self.assertIn("boundary_path", result["message"])


class TestExtractStreamNetwork(unittest.TestCase):
    def setUp(self):
        self.dem_path = os.path.join(tempfile.gettempdir(), f"test_dem_sn_{os.getpid()}.tif")
        try:
            dem = _make_synthetic_dem()
            _save_synthetic_dem(dem, self.dem_path)
            self.has_rasterio = True
        except ImportError:
            self.has_rasterio = False

    def tearDown(self):
        if os.path.exists(self.dem_path):
            os.remove(self.dem_path)

    @patch("data_agent.watershed_analysis._resolve_path", side_effect=lambda p: p)
    @patch("data_agent.watershed_analysis._generate_output_path")
    def test_stream_extraction(self, mock_out, _):
        if not self.has_rasterio:
            self.skipTest("rasterio not installed")
        from data_agent.watershed_analysis import extract_stream_network

        out_path = os.path.join(tempfile.gettempdir(), f"stream_{os.getpid()}.geojson")
        mock_out.return_value = out_path

        result = json.loads(extract_stream_network(self.dem_path, threshold="50"))
        self.assertEqual(result["status"], "ok")
        self.assertGreater(result["stream_cells"], 0)

        if os.path.exists(out_path):
            os.remove(out_path)

    def test_nonexistent_file(self):
        from data_agent.watershed_analysis import extract_stream_network
        result = json.loads(extract_stream_network("/nonexistent.tif"))
        self.assertEqual(result["status"], "error")


class TestComputeFlowAccumulation(unittest.TestCase):
    def setUp(self):
        self.dem_path = os.path.join(tempfile.gettempdir(), f"test_dem_fa_{os.getpid()}.tif")
        try:
            dem = _make_synthetic_dem(50, 50)
            _save_synthetic_dem(dem, self.dem_path)
            self.has_rasterio = True
        except ImportError:
            self.has_rasterio = False

    def tearDown(self):
        if os.path.exists(self.dem_path):
            os.remove(self.dem_path)

    @patch("data_agent.watershed_analysis._resolve_path", side_effect=lambda p: p)
    @patch("data_agent.watershed_analysis._generate_output_path")
    def test_flow_accumulation(self, mock_out, _):
        if not self.has_rasterio:
            self.skipTest("rasterio not installed")
        from data_agent.watershed_analysis import compute_flow_accumulation

        outputs = [os.path.join(tempfile.gettempdir(), f"fa_{i}_{os.getpid()}.tmp") for i in range(2)]
        mock_out.side_effect = outputs

        result = json.loads(compute_flow_accumulation(self.dem_path))
        self.assertEqual(result["status"], "ok")
        self.assertIn("statistics", result)
        self.assertGreater(result["statistics"]["max_accumulation"], 0)

        for f in outputs:
            if os.path.exists(f):
                os.remove(f)


class TestWatershedToolset(unittest.TestCase):
    def test_toolset_exists(self):
        from data_agent.toolsets.watershed_tools import WatershedToolset
        ts = WatershedToolset()
        self.assertIsNotNone(ts)

    def test_toolset_has_3_tools(self):
        from data_agent.toolsets.watershed_tools import _ALL_FUNCS
        self.assertEqual(len(_ALL_FUNCS), 3)

    def test_toolset_in_registry(self):
        from data_agent.custom_skills import TOOLSET_NAMES
        self.assertIn("WatershedToolset", TOOLSET_NAMES)

    def test_hydrology_domain_includes_watershed(self):
        from data_agent.agent_composer import _DOMAIN_TOOLSETS
        self.assertIn("WatershedToolset", _DOMAIN_TOOLSETS["hydrology"])


class TestPreprocessing(unittest.TestCase):
    def test_find_pour_point(self):
        from data_agent.watershed_analysis import _find_pour_point
        # Create a mock grid with affine transform
        mock_grid = MagicMock()
        mock_grid.affine = (0.01, 0, 100.0, 0, -0.01, 31.0)

        acc = np.zeros((10, 10), dtype=np.float32)
        acc[5, 7] = 1000  # max accumulation at row=5, col=7

        x, y = _find_pour_point(mock_grid, acc, None)
        # Expected: x = 100.0 + 7*0.01 + 0.005 = 100.075
        # Expected: y = 31.0 + 5*(-0.01) + (-0.005) = 30.945
        self.assertAlmostEqual(x, 100.075, places=3)
        self.assertAlmostEqual(y, 30.945, places=3)


if __name__ == "__main__":
    unittest.main()

"""Tests for remote sensing tools (remote_sensing.py)."""
import ast
import csv
import json
import os
import sys
import tempfile
import unittest

import numpy as np
import rasterio
from rasterio.transform import from_bounds

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_agent.remote_sensing import (
    describe_raster,
    calculate_ndvi,
    raster_band_math,
    classify_raster,
    visualize_raster,
)


def _create_synthetic_raster(path, width=20, height=20, count=1, dtype="float32",
                              nodata=None, data=None):
    """Helper to create a synthetic GeoTIFF for testing."""
    transform = from_bounds(116.0, 39.0, 117.0, 40.0, width, height)
    profile = {
        "driver": "GTiff",
        "width": width,
        "height": height,
        "count": count,
        "dtype": dtype,
        "crs": "EPSG:4326",
        "transform": transform,
    }
    if nodata is not None:
        profile["nodata"] = nodata
    with rasterio.open(path, "w", **profile) as dst:
        if data is not None:
            if count == 1 and data.ndim == 2:
                dst.write(data, 1)
            else:
                for i in range(count):
                    dst.write(data[i], i + 1)
        else:
            for i in range(1, count + 1):
                band = np.random.rand(height, width).astype(dtype) * 100
                dst.write(band, i)


class TestDescribeRaster(unittest.TestCase):
    """Test describe_raster function."""

    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp()
        cls.single_band = os.path.join(cls.tmpdir, "single.tif")
        _create_synthetic_raster(cls.single_band, count=1)
        cls.multi_band = os.path.join(cls.tmpdir, "multi.tif")
        _create_synthetic_raster(cls.multi_band, count=4)

    def test_single_band(self):
        result = describe_raster(self.single_band)
        data = json.loads(result)
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["crs"], "EPSG:4326")
        self.assertEqual(len(data["bands"]), 1)
        self.assertIn("min", data["bands"][0])
        self.assertIn("p50", data["bands"][0])

    def test_multi_band(self):
        result = describe_raster(self.multi_band)
        data = json.loads(result)
        self.assertEqual(data["count"], 4)
        self.assertEqual(len(data["bands"]), 4)
        for band in data["bands"]:
            self.assertGreater(band["valid_pixels"], 0)

    def test_invalid_file(self):
        result = describe_raster("nonexistent_file.tif")
        self.assertIn("Error", result)


class TestCalculateNDVI(unittest.TestCase):
    """Test calculate_ndvi function."""

    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp()
        cls.raster_4band = os.path.join(cls.tmpdir, "landsat.tif")
        # Create 4-band raster: band3=red, band4=NIR
        data = np.zeros((4, 20, 20), dtype=np.float32)
        data[0] = 50  # blue
        data[1] = 60  # green
        data[2] = 30  # red (low reflectance in vegetation)
        data[3] = 80  # NIR (high reflectance in vegetation)
        _create_synthetic_raster(cls.raster_4band, count=4, data=data)

        cls.single_band = os.path.join(cls.tmpdir, "dem.tif")
        _create_synthetic_raster(cls.single_band, count=1)

    def test_ndvi_normal(self):
        result = calculate_ndvi(self.raster_4band)
        self.assertNotIn("Error", result)
        # Should produce a .tif file path
        lines = result.strip().split("\n")
        self.assertTrue(lines[0].endswith(".tif"))
        self.assertIn("NDVI", lines[1])
        # Check output file exists and has valid data
        with rasterio.open(lines[0]) as src:
            ndvi = src.read(1)
            valid = ndvi[ndvi != -9999.0]
            # With red=30, NIR=80: NDVI = (80-30)/(80+30) ≈ 0.4545
            self.assertAlmostEqual(float(np.mean(valid)), 0.4545, places=2)

    def test_custom_bands(self):
        result = calculate_ndvi(self.raster_4band, red_band=1, nir_band=2)
        self.assertNotIn("Error", result)
        lines = result.strip().split("\n")
        self.assertTrue(lines[0].endswith(".tif"))

    def test_single_band_error(self):
        result = calculate_ndvi(self.single_band, red_band=3, nir_band=4)
        self.assertIn("Error", result)
        self.assertIn("1 band", result)


class TestRasterBandMath(unittest.TestCase):
    """Test raster_band_math function."""

    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp()
        cls.raster = os.path.join(cls.tmpdir, "test_math.tif")
        data = np.zeros((3, 20, 20), dtype=np.float32)
        data[0] = 10.0
        data[1] = 20.0
        data[2] = 30.0
        _create_synthetic_raster(cls.raster, count=3, data=data)

    def test_simple_expression(self):
        result = raster_band_math(self.raster, "b1 + b2")
        self.assertNotIn("Error", result)
        self.assertTrue(result.endswith(".tif"))
        with rasterio.open(result) as src:
            out = src.read(1)
            np.testing.assert_allclose(out, 30.0, atol=0.01)

    def test_numpy_expression(self):
        result = raster_band_math(self.raster, "np.sqrt(b1**2 + b2**2)")
        self.assertNotIn("Error", result)
        with rasterio.open(result) as src:
            out = src.read(1)
            expected = np.sqrt(10.0**2 + 20.0**2)
            np.testing.assert_allclose(out, expected, atol=0.01)

    def test_unsafe_expression_rejected(self):
        result = raster_band_math(self.raster, "import os; b1")
        self.assertIn("Error", result)
        self.assertIn("forbidden", result)

    def test_os_access_rejected(self):
        result = raster_band_math(self.raster, "os.system('ls')")
        self.assertIn("Error", result)


class TestClassifyRaster(unittest.TestCase):
    """Test classify_raster function."""

    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp()
        cls.raster = os.path.join(cls.tmpdir, "classify_test.tif")
        # Create raster with distinct clusters
        data = np.zeros((3, 40, 40), dtype=np.float32)
        data[:, :20, :20] = 10  # cluster 1
        data[:, :20, 20:] = 50  # cluster 2
        data[:, 20:, :20] = 90  # cluster 3
        data[:, 20:, 20:] = 130  # cluster 4
        # Add some noise
        data += np.random.randn(3, 40, 40).astype(np.float32) * 2
        _create_synthetic_raster(cls.raster, width=40, height=40, count=3, data=data)

    def test_kmeans_default(self):
        result = classify_raster(self.raster, n_classes=4)
        self.assertNotIn("Error", result)
        self.assertIn("分类完成", result)
        # Check output files
        lines = result.strip().split("\n")
        tif_path = lines[0].split(": ")[1]
        csv_path = lines[1].split(": ")[1]
        self.assertTrue(os.path.exists(tif_path))
        self.assertTrue(os.path.exists(csv_path))
        # Check classified raster
        with rasterio.open(tif_path) as src:
            cls_data = src.read(1)
            unique = np.unique(cls_data[cls_data > 0])
            self.assertEqual(len(unique), 4)

    def test_mini_batch(self):
        result = classify_raster(self.raster, n_classes=3, method="mini_batch")
        self.assertNotIn("Error", result)
        self.assertIn("分类完成", result)

    def test_band_selection(self):
        result = classify_raster(self.raster, n_classes=3, band_indices="1,2")
        self.assertNotIn("Error", result)
        self.assertIn("分类完成", result)

    def test_invalid_band(self):
        result = classify_raster(self.raster, band_indices="1,2,5")
        self.assertIn("Error", result)
        self.assertIn("out of range", result)


class TestVisualizeRaster(unittest.TestCase):
    """Test visualize_raster function."""

    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp()
        cls.single = os.path.join(cls.tmpdir, "viz_single.tif")
        _create_synthetic_raster(cls.single, count=1)
        cls.rgb = os.path.join(cls.tmpdir, "viz_rgb.tif")
        _create_synthetic_raster(cls.rgb, count=3)

    def test_single_band(self):
        result = visualize_raster(self.single, band=1)
        self.assertNotIn("Error", result)
        self.assertTrue(result.endswith(".png"))
        self.assertTrue(os.path.exists(result))

    def test_rgb_composite(self):
        result = visualize_raster(self.rgb, band=0)
        self.assertNotIn("Error", result)
        self.assertTrue(result.endswith(".png"))

    def test_custom_colormap(self):
        result = visualize_raster(self.single, band=1, colormap="terrain")
        self.assertNotIn("Error", result)
        self.assertTrue(result.endswith(".png"))

    def test_band_out_of_range(self):
        result = visualize_raster(self.single, band=5)
        self.assertIn("Error", result)


class TestRemoteSensingToolset(unittest.TestCase):
    """Test the RemoteSensingToolset class."""

    def _run(self, coro):
        import asyncio
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_tool_count(self):
        from data_agent.toolsets.remote_sensing_tools import RemoteSensingToolset
        ts = RemoteSensingToolset()
        tools = self._run(ts.get_tools())
        self.assertEqual(len(tools), 5)

    def test_tool_names(self):
        from data_agent.toolsets.remote_sensing_tools import RemoteSensingToolset
        ts = RemoteSensingToolset()
        tools = self._run(ts.get_tools())
        names = {t.name for t in tools}
        self.assertEqual(names, {
            "describe_raster", "calculate_ndvi", "raster_band_math",
            "classify_raster", "visualize_raster",
        })

    def test_filter(self):
        from data_agent.toolsets.remote_sensing_tools import RemoteSensingToolset
        ts = RemoteSensingToolset(tool_filter=["describe_raster"])
        tools = self._run(ts.get_tools())
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0].name, "describe_raster")


class TestToolImportMapEntries(unittest.TestCase):
    """Verify code_exporter has entries for all remote sensing tools."""

    def test_all_rs_tools_in_import_map(self):
        from data_agent.code_exporter import TOOL_IMPORT_MAP
        rs_tools = [
            "describe_raster", "calculate_ndvi", "raster_band_math",
            "classify_raster", "visualize_raster",
        ]
        for tool in rs_tools:
            self.assertIn(tool, TOOL_IMPORT_MAP, f"{tool} missing from TOOL_IMPORT_MAP")

    def test_import_statements_valid(self):
        from data_agent.code_exporter import TOOL_IMPORT_MAP
        for tool in ["describe_raster", "calculate_ndvi", "raster_band_math",
                      "classify_raster", "visualize_raster"]:
            imp = TOOL_IMPORT_MAP[tool]
            self.assertIn("from data_agent.remote_sensing import", imp)


if __name__ == "__main__":
    unittest.main()

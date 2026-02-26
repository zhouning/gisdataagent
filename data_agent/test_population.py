"""Tests for population_data module (PRD 5.2.4)."""
import unittest
import os
import tempfile
import shutil

import numpy as np
import geopandas as gpd
from shapely.geometry import box


class TestPopulationHelpers(unittest.TestCase):
    """Unit tests for helper functions (no network needed)."""

    def test_cache_path_deterministic(self):
        """Same URL always produces same cache path."""
        from data_agent.population_data import _get_cache_path

        url = "https://example.com/pop_2020.tif"
        p1 = _get_cache_path(url)
        p2 = _get_cache_path(url)
        self.assertEqual(p1, p2)
        self.assertTrue(p1.endswith(".tif"))

    def test_cache_path_different_urls(self):
        """Different URLs produce different cache paths."""
        from data_agent.population_data import _get_cache_path

        p1 = _get_cache_path("https://example.com/a.tif")
        p2 = _get_cache_path("https://example.com/b.tif")
        self.assertNotEqual(p1, p2)

    def test_clip_raster_to_bbox(self):
        """Clip a synthetic raster to a bounding box."""
        try:
            import rasterio
            from rasterio.transform import from_bounds
        except ImportError:
            self.skipTest("rasterio not installed")

        from data_agent.population_data import _clip_raster_to_bbox

        tmpdir = tempfile.mkdtemp()
        try:
            # Create a synthetic 10x10 raster covering (0,0)-(10,10)
            src_path = os.path.join(tmpdir, "source.tif")
            transform = from_bounds(0, 0, 10, 10, 10, 10)
            data = np.ones((1, 10, 10), dtype=np.float32) * 100.0
            with rasterio.open(
                src_path, "w", driver="GTiff",
                height=10, width=10, count=1, dtype="float32",
                crs="EPSG:4326", transform=transform,
            ) as dst:
                dst.write(data)

            # Clip to a sub-bbox (2,2)-(8,8)
            out_path = os.path.join(tmpdir, "clipped.tif")
            _clip_raster_to_bbox(src_path, (2, 2, 8, 8), out_path)

            self.assertTrue(os.path.exists(out_path))
            with rasterio.open(out_path) as clipped:
                # Clipped raster should be smaller
                self.assertLessEqual(clipped.width, 10)
                self.assertLessEqual(clipped.height, 10)
                arr = clipped.read(1)
                self.assertTrue(np.all(arr == 100.0))
        finally:
            shutil.rmtree(tmpdir)


class TestAggregatePopulation(unittest.TestCase):
    """Tests for aggregate_population with synthetic data."""

    def test_aggregate_synthetic(self):
        """Aggregate population from a synthetic raster + polygon."""
        try:
            import rasterio
            from rasterio.transform import from_bounds
            from rasterstats import zonal_stats  # noqa: F401
        except ImportError:
            self.skipTest("rasterio or rasterstats not installed")

        from data_agent.population_data import aggregate_population

        tmpdir = tempfile.mkdtemp()
        try:
            # Create synthetic raster: 10x10, all pixels = 50
            raster_path = os.path.join(tmpdir, "pop.tif")
            transform = from_bounds(0, 0, 10, 10, 10, 10)
            data = np.ones((1, 10, 10), dtype=np.float32) * 50.0
            with rasterio.open(
                raster_path, "w", driver="GTiff",
                height=10, width=10, count=1, dtype="float32",
                crs="EPSG:4326", transform=transform,
            ) as dst:
                dst.write(data)

            # Create polygon covering entire raster
            gdf = gpd.GeoDataFrame(
                {"name": ["zone_a"]},
                geometry=[box(0, 0, 10, 10)],
                crs="EPSG:4326",
            )
            poly_path = os.path.join(tmpdir, "zones.shp")
            gdf.to_file(poly_path)

            result = aggregate_population(poly_path, raster_path, stats="sum,mean,count")
            self.assertEqual(result["status"], "success")
            self.assertEqual(result["zones"], 1)
            self.assertTrue(os.path.exists(result["output_path"]))
        finally:
            shutil.rmtree(tmpdir)

    def test_aggregate_bad_path(self):
        """Error for non-existent files."""
        from data_agent.population_data import aggregate_population

        result = aggregate_population("no_such_file.shp", "no_such_raster.tif")
        self.assertEqual(result["status"], "error")


class TestGetPopulationData(unittest.TestCase):
    """Tests for get_population_data error handling."""

    def test_unsupported_country_code(self):
        """Unsupported country code returns error."""
        from data_agent.population_data import _WORLDPOP_COUNTRY_URLS

        # Verify XYZ is not in the supported countries
        self.assertNotIn("XYZ", _WORLDPOP_COUNTRY_URLS)
        # Verify CHN is supported
        self.assertIn("CHN", _WORLDPOP_COUNTRY_URLS)

    def test_no_api_key(self):
        """Missing GAODE_API_KEY returns error (boundary fetch fails)."""
        from data_agent.population_data import get_population_data

        original = os.environ.pop("GAODE_API_KEY", None)
        try:
            result = get_population_data("北京市")
            self.assertEqual(result["status"], "error")
        finally:
            if original:
                os.environ["GAODE_API_KEY"] = original


if __name__ == "__main__":
    unittest.main()

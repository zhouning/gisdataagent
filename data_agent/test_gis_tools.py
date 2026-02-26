"""
Tests for 5 open-source GIS tools (ArcPy alternatives):
- polygon_neighbors
- add_field
- add_join
- calculate_field
- summary_statistics
"""
import unittest
import os
import tempfile
import shutil
import geopandas as gpd
import pandas as pd
from shapely.geometry import Polygon, Point
from unittest.mock import patch


class GISToolsTestBase(unittest.TestCase):
    """Base class that creates temp dir and patches path helpers."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        # Patch _generate_output_path to write into tmpdir
        self._patch_out = patch(
            'data_agent.gis_processors._generate_output_path',
            side_effect=lambda prefix, ext: os.path.join(
                self.tmpdir, f"{prefix}_test.{ext}"
            )
        )
        self._patch_resolve = patch(
            'data_agent.gis_processors._resolve_path',
            side_effect=lambda p: p
        )
        self._patch_out.start()
        self._patch_resolve.start()

    def tearDown(self):
        self._patch_out.stop()
        self._patch_resolve.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _create_polygon_shp(self, name="polys.shp"):
        """Create a simple 2x1 grid of adjacent polygons."""
        polys = [
            Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]),
            Polygon([(1, 0), (2, 0), (2, 1), (1, 1)]),
        ]
        gdf = gpd.GeoDataFrame(
            {"id": [1, 2], "area_val": [100.0, 200.0], "name": ["A", "B"]},
            geometry=polys, crs="EPSG:3857"
        )
        path = os.path.join(self.tmpdir, name)
        gdf.to_file(path, encoding='utf-8')
        return path

    def _create_point_shp(self, name="points.shp"):
        """Create simple point data."""
        gdf = gpd.GeoDataFrame(
            {"id": [1, 2, 3], "value": [10, 20, 30], "category": ["X", "X", "Y"]},
            geometry=[Point(0, 0), Point(1, 1), Point(2, 2)],
            crs="EPSG:4326"
        )
        path = os.path.join(self.tmpdir, name)
        gdf.to_file(path, encoding='utf-8')
        return path


class TestPolygonNeighbors(GISToolsTestBase):

    def test_adjacent_polygons_detected(self):
        from data_agent.gis_processors import polygon_neighbors
        shp = self._create_polygon_shp()
        result = polygon_neighbors(shp)
        self.assertTrue(result.endswith('.csv'))
        df = pd.read_csv(result)
        self.assertEqual(len(df), 1)  # One pair of neighbors
        self.assertEqual(df.iloc[0]['src_FID'], 0)
        self.assertEqual(df.iloc[0]['nbr_FID'], 1)
        self.assertGreater(df.iloc[0]['LENGTH'], 0)

    def test_non_adjacent_polygons(self):
        """Separated polygons should produce empty result."""
        from data_agent.gis_processors import polygon_neighbors
        polys = [
            Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]),
            Polygon([(5, 5), (6, 5), (6, 6), (5, 6)]),
        ]
        gdf = gpd.GeoDataFrame(
            {"id": [1, 2]}, geometry=polys, crs="EPSG:3857"
        )
        path = os.path.join(self.tmpdir, "separated.shp")
        gdf.to_file(path, encoding='utf-8')
        result = polygon_neighbors(path)
        df = pd.read_csv(result)
        self.assertEqual(len(df), 0)

    def test_empty_data(self):
        from data_agent.gis_processors import polygon_neighbors
        gdf = gpd.GeoDataFrame(
            {"id": []}, geometry=[], crs="EPSG:3857"
        )
        path = os.path.join(self.tmpdir, "empty.shp")
        gdf.to_file(path, encoding='utf-8')
        result = polygon_neighbors(path)
        self.assertIn("空", result)  # "数据为空"


class TestAddField(GISToolsTestBase):

    def test_add_text_field(self):
        from data_agent.gis_processors import add_field
        shp = self._create_polygon_shp()
        result = add_field(shp, "status", "TEXT", "active")
        self.assertTrue(result.endswith('.shp'))
        gdf = gpd.read_file(result)
        self.assertIn("status", gdf.columns)
        self.assertTrue(all(gdf["status"] == "active"))

    def test_add_float_field(self):
        from data_agent.gis_processors import add_field
        shp = self._create_polygon_shp()
        result = add_field(shp, "score", "FLOAT", "3.14")
        gdf = gpd.read_file(result)
        self.assertIn("score", gdf.columns)
        self.assertAlmostEqual(gdf["score"].iloc[0], 3.14, places=1)

    def test_add_field_no_default(self):
        from data_agent.gis_processors import add_field
        shp = self._create_polygon_shp()
        result = add_field(shp, "notes", "TEXT")
        gdf = gpd.read_file(result)
        self.assertIn("notes", gdf.columns)
        self.assertTrue(gdf["notes"].isna().all())


class TestAddJoin(GISToolsTestBase):

    def test_join_csv(self):
        from data_agent.gis_processors import add_join
        shp = self._create_polygon_shp()
        csv_path = os.path.join(self.tmpdir, "lookup.csv")
        pd.DataFrame({
            "id": [1, 2],
            "label": ["Alpha", "Beta"]
        }).to_csv(csv_path, index=False)
        result = add_join(shp, csv_path, "id", "id")
        self.assertTrue(result.endswith('.shp'))
        gdf = gpd.read_file(result)
        self.assertIn("label", gdf.columns)
        self.assertEqual(gdf.loc[gdf["id"] == 1, "label"].iloc[0], "Alpha")

    def test_join_shp_to_shp(self):
        from data_agent.gis_processors import add_join
        target = self._create_polygon_shp("target.shp")
        # Create join shapefile
        join_gdf = gpd.GeoDataFrame(
            {"id": [1, 2], "extra": ["X", "Y"]},
            geometry=[Point(0, 0), Point(1, 1)], crs="EPSG:3857"
        )
        join_path = os.path.join(self.tmpdir, "join_data.shp")
        join_gdf.to_file(join_path, encoding='utf-8')
        result = add_join(target, join_path, "id", "id")
        gdf = gpd.read_file(result)
        self.assertIn("extra", gdf.columns)

    def test_join_no_match(self):
        from data_agent.gis_processors import add_join
        shp = self._create_polygon_shp()
        csv_path = os.path.join(self.tmpdir, "nomatch.csv")
        pd.DataFrame({"fid": [99], "val": ["Z"]}).to_csv(csv_path, index=False)
        result = add_join(shp, csv_path, "id", "fid")
        gdf = gpd.read_file(result)
        self.assertIn("val", gdf.columns)
        self.assertTrue(gdf["val"].isna().all())


class TestCalculateField(GISToolsTestBase):

    def test_arithmetic_expression(self):
        from data_agent.gis_processors import calculate_field
        shp = self._create_polygon_shp()
        result = calculate_field(shp, "area_ha", "!area_val! * 0.0001")
        gdf = gpd.read_file(result)
        self.assertIn("area_ha", gdf.columns)
        self.assertAlmostEqual(gdf["area_ha"].iloc[0], 0.01, places=4)
        self.assertAlmostEqual(gdf["area_ha"].iloc[1], 0.02, places=4)

    def test_field_addition(self):
        from data_agent.gis_processors import calculate_field
        shp = self._create_polygon_shp()
        result = calculate_field(shp, "doubled", "!area_val! + !area_val!")
        gdf = gpd.read_file(result)
        self.assertAlmostEqual(gdf["doubled"].iloc[0], 200.0, places=1)

    def test_invalid_expression(self):
        from data_agent.gis_processors import calculate_field
        shp = self._create_polygon_shp()
        result = calculate_field(shp, "bad", "!nonexistent_col! + 1")
        self.assertIn("失败", result)


class TestSummaryStatistics(GISToolsTestBase):

    def test_basic_stats(self):
        from data_agent.gis_processors import summary_statistics
        shp = self._create_point_shp()
        result = summary_statistics(shp, "value SUM;value MEAN;value COUNT")
        self.assertTrue(result.endswith('.csv'))
        df = pd.read_csv(result)
        self.assertEqual(df['value_SUM'].iloc[0], 60)
        self.assertAlmostEqual(df['value_MEAN'].iloc[0], 20.0)
        self.assertEqual(df['value_COUNT'].iloc[0], 3)

    def test_grouped_stats(self):
        from data_agent.gis_processors import summary_statistics
        shp = self._create_point_shp()
        result = summary_statistics(shp, "value SUM;value COUNT", case_field="category")
        df = pd.read_csv(result)
        self.assertEqual(len(df), 2)  # X and Y groups
        x_row = df[df['category'] == 'X']
        self.assertEqual(x_row['value_SUM'].iloc[0], 30)  # 10+20
        self.assertEqual(x_row['value_COUNT'].iloc[0], 2)

    def test_invalid_stats_format(self):
        from data_agent.gis_processors import summary_statistics
        shp = self._create_point_shp()
        result = summary_statistics(shp, "invalid")
        self.assertIn("未能解析", result)

    def test_multi_field_stats(self):
        from data_agent.gis_processors import summary_statistics
        shp = self._create_point_shp()
        result = summary_statistics(shp, "value MIN;value MAX")
        df = pd.read_csv(result)
        self.assertEqual(df['value_MIN'].iloc[0], 10)
        self.assertEqual(df['value_MAX'].iloc[0], 30)


if __name__ == "__main__":
    unittest.main()

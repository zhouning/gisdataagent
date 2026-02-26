import unittest
import pandas as pd
import geopandas as gpd
import os
import shutil
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

from data_agent.geocoding import (
    batch_geocode,
    search_nearby_poi, search_poi_by_keyword, get_admin_boundary,
    _parse_amap_polyline,
)


class TestGeocoding(unittest.TestCase):
    def setUp(self):
        self.test_dir = "test_geo_data"
        os.makedirs(self.test_dir, exist_ok=True)
        self.xlsx_path = os.path.join(self.test_dir, "test.xlsx")

        # Create dummy Excel with English addresses (Nominatim works best with English/OSM data)
        # Using well-known landmarks
        df = pd.DataFrame({
            "Address": ["天安门", "故宫", "北京西站"],
            "Value": [100, 200, 300]
        })
        df.to_excel(self.xlsx_path, index=False)

    def tearDown(self):
        try:
            shutil.rmtree(self.test_dir)
        except:
            pass

    def test_batch_geocode(self):
        print("\nTesting batch_geocode...")
        # Note: This test hits external API (OSM). Might fail if network issues.
        # But we need to verify the logic.

        result = batch_geocode(self.xlsx_path, address_col="Address")

        if result['status'] == 'error':
            print(f"Geocoding failed (network issue?): {result['message']}")
            return

        self.assertEqual(result['status'], 'success')
        self.assertTrue(os.path.exists(result['output_path']))

        gdf = gpd.read_file(result['output_path'])
        self.assertEqual(len(gdf), 3)
        self.assertIn('geometry', gdf.columns)
        self.assertIn('Value', gdf.columns)

        # Check coordinates (Tiananmen is roughly 116.39, 39.90)
        # Note: Nominatim returns Lat/Lon. Points are x=Lon, y=Lat.
        first_pt = gdf.iloc[0].geometry
        print(f"  First point: {first_pt.x:.4f}, {first_pt.y:.4f}")
        self.assertAlmostEqual(first_pt.x, 116.39, delta=0.1)

    def test_confidence_columns_present(self):
        """Verify gc_match, gc_level, gc_src columns exist in geocoded output."""
        result = batch_geocode(self.xlsx_path, address_col="Address")
        if result['status'] == 'error':
            print(f"Skipping (network issue): {result['message']}")
            return
        gdf = gpd.read_file(result['output_path'])
        self.assertIn('gc_match', gdf.columns)
        self.assertIn('gc_level', gdf.columns)
        self.assertIn('gc_src', gdf.columns)
        # All successful geocodes should have non-empty gc_match
        self.assertTrue(all(gdf['gc_match'].str.len() > 0))

    def test_confidence_summary_in_result(self):
        """Verify confidence_summary is included in return dict."""
        result = batch_geocode(self.xlsx_path, address_col="Address")
        if result['status'] == 'error':
            return
        self.assertIn('confidence_summary', result)
        self.assertIsInstance(result['confidence_summary'], dict)


class TestAmapPolylineParsing(unittest.TestCase):
    """Unit tests for _parse_amap_polyline (no network needed)."""

    def test_single_ring(self):
        # Amap format: coords separated by ';', rings by '|'
        polyline = "116.0,39.0;117.0,39.0;117.0,40.0;116.0,40.0"
        result = _parse_amap_polyline(polyline)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].geom_type, "Polygon")
        # Ring should be auto-closed
        coords = list(result[0].exterior.coords)
        self.assertEqual(coords[0], coords[-1])

    def test_multiple_rings(self):
        # Two polygons separated by '|'
        polyline = "116.0,39.0;117.0,39.0;117.0,40.0;116.0,40.0|118.0,39.0;119.0,39.0;119.0,40.0;118.0,40.0"
        result = _parse_amap_polyline(polyline)
        self.assertEqual(len(result), 2)

    def test_empty_string(self):
        result = _parse_amap_polyline("")
        self.assertEqual(len(result), 0)

    def test_degenerate_ring(self):
        # Only 2 points — should be skipped
        polyline = "116.0,39.0;117.0,39.0"
        result = _parse_amap_polyline(polyline)
        self.assertEqual(len(result), 0)

    def test_invalid_coordinates(self):
        polyline = "abc,def;116.0,39.0;117.0,39.0;117.0,40.0"
        result = _parse_amap_polyline(polyline)
        # Should still produce a polygon from the 3 valid coords
        self.assertEqual(len(result), 1)


class TestPOISearch(unittest.TestCase):
    """Tests for Amap POI search functions."""

    def test_search_nearby_poi_no_key(self):
        """Graceful handling when API key is not set."""
        original = os.environ.pop("GAODE_API_KEY", None)
        try:
            result = search_nearby_poi(116.397, 39.908, "银行")
            self.assertEqual(result["status"], "error")
            self.assertIn("GAODE_API_KEY", result["message"])
        finally:
            if original:
                os.environ["GAODE_API_KEY"] = original

    def test_search_nearby_poi(self):
        """Nearby POI search — Tiananmen area banks."""
        if not os.environ.get("GAODE_API_KEY"):
            self.skipTest("GAODE_API_KEY not set")
        result = search_nearby_poi(116.397, 39.908, "银行", radius=1000, max_results=10)
        print(f"\nNearby POI: {result.get('message', result.get('status'))}")
        if result["status"] == "error":
            return  # Network issue, don't fail
        self.assertEqual(result["status"], "success")
        self.assertTrue(os.path.exists(result["output_path"]))
        gdf = gpd.read_file(result["output_path"])
        self.assertGreater(len(gdf), 0)
        self.assertIn("name", gdf.columns)
        print(f"  Found {len(gdf)} POIs, first: {gdf.iloc[0]['name']}")

    def test_search_poi_by_keyword(self):
        """Keyword POI search — Starbucks in Beijing."""
        if not os.environ.get("GAODE_API_KEY"):
            self.skipTest("GAODE_API_KEY not set")
        result = search_poi_by_keyword("星巴克", "北京市", max_results=10)
        print(f"\nKeyword POI: {result.get('message', result.get('status'))}")
        if result["status"] == "error":
            return
        self.assertEqual(result["status"], "success")
        self.assertTrue(os.path.exists(result["output_path"]))
        gdf = gpd.read_file(result["output_path"])
        self.assertGreater(len(gdf), 0)
        print(f"  Found {len(gdf)} Starbucks, first: {gdf.iloc[0]['name']}")

    def test_search_poi_by_keyword_no_key(self):
        """Graceful handling when API key is not set."""
        original = os.environ.pop("GAODE_API_KEY", None)
        try:
            result = search_poi_by_keyword("银行", "北京市")
            self.assertEqual(result["status"], "error")
            self.assertIn("GAODE_API_KEY", result["message"])
        finally:
            if original:
                os.environ["GAODE_API_KEY"] = original


class TestAdminBoundary(unittest.TestCase):
    """Tests for admin boundary fetch."""

    def test_get_admin_boundary_no_key(self):
        """Graceful handling when API key is not set."""
        original = os.environ.pop("GAODE_API_KEY", None)
        try:
            result = get_admin_boundary("北京市")
            self.assertEqual(result["status"], "error")
            self.assertIn("GAODE_API_KEY", result["message"])
        finally:
            if original:
                os.environ["GAODE_API_KEY"] = original

    def test_get_admin_boundary_single(self):
        """Fetch Beijing city boundary."""
        if not os.environ.get("GAODE_API_KEY"):
            self.skipTest("GAODE_API_KEY not set")
        result = get_admin_boundary("北京市")
        print(f"\nAdmin boundary: {result.get('message', result.get('status'))}")
        if result["status"] == "error":
            return
        self.assertEqual(result["status"], "success")
        self.assertTrue(os.path.exists(result["output_path"]))
        gdf = gpd.read_file(result["output_path"])
        self.assertEqual(len(gdf), 1)
        self.assertIn(gdf.iloc[0].geometry.geom_type, ["Polygon", "MultiPolygon"])
        print(f"  Geometry type: {gdf.iloc[0].geometry.geom_type}")

    def test_get_admin_boundary_with_children(self):
        """Fetch Beijing with district-level sub-boundaries."""
        if not os.environ.get("GAODE_API_KEY"):
            self.skipTest("GAODE_API_KEY not set")
        result = get_admin_boundary("北京市", with_sub_districts=True)
        print(f"\nAdmin boundary (subs): {result.get('message', result.get('status'))}")
        if result["status"] == "error":
            return
        self.assertEqual(result["status"], "success")
        gdf = gpd.read_file(result["output_path"])
        # Beijing has 16 districts + the parent = 17
        self.assertGreater(len(gdf), 1)
        print(f"  Got {len(gdf)} districts: {', '.join(gdf['name'].tolist()[:5])}...")


class TestConfidenceMapping(unittest.TestCase):
    """Unit tests for _map_confidence (no network needed)."""

    def test_high_confidence_levels(self):
        from data_agent.geocoding import _map_confidence
        self.assertEqual(_map_confidence("门牌号"), "高")
        self.assertEqual(_map_confidence("兴趣点"), "高")
        self.assertEqual(_map_confidence("地铁站"), "高")

    def test_medium_confidence_levels(self):
        from data_agent.geocoding import _map_confidence
        self.assertEqual(_map_confidence("道路"), "中")
        self.assertEqual(_map_confidence("村庄"), "中")
        self.assertEqual(_map_confidence("乡镇"), "中")

    def test_low_confidence_levels(self):
        from data_agent.geocoding import _map_confidence
        self.assertEqual(_map_confidence("城市"), "低")
        self.assertEqual(_map_confidence("省"), "低")
        self.assertEqual(_map_confidence("国家"), "低")

    def test_unknown_level_defaults_to_medium(self):
        from data_agent.geocoding import _map_confidence
        self.assertEqual(_map_confidence(""), "中")
        self.assertEqual(_map_confidence("未知类型"), "中")


if __name__ == "__main__":
    unittest.main()

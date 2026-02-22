import unittest
import os
import sys
import shutil
import geopandas as gpd
from shapely.geometry import Point, Polygon, box
import numpy as np
import rasterio
from rasterio.transform import from_origin
import pandas as pd

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_agent.gis_processors import (
    generate_tessellation, 
    raster_to_polygon, 
    pairwise_clip, 
    tabulate_intersection, 
    surface_parameters, 
    zonal_statistics_as_table,
    check_topology,
    check_field_standards
)
from data_agent.doc_auditor import check_consistency
from unittest.mock import patch

class TestGISProcessors(unittest.TestCase):
    def setUp(self):
        """Create temporary test data."""
        self.test_dir = os.path.join(os.path.dirname(__file__), "test_gis_data")
        os.makedirs(self.test_dir, exist_ok=True)
        # Ensure data_agent/uploads exists for tool output
        os.makedirs(os.path.join(os.path.dirname(__file__), "uploads"), exist_ok=True)
        
        # 1. Create a simple extent polygon (Square 0,0 to 1000,1000)
        self.extent_shp = os.path.join(self.test_dir, "extent.shp")
        gpd.GeoDataFrame(
            {'id': [1]}, 
            geometry=[Polygon([(0,0), (1000,0), (1000,1000), (0,1000)])],
            crs="EPSG:3857"
        ).to_file(self.extent_shp)
        
        # 2. Create a dummy raster (10x10 pixels, covering 0,0 to 100,100)
        self.raster_path = os.path.join(self.test_dir, "test_raster.tif")
        # Create an elevation-like gradient for slope test
        x = np.linspace(0, 10, 10)
        y = np.linspace(0, 10, 10)
        X, Y = np.meshgrid(x, y)
        self.dem_arr = (X + Y).astype(np.float32) 
        
        transform = from_origin(0, 100, 10, 10) # West, North, xres, yres
        
        with rasterio.open(
            self.raster_path, 'w',
            driver='GTiff', height=10, width=10, count=1, 
            dtype=rasterio.float32, crs='EPSG:3857', transform=transform
        ) as dst:
            dst.write(self.dem_arr, 1)

    def tearDown(self):
        """Cleanup."""
        try:
            shutil.rmtree(self.test_dir)
        except:
            pass

    def test_generate_tessellation(self):
        print("\nTesting generate_tessellation...")
        out = generate_tessellation(self.extent_shp, size=100.0)
        self.assertTrue(os.path.exists(out))
        gdf = gpd.read_file(out)
        self.assertGreater(len(gdf), 0)
        print(f"  Generated {len(gdf)} grid cells.")

    def test_raster_to_polygon(self):
        print("\nTesting raster_to_polygon...")
        out = raster_to_polygon(self.raster_path)
        self.assertTrue(os.path.exists(out))
        gdf = gpd.read_file(out)
        self.assertGreater(len(gdf), 0)
        self.assertIn('gridcode', gdf.columns)
        print(f"  Vectorized into {len(gdf)} polygons.")

    def test_surface_parameters(self):
        print("\nTesting surface_parameters (Slope)...")
        out = surface_parameters(self.raster_path, "SLOPE")
        self.assertTrue(os.path.exists(out))
        with rasterio.open(out) as src:
            slope = src.read(1)
            self.assertEqual(slope.shape, (10, 10))
            print(f"  Mean Slope: {np.mean(slope):.2f} degrees")

    def test_zonal_statistics(self):
        print("\nTesting zonal_statistics_as_table...")
        # Create zones (two polygons)
        zones_shp = os.path.join(self.test_dir, "zones.shp")
        gpd.GeoDataFrame(
            {'id': [1, 2]}, 
            geometry=[
                box(0, 0, 50, 100),   # Left half
                box(50, 0, 100, 100)  # Right half
            ],
            crs="EPSG:3857"
        ).to_file(zones_shp)
        
        out = zonal_statistics_as_table(zones_shp, self.raster_path)
        self.assertTrue(os.path.exists(out))
        df = pd.read_csv(out)
        self.assertEqual(len(df), 2)
        self.assertIn('mean', df.columns)
        print(f"  Zonal Stats:\n{df.head()}")

    def test_governance_topology(self):
        print("\nTesting check_topology (Governance)...")
        # Create topology error data: Overlapping polygons
        topo_err_path = os.path.join(self.test_dir, "topo_err.shp")
        gpd.GeoDataFrame(
            {'id': [1, 2]},
            geometry=[
                box(0, 0, 100, 100),    # Poly A
                box(50, 0, 150, 100)    # Poly B (Overlaps A by 50x100)
            ],
            crs="EPSG:3857"
        ).to_file(topo_err_path)
        
        report = check_topology(topo_err_path)
        
        # Verify
        self.assertEqual(report["status"], "fail")
        self.assertIn("overlaps", report["errors"])
        self.assertEqual(report["errors"]["overlaps"]["count"], 1) # One overlap event
        self.assertIn("layer", report["errors"]["overlaps"])
        print(f"  Topology Audit: Detected {report['errors']['overlaps']['count']} overlap(s). Error layer: {report['errors']['overlaps']['layer']}")

    def test_governance_standards(self):
        print("\nTesting check_field_standards (Governance)...")
        # Create data with schema violations
        # Standard: DLMC must be '水田' or '旱地'
        # Data: DLMC includes '非法用地'
        std_err_path = os.path.join(self.test_dir, "std_err.shp")
        gpd.GeoDataFrame(
            {'DLMC': ['水田', '非法用地'], 'KSL': [1.0, 2.0]},
            geometry=[Point(0,0), Point(1,1)],
            crs="EPSG:3857"
        ).to_file(std_err_path)
        
        schema = {
            "DLMC": {"type": "string", "allowed": ["水田", "旱地"]},
            "KSL": {"type": "float"}
        }
        
        result = check_field_standards(std_err_path, schema)
        
        # Verify
        self.assertFalse(result["is_standard"])
        self.assertEqual(len(result["invalid_values"]), 1)
        self.assertEqual(result["invalid_values"][0]["field"], "DLMC")
        self.assertEqual(result["invalid_values"][0]["count"], 1)
        self.assertIn("非法用地", result["invalid_values"][0]["sample"])
        print(f"  Standard Audit: Detected invalid value '{result['invalid_values'][0]['sample'][0]}' in field '{result['invalid_values'][0]['field']}'")

    @patch('data_agent.doc_auditor.extract_metrics_from_pdf')
    def test_doc_consistency(self, mock_extract):
        print("\nTesting check_consistency (Governance)...")
        
        # 1. Create a SHP with known areas
        # 2 Features: "水田" (Area 1000), "有林地" (Area 2000)
        # Total Area: 3000
        shp_path = os.path.join(self.test_dir, "consistency_test.shp")
        gpd.GeoDataFrame(
            {'DLMC': ['水田', '有林地'], 'Shape_Area': [1000.0, 2000.0]},
            geometry=[box(0,0,10,100), box(10,0,30,100)], # 10x100=1000, 20x100=2000
            crs="EPSG:3857"
        ).to_file(shp_path)
        
        # 2. Mock PDF content (The "Report" says we have 1050 Water, 1900 Forest)
        # Water: 1000 vs 1050 (Diff -50, ~4.7% -> MATCH)
        # Forest: 2000 vs 1900 (Diff +100, ~5.2% -> MISMATCH)
        mock_extract.return_value = {
            "metrics": {
                "耕地": 1050.0,  # "水田" should match "耕地" logic
                "林地": 1900.0
            }
        }
        
        # 3. Run Check
        report = check_consistency("dummy.pdf", shp_path, area_field='Shape_Area')
        
        # 4. Verify
        self.assertEqual(report['status'], 'success')
        self.assertEqual(len(report['report']), 2)
        
        # Check Water (耕地)
        res_water = next(r for r in report['report'] if r['category'] == '耕地')
        self.assertEqual(res_water['data_value'], 1000.0)
        self.assertEqual(res_water['status'], 'MATCH')
        
        # Check Forest (林地)
        res_forest = next(r for r in report['report'] if r['category'] == '林地')
        self.assertEqual(res_forest['data_value'], 2000.0)
        self.assertEqual(res_forest['status'], 'MISMATCH (>5%)')
        
        print(f"  Consistency Audit: Verified {len(report['report'])} metrics. Found MISMATCH for 林地 as expected.")

if __name__ == "__main__":
    unittest.main()

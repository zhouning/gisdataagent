import unittest
import geopandas as gpd
import pandas as pd
from shapely.geometry import Point, Polygon
import os
import shutil

# Add project root to path
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_agent.gis_processors import create_buffer, overlay_difference

class TestSemanticChain(unittest.TestCase):
    def setUp(self):
        self.test_dir = "test_semantic_data"
        os.makedirs(self.test_dir, exist_ok=True)
        
        # 1. Create Farmland (Big Polygon)
        # 2000x2000 meters square
        poly = Polygon([(0,0), (2000,0), (2000,2000), (0,2000)])
        gdf_farm = gpd.GeoDataFrame(
            {'id': [1], 'type': ['Farmland']}, 
            geometry=[poly], 
            crs="EPSG:3857"
        )
        self.farm_path = os.path.join(self.test_dir, "farmland.shp")
        gdf_farm.to_file(self.farm_path)
        
        # 2. Create Settlements (Points inside)
        # Center point at (1000, 1000)
        p1 = Point(1000, 1000)
        gdf_town = gpd.GeoDataFrame(
            {'id': [1], 'name': ['TownCenter']}, 
            geometry=[p1], 
            crs="EPSG:3857"
        )
        self.town_path = os.path.join(self.test_dir, "towns.shp")
        gdf_town.to_file(self.town_path)

    def tearDown(self):
        try:
            shutil.rmtree(self.test_dir)
        except:
            pass

    def test_site_selection_chain(self):
        print("\nTesting Semantic Chain: Buffer -> Difference...")
        
        # Step 1: Buffer Settlements (500m)
        print("  1. Creating 500m buffer around towns...")
        buffer_path = create_buffer(self.town_path, distance=500.0)
        self.assertTrue(os.path.exists(buffer_path))
        
        # Verify buffer size (Area of circle r=500 is pi*r^2 approx 785,398)
        gdf_buf = gpd.read_file(buffer_path)
        area = gdf_buf.geometry.area.sum()
        print(f"     Buffer Area: {area:.2f} sq meters")
        self.assertGreater(area, 780000)
        
        # Step 2: Erase Buffer from Farmland (Find land AWAY from towns)
        print("  2. Erasing buffer from farmland...")
        result_path = overlay_difference(self.farm_path, buffer_path)
        self.assertTrue(os.path.exists(result_path))
        
        # Step 3: Validation
        gdf_res = gpd.read_file(result_path)
        final_area = gdf_res.geometry.area.sum()
        initial_area = 2000 * 2000 # 4,000,000
        expected_area = initial_area - area
        
        print(f"     Initial Area: {initial_area}")
        print(f"     Final Area:   {final_area:.2f}")
        
        # Allow small tolerance for tessellation/precision
        self.assertAlmostEqual(final_area, expected_area, delta=1000)
        
        print("✅ Chain test passed!")

if __name__ == "__main__":
    unittest.main()

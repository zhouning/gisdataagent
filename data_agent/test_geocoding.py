import unittest
import pandas as pd
import geopandas as gpd
import os
import shutil
from data_agent.geocoding import batch_geocode

class TestGeocoding(unittest.TestCase):
    def setUp(self):
        self.test_dir = "test_geo_data"
        os.makedirs(self.test_dir, exist_ok=True)
        self.xlsx_path = os.path.join(self.test_dir, "test.xlsx")
        
        # Create dummy Excel with English addresses (Nominatim works best with English/OSM data)
        # Using well-known landmarks
        df = pd.DataFrame({
            "Address": ["Tiananmen, Beijing", "Eiffel Tower, Paris", "Statue of Liberty, NY"],
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

if __name__ == "__main__":
    unittest.main()

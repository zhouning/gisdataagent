import unittest
import os
import sys
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_agent.agent import engineer_spatial_features, describe_geodataframe, _resolve_path

class TestMultiFormat(unittest.TestCase):
    def setUp(self):
        # Create a dummy CSV with lat/lon
        self.csv_path = "test_data.csv"
        data = {
            'id': [1, 2, 3],
            'lat': [30.1, 30.2, 30.3],
            'lon': [110.1, 110.2, 110.3],
            'DLMC': ['旱地', '林地', '旱地'],
            'Slope': [5, 15, 25]
        }
        pd.DataFrame(data).to_csv(self.csv_path, index=False)
        print(f"Created dummy CSV at {os.path.abspath(self.csv_path)}")

    def tearDown(self):
        if os.path.exists(self.csv_path):
            os.remove(self.csv_path)

    def test_csv_ingestion(self):
        """Test if CSV is correctly converted to Spatial DataFrame."""
        print("\n--- Testing CSV Ingestion ---")
        
        # 1. Test Describe (Health Check)
        print("Step 1: Describing CSV...")
        desc = describe_geodataframe(self.csv_path)
        print(f"Description: {desc}")
        self.assertEqual(desc['status'], 'success')
        self.assertEqual(desc['summary']['num_features'], 3)
        self.assertIn('.csv', desc['summary']['file_type'])
        
        # 2. Test Feature Engineering (Conversion)
        print("Step 2: Processing CSV to SHP...")
        result = engineer_spatial_features(self.csv_path)
        print(f"Result: {result}")
        
        self.assertEqual(result['status'], 'success')
        out_path = result['output_path']
        self.assertTrue(out_path.endswith('.shp'))
        self.assertTrue(os.path.exists(out_path))
        
        # 3. Verify Geometry
        print("Step 3: Verifying output geometry...")
        gdf_out = gpd.read_file(out_path)
        print(gdf_out.head())
        self.assertIsInstance(gdf_out.geometry[0], Point)
        self.assertEqual(len(gdf_out), 3)
        self.assertTrue('S_Idx' in gdf_out.columns) # Feature added?
        
        print("Success: CSV successfully converted to Shapefile with features!")

if __name__ == "__main__":
    unittest.main()

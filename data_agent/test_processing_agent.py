import unittest
import os
import sys
import geopandas as gpd

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_agent.agent import engineer_spatial_features, reproject_spatial_data

# Use absolute path for test data
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEST_SHP_PATH = os.path.join(BASE_DIR, "斑竹村10000.shp")

class TestProcessingAgent(unittest.TestCase):
    def test_engineer_spatial_features(self):
        """Test if advanced spatial features are correctly calculated with short names."""
        print("\n--- Testing engineer_spatial_features (Short Names) ---")
        
        # 1. Run the tool
        result = engineer_spatial_features(TEST_SHP_PATH)
        
        # 2. Verify status
        self.assertEqual(result["status"], "success")
        
        # 3. Check the output file
        out_path = result["output_path"]
        self.assertTrue(os.path.exists(out_path))
        
        # 4. Read the processed file and verify columns (Short names for Shapefile compatibility)
        gdf_new = gpd.read_file(out_path)
        self.assertIn("S_Idx", gdf_new.columns)
        self.assertIn("CX", gdf_new.columns)
        self.assertIn("CY", gdf_new.columns)
        
        # Verify values are reasonable (Shape Index >= 1)
        self.assertTrue((gdf_new["S_Idx"] >= 0.99).all())
        
        print("Success: Features added with compatible names.")

    def test_reproject_spatial_data(self):
        """Test if CRS reprojection works correctly."""
        print("\n--- Testing reproject_spatial_data ---")
        
        target_crs = "EPSG:3857"
        out_path = reproject_spatial_data(TEST_SHP_PATH, target_crs=target_crs)
        
        # Verify file creation
        self.assertTrue(os.path.exists(out_path))
        
        # Verify CRS in the new file
        gdf_reprojected = gpd.read_file(out_path)
        self.assertEqual(gdf_reprojected.crs.to_epsg(), 3857)
        
        print("Success: Reprojected data.")

if __name__ == "__main__":
    unittest.main()

import unittest
import os
import sys
import geopandas as gpd

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_agent.agent import drl_model, visualize_optimization_comparison, visualize_interactive_map

# Path to the real test data
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEST_SHP_PATH = os.path.abspath(os.path.join(BASE_DIR, "斑竹村10000.shp"))

class TestVisualizationAgent(unittest.TestCase):
    def test_visualize_all(self):
        """Test both static comparison and interactive map generation."""
        print("\n--- Testing Visualization Suite ---")
        
        # 1. Dependency: Generate optimized data
        print("Step 1: Running DRL model...")
        model_result = drl_model(TEST_SHP_PATH)
        if isinstance(model_result, str) and "Error" in model_result:
            self.fail("DRL model failed.")
        opt_data_path = model_result["optimized_data_path"]
        
        # 2. Test Static Comparison
        print("Step 2: Generating Static Comparison...")
        static_res = visualize_optimization_comparison(TEST_SHP_PATH, opt_data_path)
        print(static_res)
        self.assertIn("saved to", static_res.lower())
        self.assertTrue(os.path.exists(static_res.split("saved to ")[1].strip()))
        
        # 3. Test Interactive Map (New Signature)
        print("Step 3: Generating Interactive Comparison Map...")
        # Now passing BOTH original and optimized paths
        interactive_res = visualize_interactive_map(TEST_SHP_PATH, opt_data_path)
        print(interactive_res)
        
        self.assertIn("saved to", interactive_res.lower())
        html_path = interactive_res.split("saved to ")[1].strip()
        self.assertTrue(os.path.exists(html_path))
        self.assertTrue(html_path.endswith(".html"))
        
        print(f"Success: Interactive comparison map created at {html_path}")

if __name__ == "__main__":
    unittest.main()

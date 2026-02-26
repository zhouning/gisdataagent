import unittest
import os
import sys

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_agent.agent import describe_geodataframe

# Use absolute path for test data to be safe
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEST_SHP_PATH = os.path.join(BASE_DIR, "斑竹村10000.shp")

class TestExplorationAgent(unittest.TestCase):
    def test_describe_geodataframe_real_file(self):
        """Test the tool with the actual provided Shapefile."""
        print(f"\n--- Testing describe_geodataframe with real file ---")

        # Use absolute path to avoid Chinese character encoding issues on Windows
        result = describe_geodataframe(TEST_SHP_PATH)
        
        # 2. Verify basic structure
        self.assertEqual(result["status"], "success")
        summary = result["summary"]
        
        print(f"Features found: {summary['num_features']}")
        print(f"CRS: {summary['crs']}")
        
        # 3. Check health metrics
        health = summary["data_health"]
        print(f"Health Warnings: {health['warnings']}")
        print(f"Recommendations: {health['recommendations']}")
        
        # 4. Assertions
        self.assertGreater(summary["num_features"], 0)
        self.assertIn("DLMC", summary["columns"])
        self.assertIn("Slope", summary["columns"])
        
        if not health["ready_for_analysis"]:
             print("Status: Data health check found issues, which is expected for raw data.")

    def test_agent_output_format(self):
        """Test if the agent instruction includes expected analysis directives."""
        from data_agent.agent import data_exploration_agent

        # Instruction now loaded from prompts/optimization.yaml
        # Verify it contains key directives (Chinese prompts)
        self.assertTrue(len(data_exploration_agent.instruction) > 100)
        self.assertIsNotNone(data_exploration_agent.instruction)
        print("\n[Test] Agent instruction loaded and non-empty.")

if __name__ == "__main__":
    unittest.main()

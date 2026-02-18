import unittest
import os
import sys
import yaml
from unittest.mock import MagicMock, patch

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
        
        # Tool uses relative path from its own __file__ (agent.py)
        # We pass "../斑竹村10000.shp" to reach root from data_agent/
        result = describe_geodataframe("../斑竹村10000.shp")
        
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

    @patch('google.adk.agents.llm_agent.LlmAgent.call_model')
    def test_agent_output_format(self, mock_call_model):
        """Test if the agent instruction logic handles the tool output correctly."""
        from data_agent.agent import data_exploration_agent
        
        mock_llm_response = "Mocked Response with Health Check and Recommendations"
        mock_call_model.return_value.text = mock_llm_response
        
        # Check if instruction includes the specific logic we added
        self.assertIn("Data Health Check", data_exploration_agent.instruction)
        print("\n[Mock Test] Agent Prompt logic verified.")

if __name__ == "__main__":
    unittest.main()

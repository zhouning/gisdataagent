import unittest
import os
import sys
import time

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_agent.agent import ffi, drl_model

# Use absolute path for test data
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEST_SHP_PATH = os.path.abspath(os.path.join(BASE_DIR, "斑竹村10000.shp"))

class TestAnalysisAgent(unittest.TestCase):
    def test_ffi_calculation(self):
        """Test FFI tool performance and output with absolute path."""
        print("\n--- Testing FFI Tool ---")
        
        start_time = time.time()
        # Use absolute path to bypass encoding issues in Windows Shell
        result = ffi(TEST_SHP_PATH)
        duration = time.time() - start_time
        
        print(f"Calculation took: {duration:.2f} seconds")
        
        # Assertions
        self.assertIsInstance(result, str)
        if "Error" in result:
             self.fail(f"FFI calculation failed: {result}")
             
        self.assertIn("FFI", result)
        self.assertIn("|", result) 
        self.assertLess(duration, 30, "FFI calculation is too slow.")

    def test_drl_model_inference(self):
        """Test PPO model loading and inference with absolute path."""
        print("\n--- Testing DRL Model Tool (Inference) ---")
        
        # 1. Run the tool
        result = drl_model(TEST_SHP_PATH)
        
        # 2. Check result type
        if isinstance(result, str) and "Error" in result:
            self.fail(f"DRL Model failed: {result}")
            
        self.assertIsInstance(result, dict)
        self.assertIn("output_path", result)
        
        # 3. Verify output files
        self.assertTrue(os.path.exists(result["output_path"]))
        
        print("Optimization Status: Success")
        print(f"Output map saved to: {result['output_path']}")

if __name__ == "__main__":
    unittest.main()

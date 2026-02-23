import unittest
import os
import sys
# Load dotenv before importing modules that need env vars
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

from data_agent.database_tools import query_database
from data_agent.agent import drl_model, ffi

class TestDBOptimization(unittest.TestCase):
    def test_end_to_end_from_db(self):
        print("\n=== Testing Optimization Pipeline from Database Source ===")
        
        # 1. Fetch data from DB
        print("\n[Step 1] Querying 'banzhu_village_10000' from PostgreSQL...")
        sql = "SELECT * FROM banzhu_village_10000"
        query_result = query_database(sql)
        
        if query_result.get('status') == 'error':
            self.fail(f"Database query failed: {query_result['message']}")
        
        self.assertEqual(query_result['status'], 'success')
        self.assertTrue(os.path.exists(query_result['output_path']))
        print(f"  -> Data fetched successfully: {query_result.get('rows')} rows.")
        print(f"  -> Saved to local cache: {query_result['output_path']}")
        
        local_shp_path = query_result['output_path']
        
        # 2. Calculate Baseline FFI
        print("\n[Step 2] Calculating Baseline FFI...")
        ffi_result = ffi(local_shp_path)
        self.assertIn("FFI", ffi_result)
        print("  -> FFI Calculation successful.")
        
        # 3. Run DRL Optimization
        print("\n[Step 3] Running DRL Optimization Model (v7)...")
        opt_result = drl_model(local_shp_path)
        
        # Validate result structure
        if isinstance(opt_result, str) and "Error" in opt_result:
            self.fail(f"Optimization failed: {opt_result}")
            
        self.assertIsInstance(opt_result, dict)
        self.assertIn("summary", opt_result)
        self.assertIn("output_path", opt_result)
        
        print("\n[Step 4] Validation")
        print(f"  -> Visualization: {opt_result['output_path']}")
        print(f"  -> Optimized SHP: {opt_result['optimized_data_path']}")
        print(f"  -> Summary: \n{opt_result['summary']}")
        
        print("\n✅ End-to-End Database Optimization Test Passed!")

if __name__ == "__main__":
    unittest.main()

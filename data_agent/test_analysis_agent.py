import unittest
import os
import sys
import time
import asyncio

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_agent.agent import ffi, drl_model
from data_agent.toolsets.analysis_tools import AnalysisToolset, drl_model_long_running

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


# ---------------------------------------------------------------------------
# LongRunningFunctionTool integration tests (v9.5.5)
# ---------------------------------------------------------------------------

class TestDRLLongRunning(unittest.TestCase):
    """Tests for DRL LongRunningFunctionTool wrapper."""

    @staticmethod
    def _run(coro):
        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                raise RuntimeError
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)

    def test_drl_model_long_running_is_async(self):
        """drl_model_long_running should be a coroutine function."""
        self.assertTrue(asyncio.iscoroutinefunction(drl_model_long_running))

    def test_drl_model_long_running_preserves_name(self):
        """Async wrapper should keep __name__ = 'drl_model' for ADK tool registration."""
        self.assertEqual(drl_model_long_running.__name__, "drl_model")

    def test_drl_model_sync_still_callable(self):
        """Original sync drl_model should remain callable for backward compat."""
        self.assertTrue(callable(drl_model))
        self.assertFalse(asyncio.iscoroutinefunction(drl_model))

    def test_toolset_has_long_running_tool(self):
        """AnalysisToolset should register drl_model as LongRunningFunctionTool."""
        from google.adk.tools import LongRunningFunctionTool

        toolset = AnalysisToolset()
        tools = self._run(toolset.get_tools())
        drl_tools = [t for t in tools if t.name == "drl_model"]
        self.assertEqual(len(drl_tools), 1)
        self.assertIsInstance(drl_tools[0], LongRunningFunctionTool)
        self.assertTrue(drl_tools[0].is_long_running)

    def test_toolset_drl_description_has_long_running_note(self):
        """LongRunningFunctionTool should append 'do not call again' to description."""
        toolset = AnalysisToolset()
        tools = self._run(toolset.get_tools())
        drl_tools = [t for t in tools if t.name == "drl_model"]
        decl = drl_tools[0]._get_declaration()
        self.assertIn("long-running", decl.description.lower())

    def test_toolset_ffi_is_regular_function_tool(self):
        """FFI should remain a regular FunctionTool (not long-running)."""
        from google.adk.tools import FunctionTool, LongRunningFunctionTool

        toolset = AnalysisToolset()
        tools = self._run(toolset.get_tools())
        ffi_tools = [t for t in tools if t.name == "ffi"]
        self.assertEqual(len(ffi_tools), 1)
        self.assertIsInstance(ffi_tools[0], FunctionTool)
        self.assertNotIsInstance(ffi_tools[0], LongRunningFunctionTool)

    def test_toolset_tool_count(self):
        """AnalysisToolset should have 3 tools: ffi + drl_model + drl_multi_objective."""
        toolset = AnalysisToolset()
        tools = self._run(toolset.get_tools())
        self.assertEqual(len(tools), 3)
        names = {t.name for t in tools}
        self.assertIn("ffi", names)
        self.assertIn("drl_model", names)
        self.assertIn("drl_multi_objective", names)


if __name__ == "__main__":
    unittest.main()

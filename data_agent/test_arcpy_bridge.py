"""
Tests for ArcPy integration bridge.

- TestArcPyBridgeNoBridge: Tests graceful degradation when ArcPy is not available.
- TestArcPyBridgeWithWorker: Integration tests that require a live ArcPy environment.
"""
import unittest
import os
from unittest.mock import patch, MagicMock
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))


class TestArcPyBridgeNoBridge(unittest.TestCase):
    """Tests for graceful degradation when ArcPy env is not configured."""

    @patch.dict(os.environ, {"ARCPY_PYTHON_EXE": ""}, clear=False)
    def test_is_arcpy_available_no_env(self):
        """is_arcpy_available returns False when env var is empty."""
        from data_agent.arcpy_tools import ArcPyBridge
        ArcPyBridge._instance = None  # reset singleton
        from data_agent.arcpy_tools import is_arcpy_available
        self.assertFalse(is_arcpy_available())

    @patch.dict(os.environ, {"ARCPY_PYTHON_EXE": ""}, clear=False)
    def test_arcpy_buffer_no_bridge(self):
        """arcpy_buffer returns error string when bridge unavailable."""
        from data_agent.arcpy_tools import ArcPyBridge, arcpy_buffer
        ArcPyBridge._instance = None
        result = arcpy_buffer("test.shp", 500)
        self.assertIn("Error", result)

    @patch.dict(os.environ, {"ARCPY_PYTHON_EXE": ""}, clear=False)
    def test_arcpy_clip_no_bridge(self):
        """arcpy_clip returns error string when bridge unavailable."""
        from data_agent.arcpy_tools import ArcPyBridge, arcpy_clip
        ArcPyBridge._instance = None
        result = arcpy_clip("input.shp", "clip.shp")
        self.assertIn("Error", result)

    @patch.dict(os.environ, {"ARCPY_PYTHON_EXE": ""}, clear=False)
    def test_arcpy_dissolve_no_bridge(self):
        """arcpy_dissolve returns error string when bridge unavailable."""
        from data_agent.arcpy_tools import ArcPyBridge, arcpy_dissolve
        ArcPyBridge._instance = None
        result = arcpy_dissolve("test.shp", "FIELD")
        self.assertIn("Error", result)

    @patch.dict(os.environ, {"ARCPY_PYTHON_EXE": ""}, clear=False)
    def test_arcpy_project_no_bridge(self):
        """arcpy_project returns error string when bridge unavailable."""
        from data_agent.arcpy_tools import ArcPyBridge, arcpy_project
        ArcPyBridge._instance = None
        result = arcpy_project("test.shp", "EPSG:4490")
        self.assertIn("Error", result)

    @patch.dict(os.environ, {"ARCPY_PYTHON_EXE": ""}, clear=False)
    def test_arcpy_check_geometry_no_bridge(self):
        """arcpy_check_geometry returns error dict when bridge unavailable."""
        from data_agent.arcpy_tools import ArcPyBridge, arcpy_check_geometry
        ArcPyBridge._instance = None
        result = arcpy_check_geometry("test.shp")
        self.assertIsInstance(result, dict)
        self.assertEqual(result["status"], "error")

    @patch.dict(os.environ, {"ARCPY_PYTHON_EXE": ""}, clear=False)
    def test_arcpy_repair_geometry_no_bridge(self):
        """arcpy_repair_geometry returns error string when bridge unavailable."""
        from data_agent.arcpy_tools import ArcPyBridge, arcpy_repair_geometry
        ArcPyBridge._instance = None
        result = arcpy_repair_geometry("test.shp")
        self.assertIn("Error", result)

    @patch.dict(os.environ, {"ARCPY_PYTHON_EXE": ""}, clear=False)
    def test_arcpy_slope_no_bridge(self):
        """arcpy_slope returns error string when bridge unavailable."""
        from data_agent.arcpy_tools import ArcPyBridge, arcpy_slope
        ArcPyBridge._instance = None
        result = arcpy_slope("dem.tif")
        self.assertIn("Error", result)

    @patch.dict(os.environ, {"ARCPY_PYTHON_EXE": ""}, clear=False)
    def test_arcpy_zonal_statistics_no_bridge(self):
        """arcpy_zonal_statistics returns error string when bridge unavailable."""
        from data_agent.arcpy_tools import ArcPyBridge, arcpy_zonal_statistics
        ArcPyBridge._instance = None
        result = arcpy_zonal_statistics("zones.shp", "values.tif")
        self.assertIn("Error", result)


class TestArcPyBridgeMocked(unittest.TestCase):
    """Tests with mocked bridge to verify call patterns."""

    def setUp(self):
        from data_agent.arcpy_tools import ArcPyBridge
        self.mock_bridge = MagicMock(spec=ArcPyBridge)
        self._orig_instance = ArcPyBridge._instance

    def tearDown(self):
        from data_agent.arcpy_tools import ArcPyBridge
        ArcPyBridge._instance = self._orig_instance

    @patch('data_agent.arcpy_tools.ArcPyBridge.get_instance')
    @patch('data_agent.arcpy_tools._resolve_path', return_value='/tmp/test.shp')
    @patch('data_agent.arcpy_tools._generate_output_path', return_value='/tmp/output.shp')
    def test_arcpy_buffer_success(self, mock_gen, mock_resolve, mock_get):
        """arcpy_buffer returns output path on success."""
        mock_bridge = MagicMock()
        mock_bridge.call.return_value = {
            "status": "success",
            "output_path": "/tmp/output.shp",
            "feature_count": 10,
        }
        mock_get.return_value = mock_bridge

        from data_agent.arcpy_tools import arcpy_buffer
        result = arcpy_buffer("test.shp", 500.0, "NONE")
        self.assertEqual(result, "/tmp/output.shp")
        mock_bridge.call.assert_called_once_with("buffer", {
            "input_path": "/tmp/test.shp",
            "output_path": "/tmp/output.shp",
            "distance": 500.0,
            "dissolve_type": "NONE",
        })

    @patch('data_agent.arcpy_tools.ArcPyBridge.get_instance')
    @patch('data_agent.arcpy_tools._resolve_path', return_value='/tmp/test.shp')
    @patch('data_agent.arcpy_tools._generate_output_path', return_value='/tmp/output.csv')
    def test_arcpy_check_geometry_success(self, mock_gen, mock_resolve, mock_get):
        """arcpy_check_geometry returns full result dict on success."""
        mock_bridge = MagicMock()
        mock_bridge.call.return_value = {
            "status": "success",
            "total_errors": 3,
            "error_counts": {"Self Intersection": 2, "Null Geometry": 1},
            "output_path": "/tmp/output.csv",
        }
        mock_get.return_value = mock_bridge

        from data_agent.arcpy_tools import arcpy_check_geometry
        result = arcpy_check_geometry("test.shp")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["total_errors"], 3)

    @patch('data_agent.arcpy_tools.ArcPyBridge.get_instance')
    @patch('data_agent.arcpy_tools._resolve_path', return_value='/tmp/test.shp')
    @patch('data_agent.arcpy_tools._generate_output_path', return_value='/tmp/output.shp')
    def test_arcpy_buffer_error(self, mock_gen, mock_resolve, mock_get):
        """arcpy_buffer returns error message on failure."""
        mock_bridge = MagicMock()
        mock_bridge.call.return_value = {
            "status": "error",
            "message": "Input dataset does not exist",
        }
        mock_get.return_value = mock_bridge

        from data_agent.arcpy_tools import arcpy_buffer
        result = arcpy_buffer("test.shp", 500.0)
        self.assertIn("Error", result)
        self.assertIn("does not exist", result)


class TestArcPyWorkerIntegration(unittest.TestCase):
    """Integration tests — requires live ArcPy environment.
    Skipped automatically if ARCPY_PYTHON_EXE is not configured."""

    @classmethod
    def setUpClass(cls):
        from data_agent.arcpy_tools import ArcPyBridge
        ArcPyBridge._instance = None  # force fresh start
        from data_agent.arcpy_tools import is_arcpy_available
        if not is_arcpy_available():
            raise unittest.SkipTest("ArcPy environment not available")

    def test_bridge_ping(self):
        """Worker responds to ping."""
        from data_agent.arcpy_tools import ArcPyBridge
        bridge = ArcPyBridge.get_instance()
        self.assertIsNotNone(bridge)
        self.assertTrue(bridge.is_healthy())

    @classmethod
    def tearDownClass(cls):
        from data_agent.arcpy_tools import ArcPyBridge
        if ArcPyBridge._instance:
            ArcPyBridge._instance.shutdown()


if __name__ == "__main__":
    unittest.main()

"""Tests for Proactive Explorer (v11.0.3).

Covers file profiling, suggestion generation, CRUD, and deduplication.
"""
import json
import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock


class TestProactiveConstants(unittest.TestCase):
    def test_table_name(self):
        from data_agent.proactive_explorer import T_OBSERVATIONS
        self.assertEqual(T_OBSERVATIONS, "agent_proactive_observations")

    def test_spatial_extensions(self):
        from data_agent.proactive_explorer import SPATIAL_EXTENSIONS
        self.assertIn(".shp", SPATIAL_EXTENSIONS)
        self.assertIn(".csv", SPATIAL_EXTENSIONS)
        self.assertIn(".geojson", SPATIAL_EXTENSIONS)


class TestFileProfiling(unittest.TestCase):
    def test_profile_csv(self):
        from data_agent.proactive_explorer import profile_file
        # Create a temp CSV
        path = os.path.join(tempfile.gettempdir(), "test_profile.csv")
        with open(path, "w", encoding="utf-8") as f:
            f.write("lng,lat,value\n120.5,30.1,100\n121.0,30.5,200\n")
        profile = profile_file(path)
        self.assertEqual(profile["extension"], ".csv")
        self.assertGreater(profile["row_count"], 0)
        self.assertTrue(profile["has_coordinates"])
        os.remove(path)

    def test_profile_nonexistent(self):
        from data_agent.proactive_explorer import profile_file
        profile = profile_file("/nonexistent/file.shp")
        self.assertIn("error", profile)

    def test_file_hash(self):
        from data_agent.proactive_explorer import _compute_file_hash
        path = os.path.join(tempfile.gettempdir(), "test_hash.txt")
        with open(path, "w") as f:
            f.write("test content")
        h = _compute_file_hash(path)
        self.assertTrue(h)
        self.assertEqual(len(h), 16)
        os.remove(path)

    def test_file_hash_nonexistent(self):
        from data_agent.proactive_explorer import _compute_file_hash
        h = _compute_file_hash("/nonexistent")
        self.assertEqual(h, "")


class TestSuggestionGeneration(unittest.TestCase):
    def test_polygon_suggestions(self):
        from data_agent.proactive_explorer import generate_suggestions
        profile = {
            "geometry_types": ["Polygon"],
            "row_count": 500,
            "numeric_columns": ["area", "perimeter"],
        }
        suggestions = generate_suggestions(profile, "test.shp")
        self.assertGreater(len(suggestions), 0)
        titles = [s.title for s in suggestions]
        self.assertIn("空间自相关分析", titles)

    def test_point_suggestions(self):
        from data_agent.proactive_explorer import generate_suggestions
        profile = {
            "geometry_types": ["Point"],
            "row_count": 200,
        }
        suggestions = generate_suggestions(profile, "points.geojson")
        titles = [s.title for s in suggestions]
        self.assertIn("热点分析", titles)

    def test_csv_with_coords(self):
        from data_agent.proactive_explorer import generate_suggestions
        profile = {
            "has_coordinates": True,
            "coordinate_columns": ["lng", "lat"],
        }
        suggestions = generate_suggestions(profile, "data.csv")
        titles = [s.title for s in suggestions]
        self.assertIn("空间可视化", titles)

    def test_empty_profile(self):
        from data_agent.proactive_explorer import generate_suggestions
        suggestions = generate_suggestions({}, "empty.txt")
        self.assertEqual(len(suggestions), 0)

    def test_max_5_suggestions(self):
        from data_agent.proactive_explorer import generate_suggestions
        # Profile that triggers many conditions
        profile = {
            "geometry_types": ["Polygon", "Point"],
            "row_count": 500,
            "has_coordinates": True,
            "numeric_columns": ["a", "b", "c"],
        }
        suggestions = generate_suggestions(profile, "rich.shp")
        self.assertLessEqual(len(suggestions), 5)


class TestAnalysisSuggestion(unittest.TestCase):
    def test_to_dict(self):
        from data_agent.proactive_explorer import AnalysisSuggestion
        s = AnalysisSuggestion(title="Test", description="desc", relevance_score=0.75)
        d = s.to_dict()
        self.assertEqual(d["title"], "Test")
        self.assertEqual(d["relevance_score"], 0.75)


class TestDataObservation(unittest.TestCase):
    def test_to_dict(self):
        from data_agent.proactive_explorer import DataObservation, AnalysisSuggestion
        obs = DataObservation(
            user_id="alice", file_path="test.shp",
            suggestions=[AnalysisSuggestion(title="s1")]
        )
        d = obs.to_dict()
        self.assertEqual(d["user_id"], "alice")
        self.assertEqual(len(d["suggestions"]), 1)


class TestCRUD(unittest.TestCase):
    @patch("data_agent.proactive_explorer.get_engine", return_value=None)
    def test_save_no_engine(self, _):
        from data_agent.proactive_explorer import save_observation, DataObservation
        obs = DataObservation(user_id="alice")
        self.assertFalse(save_observation(obs))

    @patch("data_agent.proactive_explorer.get_engine", return_value=None)
    def test_get_suggestions_no_engine(self, _):
        from data_agent.proactive_explorer import get_suggestions
        self.assertEqual(get_suggestions("alice"), [])

    @patch("data_agent.proactive_explorer.get_engine", return_value=None)
    def test_dismiss_no_engine(self, _):
        from data_agent.proactive_explorer import dismiss_suggestion
        self.assertFalse(dismiss_suggestion("obs123"))

    @patch("data_agent.proactive_explorer.get_engine")
    def test_dismiss_success(self, mock_eng):
        from data_agent.proactive_explorer import dismiss_suggestion
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_eng.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.rowcount = 1
        self.assertTrue(dismiss_suggestion("obs123"))


class TestProactiveRoutes(unittest.TestCase):
    def test_routes_exist(self):
        # The suggestion routes will be added in frontend_api.py
        # For now just verify the module loads cleanly
        from data_agent.proactive_explorer import (
            scan_user_uploads, get_suggestions, dismiss_suggestion,
            profile_file, generate_suggestions
        )
        self.assertTrue(callable(scan_user_uploads))


if __name__ == "__main__":
    unittest.main()

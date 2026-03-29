"""Tests for data versioning — versions, rollback, notifications, diff (v15.0)."""
import unittest
from unittest.mock import patch, MagicMock


class TestCreateSnapshot(unittest.TestCase):
    @patch("data_agent.data_versioning.get_engine", return_value=None)
    def test_no_db(self, _):
        from data_agent.data_versioning import create_version_snapshot
        result = create_version_snapshot(1, "admin")
        self.assertEqual(result["status"], "error")


class TestListVersions(unittest.TestCase):
    @patch("data_agent.data_versioning.get_engine", return_value=None)
    def test_no_db(self, _):
        from data_agent.data_versioning import list_versions
        self.assertEqual(list_versions(1), [])


class TestRollback(unittest.TestCase):
    @patch("data_agent.data_versioning.get_engine", return_value=None)
    def test_no_db(self, _):
        from data_agent.data_versioning import rollback_version
        result = rollback_version(1, 1, "admin")
        self.assertEqual(result["status"], "error")


class TestNotifications(unittest.TestCase):
    @patch("data_agent.data_versioning.get_engine", return_value=None)
    def test_notify_no_db(self, _):
        from data_agent.data_versioning import notify_asset_update
        result = notify_asset_update(1, "test.shp", message="updated")
        self.assertEqual(result["status"], "error")

    @patch("data_agent.data_versioning.get_engine", return_value=None)
    def test_get_notifications_no_db(self, _):
        from data_agent.data_versioning import get_notifications
        self.assertEqual(get_notifications("user1"), [])

    @patch("data_agent.data_versioning.get_engine", return_value=None)
    def test_mark_read_no_db(self, _):
        from data_agent.data_versioning import mark_notification_read
        result = mark_notification_read(1)
        self.assertEqual(result["status"], "error")


class TestCompareDatasets(unittest.TestCase):
    @patch("geopandas.read_file")
    def test_compare(self, mock_read):
        import geopandas as gpd
        from shapely.geometry import Point

        old = gpd.GeoDataFrame({"a": [1, 2]}, geometry=[Point(0, 0), Point(1, 1)], crs="EPSG:4326")
        new = gpd.GeoDataFrame({"a": [1, 2, 3], "b": [4, 5, 6]},
                                geometry=[Point(0, 0), Point(1, 1), Point(2, 2)], crs="EPSG:4326")
        mock_read.side_effect = [old, new]
        from data_agent.data_versioning import compare_datasets
        result = compare_datasets("/old.shp", "/new.shp")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["old_features"], 2)
        self.assertEqual(result["new_features"], 3)
        self.assertIn("b", result["columns_added"])


class TestConstants(unittest.TestCase):
    def test_table_names(self):
        from data_agent.data_versioning import T_ASSET_VERSIONS, T_UPDATE_NOTIFICATIONS
        self.assertEqual(T_ASSET_VERSIONS, "agent_asset_versions")
        self.assertEqual(T_UPDATE_NOTIFICATIONS, "agent_update_notifications")


if __name__ == "__main__":
    unittest.main()

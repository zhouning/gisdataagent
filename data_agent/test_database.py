import unittest
import os
from unittest.mock import patch, MagicMock
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))
from data_agent.database_tools import get_db_connection_url, query_database, import_to_postgis

class TestDatabase(unittest.TestCase):
    def test_connection_string(self):
        url = get_db_connection_url()
        self.assertIsNotNone(url)
        self.assertIn("postgresql://", url)
        print(f"Connection String: {url.replace(os.environ.get('POSTGRES_PASSWORD'), '***')}")

    def test_query_failure_graceful(self):
        # We expect connection to fail if DB is not reachable, but tool should handle it
        # This test just checks if the tool returns the expected error structure
        result = query_database("SELECT 1")
        if result['status'] == 'error':
            print(f"Query failed as expected (network/db offline): {result['message']}")
        else:
            print("Query success!")


class TestImportToPostgis(unittest.TestCase):
    """Tests for the import_to_postgis tool function."""

    @patch("data_agent.database_tools.get_engine", return_value=None)
    def test_no_database(self, _mock):
        """Returns error when database is not configured."""
        result = import_to_postgis("test.shp")
        self.assertEqual(result["status"], "error")
        self.assertIn("数据库未配置", result["message"])

    @patch("data_agent.database_tools.get_engine", return_value=MagicMock())
    def test_invalid_table_name(self, _mock):
        """Rejects table names with special characters."""
        result = import_to_postgis("test.shp", table_name="drop;table")
        self.assertEqual(result["status"], "error")
        self.assertIn("格式无效", result["message"])

    @patch("data_agent.database_tools.get_engine", return_value=MagicMock())
    def test_invalid_table_name_starts_with_digit(self, _mock):
        """Rejects table names starting with a digit."""
        result = import_to_postgis("test.shp", table_name="123abc")
        self.assertEqual(result["status"], "error")
        self.assertIn("格式无效", result["message"])

    @patch("data_agent.database_tools.get_engine", return_value=MagicMock())
    def test_invalid_if_exists(self, _mock):
        """Rejects invalid if_exists values."""
        result = import_to_postgis("test.shp", if_exists="drop")
        self.assertEqual(result["status"], "error")
        self.assertIn("if_exists", result["message"])

    @patch("data_agent.database_tools.get_engine", return_value=MagicMock())
    @patch("data_agent.database_tools._resolve_path", return_value="/nonexistent/file.shp")
    def test_file_not_found(self, _mock_resolve, _mock_engine):
        """Returns error when file cannot be loaded."""
        result = import_to_postgis("/nonexistent/file.shp", table_name="test_table")
        self.assertEqual(result["status"], "error")
        self.assertIn("读取文件失败", result["message"])

    @patch("data_agent.database_tools.get_engine", return_value=MagicMock())
    def test_auto_generate_table_name(self, _mock_engine):
        """Auto-generates a valid table name from filename."""
        import geopandas as gpd
        from shapely.geometry import Point

        gdf = gpd.GeoDataFrame(
            {"name": ["a"]}, geometry=[Point(0, 0)], crs="EPSG:4326"
        )
        with patch("data_agent.database_tools._resolve_path", return_value="my-data.shp"), \
             patch("data_agent.utils._load_spatial_data", return_value=gdf) as mock_load, \
             patch.object(gdf, "to_postgis") as mock_to_postgis, \
             patch("data_agent.database_tools.register_table_ownership", return_value={"status": "success"}), \
             patch("data_agent.database_tools.current_user_id") as mock_uid:
            mock_uid.get.return_value = "testuser"
            # Mock the connection context manager
            mock_conn = MagicMock()
            _mock_engine.return_value.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
            _mock_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)

            result = import_to_postgis("my-data.shp")

        self.assertEqual(result["status"], "success")
        self.assertTrue(result["table_name"].startswith("my_data_"))
        self.assertEqual(result["rows"], 1)
        self.assertEqual(result["srid"], 4326)


if __name__ == "__main__":
    unittest.main()

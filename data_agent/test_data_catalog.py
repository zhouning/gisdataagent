"""Tests for the Data Asset Catalog."""
import json
import os
import unittest
from unittest.mock import patch, MagicMock, PropertyMock


class TestDetectAssetType(unittest.TestCase):
    """Test file extension → asset type detection."""

    def test_raster_types(self):
        from data_agent.data_catalog import _detect_asset_type
        self.assertEqual(_detect_asset_type("data.tif"), "raster")
        self.assertEqual(_detect_asset_type("data.tiff"), "raster")
        self.assertEqual(_detect_asset_type("data.img"), "raster")

    def test_vector_types(self):
        from data_agent.data_catalog import _detect_asset_type
        self.assertEqual(_detect_asset_type("data.shp"), "vector")
        self.assertEqual(_detect_asset_type("data.geojson"), "vector")
        self.assertEqual(_detect_asset_type("data.gpkg"), "vector")
        self.assertEqual(_detect_asset_type("data.kml"), "vector")

    def test_tabular_types(self):
        from data_agent.data_catalog import _detect_asset_type
        self.assertEqual(_detect_asset_type("data.csv"), "tabular")
        self.assertEqual(_detect_asset_type("data.xlsx"), "tabular")

    def test_map_types(self):
        from data_agent.data_catalog import _detect_asset_type
        self.assertEqual(_detect_asset_type("map.html"), "map")
        self.assertEqual(_detect_asset_type("chart.png"), "map")

    def test_report_types(self):
        from data_agent.data_catalog import _detect_asset_type
        self.assertEqual(_detect_asset_type("report.docx"), "report")
        self.assertEqual(_detect_asset_type("report.pdf"), "report")

    def test_unknown_type(self):
        from data_agent.data_catalog import _detect_asset_type
        self.assertEqual(_detect_asset_type("data.xyz"), "other")
        self.assertEqual(_detect_asset_type("noext"), "other")


class TestExtractSpatialMetadata(unittest.TestCase):
    """Test spatial metadata extraction."""

    def test_nonexistent_file(self):
        from data_agent.data_catalog import _extract_spatial_metadata
        meta = _extract_spatial_metadata("/nonexistent/file.tif")
        self.assertEqual(meta["file_size_bytes"], 0)
        self.assertEqual(meta["crs"], "")
        self.assertIsNone(meta["spatial_extent"])

    def test_csv_file(self):
        import tempfile
        from data_agent.data_catalog import _extract_spatial_metadata
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode='w') as f:
            f.write("a,b\n1,2\n3,4\n")
            tmp = f.name
        try:
            meta = _extract_spatial_metadata(tmp)
            self.assertGreater(meta["file_size_bytes"], 0)
            self.assertEqual(meta["crs"], "")
        finally:
            os.unlink(tmp)


class TestTableInitialization(unittest.TestCase):
    """Test ensure_data_catalog_table."""

    @patch("data_agent.data_catalog.get_engine", return_value=None)
    def test_no_db_prints_warning(self, mock_engine):
        from data_agent.data_catalog import ensure_data_catalog_table
        # Should not raise
        ensure_data_catalog_table()

    @patch("data_agent.data_catalog.get_engine")
    def test_creates_table(self, mock_get_engine):
        mock_conn = MagicMock()
        mock_engine = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_get_engine.return_value = mock_engine

        from data_agent.data_catalog import ensure_data_catalog_table
        ensure_data_catalog_table()

        # Should have executed CREATE TABLE + indexes + commit
        self.assertTrue(mock_conn.execute.called)
        mock_conn.commit.assert_called_once()


class TestAutoRegister(unittest.TestCase):
    """Test auto_register_from_path."""

    @patch("data_agent.data_catalog.get_engine", return_value=None)
    def test_no_db_returns_none(self, mock_engine):
        from data_agent.data_catalog import auto_register_from_path
        result = auto_register_from_path("/tmp/data.csv")
        self.assertIsNone(result)

    @patch("data_agent.data_catalog.current_user_id")
    @patch("data_agent.data_catalog._inject_user_context")
    @patch("data_agent.data_catalog._extract_spatial_metadata")
    @patch("data_agent.data_catalog.get_engine")
    def test_registers_asset(self, mock_engine, mock_extract, mock_inject, mock_uid):
        mock_uid.get.return_value = "alice"
        mock_extract.return_value = {
            "file_size_bytes": 1024, "crs": "EPSG:4326", "srid": 4326,
            "feature_count": 10, "spatial_extent": {"minx": 0, "miny": 0, "maxx": 1, "maxy": 1},
        }

        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (42,)
        mock_conn.execute.return_value = mock_result

        mock_eng = MagicMock()
        mock_eng.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_eng.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_engine.return_value = mock_eng

        from data_agent.data_catalog import auto_register_from_path
        asset_id = auto_register_from_path("/tmp/data.shp", creation_tool="test_tool")
        self.assertEqual(asset_id, 42)
        mock_conn.commit.assert_called_once()


class TestRegisterToolOutput(unittest.TestCase):
    """Test the non-fatal wrapper."""

    @patch("data_agent.data_catalog.auto_register_from_path", return_value=99)
    def test_delegates(self, mock_register):
        from data_agent.data_catalog import register_tool_output
        result = register_tool_output("/tmp/out.csv", "query_database", {"sql": "SELECT 1"})
        self.assertEqual(result, 99)
        mock_register.assert_called_once()

    @patch("data_agent.data_catalog.auto_register_from_path", side_effect=Exception("boom"))
    def test_non_fatal(self, mock_register):
        from data_agent.data_catalog import register_tool_output
        result = register_tool_output("/tmp/out.csv", "test_tool")
        self.assertIsNone(result)


class TestListDataAssets(unittest.TestCase):
    """Test list_data_assets tool function."""

    @patch("data_agent.data_catalog.get_engine", return_value=None)
    def test_no_db(self, mock_engine):
        from data_agent.data_catalog import list_data_assets
        result = list_data_assets()
        self.assertEqual(result["status"], "error")

    @patch("data_agent.data_catalog._inject_user_context")
    @patch("data_agent.data_catalog.get_engine")
    def test_returns_assets(self, mock_engine, mock_inject):
        import datetime
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = [
            (1, "data.tif", "raster", "tif", "cloud", "EPSG:4326", 100,
             1024, '["遥感"]', "Land use data", "alice", False,
             datetime.datetime(2025, 1, 1)),
        ]

        mock_eng = MagicMock()
        mock_eng.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_eng.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_engine.return_value = mock_eng

        from data_agent.data_catalog import list_data_assets
        result = list_data_assets(asset_type="raster")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["assets"][0]["name"], "data.tif")

    @patch("data_agent.data_catalog._inject_user_context")
    @patch("data_agent.data_catalog.get_engine")
    def test_keyword_filter(self, mock_engine, mock_inject):
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = []

        mock_eng = MagicMock()
        mock_eng.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_eng.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_engine.return_value = mock_eng

        from data_agent.data_catalog import list_data_assets
        result = list_data_assets(keyword="DEM")
        self.assertEqual(result["status"], "success")
        # Verify the SQL contains ILIKE
        call_args = mock_conn.execute.call_args
        sql_str = str(call_args[0][0])
        self.assertIn("ILIKE", sql_str)


class TestDescribeDataAsset(unittest.TestCase):
    """Test describe_data_asset tool function."""

    @patch("data_agent.data_catalog.get_engine", return_value=None)
    def test_no_db(self, mock_engine):
        from data_agent.data_catalog import describe_data_asset
        result = describe_data_asset("1")
        self.assertEqual(result["status"], "error")

    @patch("data_agent.data_catalog._inject_user_context")
    @patch("data_agent.data_catalog.get_engine")
    def test_not_found(self, mock_engine, mock_inject):
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = None

        mock_eng = MagicMock()
        mock_eng.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_eng.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_engine.return_value = mock_eng

        from data_agent.data_catalog import describe_data_asset
        result = describe_data_asset("nonexistent")
        self.assertEqual(result["status"], "error")
        self.assertIn("not found", result["message"])


class TestSearchDataAssets(unittest.TestCase):
    """Test search_data_assets tool function."""

    @patch("data_agent.data_catalog.get_engine", return_value=None)
    def test_no_db(self, mock_engine):
        from data_agent.data_catalog import search_data_assets
        result = search_data_assets("DEM")
        self.assertEqual(result["status"], "error")

    @patch("data_agent.data_catalog._inject_user_context")
    @patch("data_agent.data_catalog.get_engine")
    def test_fuzzy_search(self, mock_engine, mock_inject):
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = [
            (1, "dem_banzhu.tif", "raster", "tif", "cloud", "EPSG:4326",
             1, 34000, '["DEM"]', "Digital elevation model for Banzhu",
             "admin", True),
            (2, "lulc_banzhu_2023.tif", "raster", "tif", "cloud", "EPSG:4326",
             1, 240000, '["LULC"]', "Land use cover 2023",
             "admin", True),
        ]

        mock_eng = MagicMock()
        mock_eng.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_eng.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_engine.return_value = mock_eng

        from data_agent.data_catalog import search_data_assets
        result = search_data_assets("dem banzhu")
        self.assertEqual(result["status"], "success")
        # dem_banzhu should rank higher (substring match)
        self.assertGreater(result["count"], 0)

    @patch("data_agent.data_catalog._inject_user_context")
    @patch("data_agent.data_catalog.get_engine")
    def test_substring_match_priority(self, mock_engine, mock_inject):
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = [
            (1, "dem_banzhu.tif", "raster", "tif", "local", "",
             1, 1000, "[]", "", "admin", False),
        ]

        mock_eng = MagicMock()
        mock_eng.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_eng.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_engine.return_value = mock_eng

        from data_agent.data_catalog import search_data_assets
        result = search_data_assets("dem")
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["assets"][0]["relevance"], 0.9)


class TestTagDataAsset(unittest.TestCase):
    """Test tag_data_asset tool function."""

    @patch("data_agent.data_catalog.get_engine", return_value=None)
    def test_no_db(self, mock_engine):
        from data_agent.data_catalog import tag_data_asset
        result = tag_data_asset("1", '["tag1"]')
        self.assertEqual(result["status"], "error")

    def test_invalid_json(self):
        from data_agent.data_catalog import tag_data_asset
        with patch("data_agent.data_catalog.get_engine") as mock_eng:
            mock_eng.return_value = MagicMock()
            result = tag_data_asset("1", "not json")
            self.assertEqual(result["status"], "error")
            self.assertIn("Invalid JSON", result["message"])

    def test_non_array_json(self):
        from data_agent.data_catalog import tag_data_asset
        with patch("data_agent.data_catalog.get_engine") as mock_eng:
            mock_eng.return_value = MagicMock()
            result = tag_data_asset("1", '{"key": "value"}')
            self.assertEqual(result["status"], "error")
            self.assertIn("JSON array", result["message"])


class TestDeleteDataAsset(unittest.TestCase):
    """Test delete_data_asset tool function."""

    @patch("data_agent.data_catalog._inject_user_context")
    @patch("data_agent.data_catalog.get_engine")
    def test_delete_success(self, mock_engine, mock_inject):
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 1
        mock_conn.execute.return_value = mock_result

        mock_eng = MagicMock()
        mock_eng.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_eng.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_engine.return_value = mock_eng

        from data_agent.data_catalog import delete_data_asset
        result = delete_data_asset("42")
        self.assertEqual(result["status"], "success")

    @patch("data_agent.data_catalog._inject_user_context")
    @patch("data_agent.data_catalog.get_engine")
    def test_delete_not_found(self, mock_engine, mock_inject):
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 0
        mock_conn.execute.return_value = mock_result

        mock_eng = MagicMock()
        mock_eng.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_eng.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_engine.return_value = mock_eng

        from data_agent.data_catalog import delete_data_asset
        result = delete_data_asset("999")
        self.assertEqual(result["status"], "error")
        self.assertIn("not found", result["message"])


class TestShareDataAsset(unittest.TestCase):
    """Test share_data_asset tool function."""

    @patch("data_agent.data_catalog.current_user_role")
    def test_non_admin_denied(self, mock_role):
        mock_role.get.return_value = "analyst"
        from data_agent.data_catalog import share_data_asset
        result = share_data_asset("1")
        self.assertEqual(result["status"], "error")
        self.assertIn("admin", result["message"])

    @patch("data_agent.data_catalog._inject_user_context")
    @patch("data_agent.data_catalog.get_engine")
    @patch("data_agent.data_catalog.current_user_role")
    def test_admin_can_share(self, mock_role, mock_engine, mock_inject):
        mock_role.get.return_value = "admin"

        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 1
        mock_conn.execute.return_value = mock_result

        mock_eng = MagicMock()
        mock_eng.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_eng.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_engine.return_value = mock_eng

        from data_agent.data_catalog import share_data_asset
        result = share_data_asset("1")
        self.assertEqual(result["status"], "success")


class TestRegisterDataAsset(unittest.TestCase):
    """Test register_data_asset tool function."""

    @patch("data_agent.data_catalog.get_engine", return_value=None)
    def test_no_db(self, mock_engine):
        from data_agent.data_catalog import register_data_asset
        result = register_data_asset("test.csv", "tabular", "local")
        self.assertEqual(result["status"], "error")

    @patch("data_agent.data_catalog.current_user_id")
    @patch("data_agent.data_catalog._inject_user_context")
    @patch("data_agent.data_catalog.get_engine")
    def test_register_manual(self, mock_engine, mock_inject, mock_uid):
        mock_uid.get.return_value = "bob"

        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (55,)
        mock_conn.execute.return_value = mock_result

        mock_eng = MagicMock()
        mock_eng.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_eng.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_engine.return_value = mock_eng

        from data_agent.data_catalog import register_data_asset
        result = register_data_asset(
            "external_dem.tif", "raster", "cloud",
            description="External DEM data", tags="DEM,terrain"
        )
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["asset_id"], 55)


if __name__ == "__main__":
    unittest.main()

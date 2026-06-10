"""Regression tests for uploaded dataset discovery and registration."""
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch


class TestUploadedDatasetVisibility(unittest.TestCase):
    def test_list_user_files_includes_nested_uploaded_shapefile(self):
        from data_agent.toolsets.file_tools import list_user_files

        with tempfile.TemporaryDirectory() as tmp:
            nested = os.path.join(tmp, "斑竹村10000")
            os.makedirs(nested)
            with open(os.path.join(tmp, "斑竹村10000.zip"), "wb") as f:
                f.write(b"zip")
            with open(os.path.join(nested, "斑竹村10000.shp"), "wb") as f:
                f.write(b"shp")
            with open(os.path.join(nested, "斑竹村10000.dbf"), "wb") as f:
                f.write(b"dbf")

            with patch("data_agent.user_context.get_user_upload_dir", return_value=tmp), \
                 patch("data_agent.obs_storage.is_obs_configured", return_value=False):
                result = list_user_files()

            self.assertIn("斑竹村10000.zip", result)
            self.assertIn("斑竹村10000/斑竹村10000.shp", result)
            self.assertNotIn("斑竹村10000/斑竹村10000.dbf", result)

    def test_resolve_path_accepts_user_upload_relative_subpath(self):
        from data_agent.gis_processors import _resolve_path

        with tempfile.TemporaryDirectory() as tmp:
            nested = os.path.join(tmp, "斑竹村10000")
            os.makedirs(nested)
            target = os.path.join(nested, "斑竹村10000.shp")
            with open(target, "wb") as f:
                f.write(b"shp")

            with patch("data_agent.gis_processors.get_user_upload_dir", return_value=tmp):
                self.assertEqual(
                    _resolve_path("斑竹村10000/斑竹村10000.shp"),
                    os.path.realpath(target),
                )
                self.assertEqual(_resolve_path("../outside.shp"), "../outside.shp")


class TestDataCatalogUpsert(unittest.TestCase):
    @patch("data_agent.data_catalog.current_user_id")
    @patch("data_agent.data_catalog._inject_user_context")
    @patch("data_agent.data_catalog._extract_spatial_metadata")
    @patch("data_agent.data_catalog.get_engine")
    def test_auto_register_does_not_require_unique_conflict_index(
        self, mock_engine, mock_extract, mock_inject, mock_uid
    ):
        mock_uid.get.return_value = "admin"
        mock_extract.return_value = {
            "file_size_bytes": 1024,
            "crs": "EPSG:4523",
            "srid": 4523,
            "feature_count": 10653,
            "spatial_extent": {"minx": 0, "miny": 0, "maxx": 1, "maxy": 1},
            "column_schema": [{"name": "DLMC", "type": "object"}],
        }

        update_result = MagicMock()
        update_result.fetchone.return_value = None
        insert_result = MagicMock()
        insert_result.fetchone.return_value = (42,)
        code_result = MagicMock()

        mock_conn = MagicMock()
        mock_conn.execute.side_effect = [update_result, insert_result, code_result]
        mock_eng = MagicMock()
        mock_eng.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_eng.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_engine.return_value = mock_eng

        from data_agent.data_catalog import auto_register_from_path

        asset_id = auto_register_from_path("/tmp/斑竹村10000.shp", owner="admin")

        self.assertEqual(asset_id, 42)
        sql_text = "\n".join(str(call.args[0]) for call in mock_conn.execute.call_args_list)
        self.assertIn("UPDATE agent_data_assets", sql_text)
        self.assertIn("INSERT INTO agent_data_assets", sql_text)
        self.assertNotIn("ON CONFLICT", sql_text)


if __name__ == "__main__":
    unittest.main()

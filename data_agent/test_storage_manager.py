"""Tests for StorageManager — data lake storage abstraction layer."""
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch


class TestStorageURI(unittest.TestCase):
    """Test URI parsing."""

    def test_bare_path(self):
        from data_agent.storage_manager import StorageURI
        uri = StorageURI("/data/file.shp")
        self.assertEqual(uri.scheme, "file")
        self.assertEqual(uri.path, "/data/file.shp")
        self.assertTrue(uri.is_local)
        self.assertFalse(uri.is_cloud)
        self.assertEqual(uri.filename, "file.shp")

    def test_s3_uri(self):
        from data_agent.storage_manager import StorageURI
        uri = StorageURI("s3://mybucket/users/admin/data.geojson")
        self.assertEqual(uri.scheme, "s3")
        self.assertEqual(uri.bucket, "mybucket")
        self.assertEqual(uri.key, "users/admin/data.geojson")
        self.assertTrue(uri.is_cloud)
        self.assertFalse(uri.is_local)
        self.assertEqual(uri.filename, "data.geojson")

    def test_obs_uri(self):
        from data_agent.storage_manager import StorageURI
        uri = StorageURI("obs://gisdatalake/admin/dem.tif")
        self.assertEqual(uri.scheme, "obs")
        self.assertTrue(uri.is_cloud)
        self.assertEqual(uri.bucket, "gisdatalake")
        self.assertEqual(uri.key, "admin/dem.tif")

    def test_postgis_uri(self):
        from data_agent.storage_manager import StorageURI
        uri = StorageURI("postgis://my_table")
        self.assertEqual(uri.scheme, "postgis")
        self.assertTrue(uri.is_postgis)
        self.assertEqual(uri.path, "my_table")

    def test_file_uri(self):
        from data_agent.storage_manager import StorageURI
        uri = StorageURI("file:///D:/data/test.csv")
        self.assertEqual(uri.scheme, "file")
        self.assertTrue(uri.is_local)
        # Windows path handling
        self.assertIn("data", uri.path)

    def test_relative_path(self):
        from data_agent.storage_manager import StorageURI
        uri = StorageURI("uploads/admin/test.shp")
        self.assertEqual(uri.scheme, "file")
        self.assertTrue(uri.is_local)
        self.assertEqual(uri.path, "uploads/admin/test.shp")


class TestStorageManagerLocal(unittest.TestCase):
    """Test StorageManager with local files."""

    def test_resolve_local(self):
        from data_agent.storage_manager import StorageManager
        sm = StorageManager()
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            f.write(b"a,b\n1,2\n")
            path = f.name
        try:
            resolved = sm.resolve(path)
            self.assertEqual(resolved, path)
        finally:
            os.unlink(path)

    def test_exists_local(self):
        from data_agent.storage_manager import StorageManager
        sm = StorageManager()
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"test")
            path = f.name
        try:
            self.assertTrue(sm.exists(path))
            self.assertFalse(sm.exists(path + ".nonexistent"))
        finally:
            os.unlink(path)

    def test_delete_local(self):
        from data_agent.storage_manager import StorageManager
        sm = StorageManager()
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"test")
            path = f.name
        self.assertTrue(os.path.isfile(path))
        result = sm.delete(path)
        self.assertTrue(result)
        self.assertFalse(os.path.isfile(path))

    def test_store_local_to_local(self):
        from data_agent.storage_manager import StorageManager
        sm = StorageManager()
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            f.write(b"a,b\n1,2\n")
            src = f.name
        try:
            uri = sm.store(src)
            self.assertTrue(uri.startswith("file://"))
        finally:
            os.unlink(src)

    def test_get_info(self):
        from data_agent.storage_manager import StorageManager
        sm = StorageManager()
        info = sm.get_info()
        self.assertIn("default_backend", info)
        self.assertIn("cloud_available", info)
        self.assertIn("cache_dir", info)
        self.assertIn("cache_size_mb", info)


class TestStorageManagerCloud(unittest.TestCase):
    """Test StorageManager cloud operations with mock."""

    def _make_sm_with_mock_cloud(self):
        from data_agent.storage_manager import StorageManager
        sm = StorageManager()
        mock_cloud = MagicMock()
        mock_cloud.get_bucket_name.return_value = "test-bucket"
        mock_cloud.exists.return_value = True
        mock_cloud.list_objects.return_value = [
            {"key": "admin/roads.shp", "filename": "roads.shp", "size": 1024, "last_modified": "2026-01-01"},
            {"key": "admin/dem.tif", "filename": "dem.tif", "size": 2048000, "last_modified": "2026-01-02"},
        ]
        mock_cloud.upload_file_smart.return_value = ["admin/test.csv"]
        sm._cloud = mock_cloud
        sm._cloud_checked = True
        return sm, mock_cloud

    def test_cloud_available(self):
        sm, _ = self._make_sm_with_mock_cloud()
        self.assertTrue(sm.cloud_available)

    def test_exists_cloud(self):
        sm, mock_cloud = self._make_sm_with_mock_cloud()
        result = sm.exists("s3://test-bucket/admin/roads.shp")
        self.assertTrue(result)
        mock_cloud.exists.assert_called_once_with("admin/roads.shp")

    def test_list_objects(self):
        sm, _ = self._make_sm_with_mock_cloud()
        objects = sm.list_objects("admin/")
        self.assertEqual(len(objects), 2)
        self.assertTrue(objects[0]["uri"].startswith("s3://"))
        self.assertEqual(objects[0]["filename"], "roads.shp")

    def test_store_to_cloud(self):
        sm, mock_cloud = self._make_sm_with_mock_cloud()
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            f.write(b"a,b\n1,2\n")
            path = f.name
        try:
            uri = sm.store(path, user_id="admin")
            # Default backend is 'local', so it should stay local
            self.assertTrue(uri.startswith("file://"))

            # Force cloud backend
            with patch.dict(os.environ, {"DEFAULT_STORAGE_BACKEND": "cloud"}):
                uri = sm.store(path, user_id="admin")
                self.assertTrue(uri.startswith("s3://"))
                mock_cloud.upload_file_smart.assert_called()
        finally:
            os.unlink(path)


class TestDefaultBackend(unittest.TestCase):
    """Test DEFAULT_STORAGE_BACKEND routing."""

    def test_default_is_local(self):
        from data_agent.storage_manager import get_default_backend
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DEFAULT_STORAGE_BACKEND", None)
            self.assertEqual(get_default_backend(), "local")

    def test_cloud_backend(self):
        from data_agent.storage_manager import get_default_backend
        with patch.dict(os.environ, {"DEFAULT_STORAGE_BACKEND": "cloud"}):
            self.assertEqual(get_default_backend(), "cloud")

    def test_postgis_backend(self):
        from data_agent.storage_manager import get_default_backend
        with patch.dict(os.environ, {"DEFAULT_STORAGE_BACKEND": "postgis"}):
            self.assertEqual(get_default_backend(), "postgis")


class TestSingleton(unittest.TestCase):
    """Test singleton pattern."""

    def test_singleton(self):
        from data_agent.storage_manager import get_storage_manager, reset_storage_manager
        reset_storage_manager()
        sm1 = get_storage_manager()
        sm2 = get_storage_manager()
        self.assertIs(sm1, sm2)

    def test_reset(self):
        from data_agent.storage_manager import get_storage_manager, reset_storage_manager
        sm1 = get_storage_manager()
        reset_storage_manager()
        sm2 = get_storage_manager()
        self.assertIsNot(sm1, sm2)


class TestStorageToolset(unittest.TestCase):
    """Test StorageToolset registration."""

    def test_toolset_in_registry(self):
        from data_agent.custom_skills import TOOLSET_NAMES
        self.assertIn("StorageToolset", TOOLSET_NAMES)

    def test_toolset_has_tools(self):
        from data_agent.toolsets.storage_tools import StorageToolset
        ts = StorageToolset()
        tools = ts.get_tools()
        self.assertEqual(len(tools), 4)
        names = [t.name for t in tools]
        self.assertIn("list_lake_assets", names)
        self.assertIn("upload_to_lake", names)
        self.assertIn("download_from_lake", names)
        self.assertIn("get_storage_info", names)


class TestResolvePathWithURI(unittest.TestCase):
    """Test that _resolve_path handles URI schemes."""

    @patch("data_agent.gis_processors.get_user_upload_dir", return_value="/tmp/test_user")
    def test_s3_uri_routed(self, _):
        """s3:// URIs should be routed to StorageManager."""
        from data_agent.gis_processors import _resolve_path
        with patch("data_agent.storage_manager.get_storage_manager") as mock_gsm:
            mock_sm = MagicMock()
            mock_sm.resolve.return_value = "/tmp/cached/file.shp"
            mock_gsm.return_value = mock_sm
            result = _resolve_path("s3://bucket/admin/file.shp")
            mock_sm.resolve.assert_called_once_with("s3://bucket/admin/file.shp")
            self.assertEqual(result, "/tmp/cached/file.shp")


if __name__ == "__main__":
    unittest.main()

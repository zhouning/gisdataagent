"""
Tests for OBS S3-compatible cloud storage integration.

- TestOBSConfiguration: is_obs_configured, get_s3_client
- TestGracefulDegradation: all ops return None/[] when OBS not configured
- TestShapefileBundling: sidecar file upload/delete logic
- TestResolvePathFallback: _resolve_path cloud fallback
- TestListUserFilesMerged: merged local+cloud view
- TestDeleteUserFileDualEnd: dual-end deletion
- TestSyncToObs: sync_to_obs helper
"""
import unittest
import os
import tempfile
from unittest.mock import patch, MagicMock, call
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))


_OBS_ENV = {
    'HUAWEI_OBS_AK': 'test_ak',
    'HUAWEI_OBS_SK': 'test_sk',
    'HUAWEI_OBS_SERVER': 'https://obs.cn-north-4.myhuaweicloud.com',
    'HUAWEI_OBS_BUCKET': 'test-bucket',
}

_NO_OBS_ENV = {
    'HUAWEI_OBS_AK': '',
    'HUAWEI_OBS_SK': '',
    'HUAWEI_OBS_SERVER': '',
    'HUAWEI_OBS_BUCKET': '',
}


class TestOBSConfiguration(unittest.TestCase):

    def setUp(self):
        from data_agent.cloud_storage import reset_cloud_adapter
        reset_cloud_adapter()

    def tearDown(self):
        from data_agent.cloud_storage import reset_cloud_adapter
        reset_cloud_adapter()

    @patch.dict(os.environ, _OBS_ENV)
    def test_is_configured_when_set(self):
        from data_agent.obs_storage import is_obs_configured
        self.assertTrue(is_obs_configured())

    @patch.dict(os.environ, _NO_OBS_ENV)
    def test_is_not_configured_when_empty(self):
        from data_agent.obs_storage import is_obs_configured
        self.assertFalse(is_obs_configured())

    @patch.dict(os.environ, _NO_OBS_ENV)
    def test_get_s3_client_returns_none_when_not_configured(self):
        from data_agent.obs_storage import get_s3_client
        client = get_s3_client()
        self.assertIsNone(client)


class TestGracefulDegradation(unittest.TestCase):
    """All operations must return None/[]/False/0 when OBS is not configured."""

    def setUp(self):
        from data_agent.cloud_storage import reset_cloud_adapter
        reset_cloud_adapter()

    def tearDown(self):
        from data_agent.cloud_storage import reset_cloud_adapter
        reset_cloud_adapter()

    @patch.dict(os.environ, _NO_OBS_ENV)
    def test_upload_returns_none(self):
        from data_agent.obs_storage import upload_to_obs
        self.assertIsNone(upload_to_obs('/nonexistent/file.shp', 'user1'))

    @patch.dict(os.environ, _NO_OBS_ENV)
    def test_download_returns_false(self):
        from data_agent.obs_storage import download_from_obs
        self.assertFalse(download_from_obs('user1/test.shp', '/tmp/test.shp'))

    @patch.dict(os.environ, _NO_OBS_ENV)
    def test_list_returns_empty(self):
        from data_agent.obs_storage import list_user_objects
        self.assertEqual(list_user_objects('user1'), [])

    @patch.dict(os.environ, _NO_OBS_ENV)
    def test_delete_returns_false(self):
        from data_agent.obs_storage import delete_from_obs
        self.assertFalse(delete_from_obs('user1/test.shp'))

    @patch.dict(os.environ, _NO_OBS_ENV)
    def test_presigned_url_returns_none(self):
        from data_agent.obs_storage import generate_presigned_url
        self.assertIsNone(generate_presigned_url('user1/test.shp'))

    @patch.dict(os.environ, _NO_OBS_ENV)
    def test_upload_file_smart_returns_empty(self):
        from data_agent.obs_storage import upload_file_smart
        self.assertEqual(upload_file_smart('/nonexistent/file.csv', 'user1'), [])


class TestShapefileBundling(unittest.TestCase):

    def setUp(self):
        from data_agent.cloud_storage import reset_cloud_adapter
        reset_cloud_adapter()

    def tearDown(self):
        from data_agent.cloud_storage import reset_cloud_adapter
        reset_cloud_adapter()

    @patch('data_agent.cloud_storage.get_cloud_adapter')
    @patch('os.path.exists')
    def test_upload_bundle_includes_sidecars(self, mock_exists, mock_get):
        mock_exists.return_value = True
        adapter = MagicMock()
        adapter.upload_shapefile_bundle.return_value = [
            f"user1/test{ext}" for ext in
            ['.shp', '.cpg', '.dbf', '.prj', '.shx', '.sbn', '.sbx', '.shp.xml']
        ]
        mock_get.return_value = adapter
        from data_agent.obs_storage import upload_shapefile_bundle
        keys = upload_shapefile_bundle('/tmp/test.shp', 'user1')
        self.assertEqual(len(keys), 8)
        self.assertIn('user1/test.shp', keys)
        self.assertIn('user1/test.dbf', keys)
        self.assertIn('user1/test.prj', keys)

    @patch('data_agent.cloud_storage.get_cloud_adapter')
    @patch('os.path.exists')
    def test_upload_bundle_skips_missing_sidecars(self, mock_exists, mock_get):
        adapter = MagicMock()
        adapter.upload_shapefile_bundle.return_value = [
            'user1/test.shp', 'user1/test.dbf'
        ]
        mock_get.return_value = adapter
        from data_agent.obs_storage import upload_shapefile_bundle
        keys = upload_shapefile_bundle('/tmp/test.shp', 'user1')
        self.assertEqual(len(keys), 2)

    @patch('data_agent.cloud_storage.get_cloud_adapter')
    @patch('os.path.exists')
    def test_smart_upload_detects_shp(self, mock_exists, mock_get):
        mock_exists.return_value = True
        adapter = MagicMock()
        adapter.upload_file_smart.return_value = [
            'user1/data.shp', 'user1/data.dbf', 'user1/data.shx'
        ]
        mock_get.return_value = adapter
        from data_agent.obs_storage import upload_file_smart
        keys = upload_file_smart('/tmp/data.shp', 'user1')
        self.assertGreater(len(keys), 1)  # Bundle

    @patch('data_agent.cloud_storage.get_cloud_adapter')
    def test_smart_upload_single_csv(self, mock_get):
        adapter = MagicMock()
        adapter.upload_file_smart.return_value = ['user1/data.csv']
        mock_get.return_value = adapter
        from data_agent.obs_storage import upload_file_smart
        keys = upload_file_smart('/tmp/data.csv', 'user1')
        self.assertEqual(len(keys), 1)
        self.assertEqual(keys[0], 'user1/data.csv')


class TestResolvePathFallback(unittest.TestCase):
    """Test that _resolve_path falls back to OBS download."""

    @patch('data_agent.obs_storage.download_file_smart')
    @patch('data_agent.obs_storage.is_obs_configured', return_value=True)
    @patch('data_agent.user_context.current_user_id')
    def test_cloud_fallback_triggered(self, mock_uid, mock_configured, mock_download):
        mock_uid.get.return_value = 'testuser'
        # Create a temp file that download_file_smart would "produce"
        with tempfile.NamedTemporaryFile(suffix='.csv', delete=False) as f:
            tmp = f.name
            f.write(b"col1,col2\n1,2\n")
        try:
            mock_download.return_value = tmp
            from data_agent.gis_processors import _resolve_path
            result = _resolve_path('nonexistent_file_xyz.csv')
            # Should have attempted cloud download
            mock_download.assert_called_once()
            self.assertEqual(result, tmp)
        finally:
            os.unlink(tmp)

    def test_local_file_not_triggers_cloud(self):
        """If file exists locally, should not try cloud."""
        with tempfile.NamedTemporaryFile(suffix='.csv', delete=False) as f:
            tmp = f.name
            f.write(b"data")
        try:
            from data_agent.gis_processors import _resolve_path
            with patch('data_agent.obs_storage.download_file_smart') as mock_dl:
                result = _resolve_path(tmp)
                mock_dl.assert_not_called()
                self.assertEqual(result, tmp)
        finally:
            os.unlink(tmp)


class TestSyncToObs(unittest.TestCase):

    @patch('data_agent.obs_storage.upload_file_smart')
    @patch('data_agent.obs_storage.is_obs_configured', return_value=True)
    @patch('data_agent.user_context.current_user_id')
    def test_sync_calls_upload(self, mock_uid, mock_configured, mock_upload):
        mock_uid.get.return_value = 'admin'
        mock_upload.return_value = ['admin/test.csv']
        from data_agent.gis_processors import sync_to_obs
        sync_to_obs('/tmp/test.csv')
        mock_upload.assert_called_once_with('/tmp/test.csv', 'admin')

    @patch('data_agent.obs_storage.is_obs_configured', return_value=False)
    def test_sync_skips_when_not_configured(self, mock_configured):
        from data_agent.gis_processors import sync_to_obs
        with patch('data_agent.obs_storage.upload_file_smart') as mock_upload:
            sync_to_obs('/tmp/test.csv')
            mock_upload.assert_not_called()


class TestSyncToolOutput(unittest.TestCase):

    @patch('data_agent.app.upload_file_smart')
    @patch('data_agent.app.is_obs_configured', return_value=True)
    @patch('data_agent.app.current_user_id')
    def test_sync_dict_with_path(self, mock_uid, mock_configured, mock_upload):
        mock_uid.get.return_value = 'admin'
        mock_upload.return_value = ['admin/out.csv']
        from data_agent.app import _sync_tool_output_to_obs
        with tempfile.NamedTemporaryFile(suffix='.csv', delete=False) as f:
            tmp = f.name
        try:
            _sync_tool_output_to_obs({"output_path": tmp, "status": "success"})
            mock_upload.assert_called_once_with(tmp, 'admin')
        finally:
            os.unlink(tmp)

    @patch('data_agent.app.is_obs_configured', return_value=False)
    def test_sync_skips_when_not_configured(self, mock_configured):
        from data_agent.app import _sync_tool_output_to_obs
        with patch('data_agent.app.upload_file_smart') as mock_upload:
            _sync_tool_output_to_obs({"output_path": "/tmp/x.csv"})
            mock_upload.assert_not_called()


if __name__ == "__main__":
    unittest.main()

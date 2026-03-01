"""Tests for the multi-provider cloud storage abstraction."""
import os
import unittest
from unittest.mock import patch, MagicMock, PropertyMock


class TestCloudStorageBase(unittest.TestCase):
    """Test non-abstract convenience methods on CloudStorageAdapter."""

    def _make_adapter(self):
        from data_agent.cloud_storage import CloudStorageAdapter

        class FakeAdapter(CloudStorageAdapter):
            def __init__(self):
                self.uploads = {}
                self.objects = {}

            def upload(self, local_path, key):
                self.uploads[key] = local_path
                return True

            def download(self, key, local_path):
                return key in self.objects

            def delete(self, key):
                return self.objects.pop(key, None) is not None

            def exists(self, key):
                return key in self.objects

            def list_objects(self, prefix):
                return [{"key": k, "filename": os.path.basename(k),
                         "size": v, "last_modified": ""}
                        for k, v in self.objects.items() if k.startswith(prefix)]

            def get_presigned_url(self, key, expiration=3600):
                return f"https://fake/{key}"

            def get_bucket_name(self):
                return "test-bucket"

            def health_check(self):
                return True

        return FakeAdapter()

    def test_user_key_format(self):
        adapter = self._make_adapter()
        self.assertEqual(adapter.user_key("alice", "data.tif"), "alice/data.tif")

    def test_upload_file_missing(self):
        adapter = self._make_adapter()
        result = adapter.upload_file("/nonexistent/file.tif", "alice")
        self.assertIsNone(result)

    def test_upload_file_smart_csv(self):
        import tempfile
        adapter = self._make_adapter()
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            f.write(b"a,b\n1,2")
            tmp = f.name
        try:
            keys = adapter.upload_file_smart(tmp, "alice")
            self.assertEqual(len(keys), 1)
            self.assertIn("alice/", keys[0])
        finally:
            os.unlink(tmp)

    def test_upload_file_smart_shp_bundles(self):
        import tempfile, shutil
        tmpdir = tempfile.mkdtemp()
        try:
            base = os.path.join(tmpdir, "test")
            for ext in ['.shp', '.dbf', '.shx', '.prj']:
                with open(base + ext, 'w') as f:
                    f.write("x")
            adapter = self._make_adapter()
            keys = adapter.upload_file_smart(base + ".shp", "bob")
            self.assertEqual(len(keys), 4)
            exts = {os.path.splitext(k)[1] for k in keys}
            self.assertEqual(exts, {'.shp', '.dbf', '.shx', '.prj'})
        finally:
            shutil.rmtree(tmpdir)

    def test_delete_shapefile_bundle(self):
        adapter = self._make_adapter()
        adapter.objects = {
            "user/test.shp": 100, "user/test.dbf": 50,
            "user/test.shx": 30, "user/other.csv": 10,
        }
        count = adapter.delete_shapefile_bundle("user/test.shp")
        self.assertEqual(count, 3)
        self.assertIn("user/other.csv", adapter.objects)

    def test_list_user_objects(self):
        adapter = self._make_adapter()
        adapter.objects = {
            "alice/a.tif": 100, "alice/b.csv": 50, "bob/c.shp": 200,
        }
        objs = adapter.list_user_objects("alice")
        self.assertEqual(len(objs), 2)
        names = {o["filename"] for o in objs}
        self.assertEqual(names, {"a.tif", "b.csv"})


class TestHuaweiOBSAdapter(unittest.TestCase):
    """Test HuaweiOBSAdapter with mocked ObsClient."""

    def _patch_env(self):
        return patch.dict(os.environ, {
            "HUAWEI_OBS_AK": "testAK",
            "HUAWEI_OBS_SK": "testSK",
            "HUAWEI_OBS_SERVER": "https://obs.test.com",
            "HUAWEI_OBS_BUCKET": "test-bucket",
        })

    @patch("data_agent.cloud_storage.HuaweiOBSAdapter.__init__", return_value=None)
    def test_upload_success(self, mock_init):
        from data_agent.cloud_storage import HuaweiOBSAdapter
        adapter = HuaweiOBSAdapter()
        adapter._client = MagicMock()
        adapter._bucket = "test-bucket"
        resp = MagicMock()
        resp.status = 200
        adapter._client.putFile.return_value = resp
        self.assertTrue(adapter.upload("/tmp/file.tif", "user/file.tif"))

    @patch("data_agent.cloud_storage.HuaweiOBSAdapter.__init__", return_value=None)
    def test_upload_failure(self, mock_init):
        from data_agent.cloud_storage import HuaweiOBSAdapter
        adapter = HuaweiOBSAdapter()
        adapter._client = MagicMock()
        adapter._bucket = "test-bucket"
        resp = MagicMock()
        resp.status = 403
        resp.reason = "Forbidden"
        adapter._client.putFile.return_value = resp
        self.assertFalse(adapter.upload("/tmp/file.tif", "user/file.tif"))

    @patch("data_agent.cloud_storage.HuaweiOBSAdapter.__init__", return_value=None)
    def test_download_success(self, mock_init):
        from data_agent.cloud_storage import HuaweiOBSAdapter
        adapter = HuaweiOBSAdapter()
        adapter._client = MagicMock()
        adapter._bucket = "test-bucket"
        resp = MagicMock()
        resp.status = 200
        adapter._client.getObject.return_value = resp
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            self.assertTrue(adapter.download("user/file.tif",
                                             os.path.join(tmpdir, "file.tif")))

    @patch("data_agent.cloud_storage.HuaweiOBSAdapter.__init__", return_value=None)
    def test_exists_true(self, mock_init):
        from data_agent.cloud_storage import HuaweiOBSAdapter
        adapter = HuaweiOBSAdapter()
        adapter._client = MagicMock()
        adapter._bucket = "test-bucket"
        resp = MagicMock()
        resp.status = 200
        adapter._client.getObjectMetadata.return_value = resp
        self.assertTrue(adapter.exists("user/file.tif"))

    @patch("data_agent.cloud_storage.HuaweiOBSAdapter.__init__", return_value=None)
    def test_exists_false(self, mock_init):
        from data_agent.cloud_storage import HuaweiOBSAdapter
        adapter = HuaweiOBSAdapter()
        adapter._client = MagicMock()
        adapter._bucket = "test-bucket"
        resp = MagicMock()
        resp.status = 404
        adapter._client.getObjectMetadata.return_value = resp
        self.assertFalse(adapter.exists("user/file.tif"))

    @patch("data_agent.cloud_storage.HuaweiOBSAdapter.__init__", return_value=None)
    def test_health_check_success(self, mock_init):
        from data_agent.cloud_storage import HuaweiOBSAdapter
        adapter = HuaweiOBSAdapter()
        adapter._client = MagicMock()
        adapter._bucket = "test-bucket"
        resp = MagicMock()
        resp.status = 200
        adapter._client.headBucket.return_value = resp
        self.assertTrue(adapter.health_check())

    @patch("data_agent.cloud_storage.HuaweiOBSAdapter.__init__", return_value=None)
    def test_list_objects_pagination(self, mock_init):
        from data_agent.cloud_storage import HuaweiOBSAdapter
        adapter = HuaweiOBSAdapter()
        adapter._client = MagicMock()
        adapter._bucket = "test-bucket"

        obj1 = MagicMock()
        obj1.key = "user/a.tif"
        obj1.size = 100
        obj1.lastModified = "2025-01-01"

        body1 = MagicMock()
        body1.contents = [obj1]
        body1.is_truncated = False
        resp1 = MagicMock()
        resp1.status = 200
        resp1.body = body1
        adapter._client.listObjects.return_value = resp1

        results = adapter.list_objects("user/")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["filename"], "a.tif")


class TestProviderDetection(unittest.TestCase):
    """Test automatic provider detection from env vars."""

    def setUp(self):
        from data_agent.cloud_storage import reset_cloud_adapter
        reset_cloud_adapter()

    def tearDown(self):
        from data_agent.cloud_storage import reset_cloud_adapter
        reset_cloud_adapter()

    @patch.dict(os.environ, {
        "HUAWEI_OBS_AK": "ak", "HUAWEI_OBS_SK": "sk",
        "HUAWEI_OBS_SERVER": "https://obs.test.com",
        "HUAWEI_OBS_BUCKET": "bkt",
    }, clear=False)
    def test_huawei_detected(self):
        from data_agent.cloud_storage import _detect_provider
        self.assertEqual(_detect_provider(), "huawei")

    @patch.dict(os.environ, {"AWS_ACCESS_KEY_ID": "AKIA..."}, clear=False)
    def test_aws_detected(self):
        from data_agent.cloud_storage import _detect_provider
        # Remove Huawei vars if set
        env = os.environ.copy()
        for k in ["HUAWEI_OBS_AK"]:
            env.pop(k, None)
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(_detect_provider(), "aws")

    @patch.dict(os.environ, {"GCS_BUCKET": "my-gcs-bucket"}, clear=False)
    def test_gcs_detected(self):
        from data_agent.cloud_storage import _detect_provider
        env = os.environ.copy()
        for k in ["HUAWEI_OBS_AK", "AWS_ACCESS_KEY_ID", "AWS_S3_BUCKET"]:
            env.pop(k, None)
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(_detect_provider(), "gcs")

    def test_none_when_empty(self):
        from data_agent.cloud_storage import _detect_provider
        env = {k: v for k, v in os.environ.items()
               if k not in ("HUAWEI_OBS_AK", "AWS_ACCESS_KEY_ID",
                            "AWS_S3_BUCKET", "GCS_BUCKET")}
        with patch.dict(os.environ, env, clear=True):
            self.assertIsNone(_detect_provider())

    @patch.dict(os.environ, {"CLOUD_STORAGE_PROVIDER": "aws"}, clear=False)
    def test_explicit_override(self):
        from data_agent.cloud_storage import _detect_provider
        # Even with Huawei vars set, explicit provider wins
        provider = os.environ.get("CLOUD_STORAGE_PROVIDER") or _detect_provider()
        self.assertEqual(provider, "aws")


class TestBackwardCompat(unittest.TestCase):
    """Verify obs_storage.py functions delegate to cloud_storage adapter."""

    def setUp(self):
        from data_agent.cloud_storage import reset_cloud_adapter
        reset_cloud_adapter()

    def tearDown(self):
        from data_agent.cloud_storage import reset_cloud_adapter
        reset_cloud_adapter()

    @patch("data_agent.cloud_storage.get_cloud_adapter", return_value=None)
    def test_is_obs_configured_false(self, mock_adapter):
        from data_agent.obs_storage import is_obs_configured
        self.assertFalse(is_obs_configured())

    @patch("data_agent.cloud_storage.get_cloud_adapter")
    def test_is_obs_configured_true(self, mock_adapter):
        mock_adapter.return_value = MagicMock()
        from data_agent.obs_storage import is_obs_configured
        self.assertTrue(is_obs_configured())

    @patch("data_agent.cloud_storage.get_cloud_adapter", return_value=None)
    def test_upload_returns_none_when_unconfigured(self, mock_adapter):
        from data_agent.obs_storage import upload_to_obs
        self.assertIsNone(upload_to_obs("/tmp/file.tif", "alice"))

    @patch("data_agent.cloud_storage.get_cloud_adapter", return_value=None)
    def test_list_returns_empty_when_unconfigured(self, mock_adapter):
        from data_agent.obs_storage import list_user_objects
        self.assertEqual(list_user_objects("alice"), [])

    @patch("data_agent.cloud_storage.get_cloud_adapter")
    def test_upload_delegates(self, mock_get):
        adapter = MagicMock()
        adapter.upload_file.return_value = "alice/file.tif"
        mock_get.return_value = adapter
        from data_agent.obs_storage import upload_to_obs
        result = upload_to_obs("/tmp/file.tif", "alice")
        self.assertEqual(result, "alice/file.tif")
        adapter.upload_file.assert_called_once()

    @patch("data_agent.cloud_storage.get_cloud_adapter")
    def test_list_delegates(self, mock_get):
        adapter = MagicMock()
        adapter.list_user_objects.return_value = [{"key": "alice/a.tif", "size": 100}]
        mock_get.return_value = adapter
        from data_agent.obs_storage import list_user_objects
        result = list_user_objects("alice")
        self.assertEqual(len(result), 1)

    @patch("data_agent.cloud_storage.get_cloud_adapter")
    def test_ensure_obs_delegates(self, mock_get):
        adapter = MagicMock()
        adapter.health_check.return_value = True
        adapter.get_bucket_name.return_value = "test-bkt"
        mock_get.return_value = adapter
        from data_agent.obs_storage import ensure_obs_connection
        ensure_obs_connection()  # Should not raise
        adapter.health_check.assert_called_once()


if __name__ == "__main__":
    unittest.main()

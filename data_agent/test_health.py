"""Tests for health check and system diagnostics module."""

import unittest
from unittest.mock import patch, MagicMock


class TestLivenessCheck(unittest.TestCase):
    """Liveness probe should always succeed if the process is alive."""

    def test_liveness_always_ok(self):
        from data_agent.health import liveness_check
        result = liveness_check()
        self.assertEqual(result["status"], "ok")

    def test_liveness_has_uptime(self):
        from data_agent.health import liveness_check
        result = liveness_check()
        self.assertIn("uptime_seconds", result)
        self.assertIsInstance(result["uptime_seconds"], float)
        self.assertGreaterEqual(result["uptime_seconds"], 0)


class TestDatabaseCheck(unittest.TestCase):
    """Database health check should handle ok/error/unconfigured states."""

    @patch("data_agent.health.get_engine", return_value=None)
    def test_db_unconfigured(self, _mock):
        from data_agent.health import check_database
        result = check_database()
        self.assertEqual(result["status"], "unconfigured")

    @patch("data_agent.health.get_engine")
    def test_db_ok(self, mock_engine):
        mock_conn = MagicMock()
        mock_engine.return_value.connect.return_value.__enter__ = lambda s: mock_conn
        mock_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)
        from data_agent.health import check_database
        result = check_database()
        self.assertEqual(result["status"], "ok")
        self.assertGreaterEqual(result["latency_ms"], 0)

    @patch("data_agent.health.get_engine")
    def test_db_error(self, mock_engine):
        mock_engine.return_value.connect.side_effect = Exception("connection refused")
        from data_agent.health import check_database
        result = check_database()
        self.assertEqual(result["status"], "error")
        self.assertIn("connection refused", result["detail"])


class TestCloudStorageCheck(unittest.TestCase):
    """Cloud storage health check should handle ok/error/unconfigured states."""

    def setUp(self):
        from data_agent.cloud_storage import reset_cloud_adapter
        reset_cloud_adapter()

    def tearDown(self):
        from data_agent.cloud_storage import reset_cloud_adapter
        reset_cloud_adapter()

    @patch("data_agent.health.get_cloud_adapter", return_value=None)
    def test_cloud_unconfigured(self, _mock):
        from data_agent.health import check_cloud_storage
        result = check_cloud_storage()
        self.assertEqual(result["status"], "unconfigured")

    @patch("data_agent.health.get_cloud_adapter")
    def test_cloud_ok(self, mock_get):
        adapter = MagicMock()
        adapter.health_check.return_value = True
        adapter.get_bucket_name.return_value = "test-bucket"
        type(adapter).__name__ = "HuaweiOBSAdapter"
        mock_get.return_value = adapter
        from data_agent.health import check_cloud_storage
        result = check_cloud_storage()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["bucket"], "test-bucket")
        self.assertEqual(result["provider"], "HuaweiOBS")

    @patch("data_agent.health.get_cloud_adapter")
    def test_cloud_error(self, mock_get):
        adapter = MagicMock()
        adapter.health_check.return_value = False
        adapter.get_bucket_name.return_value = "test-bucket"
        type(adapter).__name__ = "AWSS3Adapter"
        mock_get.return_value = adapter
        from data_agent.health import check_cloud_storage
        result = check_cloud_storage()
        self.assertEqual(result["status"], "error")

    @patch("data_agent.health.get_cloud_adapter")
    def test_cloud_exception(self, mock_get):
        adapter = MagicMock()
        adapter.health_check.side_effect = Exception("timeout")
        mock_get.return_value = adapter
        from data_agent.health import check_cloud_storage
        result = check_cloud_storage()
        self.assertEqual(result["status"], "error")


class TestRedisCheck(unittest.TestCase):
    """Redis health check should handle ok/unconfigured states."""

    @patch("data_agent.health.get_stream_engine")
    def test_redis_ok(self, mock_get):
        engine = MagicMock()
        engine._use_redis = True
        engine._redis = MagicMock()
        mock_get.return_value = engine
        from data_agent.health import check_redis
        result = check_redis()
        self.assertEqual(result["status"], "ok")

    @patch("data_agent.health.get_stream_engine")
    def test_redis_unconfigured_no_redis(self, mock_get):
        engine = MagicMock()
        engine._use_redis = False
        engine._redis = None
        mock_get.return_value = engine
        from data_agent.health import check_redis
        result = check_redis()
        self.assertEqual(result["status"], "unconfigured")

    @patch("data_agent.health.get_stream_engine", return_value=None)
    def test_redis_no_engine(self, _mock):
        from data_agent.health import check_redis
        result = check_redis()
        self.assertEqual(result["status"], "unconfigured")


class TestSessionServiceCheck(unittest.TestCase):
    """Session service check should detect backend type."""

    def test_session_db_backed(self):
        from data_agent.health import check_session_service
        svc = MagicMock()
        type(svc).__name__ = "DatabaseSessionService"
        result = check_session_service(svc)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["backend"], "postgresql")

    def test_session_in_memory(self):
        from data_agent.health import check_session_service
        svc = MagicMock()
        type(svc).__name__ = "InMemorySessionService"
        result = check_session_service(svc)
        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["backend"], "memory")

    def test_session_none(self):
        from data_agent.health import check_session_service
        result = check_session_service(None)
        self.assertEqual(result["status"], "unconfigured")


class TestReadinessCheck(unittest.TestCase):
    """Readiness probe depends on database status."""

    @patch("data_agent.health.check_database")
    def test_ready_with_db(self, mock_db):
        mock_db.return_value = {"status": "ok", "latency_ms": 5.0, "detail": "Connected"}
        from data_agent.health import readiness_check
        result = readiness_check()
        self.assertEqual(result["status"], "ok")

    @patch("data_agent.health.check_database")
    def test_not_ready_db_error(self, mock_db):
        mock_db.return_value = {"status": "error", "latency_ms": 0, "detail": "refused"}
        from data_agent.health import readiness_check
        result = readiness_check()
        self.assertEqual(result["status"], "not_ready")

    @patch("data_agent.health.check_database")
    def test_ready_db_unconfigured(self, mock_db):
        mock_db.return_value = {"status": "unconfigured", "latency_ms": 0, "detail": "No creds"}
        from data_agent.health import readiness_check
        result = readiness_check()
        # Unconfigured DB = local-only mode, still considered ready
        self.assertEqual(result["status"], "ok")


class TestSystemStatus(unittest.TestCase):
    """System status should include all expected sections."""

    @patch("data_agent.health.check_database")
    @patch("data_agent.health.check_cloud_storage")
    @patch("data_agent.health.check_redis")
    @patch("data_agent.health._get_feature_flags")
    def test_system_status_structure(self, mock_flags, mock_redis, mock_cloud, mock_db):
        mock_db.return_value = {"status": "ok", "latency_ms": 3.0, "detail": "Connected"}
        mock_cloud.return_value = {"status": "unconfigured", "provider": "", "bucket": ""}
        mock_redis.return_value = {"status": "unconfigured"}
        mock_flags.return_value = {"dynamic_planner": True, "arcpy": False}

        from data_agent.health import get_system_status
        result = get_system_status()

        self.assertIn("version", result)
        self.assertIn("uptime_seconds", result)
        self.assertIn("python_version", result)
        self.assertIn("platform", result)
        self.assertIn("features", result)
        self.assertIn("subsystems", result)

    @patch("data_agent.health.check_database")
    @patch("data_agent.health.check_cloud_storage")
    @patch("data_agent.health.check_redis")
    @patch("data_agent.health._get_feature_flags")
    def test_system_status_subsystems(self, mock_flags, mock_redis, mock_cloud, mock_db):
        mock_db.return_value = {"status": "ok", "latency_ms": 3.0, "detail": "Connected"}
        mock_cloud.return_value = {"status": "ok", "provider": "HuaweiOBS", "bucket": "gisdatalake"}
        mock_redis.return_value = {"status": "ok"}
        mock_flags.return_value = {}

        from data_agent.health import get_system_status
        svc = MagicMock()
        type(svc).__name__ = "DatabaseSessionService"
        result = get_system_status(session_svc=svc)

        self.assertEqual(result["subsystems"]["database"]["status"], "ok")
        self.assertEqual(result["subsystems"]["cloud_storage"]["status"], "ok")
        self.assertEqual(result["subsystems"]["redis"]["status"], "ok")
        self.assertEqual(result["subsystems"]["session_service"]["status"], "ok")


class TestStartupSummary(unittest.TestCase):
    """Startup summary should produce a readable banner."""

    @patch("data_agent.health.check_database")
    @patch("data_agent.health.check_cloud_storage")
    @patch("data_agent.health.check_redis")
    @patch("data_agent.health.check_session_service")
    @patch("data_agent.health._get_feature_flags")
    def test_format_startup_summary_all_ok(self, mock_flags, mock_session,
                                            mock_redis, mock_cloud, mock_db):
        mock_db.return_value = {"status": "ok", "latency_ms": 5.0, "detail": "Connected"}
        mock_cloud.return_value = {"status": "ok", "provider": "HuaweiOBS", "bucket": "gisdatalake"}
        mock_redis.return_value = {"status": "ok"}
        mock_session.return_value = {"status": "ok", "backend": "postgresql"}
        mock_flags.return_value = {"dynamic_planner": True, "arcpy": False,
                                   "wecom": True, "dingtalk": False, "feishu": False}

        from data_agent.health import format_startup_summary
        banner = format_startup_summary()
        self.assertIn("GIS Data Agent", banner)
        self.assertIn("[OK] Database", banner)
        self.assertIn("[OK] Cloud Storage", banner)
        self.assertIn("Dynamic Planner: Yes", banner)
        self.assertIn("wecom", banner)

    @patch("data_agent.health.check_database")
    @patch("data_agent.health.check_cloud_storage")
    @patch("data_agent.health.check_redis")
    @patch("data_agent.health.check_session_service")
    @patch("data_agent.health._get_feature_flags")
    def test_format_startup_summary_partial_failure(self, mock_flags, mock_session,
                                                     mock_redis, mock_cloud, mock_db):
        mock_db.return_value = {"status": "error", "latency_ms": 0, "detail": "refused"}
        mock_cloud.return_value = {"status": "unconfigured", "provider": "", "bucket": ""}
        mock_redis.return_value = {"status": "unconfigured"}
        mock_session.return_value = {"status": "degraded", "backend": "memory"}
        mock_flags.return_value = {"dynamic_planner": True, "arcpy": False,
                                   "wecom": False, "dingtalk": False, "feishu": False}

        from data_agent.health import format_startup_summary
        banner = format_startup_summary()
        self.assertIn("[!!] Database", banner)
        self.assertIn("[--] Cloud Storage", banner)
        self.assertIn("[--] Session", banner)
        self.assertIn("None configured", banner)

    @patch("data_agent.health.check_database")
    @patch("data_agent.health.check_cloud_storage")
    @patch("data_agent.health.check_redis")
    @patch("data_agent.health.check_session_service")
    @patch("data_agent.health._get_feature_flags")
    def test_format_startup_summary_no_db(self, mock_flags, mock_session,
                                           mock_redis, mock_cloud, mock_db):
        mock_db.return_value = {"status": "unconfigured", "latency_ms": 0,
                                "detail": "No database credentials"}
        mock_cloud.return_value = {"status": "unconfigured", "provider": "", "bucket": ""}
        mock_redis.return_value = {"status": "unconfigured"}
        mock_session.return_value = {"status": "degraded", "backend": "memory"}
        mock_flags.return_value = {"dynamic_planner": False, "arcpy": False,
                                   "wecom": False, "dingtalk": False, "feishu": False}

        from data_agent.health import format_startup_summary
        banner = format_startup_summary()
        self.assertIn("[--] Database", banner)
        self.assertIn("Not configured", banner)
        self.assertIn("Dynamic Planner: No", banner)


class TestGetVersion(unittest.TestCase):
    """Version detection fallback."""

    def test_version_fallback(self):
        from data_agent.health import _get_version
        version = _get_version()
        self.assertIsInstance(version, str)
        self.assertTrue(len(version) > 0)


if __name__ == "__main__":
    unittest.main()

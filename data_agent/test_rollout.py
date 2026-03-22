"""Tests for AgentOps P0/P1 enhancements — feature flags, failure-to-eval, rollout."""
import os
import unittest
from unittest.mock import patch, MagicMock


class TestFeatureFlags(unittest.TestCase):
    """Test feature flag system."""

    def test_parse_env_flags(self):
        from data_agent.feature_flags import _parse_env_flags
        with patch.dict(os.environ, {"FEATURE_FLAGS": "new_ui:true,beta:false,alpha"}):
            flags = _parse_env_flags()
            self.assertTrue(flags["new_ui"])
            self.assertFalse(flags["beta"])
            self.assertTrue(flags["alpha"])  # bare name = enabled

    def test_parse_empty(self):
        from data_agent.feature_flags import _parse_env_flags
        with patch.dict(os.environ, {"FEATURE_FLAGS": ""}):
            flags = _parse_env_flags()
            self.assertEqual(flags, {})

    def test_is_enabled_default(self):
        from data_agent.feature_flags import is_enabled, reload_flags
        with patch.dict(os.environ, {"FEATURE_FLAGS": ""}):
            reload_flags()
            self.assertFalse(is_enabled("nonexistent"))
            self.assertTrue(is_enabled("nonexistent", default=True))

    def test_is_enabled_from_env(self):
        from data_agent.feature_flags import is_enabled, reload_flags
        with patch.dict(os.environ, {"FEATURE_FLAGS": "my_feature:true"}):
            reload_flags()
            self.assertTrue(is_enabled("my_feature"))

    def test_set_flag_in_memory(self):
        from data_agent.feature_flags import set_flag, is_enabled, reload_flags
        with patch.dict(os.environ, {"FEATURE_FLAGS": ""}):
            reload_flags()
            set_flag("test_flag", True, persist=False)
            self.assertTrue(is_enabled("test_flag"))
            set_flag("test_flag", False, persist=False)
            self.assertFalse(is_enabled("test_flag"))

    def test_delete_flag(self):
        from data_agent.feature_flags import set_flag, delete_flag, is_enabled, reload_flags
        with patch.dict(os.environ, {"FEATURE_FLAGS": ""}):
            reload_flags()
            set_flag("temp", True, persist=False)
            self.assertTrue(is_enabled("temp"))
            deleted = delete_flag("temp")
            self.assertTrue(deleted)
            self.assertFalse(is_enabled("temp"))

    def test_get_all_flags(self):
        from data_agent.feature_flags import get_all_flags, reload_flags
        with patch.dict(os.environ, {"FEATURE_FLAGS": "a:true,b:false"}):
            reload_flags()
            flags = get_all_flags()
            self.assertIn("a", flags)
            self.assertIn("b", flags)


class TestFailureToEval(unittest.TestCase):
    """Test failure-to-eval pipeline."""

    def test_convert_failure_to_testcase(self):
        from data_agent.failure_to_eval import convert_failure_to_testcase
        tc = convert_failure_to_testcase(
            user_query="分析这个数据",
            expected_tool="describe_geodataframe",
            failure_description="文件不存在",
        )
        self.assertEqual(tc["query"], "分析这个数据")
        self.assertIn("describe_geodataframe", tc["expected_tool_use"])
        self.assertIn("production_failure", tc["source"])
        self.assertIn("created_at", tc)

    def test_convert_without_tool(self):
        from data_agent.failure_to_eval import convert_failure_to_testcase
        tc = convert_failure_to_testcase("test query")
        self.assertEqual(tc["expected_tool_use"], [])

    @patch("data_agent.db_engine.get_engine", return_value=None)
    def test_get_recent_failures_no_db(self, _):
        from data_agent.failure_to_eval import get_recent_failures
        self.assertEqual(get_recent_failures(), [])


class TestRetryBackoff(unittest.TestCase):
    """Test retry plugin has backoff logic."""

    def test_retry_plugin_exists(self):
        from data_agent.plugins import GISToolRetryPlugin
        p = GISToolRetryPlugin()
        self.assertEqual(p.name, "gis_tool_retry")

    def test_retry_plugin_has_backoff(self):
        """Verify the on_tool_error_callback contains backoff logic."""
        import inspect
        from data_agent.plugins import GISToolRetryPlugin
        source = inspect.getsource(GISToolRetryPlugin.on_tool_error_callback)
        self.assertIn("backoff", source.lower())
        self.assertIn("asyncio.sleep", source)


class TestStagingConfig(unittest.TestCase):
    """Test staging infrastructure files exist."""

    def test_staging_compose_exists(self):
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "docker-compose.staging.yml")
        self.assertTrue(os.path.isfile(path))

    def test_cd_staging_workflow_exists(self):
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                            ".github", "workflows", "cd-staging.yml")
        self.assertTrue(os.path.isfile(path))

    def test_cd_production_workflow_exists(self):
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                            ".github", "workflows", "cd-production.yml")
        self.assertTrue(os.path.isfile(path))

    def test_terraform_exists(self):
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                            "terraform", "main.tf")
        self.assertTrue(os.path.isfile(path))


class TestFeatureFlagRoutes(unittest.TestCase):
    """Test feature flag API routes registered."""

    def test_routes_registered(self):
        from data_agent.frontend_api import get_frontend_api_routes
        routes = get_frontend_api_routes()
        paths = [r.path for r in routes]
        self.assertIn("/api/admin/flags", paths)


if __name__ == "__main__":
    unittest.main()

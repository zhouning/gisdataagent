"""Tests for frontend_api module — REST endpoints for React frontend."""
import asyncio
import json
import unittest
from unittest.mock import patch, MagicMock, AsyncMock

from starlette.responses import JSONResponse


def _run_async(coro):
    """Run an async coroutine safely, creating a new event loop if needed."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("closed")
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


def _make_request(path="/", query_params=None, cookies=None, path_params=None, method="GET", body=None):
    """Create a mock Starlette Request."""
    req = MagicMock()
    req.cookies = cookies or {}
    req.query_params = query_params or {}
    req.path_params = path_params or {}
    req.method = method
    if body is not None:
        req.json = AsyncMock(return_value=body)
    else:
        req.json = AsyncMock(side_effect=Exception("No body"))
    return req


def _make_user(identifier="testuser", role="analyst"):
    """Create a mock JWT decoded user object."""
    user = MagicMock()
    user.identifier = identifier
    user.metadata = {"role": role}
    return user


class TestCatalogAPI(unittest.TestCase):
    """Tests for /api/catalog endpoints."""

    @patch("data_agent.frontend_api._get_user_from_request", return_value=None)
    def test_catalog_list_unauthorized(self, _mock):
        import asyncio
        from data_agent.frontend_api import _api_catalog_list
        resp = _run_async(
            _api_catalog_list(_make_request()))
        self.assertEqual(resp.status_code, 401)

    @patch("data_agent.frontend_api.get_engine", return_value=None)
    @patch("data_agent.frontend_api._get_user_from_request")
    def test_catalog_list_success(self, mock_user, mock_engine):
        mock_user.return_value = _make_user()
        import asyncio
        from data_agent.frontend_api import _api_catalog_list

        with patch("data_agent.data_catalog.get_engine", return_value=None):
            resp = _run_async(
                _api_catalog_list(_make_request(query_params={"asset_type": "vector"})))
        # Should return response (even if DB is down, it returns error dict)
        self.assertEqual(resp.status_code, 200)

    @patch("data_agent.frontend_api._get_user_from_request", return_value=None)
    def test_catalog_detail_unauthorized(self, _mock):
        import asyncio
        from data_agent.frontend_api import _api_catalog_detail
        resp = _run_async(
            _api_catalog_detail(_make_request(path_params={"asset_id": "1"})))
        self.assertEqual(resp.status_code, 401)

    @patch("data_agent.frontend_api._get_user_from_request", return_value=None)
    def test_catalog_lineage_unauthorized(self, _mock):
        import asyncio
        from data_agent.frontend_api import _api_catalog_lineage
        resp = _run_async(
            _api_catalog_lineage(_make_request(path_params={"asset_id": "1"})))
        self.assertEqual(resp.status_code, 401)


class TestSemanticAPI(unittest.TestCase):
    """Tests for /api/semantic endpoints."""

    @patch("data_agent.frontend_api._get_user_from_request", return_value=None)
    def test_domains_unauthorized(self, _mock):
        import asyncio
        from data_agent.frontend_api import _api_semantic_domains
        resp = _run_async(
            _api_semantic_domains(_make_request()))
        self.assertEqual(resp.status_code, 401)

    @patch("data_agent.frontend_api._get_user_from_request")
    def test_domains_success(self, mock_user):
        mock_user.return_value = _make_user()
        import asyncio
        from data_agent.frontend_api import _api_semantic_domains
        resp = _run_async(
            _api_semantic_domains(_make_request()))
        self.assertEqual(resp.status_code, 200)
        body = json.loads(resp.body)
        self.assertIn("domains", body)
        # LAND_USE should be in the domains list
        names = [d["name"] for d in body["domains"]]
        self.assertIn("LAND_USE", names)

    @patch("data_agent.frontend_api._get_user_from_request")
    def test_hierarchy_success(self, mock_user):
        mock_user.return_value = _make_user()
        import asyncio
        from data_agent.frontend_api import _api_semantic_hierarchy
        req = _make_request(path_params={"domain": "LAND_USE"})
        resp = _run_async(
            _api_semantic_hierarchy(req))
        self.assertEqual(resp.status_code, 200)
        body = json.loads(resp.body)
        self.assertIn("tree", body)

    @patch("data_agent.frontend_api._get_user_from_request")
    def test_hierarchy_not_found(self, mock_user):
        mock_user.return_value = _make_user()
        import asyncio
        from data_agent.frontend_api import _api_semantic_hierarchy
        req = _make_request(path_params={"domain": "NONEXISTENT"})
        resp = _run_async(
            _api_semantic_hierarchy(req))
        self.assertEqual(resp.status_code, 200)
        body = json.loads(resp.body)
        self.assertEqual(body.get("status"), "not_found")

    @patch("data_agent.frontend_api._get_user_from_request", return_value=None)
    def test_hierarchy_unauthorized(self, _mock):
        import asyncio
        from data_agent.frontend_api import _api_semantic_hierarchy
        resp = _run_async(
            _api_semantic_hierarchy(_make_request(path_params={"domain": "LAND_USE"})))
        self.assertEqual(resp.status_code, 401)


class TestPipelineHistoryAPI(unittest.TestCase):
    """Tests for /api/pipeline/history."""

    @patch("data_agent.frontend_api._get_user_from_request", return_value=None)
    def test_history_unauthorized(self, _mock):
        import asyncio
        from data_agent.frontend_api import _api_pipeline_history
        resp = _run_async(
            _api_pipeline_history(_make_request()))
        self.assertEqual(resp.status_code, 401)

    @patch("data_agent.frontend_api.get_engine", return_value=None)
    @patch("data_agent.frontend_api._get_user_from_request")
    def test_history_no_db(self, mock_user, mock_engine):
        mock_user.return_value = _make_user()
        import asyncio
        from data_agent.frontend_api import _api_pipeline_history
        resp = _run_async(
            _api_pipeline_history(_make_request()))
        self.assertEqual(resp.status_code, 200)
        body = json.loads(resp.body)
        self.assertEqual(body["runs"], [])
        self.assertEqual(body["count"], 0)

    @patch("data_agent.frontend_api.get_engine", return_value=None)
    @patch("data_agent.frontend_api._get_user_from_request")
    def test_history_clamps_params(self, mock_user, mock_engine):
        """Days and limit should be clamped to max values."""
        mock_user.return_value = _make_user()
        import asyncio
        from data_agent.frontend_api import _api_pipeline_history
        req = _make_request(query_params={"days": "999", "limit": "9999"})
        resp = _run_async(
            _api_pipeline_history(req))
        self.assertEqual(resp.status_code, 200)


class TestTokenUsageAPI(unittest.TestCase):
    """Tests for /api/user/token-usage."""

    @patch("data_agent.frontend_api._get_user_from_request", return_value=None)
    def test_token_usage_unauthorized(self, _mock):
        import asyncio
        from data_agent.frontend_api import _api_user_token_usage
        resp = _run_async(
            _api_user_token_usage(_make_request()))
        self.assertEqual(resp.status_code, 401)

    @patch("data_agent.frontend_api._get_user_from_request")
    def test_token_usage_success(self, mock_user):
        mock_user.return_value = _make_user()
        import asyncio
        from data_agent.frontend_api import _api_user_token_usage

        with patch("data_agent.token_tracker.get_engine", return_value=None):
            resp = _run_async(
                _api_user_token_usage(_make_request()))
        self.assertEqual(resp.status_code, 200)
        body = json.loads(resp.body)
        self.assertIn("daily", body)
        self.assertIn("monthly", body)
        self.assertIn("limits", body)
        self.assertIn("pipeline_breakdown", body)
        self.assertIsInstance(body["pipeline_breakdown"], list)


class TestAdminUsersAPI(unittest.TestCase):
    """Tests for /api/admin/users (admin-only)."""

    @patch("data_agent.frontend_api._get_user_from_request", return_value=None)
    def test_users_list_unauthorized(self, _mock):
        import asyncio
        from data_agent.frontend_api import _api_admin_users_list
        resp = _run_async(
            _api_admin_users_list(_make_request()))
        self.assertEqual(resp.status_code, 401)

    @patch("data_agent.frontend_api._get_user_from_request")
    def test_users_list_non_admin_forbidden(self, mock_user):
        mock_user.return_value = _make_user(role="analyst")
        import asyncio
        from data_agent.frontend_api import _api_admin_users_list
        resp = _run_async(
            _api_admin_users_list(_make_request()))
        self.assertEqual(resp.status_code, 403)

    @patch("data_agent.frontend_api.get_engine", return_value=None)
    @patch("data_agent.frontend_api._get_user_from_request")
    def test_users_list_no_db(self, mock_user, mock_engine):
        mock_user.return_value = _make_user(role="admin")
        import asyncio
        from data_agent.frontend_api import _api_admin_users_list
        resp = _run_async(
            _api_admin_users_list(_make_request()))
        self.assertEqual(resp.status_code, 200)
        body = json.loads(resp.body)
        self.assertEqual(body["users"], [])

    @patch("data_agent.frontend_api._get_user_from_request")
    def test_update_role_non_admin(self, mock_user):
        mock_user.return_value = _make_user(role="analyst")
        import asyncio
        from data_agent.frontend_api import _api_admin_update_role
        req = _make_request(path_params={"username": "bob"}, body={"role": "viewer"})
        resp = _run_async(
            _api_admin_update_role(req))
        self.assertEqual(resp.status_code, 403)

    @patch("data_agent.frontend_api._get_user_from_request")
    def test_update_role_invalid_role(self, mock_user):
        mock_user.return_value = _make_user(identifier="admin", role="admin")
        import asyncio
        from data_agent.frontend_api import _api_admin_update_role
        req = _make_request(path_params={"username": "bob"}, body={"role": "superuser"})
        resp = _run_async(
            _api_admin_update_role(req))
        self.assertEqual(resp.status_code, 400)

    @patch("data_agent.frontend_api._get_user_from_request")
    def test_delete_self_forbidden(self, mock_user):
        mock_user.return_value = _make_user(identifier="admin", role="admin")
        import asyncio
        from data_agent.frontend_api import _api_admin_delete_user
        req = _make_request(path_params={"username": "admin"})
        resp = _run_async(
            _api_admin_delete_user(req))
        self.assertEqual(resp.status_code, 400)
        body = json.loads(resp.body)
        self.assertIn("Cannot delete yourself", body["error"])

    @patch("data_agent.frontend_api._get_user_from_request", return_value=None)
    def test_delete_unauthorized(self, _mock):
        import asyncio
        from data_agent.frontend_api import _api_admin_delete_user
        resp = _run_async(
            _api_admin_delete_user(_make_request(path_params={"username": "bob"})))
        self.assertEqual(resp.status_code, 401)


class TestAdminMetricsAPI(unittest.TestCase):
    """Tests for /api/admin/metrics/summary."""

    @patch("data_agent.frontend_api._get_user_from_request", return_value=None)
    def test_metrics_unauthorized(self, _mock):
        import asyncio
        from data_agent.frontend_api import _api_admin_metrics_summary
        resp = _run_async(
            _api_admin_metrics_summary(_make_request()))
        self.assertEqual(resp.status_code, 401)

    @patch("data_agent.frontend_api._get_user_from_request")
    def test_metrics_non_admin(self, mock_user):
        mock_user.return_value = _make_user(role="viewer")
        import asyncio
        from data_agent.frontend_api import _api_admin_metrics_summary
        resp = _run_async(
            _api_admin_metrics_summary(_make_request()))
        self.assertEqual(resp.status_code, 403)

    @patch("data_agent.frontend_api.get_engine", return_value=None)
    @patch("data_agent.frontend_api._get_user_from_request")
    def test_metrics_success(self, mock_user, mock_engine):
        mock_user.return_value = _make_user(role="admin")
        import asyncio
        from data_agent.frontend_api import _api_admin_metrics_summary

        with patch("data_agent.audit_logger.get_engine", return_value=None):
            resp = _run_async(
                _api_admin_metrics_summary(_make_request()))
        self.assertEqual(resp.status_code, 200)
        body = json.loads(resp.body)
        self.assertIn("audit_stats", body)
        self.assertIn("user_count", body)


class TestBasemapConfigAPI(unittest.TestCase):
    """Tests for /api/config/basemaps."""

    @patch("data_agent.frontend_api._get_user_from_request", return_value=None)
    def test_basemaps_unauthorized(self, _mock):
        import asyncio
        from data_agent.frontend_api import _api_config_basemaps
        resp = _run_async(
            _api_config_basemaps(_make_request()))
        self.assertEqual(resp.status_code, 401)

    @patch.dict("os.environ", {"TIANDITU_TOKEN": "test_tk_123"})
    @patch("data_agent.frontend_api._get_user_from_request")
    def test_basemaps_with_tianditu(self, mock_user):
        mock_user.return_value = _make_user()
        import asyncio
        from data_agent.frontend_api import _api_config_basemaps
        resp = _run_async(
            _api_config_basemaps(_make_request()))
        self.assertEqual(resp.status_code, 200)
        body = json.loads(resp.body)
        self.assertTrue(body["tianditu_enabled"])
        self.assertEqual(body["tianditu_token"], "test_tk_123")
        self.assertTrue(body["gaode_enabled"])

    @patch.dict("os.environ", {"TIANDITU_TOKEN": ""}, clear=False)
    @patch("data_agent.frontend_api._get_user_from_request")
    def test_basemaps_without_tianditu(self, mock_user):
        mock_user.return_value = _make_user()
        import asyncio
        from data_agent.frontend_api import _api_config_basemaps
        resp = _run_async(
            _api_config_basemaps(_make_request()))
        self.assertEqual(resp.status_code, 200)
        body = json.loads(resp.body)
        self.assertFalse(body["tianditu_enabled"])


class TestRouteMount(unittest.TestCase):
    """Tests for get_frontend_api_routes and mount_frontend_api."""

    def test_get_routes_count(self):
        from data_agent.frontend_api import get_frontend_api_routes
        routes = get_frontend_api_routes()
        self.assertEqual(len(routes), 105)

    def test_route_paths(self):
        from data_agent.frontend_api import get_frontend_api_routes
        routes = get_frontend_api_routes()
        paths = [r.path for r in routes]
        self.assertIn("/api/catalog", paths)
        self.assertIn("/api/semantic/domains", paths)
        self.assertIn("/api/pipeline/history", paths)
        self.assertIn("/api/user/token-usage", paths)
        self.assertIn("/api/admin/users", paths)
        self.assertIn("/api/admin/metrics/summary", paths)

    def test_mount_before_catchall(self):
        from data_agent.frontend_api import mount_frontend_api
        # Simulate app with catch-all route
        mock_app = MagicMock()
        catchall = MagicMock()
        catchall.path = "/{full_path:path}"
        mock_app.router.routes = [catchall]

        result = mount_frontend_api(mock_app)
        self.assertTrue(result)
        # 36 routes inserted before the catch-all, catch-all is now at index 36
        self.assertEqual(len(mock_app.router.routes), 106)
        self.assertEqual(mock_app.router.routes[-1].path, "/{full_path:path}")


class TestAuthHelpers(unittest.TestCase):
    """Tests for auth helper functions."""

    def test_set_user_context(self):
        from data_agent.frontend_api import _set_user_context
        user = _make_user(identifier="alice", role="admin")
        username, role = _set_user_context(user)
        self.assertEqual(username, "alice")
        self.assertEqual(role, "admin")

    def test_set_user_context_default_role(self):
        from data_agent.frontend_api import _set_user_context
        user = MagicMock()
        user.identifier = "bob"
        user.metadata = {}  # no role key
        username, role = _set_user_context(user)
        self.assertEqual(role, "analyst")

    @patch("data_agent.frontend_api._get_user_from_request", return_value=None)
    def test_require_admin_no_user(self, _mock):
        from data_agent.frontend_api import _require_admin
        user, username, role, err = _require_admin(_make_request())
        self.assertIsNotNone(err)
        self.assertEqual(err.status_code, 401)

    @patch("data_agent.frontend_api._get_user_from_request")
    def test_require_admin_non_admin(self, mock_user):
        mock_user.return_value = _make_user(role="viewer")
        from data_agent.frontend_api import _require_admin
        user, username, role, err = _require_admin(_make_request())
        self.assertIsNotNone(err)
        self.assertEqual(err.status_code, 403)

    @patch("data_agent.frontend_api._get_user_from_request")
    def test_require_admin_success(self, mock_user):
        mock_user.return_value = _make_user(identifier="root", role="admin")
        from data_agent.frontend_api import _require_admin
        user, username, role, err = _require_admin(_make_request())
        self.assertIsNone(err)
        self.assertEqual(username, "root")
        self.assertEqual(role, "admin")


class TestUserDeleteAccountAPI(unittest.TestCase):
    """Tests for DELETE /api/user/account (self-deletion)."""

    @patch("data_agent.frontend_api._get_user_from_request", return_value=None)
    def test_delete_account_unauthorized(self, _mock):
        import asyncio
        from data_agent.frontend_api import _api_user_delete_account
        resp = _run_async(
            _api_user_delete_account(_make_request()))
        self.assertEqual(resp.status_code, 401)

    @patch("data_agent.frontend_api._get_user_from_request")
    def test_delete_account_missing_password(self, mock_user):
        mock_user.return_value = _make_user()
        import asyncio
        from data_agent.frontend_api import _api_user_delete_account
        req = _make_request(body={"password": ""})
        resp = _run_async(
            _api_user_delete_account(req))
        self.assertEqual(resp.status_code, 400)
        body = json.loads(resp.body)
        self.assertIn("Password required", body.get("error", ""))

    @patch("data_agent.frontend_api._get_user_from_request")
    def test_delete_account_wrong_password(self, mock_user):
        mock_user.return_value = _make_user()
        import asyncio
        from data_agent.frontend_api import _api_user_delete_account
        req = _make_request(body={"password": "wrongpass"})
        with patch("data_agent.auth.get_engine", return_value=None):
            resp = _run_async(
                _api_user_delete_account(req))
        self.assertEqual(resp.status_code, 400)
        body = json.loads(resp.body)
        self.assertIn("error", body.get("status", ""))

    @patch("data_agent.frontend_api._get_user_from_request")
    def test_delete_account_admin_blocked(self, mock_user):
        mock_user.return_value = _make_user(identifier="admin", role="admin")
        import asyncio
        from data_agent.frontend_api import _api_user_delete_account
        req = _make_request(body={"password": "admin123"})
        # Mock authenticate_user to return admin user, and get_engine to return non-None
        with patch("data_agent.auth.authenticate_user", return_value={
            "username": "admin", "display_name": "Admin", "role": "admin"
        }), patch("data_agent.auth.get_engine", return_value=MagicMock()):
            resp = _run_async(
                _api_user_delete_account(req))
        self.assertEqual(resp.status_code, 400)
        body = json.loads(resp.body)
        self.assertIn("管理员", body.get("message", ""))


class TestDeleteUserAccount(unittest.TestCase):
    """Tests for auth.delete_user_account()."""

    def test_no_db(self):
        from data_agent.auth import delete_user_account
        with patch("data_agent.auth.get_engine", return_value=None):
            result = delete_user_account("testuser", "pass123")
        self.assertEqual(result["status"], "error")
        self.assertIn("数据库", result["message"])

    def test_wrong_password(self):
        from data_agent.auth import delete_user_account
        with patch("data_agent.auth.get_engine") as mock_eng, \
             patch("data_agent.auth.authenticate_user", return_value=None):
            mock_eng.return_value = MagicMock()
            result = delete_user_account("testuser", "wrongpass")
        self.assertEqual(result["status"], "error")
        self.assertIn("密码", result["message"])

    def test_admin_blocked(self):
        from data_agent.auth import delete_user_account
        with patch("data_agent.auth.get_engine") as mock_eng, \
             patch("data_agent.auth.authenticate_user", return_value={
                 "username": "admin", "display_name": "Admin", "role": "admin"
             }):
            mock_eng.return_value = MagicMock()
            result = delete_user_account("admin", "admin123")
        self.assertEqual(result["status"], "error")
        self.assertIn("管理员", result["message"])


class TestRegisterUser(unittest.TestCase):
    """Tests for register_user() with email parameter."""

    def test_register_email_validation(self):
        from data_agent.auth import register_user
        result = register_user("testuser", "Pass1234", email="bad-email")
        self.assertEqual(result["status"], "error")
        self.assertIn("邮箱", result["message"])

    def test_register_valid_email_format(self):
        from data_agent.auth import register_user
        # Valid email should pass validation but fail on DB (no engine)
        with patch("data_agent.auth.get_engine", return_value=None):
            result = register_user("testuser", "Pass1234", email="user@example.com")
        self.assertEqual(result["status"], "error")
        self.assertIn("数据库", result["message"])

    def test_register_empty_email_ok(self):
        from data_agent.auth import register_user
        # Empty email should be accepted (optional field)
        with patch("data_agent.auth.get_engine", return_value=None):
            result = register_user("testuser", "Pass1234", email="")
        self.assertEqual(result["status"], "error")
        self.assertIn("数据库", result["message"])

    def test_register_password_validation(self):
        from data_agent.auth import register_user
        result = register_user("testuser", "short1")
        self.assertEqual(result["status"], "error")
        self.assertIn("8位", result["message"])

    def test_register_username_validation(self):
        from data_agent.auth import register_user
        result = register_user("ab", "Pass1234")
        self.assertEqual(result["status"], "error")
        self.assertIn("3-30", result["message"])


class TestAnalysisPerspectiveAPI(unittest.TestCase):
    """Tests for /api/user/analysis-perspective endpoints."""

    def test_get_unauthorized(self):
        from data_agent.frontend_api import _api_user_perspective_get
        import asyncio
        with patch("data_agent.frontend_api._get_user_from_request", return_value=None):
            resp = _run_async(
                _api_user_perspective_get(_make_request()))
        self.assertEqual(resp.status_code, 401)

    @patch("data_agent.frontend_api._get_user_from_request")
    @patch("data_agent.memory.get_analysis_perspective", return_value="关注生态红线")
    def test_get_success(self, _mock_perspective, mock_user):
        mock_user.return_value = _make_user()
        from data_agent.frontend_api import _api_user_perspective_get
        import asyncio
        resp = _run_async(
            _api_user_perspective_get(_make_request()))
        self.assertEqual(resp.status_code, 200)
        body = json.loads(resp.body)
        self.assertEqual(body["perspective"], "关注生态红线")

    def test_put_unauthorized(self):
        from data_agent.frontend_api import _api_user_perspective_put
        import asyncio
        with patch("data_agent.frontend_api._get_user_from_request", return_value=None):
            resp = _run_async(
                _api_user_perspective_put(_make_request(body={"perspective": "test"})))
        self.assertEqual(resp.status_code, 401)

    @patch("data_agent.frontend_api._get_user_from_request")
    @patch("data_agent.memory.save_memory", return_value={"status": "success", "message": "ok"})
    def test_put_success(self, _mock_save, mock_user):
        mock_user.return_value = _make_user()
        from data_agent.frontend_api import _api_user_perspective_put
        import asyncio
        resp = _run_async(
            _api_user_perspective_put(_make_request(body={"perspective": "生态分析"})))
        self.assertEqual(resp.status_code, 200)

    @patch("data_agent.frontend_api._get_user_from_request")
    def test_put_too_long(self, mock_user):
        mock_user.return_value = _make_user()
        from data_agent.frontend_api import _api_user_perspective_put
        import asyncio
        resp = _run_async(
            _api_user_perspective_put(_make_request(body={"perspective": "x" * 2001})))
        self.assertEqual(resp.status_code, 400)


class TestMcpServerCrudAPI(unittest.TestCase):
    """Tests for MCP server CRUD endpoints."""

    def test_create_unauthorized(self):
        from data_agent.frontend_api import _api_mcp_server_create
        import asyncio
        with patch("data_agent.frontend_api._get_user_from_request", return_value=None):
            resp = _run_async(
                _api_mcp_server_create(_make_request(body={"name": "test"})))
        self.assertEqual(resp.status_code, 401)

    def test_create_missing_name(self):
        from data_agent.frontend_api import _api_mcp_server_create
        import asyncio
        with patch("data_agent.frontend_api._get_user_from_request",
                   return_value=_make_user(identifier="admin", role="admin")):
            resp = _run_async(
                _api_mcp_server_create(_make_request(body={"name": ""})))
        self.assertEqual(resp.status_code, 400)

    def test_create_invalid_transport(self):
        from data_agent.frontend_api import _api_mcp_server_create
        import asyncio
        with patch("data_agent.frontend_api._get_user_from_request",
                   return_value=_make_user(identifier="admin", role="admin")):
            resp = _run_async(
                _api_mcp_server_create(_make_request(body={"name": "s1", "transport": "invalid"})))
        self.assertEqual(resp.status_code, 400)

    @patch("data_agent.mcp_hub.McpHubManager.add_server")
    def test_create_success(self, mock_add):
        mock_add.return_value = {"status": "ok", "server": "test-srv", "connected": False}
        from data_agent.frontend_api import _api_mcp_server_create
        import asyncio
        with patch("data_agent.frontend_api._get_user_from_request",
                   return_value=_make_user(identifier="admin", role="admin")):
            resp = _run_async(
                _api_mcp_server_create(_make_request(body={
                    "name": "test-srv", "transport": "sse", "url": "http://localhost:8080"
                })))
        self.assertEqual(resp.status_code, 201)

    @patch("data_agent.mcp_hub.McpHubManager.remove_server")
    @patch("data_agent.mcp_hub.McpHubManager._can_manage_server", return_value=True)
    def test_delete_success(self, _mock_can, mock_remove):
        mock_remove.return_value = {"status": "ok", "server": "test-srv"}
        from data_agent.frontend_api import _api_mcp_server_delete
        import asyncio
        req = _make_request()
        req.path_params = {"name": "test-srv"}
        with patch("data_agent.frontend_api._get_user_from_request",
                   return_value=_make_user(identifier="admin", role="admin")):
            resp = _run_async(
                _api_mcp_server_delete(req))
        self.assertEqual(resp.status_code, 200)

    @patch("data_agent.mcp_hub.McpHubManager.update_server")
    @patch("data_agent.mcp_hub.McpHubManager._can_manage_server", return_value=True)
    def test_update_success(self, _mock_can, mock_update):
        mock_update.return_value = {"status": "ok", "server": "test-srv"}
        from data_agent.frontend_api import _api_mcp_server_update
        import asyncio
        req = _make_request(body={"description": "updated"})
        req.path_params = {"name": "test-srv"}
        with patch("data_agent.frontend_api._get_user_from_request",
                   return_value=_make_user(identifier="admin", role="admin")):
            resp = _run_async(
                _api_mcp_server_update(req))
        self.assertEqual(resp.status_code, 200)


class TestMemoryAPI(unittest.TestCase):
    """Tests for auto-extract memory REST endpoints (v7.5)."""

    @patch("data_agent.frontend_api._get_user_from_request", return_value=None)
    def test_memories_list_unauthorized(self, _):
        import asyncio
        from data_agent.frontend_api import _api_user_memories_list
        req = MagicMock()
        resp = _run_async(
            _api_user_memories_list(req))
        self.assertEqual(resp.status_code, 401)

    @patch("data_agent.frontend_api._get_user_from_request", return_value=None)
    def test_memories_delete_unauthorized(self, _):
        import asyncio
        from data_agent.frontend_api import _api_user_memories_delete
        req = MagicMock()
        req.path_params = {"id": 1}
        resp = _run_async(
            _api_user_memories_delete(req))
        self.assertEqual(resp.status_code, 401)

    @patch("data_agent.frontend_api._set_user_context")
    @patch("data_agent.frontend_api._get_user_from_request")
    def test_memories_list_success(self, mock_user, mock_ctx):
        import asyncio
        from data_agent.frontend_api import _api_user_memories_list
        mock_user.return_value = MagicMock()
        mock_ctx.return_value = ("testuser", "session1")
        req = MagicMock()
        with patch("data_agent.memory.list_auto_extract_memories",
                   return_value={"status": "success", "memories": []}):
            resp = _run_async(
                _api_user_memories_list(req))
        self.assertEqual(resp.status_code, 200)


class TestContextCacheConfig(unittest.TestCase):
    """v7.5.5: Gemini context caching configuration."""

    def test_context_cache_config_creation(self):
        from google.adk.agents.context_cache_config import ContextCacheConfig
        config = ContextCacheConfig(cache_intervals=10, ttl_seconds=1800, min_tokens=4096)
        self.assertEqual(config.cache_intervals, 10)
        self.assertEqual(config.ttl_seconds, 1800)
        self.assertEqual(config.min_tokens, 4096)
        self.assertEqual(config.ttl_string, "1800s")

    def test_context_cache_config_defaults(self):
        from google.adk.agents.context_cache_config import ContextCacheConfig
        config = ContextCacheConfig()
        self.assertEqual(config.cache_intervals, 10)
        self.assertEqual(config.ttl_seconds, 1800)
        self.assertEqual(config.min_tokens, 0)

    def test_app_accepts_cache_config(self):
        from google.adk.apps import App
        from google.adk.agents.context_cache_config import ContextCacheConfig
        from google.adk.agents import LlmAgent
        agent = LlmAgent(name="test", model="gemini-2.0-flash")
        config = ContextCacheConfig(ttl_seconds=600)
        app = App(name="test_app", root_agent=agent, context_cache_config=config)
        self.assertIs(app.context_cache_config, config)


class TestCustomSkillsAPI(unittest.TestCase):
    """v8.0.1: Custom Skills REST API endpoints."""

    def test_skills_routes_registered(self):
        from data_agent.frontend_api import get_frontend_api_routes
        routes = get_frontend_api_routes()
        paths = [r.path for r in routes]
        self.assertIn("/api/skills", paths)

    def test_skills_list_unauthenticated(self):
        """GET /api/skills without auth returns 401."""
        from starlette.testclient import TestClient
        from starlette.applications import Starlette
        from data_agent.frontend_api import get_frontend_api_routes
        app = Starlette(routes=get_frontend_api_routes())
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/skills")
        self.assertEqual(resp.status_code, 401)

    def test_skills_create_unauthenticated(self):
        """POST /api/skills without auth returns 401."""
        from starlette.testclient import TestClient
        from starlette.applications import Starlette
        from data_agent.frontend_api import get_frontend_api_routes
        app = Starlette(routes=get_frontend_api_routes())
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/api/skills", json={"skill_name": "test"})
        self.assertEqual(resp.status_code, 401)

    def test_toolset_registry_importable(self):
        """TOOLSET_REGISTRY is importable from custom_skills."""
        from data_agent.custom_skills import TOOLSET_REGISTRY
        self.assertIn("DatabaseToolset", TOOLSET_REGISTRY)

    def test_validation_functions_importable(self):
        """Validation functions are importable."""
        from data_agent.custom_skills import (
            validate_skill_name, validate_instruction, validate_toolset_names,
        )
        self.assertIsNone(validate_skill_name("valid-name"))
        self.assertIsNone(validate_instruction("Valid instruction text"))
        self.assertIsNone(validate_toolset_names(["DatabaseToolset"]))


if __name__ == "__main__":
    unittest.main()

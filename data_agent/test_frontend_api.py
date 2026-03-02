"""Tests for frontend_api module — REST endpoints for React frontend."""
import json
import unittest
from unittest.mock import patch, MagicMock, AsyncMock


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
        resp = asyncio.get_event_loop().run_until_complete(
            _api_catalog_list(_make_request()))
        self.assertEqual(resp.status_code, 401)

    @patch("data_agent.frontend_api.get_engine", return_value=None)
    @patch("data_agent.frontend_api._get_user_from_request")
    def test_catalog_list_success(self, mock_user, mock_engine):
        mock_user.return_value = _make_user()
        import asyncio
        from data_agent.frontend_api import _api_catalog_list

        with patch("data_agent.data_catalog.get_engine", return_value=None):
            resp = asyncio.get_event_loop().run_until_complete(
                _api_catalog_list(_make_request(query_params={"asset_type": "vector"})))
        # Should return response (even if DB is down, it returns error dict)
        self.assertEqual(resp.status_code, 200)

    @patch("data_agent.frontend_api._get_user_from_request", return_value=None)
    def test_catalog_detail_unauthorized(self, _mock):
        import asyncio
        from data_agent.frontend_api import _api_catalog_detail
        resp = asyncio.get_event_loop().run_until_complete(
            _api_catalog_detail(_make_request(path_params={"asset_id": "1"})))
        self.assertEqual(resp.status_code, 401)

    @patch("data_agent.frontend_api._get_user_from_request", return_value=None)
    def test_catalog_lineage_unauthorized(self, _mock):
        import asyncio
        from data_agent.frontend_api import _api_catalog_lineage
        resp = asyncio.get_event_loop().run_until_complete(
            _api_catalog_lineage(_make_request(path_params={"asset_id": "1"})))
        self.assertEqual(resp.status_code, 401)


class TestSemanticAPI(unittest.TestCase):
    """Tests for /api/semantic endpoints."""

    @patch("data_agent.frontend_api._get_user_from_request", return_value=None)
    def test_domains_unauthorized(self, _mock):
        import asyncio
        from data_agent.frontend_api import _api_semantic_domains
        resp = asyncio.get_event_loop().run_until_complete(
            _api_semantic_domains(_make_request()))
        self.assertEqual(resp.status_code, 401)

    @patch("data_agent.frontend_api._get_user_from_request")
    def test_domains_success(self, mock_user):
        mock_user.return_value = _make_user()
        import asyncio
        from data_agent.frontend_api import _api_semantic_domains
        resp = asyncio.get_event_loop().run_until_complete(
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
        resp = asyncio.get_event_loop().run_until_complete(
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
        resp = asyncio.get_event_loop().run_until_complete(
            _api_semantic_hierarchy(req))
        self.assertEqual(resp.status_code, 200)
        body = json.loads(resp.body)
        self.assertEqual(body.get("status"), "not_found")

    @patch("data_agent.frontend_api._get_user_from_request", return_value=None)
    def test_hierarchy_unauthorized(self, _mock):
        import asyncio
        from data_agent.frontend_api import _api_semantic_hierarchy
        resp = asyncio.get_event_loop().run_until_complete(
            _api_semantic_hierarchy(_make_request(path_params={"domain": "LAND_USE"})))
        self.assertEqual(resp.status_code, 401)


class TestPipelineHistoryAPI(unittest.TestCase):
    """Tests for /api/pipeline/history."""

    @patch("data_agent.frontend_api._get_user_from_request", return_value=None)
    def test_history_unauthorized(self, _mock):
        import asyncio
        from data_agent.frontend_api import _api_pipeline_history
        resp = asyncio.get_event_loop().run_until_complete(
            _api_pipeline_history(_make_request()))
        self.assertEqual(resp.status_code, 401)

    @patch("data_agent.frontend_api.get_engine", return_value=None)
    @patch("data_agent.frontend_api._get_user_from_request")
    def test_history_no_db(self, mock_user, mock_engine):
        mock_user.return_value = _make_user()
        import asyncio
        from data_agent.frontend_api import _api_pipeline_history
        resp = asyncio.get_event_loop().run_until_complete(
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
        resp = asyncio.get_event_loop().run_until_complete(
            _api_pipeline_history(req))
        self.assertEqual(resp.status_code, 200)


class TestTokenUsageAPI(unittest.TestCase):
    """Tests for /api/user/token-usage."""

    @patch("data_agent.frontend_api._get_user_from_request", return_value=None)
    def test_token_usage_unauthorized(self, _mock):
        import asyncio
        from data_agent.frontend_api import _api_user_token_usage
        resp = asyncio.get_event_loop().run_until_complete(
            _api_user_token_usage(_make_request()))
        self.assertEqual(resp.status_code, 401)

    @patch("data_agent.frontend_api._get_user_from_request")
    def test_token_usage_success(self, mock_user):
        mock_user.return_value = _make_user()
        import asyncio
        from data_agent.frontend_api import _api_user_token_usage

        with patch("data_agent.token_tracker.get_engine", return_value=None):
            resp = asyncio.get_event_loop().run_until_complete(
                _api_user_token_usage(_make_request()))
        self.assertEqual(resp.status_code, 200)
        body = json.loads(resp.body)
        self.assertIn("daily", body)
        self.assertIn("monthly", body)
        self.assertIn("limits", body)


class TestAdminUsersAPI(unittest.TestCase):
    """Tests for /api/admin/users (admin-only)."""

    @patch("data_agent.frontend_api._get_user_from_request", return_value=None)
    def test_users_list_unauthorized(self, _mock):
        import asyncio
        from data_agent.frontend_api import _api_admin_users_list
        resp = asyncio.get_event_loop().run_until_complete(
            _api_admin_users_list(_make_request()))
        self.assertEqual(resp.status_code, 401)

    @patch("data_agent.frontend_api._get_user_from_request")
    def test_users_list_non_admin_forbidden(self, mock_user):
        mock_user.return_value = _make_user(role="analyst")
        import asyncio
        from data_agent.frontend_api import _api_admin_users_list
        resp = asyncio.get_event_loop().run_until_complete(
            _api_admin_users_list(_make_request()))
        self.assertEqual(resp.status_code, 403)

    @patch("data_agent.frontend_api.get_engine", return_value=None)
    @patch("data_agent.frontend_api._get_user_from_request")
    def test_users_list_no_db(self, mock_user, mock_engine):
        mock_user.return_value = _make_user(role="admin")
        import asyncio
        from data_agent.frontend_api import _api_admin_users_list
        resp = asyncio.get_event_loop().run_until_complete(
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
        resp = asyncio.get_event_loop().run_until_complete(
            _api_admin_update_role(req))
        self.assertEqual(resp.status_code, 403)

    @patch("data_agent.frontend_api._get_user_from_request")
    def test_update_role_invalid_role(self, mock_user):
        mock_user.return_value = _make_user(identifier="admin", role="admin")
        import asyncio
        from data_agent.frontend_api import _api_admin_update_role
        req = _make_request(path_params={"username": "bob"}, body={"role": "superuser"})
        resp = asyncio.get_event_loop().run_until_complete(
            _api_admin_update_role(req))
        self.assertEqual(resp.status_code, 400)

    @patch("data_agent.frontend_api._get_user_from_request")
    def test_delete_self_forbidden(self, mock_user):
        mock_user.return_value = _make_user(identifier="admin", role="admin")
        import asyncio
        from data_agent.frontend_api import _api_admin_delete_user
        req = _make_request(path_params={"username": "admin"})
        resp = asyncio.get_event_loop().run_until_complete(
            _api_admin_delete_user(req))
        self.assertEqual(resp.status_code, 400)
        body = json.loads(resp.body)
        self.assertIn("Cannot delete yourself", body["error"])

    @patch("data_agent.frontend_api._get_user_from_request", return_value=None)
    def test_delete_unauthorized(self, _mock):
        import asyncio
        from data_agent.frontend_api import _api_admin_delete_user
        resp = asyncio.get_event_loop().run_until_complete(
            _api_admin_delete_user(_make_request(path_params={"username": "bob"})))
        self.assertEqual(resp.status_code, 401)


class TestAdminMetricsAPI(unittest.TestCase):
    """Tests for /api/admin/metrics/summary."""

    @patch("data_agent.frontend_api._get_user_from_request", return_value=None)
    def test_metrics_unauthorized(self, _mock):
        import asyncio
        from data_agent.frontend_api import _api_admin_metrics_summary
        resp = asyncio.get_event_loop().run_until_complete(
            _api_admin_metrics_summary(_make_request()))
        self.assertEqual(resp.status_code, 401)

    @patch("data_agent.frontend_api._get_user_from_request")
    def test_metrics_non_admin(self, mock_user):
        mock_user.return_value = _make_user(role="viewer")
        import asyncio
        from data_agent.frontend_api import _api_admin_metrics_summary
        resp = asyncio.get_event_loop().run_until_complete(
            _api_admin_metrics_summary(_make_request()))
        self.assertEqual(resp.status_code, 403)

    @patch("data_agent.frontend_api.get_engine", return_value=None)
    @patch("data_agent.frontend_api._get_user_from_request")
    def test_metrics_success(self, mock_user, mock_engine):
        mock_user.return_value = _make_user(role="admin")
        import asyncio
        from data_agent.frontend_api import _api_admin_metrics_summary

        with patch("data_agent.audit_logger.get_engine", return_value=None):
            resp = asyncio.get_event_loop().run_until_complete(
                _api_admin_metrics_summary(_make_request()))
        self.assertEqual(resp.status_code, 200)
        body = json.loads(resp.body)
        self.assertIn("audit_stats", body)
        self.assertIn("user_count", body)


class TestRouteMount(unittest.TestCase):
    """Tests for get_frontend_api_routes and mount_frontend_api."""

    def test_get_routes_count(self):
        from data_agent.frontend_api import get_frontend_api_routes
        routes = get_frontend_api_routes()
        self.assertEqual(len(routes), 11)

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
        # 11 routes inserted before the catch-all, catch-all is now at index 11
        self.assertEqual(len(mock_app.router.routes), 12)
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


if __name__ == "__main__":
    unittest.main()

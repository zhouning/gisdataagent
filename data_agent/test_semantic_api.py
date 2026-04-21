"""Tests for Semantic Layer Management API endpoints (v24.1)."""
import asyncio
import json
import unittest
from unittest.mock import patch, MagicMock, AsyncMock


def _run_async(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("closed")
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


def _make_request(path_params=None, query_params=None, body=None):
    req = MagicMock()
    req.cookies = {}
    req.query_params = query_params or {}
    req.path_params = path_params or {}
    if body is not None:
        req.json = AsyncMock(return_value=body)
    else:
        req.json = AsyncMock(side_effect=Exception("No body"))
    return req


def _make_user(role="analyst"):
    user = MagicMock()
    user.identifier = "testuser"
    user.metadata = {"role": role}
    return user


class TestSemanticSourcesAPI(unittest.TestCase):

    @patch("data_agent.frontend_api._get_user_from_request", return_value=None)
    def test_sources_list_unauthorized(self, _):
        from data_agent.frontend_api import _api_semantic_sources_list
        resp = _run_async(_api_semantic_sources_list(_make_request()))
        self.assertEqual(resp.status_code, 401)

    @patch("data_agent.frontend_api.get_engine", return_value=None)
    @patch("data_agent.frontend_api._get_user_from_request")
    def test_sources_list_success(self, mock_user, _):
        mock_user.return_value = _make_user()
        with patch("data_agent.semantic_layer.get_engine", return_value=None):
            from data_agent.frontend_api import _api_semantic_sources_list
            resp = _run_async(_api_semantic_sources_list(_make_request()))
            self.assertEqual(resp.status_code, 200)

    @patch("data_agent.frontend_api._get_user_from_request", return_value=None)
    def test_source_detail_unauthorized(self, _):
        from data_agent.frontend_api import _api_semantic_source_detail
        resp = _run_async(_api_semantic_source_detail(
            _make_request(path_params={"table": "test"})))
        self.assertEqual(resp.status_code, 401)

    @patch("data_agent.frontend_api._get_user_from_request")
    def test_source_upsert_viewer_forbidden(self, mock_user):
        mock_user.return_value = _make_user(role="viewer")
        from data_agent.frontend_api import _api_semantic_source_upsert
        resp = _run_async(_api_semantic_source_upsert(
            _make_request(path_params={"table": "t"}, body={"display_name": "x"})))
        self.assertEqual(resp.status_code, 403)

    @patch("data_agent.frontend_api._get_user_from_request")
    def test_source_upsert_analyst_allowed(self, mock_user):
        mock_user.return_value = _make_user(role="analyst")
        with patch("data_agent.semantic_layer.get_engine", return_value=None):
            from data_agent.frontend_api import _api_semantic_source_upsert
            resp = _run_async(_api_semantic_source_upsert(
                _make_request(path_params={"table": "t"},
                              body={"display_name": "Test", "synonyms": ["a"]})))
            # Will fail because DB is None, but should not be 403
            self.assertNotEqual(resp.status_code, 403)

    @patch("data_agent.frontend_api._get_user_from_request", return_value=None)
    def test_unregistered_unauthorized(self, _):
        from data_agent.frontend_api import _api_semantic_unregistered
        resp = _run_async(_api_semantic_unregistered(_make_request()))
        self.assertEqual(resp.status_code, 401)

    @patch("data_agent.frontend_api._get_user_from_request")
    def test_resolve_preview_missing_question(self, mock_user):
        mock_user.return_value = _make_user()
        from data_agent.frontend_api import _api_semantic_resolve_preview
        resp = _run_async(_api_semantic_resolve_preview(
            _make_request(body={"question": ""})))
        self.assertEqual(resp.status_code, 400)

    @patch("data_agent.frontend_api._get_user_from_request")
    def test_export_unauthorized(self, mock_user):
        mock_user.return_value = None
        from data_agent.frontend_api import _api_semantic_export
        resp = _run_async(_api_semantic_export(_make_request()))
        self.assertEqual(resp.status_code, 401)

    @patch("data_agent.frontend_api._get_user_from_request")
    def test_import_viewer_forbidden(self, mock_user):
        mock_user.return_value = _make_user(role="viewer")
        from data_agent.frontend_api import _api_semantic_import
        resp = _run_async(_api_semantic_import(
            _make_request(body={"sources": [], "annotations": []})))
        self.assertEqual(resp.status_code, 403)

    @patch("data_agent.frontend_api._get_user_from_request")
    def test_auto_register_viewer_forbidden(self, mock_user):
        mock_user.return_value = _make_user(role="viewer")
        from data_agent.frontend_api import _api_semantic_auto_register
        resp = _run_async(_api_semantic_auto_register(
            _make_request(body={})))
        self.assertEqual(resp.status_code, 403)


if __name__ == "__main__":
    unittest.main()

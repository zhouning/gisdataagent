"""
Tests for Pipeline Analytics Dashboard API (v9.0.5).

Tests all 5 analytics endpoints and helper functions.
"""

import json
import unittest
from unittest.mock import patch, MagicMock

import pytest

from starlette.testclient import TestClient
from starlette.applications import Starlette
from starlette.routing import Route


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_auth_request(query_params=None):
    """Create a mock authenticated request."""
    request = MagicMock()
    request.query_params = query_params or {}
    return request


def _mock_user():
    user = MagicMock()
    user.identifier = "testuser"
    user.metadata = {"role": "admin"}
    return user


def _pipeline_detail(pipeline_type="general", duration=5.0,
                      input_tokens=100, output_tokens=50,
                      tool_log=None, provenance=None):
    """Build a mock audit_log details dict."""
    d = {
        "pipeline_type": pipeline_type,
        "duration_seconds": duration,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "tool_execution_log": tool_log or [],
    }
    if provenance:
        d["provenance_trail"] = provenance
    return d


# ---------------------------------------------------------------------------
# TestSafeJson
# ---------------------------------------------------------------------------

class TestSafeJson(unittest.TestCase):

    def test_dict_passthrough(self):
        from data_agent.pipeline_analytics import _safe_json
        d = {"key": "value"}
        self.assertEqual(_safe_json(d), d)

    def test_string_parse(self):
        from data_agent.pipeline_analytics import _safe_json
        result = _safe_json('{"a": 1}')
        self.assertEqual(result, {"a": 1})

    def test_none_returns_empty(self):
        from data_agent.pipeline_analytics import _safe_json
        self.assertEqual(_safe_json(None), {})

    def test_invalid_json_returns_empty(self):
        from data_agent.pipeline_analytics import _safe_json
        self.assertEqual(_safe_json("not json"), {})


# ---------------------------------------------------------------------------
# TestLatencyEndpoint
# ---------------------------------------------------------------------------

class TestLatencyEndpoint(unittest.IsolatedAsyncioTestCase):

    @patch("data_agent.frontend_api._get_user_from_request", return_value=None)
    async def test_unauthorized(self, mock_auth):
        from data_agent.pipeline_analytics import api_analytics_latency
        request = _make_auth_request()
        resp = await api_analytics_latency(request)
        self.assertEqual(resp.status_code, 401)

    @patch("data_agent.db_engine.get_engine", return_value=None)
    @patch("data_agent.frontend_api._set_user_context")
    @patch("data_agent.frontend_api._get_user_from_request", return_value=_mock_user())
    async def test_no_db(self, mock_auth, mock_ctx, mock_engine):
        from data_agent.pipeline_analytics import api_analytics_latency
        request = _make_auth_request()
        resp = await api_analytics_latency(request)
        body = json.loads(resp.body)
        self.assertEqual(body["count"], 0)

    @patch("data_agent.db_engine.get_engine")
    @patch("data_agent.frontend_api._set_user_context")
    @patch("data_agent.frontend_api._get_user_from_request", return_value=_mock_user())
    async def test_with_data(self, mock_auth, mock_ctx, mock_engine):
        from data_agent.pipeline_analytics import api_analytics_latency
        # Mock DB rows
        details = [
            _pipeline_detail(duration=2.0),
            _pipeline_detail(duration=5.0),
            _pipeline_detail(duration=8.0),
            _pipeline_detail(duration=12.0),
        ]
        mock_conn = MagicMock()
        mock_engine.return_value.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchall.return_value = [
            (json.dumps(d),) for d in details
        ]

        request = _make_auth_request({"days": "30"})
        resp = await api_analytics_latency(request)
        body = json.loads(resp.body)
        self.assertEqual(body["count"], 4)
        self.assertIn("p50", body["percentiles"])
        self.assertIn("p90", body["percentiles"])


# ---------------------------------------------------------------------------
# TestToolSuccessEndpoint
# ---------------------------------------------------------------------------

class TestToolSuccessEndpoint(unittest.IsolatedAsyncioTestCase):

    @patch("data_agent.db_engine.get_engine")
    @patch("data_agent.frontend_api._set_user_context")
    @patch("data_agent.frontend_api._get_user_from_request", return_value=_mock_user())
    async def test_tool_aggregation(self, mock_auth, mock_ctx, mock_engine):
        from data_agent.pipeline_analytics import api_analytics_tool_success
        tool_log = [
            {"tool_name": "query_database", "is_error": False, "duration": 1.0},
            {"tool_name": "query_database", "is_error": True, "duration": 0.5},
            {"tool_name": "clip_geometry", "is_error": False, "duration": 2.0},
        ]
        details = [_pipeline_detail(tool_log=tool_log)]
        mock_conn = MagicMock()
        mock_engine.return_value.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchall.return_value = [
            (json.dumps(d),) for d in details
        ]

        request = _make_auth_request()
        resp = await api_analytics_tool_success(request)
        body = json.loads(resp.body)
        tools = body["tools"]
        self.assertEqual(len(tools), 2)
        # query_database should be first (most calls)
        db_tool = next(t for t in tools if t["tool_name"] == "query_database")
        self.assertEqual(db_tool["total_calls"], 2)
        self.assertEqual(db_tool["errors"], 1)
        self.assertEqual(db_tool["success_rate"], 50.0)


# ---------------------------------------------------------------------------
# TestTokenEfficiencyEndpoint
# ---------------------------------------------------------------------------

class TestTokenEfficiencyEndpoint(unittest.IsolatedAsyncioTestCase):

    @patch("data_agent.db_engine.get_engine", return_value=None)
    @patch("data_agent.frontend_api._set_user_context")
    @patch("data_agent.frontend_api._get_user_from_request", return_value=_mock_user())
    async def test_no_db_empty(self, mock_auth, mock_ctx, mock_engine):
        from data_agent.pipeline_analytics import api_analytics_token_efficiency
        request = _make_auth_request()
        resp = await api_analytics_token_efficiency(request)
        body = json.loads(resp.body)
        self.assertEqual(body["daily"], [])


# ---------------------------------------------------------------------------
# TestThroughputEndpoint
# ---------------------------------------------------------------------------

class TestThroughputEndpoint(unittest.IsolatedAsyncioTestCase):

    @patch("data_agent.db_engine.get_engine", return_value=None)
    @patch("data_agent.frontend_api._set_user_context")
    @patch("data_agent.frontend_api._get_user_from_request", return_value=_mock_user())
    async def test_no_db_empty(self, mock_auth, mock_ctx, mock_engine):
        from data_agent.pipeline_analytics import api_analytics_throughput
        request = _make_auth_request()
        resp = await api_analytics_throughput(request)
        body = json.loads(resp.body)
        self.assertEqual(body["daily"], [])
        self.assertEqual(body["total"], 0)


# ---------------------------------------------------------------------------
# TestAgentBreakdownEndpoint
# ---------------------------------------------------------------------------

class TestAgentBreakdownEndpoint(unittest.IsolatedAsyncioTestCase):

    @patch("data_agent.db_engine.get_engine")
    @patch("data_agent.frontend_api._set_user_context")
    @patch("data_agent.frontend_api._get_user_from_request", return_value=_mock_user())
    async def test_agent_aggregation(self, mock_auth, mock_ctx, mock_engine):
        from data_agent.pipeline_analytics import api_analytics_agent_breakdown
        tool_log = [
            {"agent_name": "DataExploration", "tool_name": "describe_geodataframe", "duration": 3.0},
            {"agent_name": "DataExploration", "tool_name": "check_topology", "duration": 2.0},
            {"agent_name": "DataProcessing", "tool_name": "reproject_spatial_data", "duration": 5.0},
        ]
        details = [_pipeline_detail(tool_log=tool_log)]
        mock_conn = MagicMock()
        mock_engine.return_value.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchall.return_value = [
            (json.dumps(d),) for d in details
        ]

        request = _make_auth_request()
        resp = await api_analytics_agent_breakdown(request)
        body = json.loads(resp.body)
        agents = body["agents"]
        self.assertEqual(len(agents), 2)
        # DataExploration has more total duration
        self.assertEqual(agents[0]["agent_name"], "DataExploration")
        self.assertEqual(agents[0]["call_count"], 2)
        self.assertEqual(agents[0]["total_duration"], 5.0)

    @patch("data_agent.db_engine.get_engine", return_value=None)
    @patch("data_agent.frontend_api._set_user_context")
    @patch("data_agent.frontend_api._get_user_from_request", return_value=_mock_user())
    async def test_no_db(self, mock_auth, mock_ctx, mock_engine):
        from data_agent.pipeline_analytics import api_analytics_agent_breakdown
        request = _make_auth_request()
        resp = await api_analytics_agent_breakdown(request)
        body = json.loads(resp.body)
        self.assertEqual(body["agents"], [])


# ---------------------------------------------------------------------------
# TestRouteRegistration
# ---------------------------------------------------------------------------

class TestAnalyticsRouteRegistration(unittest.TestCase):
    """Verify analytics routes are registered in frontend_api."""

    def test_routes_exist(self):
        from data_agent.frontend_api import get_frontend_api_routes
        routes = get_frontend_api_routes()
        paths = [r.path for r in routes]
        self.assertIn("/api/analytics/latency", paths)
        self.assertIn("/api/analytics/tool-success", paths)
        self.assertIn("/api/analytics/token-efficiency", paths)
        self.assertIn("/api/analytics/throughput", paths)
        self.assertIn("/api/analytics/agent-breakdown", paths)

    def test_total_route_count(self):
        """Should have 49 routes (44 pre-existing + 5 analytics)."""
        from data_agent.frontend_api import get_frontend_api_routes
        routes = get_frontend_api_routes()
        self.assertGreaterEqual(len(routes), 49)


if __name__ == "__main__":
    unittest.main()

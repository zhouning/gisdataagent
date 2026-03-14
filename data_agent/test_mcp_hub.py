"""Tests for MCP Hub Manager — config loading, connection lifecycle, toolset, API.

All connection-related tests mock McpToolset — no real MCP servers required.
"""
import asyncio
import json
import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock, AsyncMock

import yaml


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    """Run an async coroutine synchronously."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_request(path="/", query_params=None, cookies=None, path_params=None,
                  method="GET", body=None):
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


def _write_config(tmp_dir, servers_data):
    """Write a mcp_servers.yaml in tmp_dir and return path."""
    path = os.path.join(tmp_dir, "mcp_servers.yaml")
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(servers_data, f)
    return path


# ---------------------------------------------------------------------------
# TestMcpServerConfig
# ---------------------------------------------------------------------------

class TestMcpServerConfig(unittest.TestCase):
    """Tests for McpServerConfig dataclass defaults and parsing."""

    def test_defaults(self):
        from data_agent.mcp_hub import McpServerConfig
        cfg = McpServerConfig(name="test")
        self.assertEqual(cfg.name, "test")
        self.assertEqual(cfg.description, "")
        self.assertEqual(cfg.transport, "stdio")
        self.assertFalse(cfg.enabled)
        self.assertEqual(cfg.category, "")
        self.assertEqual(cfg.pipelines, ["general", "planner"])
        self.assertEqual(cfg.command, "")
        self.assertEqual(cfg.args, [])
        self.assertEqual(cfg.env, {})
        self.assertIsNone(cfg.cwd)
        self.assertEqual(cfg.url, "")
        self.assertEqual(cfg.headers, {})
        self.assertEqual(cfg.timeout, 5.0)

    def test_full_config(self):
        from data_agent.mcp_hub import McpServerConfig
        cfg = McpServerConfig(
            name="my-server",
            description="Test server",
            transport="sse",
            enabled=True,
            category="gis",
            pipelines=["general"],
            url="http://localhost:8080/sse",
            headers={"Authorization": "Bearer xxx"},
            timeout=10.0,
        )
        self.assertEqual(cfg.transport, "sse")
        self.assertTrue(cfg.enabled)
        self.assertEqual(cfg.pipelines, ["general"])
        self.assertEqual(cfg.url, "http://localhost:8080/sse")
        self.assertEqual(cfg.timeout, 10.0)

    def test_stdio_config(self):
        from data_agent.mcp_hub import McpServerConfig
        cfg = McpServerConfig(
            name="local",
            transport="stdio",
            command="python",
            args=["-m", "my_server"],
            env={"KEY": "value"},
            cwd="/tmp",
        )
        self.assertEqual(cfg.command, "python")
        self.assertEqual(cfg.args, ["-m", "my_server"])
        self.assertEqual(cfg.env, {"KEY": "value"})
        self.assertEqual(cfg.cwd, "/tmp")


# ---------------------------------------------------------------------------
# TestMcpServerStatus
# ---------------------------------------------------------------------------

class TestMcpServerStatus(unittest.TestCase):
    """Tests for McpServerStatus dataclass."""

    def test_defaults(self):
        from data_agent.mcp_hub import McpServerConfig, McpServerStatus
        cfg = McpServerConfig(name="test")
        status = McpServerStatus(config=cfg)
        self.assertIsNone(status.toolset)
        self.assertEqual(status.status, "disconnected")
        self.assertEqual(status.tool_count, 0)
        self.assertEqual(status.tool_names, [])
        self.assertEqual(status.error_message, "")
        self.assertIsNone(status.connected_at)


# ---------------------------------------------------------------------------
# TestMcpHubManager
# ---------------------------------------------------------------------------

class TestMcpHubManager(unittest.TestCase):
    """Tests for McpHubManager singleton and config loading."""

    def setUp(self):
        from data_agent.mcp_hub import reset_mcp_hub
        reset_mcp_hub()

    def tearDown(self):
        from data_agent.mcp_hub import reset_mcp_hub
        reset_mcp_hub()

    def test_singleton(self):
        from data_agent.mcp_hub import get_mcp_hub, reset_mcp_hub
        hub1 = get_mcp_hub()
        hub2 = get_mcp_hub()
        self.assertIs(hub1, hub2)

    def test_singleton_reset(self):
        from data_agent.mcp_hub import get_mcp_hub, reset_mcp_hub
        hub1 = get_mcp_hub()
        reset_mcp_hub()
        hub2 = get_mcp_hub()
        self.assertIsNot(hub1, hub2)

    def test_load_config_missing_file(self):
        from data_agent.mcp_hub import McpHubManager
        hub = McpHubManager()
        hub._config_path = "/nonexistent/mcp_servers.yaml"
        hub._ensure_table = MagicMock(return_value=False)
        hub._load_from_db = MagicMock(return_value=[])
        configs = hub.load_config()
        self.assertEqual(configs, [])

    def test_load_config_valid(self):
        from data_agent.mcp_hub import McpHubManager
        hub = McpHubManager()
        hub._ensure_table = MagicMock(return_value=False)
        hub._load_from_db = MagicMock(return_value=[])

        with tempfile.TemporaryDirectory() as tmp:
            path = _write_config(tmp, {
                "servers": [
                    {"name": "srv1", "description": "Server 1", "transport": "stdio",
                     "enabled": True, "command": "python", "args": ["-m", "srv"]},
                    {"name": "srv2", "description": "Server 2", "transport": "sse",
                     "enabled": False, "url": "http://localhost:8080/sse"},
                ]
            })
            hub._config_path = path
            configs = hub.load_config()

        self.assertEqual(len(configs), 2)
        self.assertEqual(configs[0].name, "srv1")
        self.assertTrue(configs[0].enabled)
        self.assertEqual(configs[0].transport, "stdio")
        self.assertEqual(configs[1].name, "srv2")
        self.assertFalse(configs[1].enabled)
        self.assertEqual(configs[1].transport, "sse")

    def test_load_config_skips_invalid_entries(self):
        from data_agent.mcp_hub import McpHubManager
        hub = McpHubManager()
        hub._ensure_table = MagicMock(return_value=False)
        hub._load_from_db = MagicMock(return_value=[])

        with tempfile.TemporaryDirectory() as tmp:
            path = _write_config(tmp, {
                "servers": [
                    {"name": "valid", "transport": "stdio"},
                    {"no_name_field": True},  # should be skipped
                    "not_a_dict",  # should be skipped
                ]
            })
            hub._config_path = path
            configs = hub.load_config()

        self.assertEqual(len(configs), 1)
        self.assertEqual(configs[0].name, "valid")

    def test_load_config_empty_yaml(self):
        from data_agent.mcp_hub import McpHubManager
        hub = McpHubManager()
        hub._ensure_table = MagicMock(return_value=False)
        hub._load_from_db = MagicMock(return_value=[])

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "mcp_servers.yaml")
            with open(path, "w", encoding="utf-8") as f:
                f.write("")
            hub._config_path = path
            configs = hub.load_config()

        self.assertEqual(configs, [])

    def test_load_config_malformed_yaml(self):
        from data_agent.mcp_hub import McpHubManager
        hub = McpHubManager()
        hub._ensure_table = MagicMock(return_value=False)
        hub._load_from_db = MagicMock(return_value=[])

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "mcp_servers.yaml")
            with open(path, "w", encoding="utf-8") as f:
                f.write("servers:\n  - {name: broken, enabled: [}")
            hub._config_path = path
            configs = hub.load_config()

        self.assertEqual(configs, [])

    def test_get_server_statuses_empty(self):
        from data_agent.mcp_hub import McpHubManager
        hub = McpHubManager()
        statuses = hub.get_server_statuses()
        self.assertEqual(statuses, [])

    def test_get_server_statuses_after_load(self):
        from data_agent.mcp_hub import McpHubManager
        hub = McpHubManager()
        hub._ensure_table = MagicMock(return_value=False)
        hub._load_from_db = MagicMock(return_value=[])

        with tempfile.TemporaryDirectory() as tmp:
            path = _write_config(tmp, {
                "servers": [
                    {"name": "s1", "description": "S1", "transport": "stdio",
                     "enabled": False, "category": "gis",
                     "pipelines": ["general"]},
                ]
            })
            hub._config_path = path
            hub.load_config()

        statuses = hub.get_server_statuses()
        self.assertEqual(len(statuses), 1)
        self.assertEqual(statuses[0]["name"], "s1")
        self.assertEqual(statuses[0]["status"], "disconnected")
        self.assertFalse(statuses[0]["enabled"])
        self.assertEqual(statuses[0]["category"], "gis")
        self.assertEqual(statuses[0]["pipelines"], ["general"])

    def test_connect_unknown_server(self):
        from data_agent.mcp_hub import McpHubManager
        hub = McpHubManager()
        result = _run(hub.connect_server("nonexistent"))
        self.assertFalse(result)

    def test_disconnect_unknown_server(self):
        from data_agent.mcp_hub import McpHubManager
        hub = McpHubManager()
        result = _run(hub.disconnect_server("nonexistent"))
        self.assertFalse(result)

    @patch("data_agent.mcp_hub.McpHubManager.connect_server", new_callable=AsyncMock)
    def test_startup_connects_enabled_only(self, mock_connect):
        from data_agent.mcp_hub import McpHubManager
        hub = McpHubManager()
        hub._ensure_table = MagicMock(return_value=False)
        hub._load_from_db = MagicMock(return_value=[])

        with tempfile.TemporaryDirectory() as tmp:
            path = _write_config(tmp, {
                "servers": [
                    {"name": "enabled1", "enabled": True},
                    {"name": "disabled1", "enabled": False},
                    {"name": "enabled2", "enabled": True},
                ]
            })
            hub._config_path = path
            hub.load_config()

        mock_connect.return_value = True
        _run(hub.startup())

        # Should only connect the 2 enabled servers
        called_names = [call.args[0] for call in mock_connect.call_args_list]
        self.assertIn("enabled1", called_names)
        self.assertIn("enabled2", called_names)
        self.assertNotIn("disabled1", called_names)
        self.assertTrue(hub._started)

    @patch("data_agent.mcp_hub.McpHubManager.connect_server", new_callable=AsyncMock)
    def test_startup_idempotent(self, mock_connect):
        from data_agent.mcp_hub import McpHubManager
        hub = McpHubManager()
        hub._ensure_table = MagicMock(return_value=False)
        hub._load_from_db = MagicMock(return_value=[])

        with tempfile.TemporaryDirectory() as tmp:
            path = _write_config(tmp, {"servers": [{"name": "s1", "enabled": True}]})
            hub._config_path = path
            hub.load_config()

        mock_connect.return_value = True
        _run(hub.startup())
        call_count_1 = mock_connect.call_count
        _run(hub.startup())  # second call — should be no-op
        self.assertEqual(mock_connect.call_count, call_count_1)

    def test_toggle_server_not_found(self):
        from data_agent.mcp_hub import McpHubManager
        hub = McpHubManager()
        result = _run(hub.toggle_server("ghost", True))
        self.assertEqual(result["status"], "error")
        self.assertIn("not found", result["message"])

    def test_reconnect_server_not_found(self):
        from data_agent.mcp_hub import McpHubManager
        hub = McpHubManager()
        result = _run(hub.reconnect_server("ghost"))
        self.assertEqual(result["status"], "error")
        self.assertIn("not found", result["message"])

    def test_get_all_tools_no_connected(self):
        from data_agent.mcp_hub import McpHubManager
        hub = McpHubManager()
        hub._ensure_table = MagicMock(return_value=False)
        hub._load_from_db = MagicMock(return_value=[])

        with tempfile.TemporaryDirectory() as tmp:
            path = _write_config(tmp, {"servers": [{"name": "s1", "enabled": False}]})
            hub._config_path = path
            hub.load_config()

        tools = _run(hub.get_all_tools())
        self.assertEqual(tools, [])

    def test_get_all_tools_pipeline_filter(self):
        """get_all_tools with pipeline filter skips non-matching servers."""
        from data_agent.mcp_hub import McpHubManager, McpServerConfig, McpServerStatus
        hub = McpHubManager()

        # Manually set up two servers: one for "general", one for "planner"
        mock_tool_a = MagicMock(name="tool_a")
        mock_tool_b = MagicMock(name="tool_b")

        cfg_a = McpServerConfig(name="a", pipelines=["general"])
        status_a = McpServerStatus(config=cfg_a, status="connected")
        status_a.toolset = MagicMock()
        status_a.toolset.get_tools = AsyncMock(return_value=[mock_tool_a])

        cfg_b = McpServerConfig(name="b", pipelines=["planner"])
        status_b = McpServerStatus(config=cfg_b, status="connected")
        status_b.toolset = MagicMock()
        status_b.toolset.get_tools = AsyncMock(return_value=[mock_tool_b])

        hub._servers = {"a": status_a, "b": status_b}

        # Filter by "general" — only tool_a should appear
        tools = _run(hub.get_all_tools(pipeline="general"))
        self.assertEqual(len(tools), 1)
        self.assertIs(tools[0], mock_tool_a)

        # No filter — both tools
        tools_all = _run(hub.get_all_tools())
        self.assertEqual(len(tools_all), 2)

    def test_get_tools_for_server_disconnected(self):
        from data_agent.mcp_hub import McpHubManager
        hub = McpHubManager()
        hub._ensure_table = MagicMock(return_value=False)
        hub._load_from_db = MagicMock(return_value=[])

        with tempfile.TemporaryDirectory() as tmp:
            path = _write_config(tmp, {"servers": [{"name": "s1"}]})
            hub._config_path = path
            hub.load_config()

        tools = _run(hub.get_tools_for_server("s1"))
        self.assertEqual(tools, [])

    def test_get_tools_for_server_connected(self):
        """get_tools_for_server returns tool metadata dicts."""
        from data_agent.mcp_hub import McpHubManager, McpServerConfig, McpServerStatus

        hub = McpHubManager()
        mock_tool = MagicMock()
        mock_tool.name = "buffer_analysis"
        mock_tool.description = "Create a buffer zone"

        cfg = McpServerConfig(name="test-srv")
        status = McpServerStatus(config=cfg, status="connected")
        status.toolset = MagicMock()
        status.toolset.get_tools = AsyncMock(return_value=[mock_tool])

        hub._servers = {"test-srv": status}

        result = _run(hub.get_tools_for_server("test-srv"))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "buffer_analysis")
        self.assertEqual(result[0]["description"], "Create a buffer zone")
        self.assertEqual(result[0]["server"], "test-srv")

    def test_shutdown_disconnects_connected(self):
        """shutdown() disconnects all connected servers."""
        from data_agent.mcp_hub import McpHubManager, McpServerConfig, McpServerStatus

        hub = McpHubManager()
        mock_toolset = MagicMock()
        mock_toolset.close = AsyncMock()

        cfg = McpServerConfig(name="s1")
        status = McpServerStatus(config=cfg, status="connected", toolset=mock_toolset)
        hub._servers = {"s1": status}
        hub._started = True

        _run(hub.shutdown())

        mock_toolset.close.assert_called_once()
        self.assertEqual(status.status, "disconnected")
        self.assertFalse(hub._started)

    def test_connect_server_unknown_transport(self):
        """Unknown transport type sets error status."""
        from data_agent.mcp_hub import McpHubManager, McpServerConfig, McpServerStatus

        hub = McpHubManager()
        cfg = McpServerConfig(name="bad", transport="websocket")
        hub._servers = {"bad": McpServerStatus(config=cfg)}

        result = _run(hub.connect_server("bad"))
        self.assertFalse(result)
        self.assertEqual(hub._servers["bad"].status, "error")
        self.assertIn("Unknown transport", hub._servers["bad"].error_message)


# ---------------------------------------------------------------------------
# TestMcpHubToolset
# ---------------------------------------------------------------------------

class TestMcpHubToolset(unittest.TestCase):
    """Tests for McpHubToolset BaseToolset wrapper."""

    def setUp(self):
        from data_agent.mcp_hub import reset_mcp_hub
        reset_mcp_hub()

    def tearDown(self):
        from data_agent.mcp_hub import reset_mcp_hub
        reset_mcp_hub()

    def test_get_tools_delegates_to_hub(self):
        """get_tools calls hub.get_all_tools with pipeline arg."""
        from data_agent.toolsets.mcp_hub_toolset import McpHubToolset

        mock_tool = MagicMock()
        mock_hub = MagicMock()
        mock_hub.get_all_tools = AsyncMock(return_value=[mock_tool])

        with patch("data_agent.mcp_hub.get_mcp_hub", return_value=mock_hub):
            toolset = McpHubToolset(pipeline="general")
            tools = _run(toolset.get_tools())

        mock_hub.get_all_tools.assert_called_once_with(pipeline="general")
        self.assertEqual(len(tools), 1)
        self.assertIs(tools[0], mock_tool)

    def test_get_tools_empty_when_no_servers(self):
        """Returns empty list when no MCP servers are connected."""
        from data_agent.toolsets.mcp_hub_toolset import McpHubToolset

        mock_hub = MagicMock()
        mock_hub.get_all_tools = AsyncMock(return_value=[])

        with patch("data_agent.mcp_hub.get_mcp_hub", return_value=mock_hub):
            toolset = McpHubToolset()
            tools = _run(toolset.get_tools())

        self.assertEqual(tools, [])

    def test_get_tools_exception_returns_empty(self):
        """If hub raises, toolset returns empty list instead of crashing."""
        from data_agent.toolsets.mcp_hub_toolset import McpHubToolset

        mock_hub = MagicMock()
        mock_hub.get_all_tools = AsyncMock(side_effect=RuntimeError("boom"))

        with patch("data_agent.mcp_hub.get_mcp_hub", return_value=mock_hub):
            toolset = McpHubToolset(pipeline="general")
            tools = _run(toolset.get_tools())

        self.assertEqual(tools, [])

    def test_close_is_noop(self):
        """close() should not raise."""
        from data_agent.toolsets.mcp_hub_toolset import McpHubToolset
        toolset = McpHubToolset()
        _run(toolset.close())  # should not raise

    def test_pipeline_attribute(self):
        from data_agent.toolsets.mcp_hub_toolset import McpHubToolset
        toolset = McpHubToolset(pipeline="planner")
        self.assertEqual(toolset._pipeline, "planner")

    def test_no_pipeline(self):
        from data_agent.toolsets.mcp_hub_toolset import McpHubToolset
        toolset = McpHubToolset()
        self.assertIsNone(toolset._pipeline)


# ---------------------------------------------------------------------------
# TestMcpApiEndpoints
# ---------------------------------------------------------------------------

class TestMcpApiEndpoints(unittest.TestCase):
    """Tests for /api/mcp/* REST endpoints."""

    def setUp(self):
        from data_agent.mcp_hub import reset_mcp_hub
        reset_mcp_hub()

    def tearDown(self):
        from data_agent.mcp_hub import reset_mcp_hub
        reset_mcp_hub()

    # --- GET /api/mcp/servers ---

    @patch("data_agent.frontend_api._get_user_from_request", return_value=None)
    def test_servers_unauthorized(self, _mock):
        from data_agent.frontend_api import _api_mcp_servers
        resp = _run(_api_mcp_servers(_make_request()))
        self.assertEqual(resp.status_code, 401)

    @patch("data_agent.frontend_api._get_user_from_request")
    def test_servers_returns_list(self, mock_user):
        mock_user.return_value = _make_user()

        mock_hub = MagicMock()
        mock_hub.get_server_statuses.return_value = [
            {"name": "s1", "status": "connected", "tool_count": 5}
        ]

        with patch("data_agent.mcp_hub.get_mcp_hub", return_value=mock_hub):
            from data_agent.frontend_api import _api_mcp_servers
            resp = _run(_api_mcp_servers(_make_request()))

        self.assertEqual(resp.status_code, 200)
        body = json.loads(resp.body)
        self.assertIn("servers", body)
        self.assertEqual(body["count"], 1)

    # --- GET /api/mcp/tools ---

    @patch("data_agent.frontend_api._get_user_from_request", return_value=None)
    def test_tools_unauthorized(self, _mock):
        from data_agent.frontend_api import _api_mcp_tools
        resp = _run(_api_mcp_tools(_make_request()))
        self.assertEqual(resp.status_code, 401)

    @patch("data_agent.frontend_api._get_user_from_request")
    def test_tools_returns_empty_no_servers(self, mock_user):
        mock_user.return_value = _make_user()

        mock_hub = MagicMock()
        mock_hub.get_server_statuses.return_value = []

        with patch("data_agent.mcp_hub.get_mcp_hub", return_value=mock_hub):
            from data_agent.frontend_api import _api_mcp_tools
            resp = _run(_api_mcp_tools(_make_request()))

        self.assertEqual(resp.status_code, 200)
        body = json.loads(resp.body)
        self.assertEqual(body["count"], 0)

    # --- POST /api/mcp/servers/{name}/toggle ---

    @patch("data_agent.frontend_api._get_user_from_request", return_value=None)
    def test_toggle_unauthorized(self, _mock):
        from data_agent.frontend_api import _api_mcp_toggle
        resp = _run(_api_mcp_toggle(
            _make_request(path_params={"name": "s1"}, body={"enabled": True})))
        self.assertEqual(resp.status_code, 401)

    @patch("data_agent.frontend_api._get_user_from_request")
    def test_toggle_non_admin_forbidden(self, mock_user):
        mock_user.return_value = _make_user(role="viewer")
        from data_agent.frontend_api import _api_mcp_toggle
        resp = _run(_api_mcp_toggle(
            _make_request(path_params={"name": "s1"}, body={"enabled": True})))
        self.assertEqual(resp.status_code, 403)

    @patch("data_agent.frontend_api._get_user_from_request")
    def test_toggle_admin_success(self, mock_user):
        mock_user.return_value = _make_user(role="admin")

        mock_hub = MagicMock()
        mock_hub.toggle_server = AsyncMock(
            return_value={"status": "ok", "server": "s1", "enabled": True, "connected": True})

        with patch("data_agent.mcp_hub.get_mcp_hub", return_value=mock_hub):
            from data_agent.frontend_api import _api_mcp_toggle
            resp = _run(_api_mcp_toggle(
                _make_request(path_params={"name": "s1"}, body={"enabled": True})))

        self.assertEqual(resp.status_code, 200)
        body = json.loads(resp.body)
        self.assertEqual(body["status"], "ok")

    # --- POST /api/mcp/servers/{name}/reconnect ---

    @patch("data_agent.frontend_api._get_user_from_request", return_value=None)
    def test_reconnect_unauthorized(self, _mock):
        from data_agent.frontend_api import _api_mcp_reconnect
        resp = _run(_api_mcp_reconnect(
            _make_request(path_params={"name": "s1"})))
        self.assertEqual(resp.status_code, 401)

    @patch("data_agent.frontend_api._get_user_from_request")
    def test_reconnect_non_admin_forbidden(self, mock_user):
        mock_user.return_value = _make_user(role="analyst")
        from data_agent.frontend_api import _api_mcp_reconnect
        resp = _run(_api_mcp_reconnect(
            _make_request(path_params={"name": "s1"})))
        self.assertEqual(resp.status_code, 403)

    @patch("data_agent.frontend_api._get_user_from_request")
    def test_reconnect_admin_success(self, mock_user):
        mock_user.return_value = _make_user(role="admin")

        mock_hub = MagicMock()
        mock_hub.reconnect_server = AsyncMock(
            return_value={"status": "ok", "server": "s1", "connected": True, "tool_count": 3})

        with patch("data_agent.mcp_hub.get_mcp_hub", return_value=mock_hub):
            from data_agent.frontend_api import _api_mcp_reconnect
            resp = _run(_api_mcp_reconnect(
                _make_request(path_params={"name": "s1"})))

        self.assertEqual(resp.status_code, 200)
        body = json.loads(resp.body)
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["tool_count"], 3)


# ---------------------------------------------------------------------------
# TestMcpHealthCheck
# ---------------------------------------------------------------------------

class TestMcpHealthCheck(unittest.TestCase):
    """Tests for check_mcp_hub() in health.py."""

    def setUp(self):
        from data_agent.mcp_hub import reset_mcp_hub
        reset_mcp_hub()

    def tearDown(self):
        from data_agent.mcp_hub import reset_mcp_hub
        reset_mcp_hub()

    def test_unconfigured(self):
        """No servers → unconfigured status."""
        from data_agent.health import check_mcp_hub
        result = check_mcp_hub()
        self.assertEqual(result["status"], "unconfigured")
        self.assertEqual(result["connected"], 0)
        self.assertEqual(result["total"], 0)

    def test_with_connected_servers(self):
        """Some connected servers → ok status."""
        from data_agent.health import check_mcp_hub
        from data_agent.mcp_hub import get_mcp_hub, McpServerConfig, McpServerStatus

        hub = get_mcp_hub()
        cfg1 = McpServerConfig(name="s1", enabled=True)
        cfg2 = McpServerConfig(name="s2", enabled=True)
        hub._servers = {
            "s1": McpServerStatus(config=cfg1, status="connected", tool_count=5),
            "s2": McpServerStatus(config=cfg2, status="disconnected"),
        }

        result = check_mcp_hub()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["connected"], 1)
        self.assertEqual(result["total"], 2)

    def test_all_disconnected(self):
        """All servers disconnected → disconnected status."""
        from data_agent.health import check_mcp_hub
        from data_agent.mcp_hub import get_mcp_hub, McpServerConfig, McpServerStatus

        hub = get_mcp_hub()
        cfg = McpServerConfig(name="s1", enabled=True)
        hub._servers = {
            "s1": McpServerStatus(config=cfg, status="disconnected"),
        }

        result = check_mcp_hub()
        self.assertEqual(result["status"], "disconnected")
        self.assertEqual(result["connected"], 0)
        self.assertEqual(result["total"], 1)


# ---------------------------------------------------------------------------
# TestMcpRouteRegistration
# ---------------------------------------------------------------------------

class TestMcpRouteRegistration(unittest.TestCase):
    """Tests that MCP routes are registered in get_frontend_api_routes()."""

    def test_mcp_routes_registered(self):
        from data_agent.frontend_api import get_frontend_api_routes
        routes = get_frontend_api_routes()
        paths = [r.path for r in routes]

        self.assertIn("/api/mcp/servers", paths)
        self.assertIn("/api/mcp/tools", paths)
        self.assertIn("/api/mcp/servers/{name}/toggle", paths)
        self.assertIn("/api/mcp/servers/{name}/reconnect", paths)
        self.assertIn("/api/mcp/servers/{name}", paths)  # PUT + DELETE


# ---------------------------------------------------------------------------
# TestMcpHubCrud
# ---------------------------------------------------------------------------

class TestMcpHubCrud(unittest.TestCase):
    """Tests for MCP Hub add/update/remove server CRUD."""

    def setUp(self):
        from data_agent.mcp_hub import reset_mcp_hub
        reset_mcp_hub()

    def tearDown(self):
        from data_agent.mcp_hub import reset_mcp_hub
        reset_mcp_hub()

    def test_add_server_duplicate(self):
        from data_agent.mcp_hub import McpHubManager, McpServerConfig, McpServerStatus
        hub = McpHubManager()
        cfg = McpServerConfig(name="existing")
        hub._servers["existing"] = McpServerStatus(config=cfg)
        result = _run(hub.add_server(McpServerConfig(name="existing")))
        self.assertEqual(result["status"], "error")
        self.assertIn("already exists", result["message"])

    def test_add_server_invalid_name(self):
        from data_agent.mcp_hub import McpHubManager, McpServerConfig
        hub = McpHubManager()
        result = _run(hub.add_server(McpServerConfig(name="")))
        self.assertEqual(result["status"], "error")

    @patch("data_agent.mcp_hub.McpHubManager._save_to_db", return_value=True)
    def test_add_server_success(self, _mock_save):
        from data_agent.mcp_hub import McpHubManager, McpServerConfig
        hub = McpHubManager()
        result = _run(hub.add_server(McpServerConfig(name="new-srv", transport="sse", url="http://x")))
        self.assertEqual(result["status"], "ok")
        self.assertIn("new-srv", hub._servers)

    @patch("data_agent.mcp_hub.McpHubManager._save_to_db", return_value=False)
    def test_add_server_db_failure(self, _mock_save):
        from data_agent.mcp_hub import McpHubManager, McpServerConfig
        hub = McpHubManager()
        result = _run(hub.add_server(McpServerConfig(name="new-srv")))
        self.assertEqual(result["status"], "error")
        self.assertNotIn("new-srv", hub._servers)

    def test_update_server_not_found(self):
        from data_agent.mcp_hub import McpHubManager
        hub = McpHubManager()
        result = _run(hub.update_server("ghost", {"description": "x"}))
        self.assertEqual(result["status"], "error")

    @patch("data_agent.mcp_hub.McpHubManager._save_to_db", return_value=True)
    def test_update_server_success(self, _mock_save):
        from data_agent.mcp_hub import McpHubManager, McpServerConfig, McpServerStatus
        hub = McpHubManager()
        cfg = McpServerConfig(name="s1", description="old")
        hub._servers["s1"] = McpServerStatus(config=cfg)
        result = _run(hub.update_server("s1", {"description": "new"}))
        self.assertEqual(result["status"], "ok")
        self.assertEqual(hub._servers["s1"].config.description, "new")

    def test_remove_server_not_found(self):
        from data_agent.mcp_hub import McpHubManager
        hub = McpHubManager()
        result = _run(hub.remove_server("ghost"))
        self.assertEqual(result["status"], "error")

    @patch("data_agent.mcp_hub.McpHubManager._delete_from_db", return_value=True)
    def test_remove_server_success(self, _mock_del):
        from data_agent.mcp_hub import McpHubManager, McpServerConfig, McpServerStatus
        hub = McpHubManager()
        cfg = McpServerConfig(name="s1")
        hub._servers["s1"] = McpServerStatus(config=cfg)
        result = _run(hub.remove_server("s1"))
        self.assertEqual(result["status"], "ok")
        self.assertNotIn("s1", hub._servers)

    @patch("data_agent.mcp_hub.McpHubManager._delete_from_db", return_value=True)
    @patch("data_agent.mcp_hub.McpHubManager.disconnect_server", new_callable=AsyncMock)
    def test_remove_server_disconnects_first(self, mock_disconnect, _mock_del):
        from data_agent.mcp_hub import McpHubManager, McpServerConfig, McpServerStatus
        hub = McpHubManager()
        cfg = McpServerConfig(name="s1")
        hub._servers["s1"] = McpServerStatus(config=cfg, status="connected")
        _run(hub.remove_server("s1"))
        mock_disconnect.assert_called_once_with("s1")


class TestMcpHubDbMethods(unittest.TestCase):
    """Tests for MCP Hub DB helper methods (no actual DB)."""

    def test_ensure_table_no_engine(self):
        from data_agent.mcp_hub import McpHubManager
        hub = McpHubManager()
        with patch("data_agent.db_engine.get_engine", return_value=None):
            result = hub._ensure_table()
        self.assertFalse(result)

    def test_load_from_db_no_engine(self):
        from data_agent.mcp_hub import McpHubManager
        hub = McpHubManager()
        with patch("data_agent.db_engine.get_engine", return_value=None):
            result = hub._load_from_db()
        self.assertEqual(result, [])

    def test_save_to_db_no_engine(self):
        from data_agent.mcp_hub import McpHubManager, McpServerConfig
        hub = McpHubManager()
        with patch("data_agent.db_engine.get_engine", return_value=None):
            result = hub._save_to_db(McpServerConfig(name="test"))
        self.assertFalse(result)

    def test_delete_from_db_no_engine(self):
        from data_agent.mcp_hub import McpHubManager
        hub = McpHubManager()
        with patch("data_agent.db_engine.get_engine", return_value=None):
            result = hub._delete_from_db("test")
        self.assertFalse(result)


# ---------------------------------------------------------------------------
# TestMcpI18n
# ---------------------------------------------------------------------------

class TestMcpI18n(unittest.TestCase):
    """Tests that MCP i18n keys exist in locale files."""

    def _load_yaml(self, lang):
        path = os.path.join(os.path.dirname(__file__), "locales", f"{lang}.yaml")
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def test_zh_keys_exist(self):
        data = self._load_yaml("zh")
        for key in ["mcp.server_connected", "mcp.server_failed",
                     "mcp.server_disconnected", "mcp.hub_startup", "mcp.no_config"]:
            self.assertIn(key, data, f"Missing zh key: {key}")

    def test_en_keys_exist(self):
        data = self._load_yaml("en")
        for key in ["mcp.server_connected", "mcp.server_failed",
                     "mcp.server_disconnected", "mcp.hub_startup", "mcp.no_config"]:
            self.assertIn(key, data, f"Missing en key: {key}")


# ---------------------------------------------------------------------------
# TestMcpUserIsolation (v10.0.1)
# ---------------------------------------------------------------------------

class TestMcpUserIsolation(unittest.TestCase):
    """Tests for per-user MCP server isolation."""

    def setUp(self):
        from data_agent.mcp_hub import reset_mcp_hub
        reset_mcp_hub()

    def tearDown(self):
        from data_agent.mcp_hub import reset_mcp_hub
        reset_mcp_hub()

    def test_config_has_owner_fields(self):
        """McpServerConfig has owner_username and is_shared fields."""
        from data_agent.mcp_hub import McpServerConfig
        cfg = McpServerConfig(name="test")
        self.assertIsNone(cfg.owner_username)
        self.assertTrue(cfg.is_shared)

    def test_config_with_owner(self):
        from data_agent.mcp_hub import McpServerConfig
        cfg = McpServerConfig(name="my-server", owner_username="alice", is_shared=False)
        self.assertEqual(cfg.owner_username, "alice")
        self.assertFalse(cfg.is_shared)

    def test_get_server_statuses_no_filter(self):
        """Without username filter, all servers returned."""
        from data_agent.mcp_hub import get_mcp_hub, McpServerConfig, McpServerStatus
        hub = get_mcp_hub()
        hub._servers["global"] = McpServerStatus(
            config=McpServerConfig(name="global", is_shared=True))
        hub._servers["alice-private"] = McpServerStatus(
            config=McpServerConfig(name="alice-private", owner_username="alice", is_shared=False))
        hub._servers["bob-private"] = McpServerStatus(
            config=McpServerConfig(name="bob-private", owner_username="bob", is_shared=False))

        statuses = hub.get_server_statuses()
        self.assertEqual(len(statuses), 3)

    def test_get_server_statuses_user_filter(self):
        """With username filter, only own + shared/global visible."""
        from data_agent.mcp_hub import get_mcp_hub, McpServerConfig, McpServerStatus
        hub = get_mcp_hub()
        hub._servers["global"] = McpServerStatus(
            config=McpServerConfig(name="global", is_shared=True))
        hub._servers["alice-private"] = McpServerStatus(
            config=McpServerConfig(name="alice-private", owner_username="alice", is_shared=False))
        hub._servers["bob-private"] = McpServerStatus(
            config=McpServerConfig(name="bob-private", owner_username="bob", is_shared=False))
        hub._servers["legacy"] = McpServerStatus(
            config=McpServerConfig(name="legacy"))  # owner=None, shared=True

        alice_statuses = hub.get_server_statuses(username="alice")
        names = {s["name"] for s in alice_statuses}
        self.assertIn("global", names)
        self.assertIn("alice-private", names)
        self.assertIn("legacy", names)  # owner_username is None → visible
        self.assertNotIn("bob-private", names)

    def test_get_server_statuses_includes_owner_fields(self):
        """Server status dicts include owner_username and is_shared."""
        from data_agent.mcp_hub import get_mcp_hub, McpServerConfig, McpServerStatus
        hub = get_mcp_hub()
        hub._servers["test"] = McpServerStatus(
            config=McpServerConfig(name="test", owner_username="alice", is_shared=False))

        statuses = hub.get_server_statuses()
        self.assertEqual(statuses[0]["owner_username"], "alice")
        self.assertFalse(statuses[0]["is_shared"])

    def test_can_manage_server_admin(self):
        """Admin can manage any server."""
        from data_agent.mcp_hub import get_mcp_hub, McpServerConfig, McpServerStatus
        hub = get_mcp_hub()
        hub._servers["alice-srv"] = McpServerStatus(
            config=McpServerConfig(name="alice-srv", owner_username="alice", is_shared=False))

        self.assertTrue(hub._can_manage_server("alice-srv", "admin", "admin"))

    def test_can_manage_server_owner(self):
        """Owner can manage their own server."""
        from data_agent.mcp_hub import get_mcp_hub, McpServerConfig, McpServerStatus
        hub = get_mcp_hub()
        hub._servers["alice-srv"] = McpServerStatus(
            config=McpServerConfig(name="alice-srv", owner_username="alice", is_shared=False))

        self.assertTrue(hub._can_manage_server("alice-srv", "alice", "analyst"))

    def test_cannot_manage_others_server(self):
        """Non-admin cannot manage another user's server."""
        from data_agent.mcp_hub import get_mcp_hub, McpServerConfig, McpServerStatus
        hub = get_mcp_hub()
        hub._servers["alice-srv"] = McpServerStatus(
            config=McpServerConfig(name="alice-srv", owner_username="alice", is_shared=False))

        self.assertFalse(hub._can_manage_server("alice-srv", "bob", "analyst"))

    def test_cannot_manage_nonexistent(self):
        from data_agent.mcp_hub import get_mcp_hub
        hub = get_mcp_hub()
        self.assertFalse(hub._can_manage_server("nonexistent", "bob", "analyst"))

    @patch("data_agent.mcp_hub.get_mcp_hub")
    def test_get_all_tools_user_filter(self, mock_get_hub):
        """get_all_tools with username filter skips other users' private servers."""
        from data_agent.mcp_hub import McpHubManager, McpServerConfig, McpServerStatus
        hub = McpHubManager()

        # Create mock server statuses
        shared_status = McpServerStatus(
            config=McpServerConfig(name="shared", is_shared=True),
            status="connected")
        alice_status = McpServerStatus(
            config=McpServerConfig(name="alice-srv", owner_username="alice", is_shared=False),
            status="connected")
        bob_status = McpServerStatus(
            config=McpServerConfig(name="bob-srv", owner_username="bob", is_shared=False),
            status="connected")

        # Mock toolsets
        class MockTool:
            def __init__(self, n): self.name = n
        class MockToolset:
            def __init__(self, tools): self._tools = tools
            async def get_tools(self): return self._tools

        shared_status.toolset = MockToolset([MockTool("shared_tool")])
        alice_status.toolset = MockToolset([MockTool("alice_tool")])
        bob_status.toolset = MockToolset([MockTool("bob_tool")])

        hub._servers = {"shared": shared_status, "alice-srv": alice_status, "bob-srv": bob_status}

        import asyncio
        tools = asyncio.get_event_loop().run_until_complete(
            hub.get_all_tools(username="alice"))
        tool_names = [t.name for t in tools]
        self.assertIn("shared_tool", tool_names)
        self.assertIn("alice_tool", tool_names)
        self.assertNotIn("bob_tool", tool_names)

    def test_mcp_new_routes_registered(self):
        """New per-user MCP routes are registered."""
        from data_agent.frontend_api import get_frontend_api_routes
        routes = get_frontend_api_routes()
        paths = [r.path for r in routes]

        self.assertIn("/api/mcp/servers/mine", paths)
        self.assertIn("/api/mcp/servers/{name}/share", paths)

    def test_add_server_sets_owner(self):
        """add_server persists owner_username."""
        from data_agent.mcp_hub import get_mcp_hub, McpServerConfig
        hub = get_mcp_hub()

        with patch.object(hub, '_save_to_db', return_value=True):
            import asyncio
            result = asyncio.get_event_loop().run_until_complete(
                hub.add_server(McpServerConfig(
                    name="user-srv", owner_username="alice", is_shared=False, enabled=False)))
            self.assertEqual(result["status"], "ok")

        status = hub._servers.get("user-srv")
        self.assertIsNotNone(status)
        self.assertEqual(status.config.owner_username, "alice")
        self.assertFalse(status.config.is_shared)

    def test_load_from_db_user_filter(self):
        """_load_from_db with username returns user's + shared + legacy servers."""
        from data_agent.mcp_hub import McpHubManager
        hub = McpHubManager()

        # Build mock result rows: 15 columns each
        #  0:name 1:desc 2:transport 3:enabled 4:category 5:pipelines
        #  6:command 7:args 8:env 9:cwd 10:url 11:headers 12:timeout
        #  13:owner_username 14:is_shared
        mock_rows = [
            ("shared-srv", "", "stdio", True, "", '["general"]', "", "[]", "{}", None, "", "{}", 5.0, "admin", True),
            ("alice-srv", "", "stdio", True, "", '["general"]', "", "[]", "{}", None, "", "{}", 5.0, "alice", False),
        ]

        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchall.return_value = mock_rows

        with patch("data_agent.db_engine.get_engine", return_value=mock_engine):
            configs = hub._load_from_db(username="alice")

        self.assertEqual(len(configs), 2)
        # Verify the SQL includes WHERE filter
        call_args = mock_conn.execute.call_args
        sql_text = str(call_args[0][0])
        self.assertIn("owner_username", sql_text)


if __name__ == "__main__":
    unittest.main()

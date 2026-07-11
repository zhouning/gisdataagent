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
        self.assertEqual(cfg.bearer_token_env_var, "")
        self.assertEqual(cfg.bearer_token_file_env_var, "")
        self.assertEqual(cfg.ca_bundle_env_var, "")
        self.assertFalse(cfg.system_managed)
        self.assertTrue(cfg.expose_raw_tools)

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
            bearer_token_env_var="ARCPY_TOKEN",
            bearer_token_file_env_var="ARCPY_TOKEN_FILE",
            ca_bundle_env_var="ARCPY_CA_FILE",
            system_managed=True,
            expose_raw_tools=False,
        )
        self.assertEqual(cfg.transport, "sse")
        self.assertTrue(cfg.enabled)
        self.assertEqual(cfg.pipelines, ["general"])
        self.assertEqual(cfg.url, "http://localhost:8080/sse")
        self.assertEqual(cfg.timeout, 10.0)
        self.assertEqual(cfg.bearer_token_env_var, "ARCPY_TOKEN")
        self.assertEqual(cfg.bearer_token_file_env_var, "ARCPY_TOKEN_FILE")
        self.assertEqual(cfg.ca_bundle_env_var, "ARCPY_CA_FILE")
        self.assertTrue(cfg.system_managed)
        self.assertFalse(cfg.expose_raw_tools)

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
        self.assertEqual(status.error_code, "")
        self.assertIsNone(status.connected_at)
        self.assertEqual(status.runtime_secrets, ())

    def test_runtime_secrets_are_excluded_from_status_repr(self):
        from data_agent.mcp_hub import McpServerConfig, McpServerStatus

        token = "repr-must-not-leak-token"
        status = McpServerStatus(
            config=McpServerConfig(name="secure"),
            runtime_secrets=(token,),
        )

        self.assertNotIn(token, repr(status))


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

    def test_load_yaml_parses_runtime_security_references(self):
        from data_agent.mcp_hub import McpHubManager
        hub = McpHubManager()

        with tempfile.TemporaryDirectory() as tmp:
            path = _write_config(tmp, {
                "servers": [{
                    "name": "secure-http",
                    "transport": "streamable_http",
                    "url": "https://arcpy.internal/mcp",
                    "bearer_token_env_var": "ARCPY_MCP_TOKEN",
                    "bearer_token_file_env_var": "ARCPY_MCP_TOKEN_FILE",
                    "ca_bundle_env_var": "ARCPY_MCP_CA_FILE",
                    "system_managed": True,
                    "expose_raw_tools": False,
                }]
            })
            hub._config_path = path
            configs = hub._load_yaml()

        self.assertEqual(len(configs), 1)
        config = configs[0]
        self.assertEqual(config.bearer_token_env_var, "ARCPY_MCP_TOKEN")
        self.assertEqual(config.bearer_token_file_env_var, "ARCPY_MCP_TOKEN_FILE")
        self.assertEqual(config.ca_bundle_env_var, "ARCPY_MCP_CA_FILE")
        self.assertTrue(config.system_managed)
        self.assertFalse(config.expose_raw_tools)

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
        self.assertEqual(statuses[0]["error_code"], "")

    def test_get_server_statuses_never_exposes_runtime_secrets(self):
        from data_agent.mcp_hub import McpHubManager, McpServerConfig, McpServerStatus

        token = "status-api-must-not-leak"
        hub = McpHubManager()
        hub._servers = {
            "secure": McpServerStatus(
                config=McpServerConfig(name="secure"),
                runtime_secrets=(token,),
            )
        }

        statuses = hub.get_server_statuses()

        self.assertNotIn("runtime_secrets", statuses[0])
        self.assertNotIn(token, repr(statuses))

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

    def test_get_all_tools_redacts_session_error_from_status_and_log(self):
        from data_agent.mcp_hub import McpHubManager, McpServerConfig, McpServerStatus

        token = "later-session-token"
        toolset = MagicMock()
        toolset.get_tools = AsyncMock(side_effect=RuntimeError(
            f"tool session failed with exact credential {token}"
        ))
        toolset.close = AsyncMock(side_effect=RuntimeError(
            f"close failed with exact credential {token}"
        ))
        status = McpServerStatus(
            config=McpServerConfig(name="secure"),
            status="connected",
            toolset=toolset,
            runtime_secrets=(token,),
        )
        hub = McpHubManager()
        hub._servers = {"secure": status}

        with patch("data_agent.mcp_hub.logger.warning") as warning:
            tools = _run(hub.get_all_tools())

        self.assertEqual(tools, [])
        self.assertNotIn(token, status.error_message)
        self.assertIn("tool session failed", status.error_message)
        self.assertNotIn("close failed", status.error_message)
        self.assertNotIn(token, repr(warning.call_args))
        toolset.close.assert_awaited_once()
        self.assertIsNone(status.toolset)
        self.assertEqual(status.runtime_secrets, ())
        self.assertEqual(status.status, "error")

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

    def test_get_tools_for_server_redacts_exact_runtime_secret(self):
        from data_agent.mcp_hub import McpHubManager, McpServerConfig, McpServerStatus

        token = "single-server-exact-token"
        toolset = MagicMock()
        toolset.get_tools = AsyncMock(side_effect=RuntimeError(
            f"tool lookup failed with exact credential {token}"
        ))
        toolset.close = AsyncMock(side_effect=RuntimeError(
            f"close lookup failed with exact credential {token}"
        ))
        status = McpServerStatus(
            config=McpServerConfig(name="secure"),
            status="connected",
            toolset=toolset,
            runtime_secrets=(token,),
        )
        hub = McpHubManager()
        hub._servers = {"secure": status}

        with patch("data_agent.mcp_hub.logger.warning") as warning:
            result = _run(hub.get_tools_for_server("secure"))

        self.assertEqual(result, [])
        self.assertNotIn(token, status.error_message)
        self.assertIn("lookup failed", status.error_message)
        self.assertNotIn("close lookup failed", status.error_message)
        self.assertNotIn(token, repr(warning.call_args))
        toolset.close.assert_awaited_once()
        self.assertIsNone(status.toolset)
        self.assertEqual(status.runtime_secrets, ())
        self.assertEqual(status.status, "error")

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

    def test_shutdown_cleans_errored_session_and_redacts_close_error(self):
        from data_agent.mcp_hub import McpHubManager, McpServerConfig, McpServerStatus

        token = "errored-shutdown-token"
        toolset = MagicMock()
        toolset.close = AsyncMock(side_effect=RuntimeError(
            f"shutdown close failed with exact credential {token}"
        ))
        status = McpServerStatus(
            config=McpServerConfig(name="secure"),
            status="error",
            toolset=toolset,
            error_message="primary sanitized failure",
            runtime_secrets=(token,),
        )
        hub = McpHubManager()
        hub._servers = {"secure": status}
        hub._started = True

        with patch("data_agent.mcp_hub.logger.warning") as warning:
            _run(hub.shutdown())

        toolset.close.assert_awaited_once()
        self.assertNotIn(token, repr(warning.call_args))
        self.assertIsNone(status.toolset)
        self.assertEqual(status.runtime_secrets, ())
        self.assertEqual(status.status, "error")
        self.assertEqual(status.error_message, "primary sanitized failure")
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


class TestSecureMcpHttpTransport(unittest.TestCase):
    """Secure streamable HTTP integration without real network calls."""

    def setUp(self):
        from data_agent.mcp_transport import (
            current_runtime_secrets,
            unregister_runtime_secrets,
        )

        while secrets := current_runtime_secrets():
            unregister_runtime_secrets(secrets)

    def tearDown(self):
        from data_agent.mcp_transport import (
            current_runtime_secrets,
            unregister_runtime_secrets,
        )

        while secrets := current_runtime_secrets():
            unregister_runtime_secrets(secrets)

    def test_connect_server_uses_runtime_bearer_and_private_ca_factory(self):
        from data_agent.mcp_hub import McpHubManager, McpServerConfig, McpServerStatus

        hub = McpHubManager()
        static_headers = {"X-Service": "arcpy"}
        config = McpServerConfig(
            name="arcpy",
            transport="streamable_http",
            url="https://arcpy.internal/mcp",
            headers=static_headers,
            bearer_token_env_var="ARCPY_TOKEN",
            bearer_token_file_env_var="ARCPY_TOKEN_FILE",
            ca_bundle_env_var="ARCPY_CA_FILE",
        )
        hub._servers = {
            "arcpy": McpServerStatus(config=config, error_code="STALE_ERROR")
        }
        toolset = MagicMock()

        async def get_tools_with_registered_secret():
            from data_agent.mcp_transport import current_runtime_secrets
            self.assertEqual(current_runtime_secrets(), ("runtime-token",))
            return []

        toolset.get_tools = AsyncMock(side_effect=get_tools_with_registered_secret)
        toolset.close = AsyncMock()
        connection_params = MagicMock()
        private_ca_factory = MagicMock(name="private_ca_factory")

        with tempfile.TemporaryDirectory() as tmp:
            token_path = os.path.join(tmp, "token")
            ca_path = os.path.join(tmp, "ca.pem")
            with open(token_path, "w", encoding="utf-8") as f:
                f.write(" runtime-token\n")
            with open(ca_path, "w", encoding="utf-8") as f:
                f.write("-----BEGIN CERTIFICATE-----\nca\n-----END CERTIFICATE-----\n")

            with (
                patch.dict(os.environ, {
                    "ARCPY_TOKEN": "environment-token",
                    "ARCPY_TOKEN_FILE": token_path,
                    "ARCPY_CA_FILE": ca_path,
                }, clear=False),
                patch(
                    "google.adk.tools.mcp_tool.mcp_session_manager."
                    "StreamableHTTPConnectionParams",
                    return_value=connection_params,
                ) as params_cls,
                patch(
                    "google.adk.tools.mcp_tool.mcp_toolset.McpToolset",
                    return_value=toolset,
                ) as toolset_cls,
                patch(
                    "data_agent.mcp_hub.build_httpx_client_factory",
                    return_value=private_ca_factory,
                ) as build_factory,
            ):
                result = _run(hub.connect_server("arcpy"))

        self.assertTrue(result)
        kwargs = params_cls.call_args.kwargs
        self.assertEqual(kwargs["headers"], {
            "X-Service": "arcpy",
            "Authorization": "Bearer runtime-token",
        })
        self.assertIs(kwargs["httpx_client_factory"], private_ca_factory)
        build_factory.assert_called_once_with(ca_path)
        self.assertEqual(static_headers, {"X-Service": "arcpy"})
        self.assertNotIn("Authorization", config.headers)
        self.assertEqual(hub._servers["arcpy"].runtime_secrets, ("runtime-token",))
        self.assertEqual(hub._servers["arcpy"].error_code, "")
        from data_agent.mcp_transport import (
            RedactingTextIO,
            current_runtime_secrets,
        )
        self.assertIsInstance(toolset_cls.call_args.kwargs["errlog"], RedactingTextIO)
        self.assertEqual(current_runtime_secrets(), ("runtime-token",))

        _run(hub.disconnect_server("arcpy"))
        self.assertEqual(current_runtime_secrets(), ())

    def test_disconnect_redacts_close_error_and_clears_runtime_secrets(self):
        from data_agent.mcp_hub import McpHubManager, McpServerConfig, McpServerStatus

        token = "close-error-exact-token"
        toolset = MagicMock()
        toolset.close = AsyncMock(side_effect=RuntimeError(
            f"close failed with exact credential {token}"
        ))
        status = McpServerStatus(
            config=McpServerConfig(name="secure"),
            status="connected",
            toolset=toolset,
            error_code="STALE_ERROR",
            runtime_secrets=(token,),
        )
        hub = McpHubManager()
        hub._servers = {"secure": status}

        with patch("data_agent.mcp_hub.logger.warning") as warning:
            result = _run(hub.disconnect_server("secure"))

        self.assertTrue(result)
        self.assertNotIn(token, repr(warning.call_args))
        self.assertIn("close failed", repr(warning.call_args))
        self.assertEqual(status.runtime_secrets, ())
        self.assertEqual(status.error_code, "")

    def test_connect_server_keeps_default_http_client_for_generic_server(self):
        from data_agent.mcp_hub import McpHubManager, McpServerConfig, McpServerStatus

        hub = McpHubManager()
        config = McpServerConfig(
            name="generic",
            transport="streamable_http",
            url="https://generic.internal/mcp",
            headers={"X-Static": "true"},
        )
        hub._servers = {"generic": McpServerStatus(config=config)}
        toolset = MagicMock()
        toolset.get_tools = AsyncMock(return_value=[])

        with (
            patch(
                "google.adk.tools.mcp_tool.mcp_session_manager."
                "StreamableHTTPConnectionParams"
            ) as params_cls,
            patch(
                "google.adk.tools.mcp_tool.mcp_toolset.McpToolset",
                return_value=toolset,
            ),
        ):
            result = _run(hub.connect_server("generic"))

        self.assertTrue(result)
        kwargs = params_cls.call_args.kwargs
        self.assertEqual(kwargs["headers"], {"X-Static": "true"})
        self.assertNotIn("httpx_client_factory", kwargs)
        self.assertEqual(config.headers, {"X-Static": "true"})

    def test_test_connection_uses_runtime_security_references(self):
        from data_agent.mcp_hub import McpHubManager, McpServerConfig

        hub = McpHubManager()
        config = McpServerConfig(
            name="__test__",
            transport="streamable_http",
            url="https://arcpy.internal/mcp",
            headers={"X-Test": "true"},
            bearer_token_env_var="ARCPY_TOKEN",
            ca_bundle_env_var="ARCPY_CA_FILE",
        )
        toolset = MagicMock()

        async def get_tools_with_ephemeral_secret():
            from data_agent.mcp_transport import current_runtime_secrets
            self.assertEqual(current_runtime_secrets(), ("test-token",))
            return [MagicMock()]

        toolset.get_tools = AsyncMock(side_effect=get_tools_with_ephemeral_secret)
        toolset.close = AsyncMock()
        private_ca_factory = MagicMock(name="private_ca_factory")

        with tempfile.TemporaryDirectory() as tmp:
            ca_path = os.path.join(tmp, "ca.pem")
            with open(ca_path, "w", encoding="utf-8") as f:
                f.write("-----BEGIN CERTIFICATE-----\nca\n-----END CERTIFICATE-----\n")
            with (
                patch.dict(os.environ, {
                    "ARCPY_TOKEN": "test-token",
                    "ARCPY_CA_FILE": ca_path,
                }, clear=False),
                patch(
                    "google.adk.tools.mcp_tool.mcp_session_manager."
                    "StreamableHTTPConnectionParams"
                ) as params_cls,
                patch(
                    "google.adk.tools.mcp_tool.mcp_toolset.McpToolset",
                    return_value=toolset,
                ),
                patch(
                    "data_agent.mcp_hub.build_httpx_client_factory",
                    return_value=private_ca_factory,
                ),
            ):
                result = _run(hub.test_connection(config))

        self.assertEqual(result["status"], "ok")
        kwargs = params_cls.call_args.kwargs
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer test-token")
        self.assertIs(kwargs["httpx_client_factory"], private_ca_factory)
        self.assertEqual(config.headers, {"X-Test": "true"})
        toolset.close.assert_awaited_once()
        from data_agent.mcp_transport import current_runtime_secrets
        self.assertEqual(current_runtime_secrets(), ())

    def test_connect_server_redacts_runtime_secret_from_status_and_log(self):
        from data_agent.mcp_hub import McpHubManager, McpServerConfig, McpServerStatus

        token = "never-print-this-token"
        failure = RuntimeError(
            f"Authorization: Bearer {token}; "
            f"GET https://arcpy.internal/mcp?token={token}&sig=signed-value failed"
        )
        hub = McpHubManager()
        config = McpServerConfig(
            name="arcpy",
            transport="streamable_http",
            url="https://arcpy.internal/mcp",
            bearer_token_env_var="ARCPY_TOKEN",
        )
        hub._servers = {"arcpy": McpServerStatus(config=config)}
        toolset = MagicMock()
        toolset.get_tools = AsyncMock(side_effect=failure)
        toolset.close = AsyncMock(side_effect=RuntimeError(
            f"probe close failed with exact credential {token}"
        ))

        with (
            patch.dict(os.environ, {"ARCPY_TOKEN": token}, clear=False),
            patch(
                "google.adk.tools.mcp_tool.mcp_toolset.McpToolset",
                return_value=toolset,
            ),
            patch("data_agent.mcp_hub.logger.warning") as warning,
        ):
            result = _run(hub.connect_server("arcpy"))

        self.assertFalse(result)
        error_message = hub._servers["arcpy"].error_message
        self.assertNotIn(token, error_message)
        self.assertNotIn("signed-value", error_message)
        self.assertIn("failed", error_message)
        self.assertNotIn(token, repr(warning.call_args))
        self.assertNotIn("signed-value", repr(warning.call_args))
        toolset.close.assert_awaited_once()
        self.assertIsNone(hub._servers["arcpy"].toolset)
        self.assertEqual(hub._servers["arcpy"].runtime_secrets, ())
        self.assertEqual(hub._servers["arcpy"].error_code, "")
        from data_agent.mcp_transport import current_runtime_secrets
        self.assertEqual(current_runtime_secrets(), ())

    def test_connect_server_returns_machine_actionable_configuration_error(self):
        from data_agent.mcp_hub import McpHubManager, McpServerConfig, McpServerStatus

        config = McpServerConfig(
            name="missing-token",
            transport="streamable_http",
            url="https://host/mcp",
            bearer_token_env_var="DEFINITELY_MISSING_MCP_TOKEN",
        )
        hub = McpHubManager()
        hub._servers = {"missing-token": McpServerStatus(config=config)}

        with patch.dict(
            os.environ, {"DEFINITELY_MISSING_MCP_TOKEN": ""}, clear=False
        ):
            result = _run(hub.connect_server("missing-token"))

        self.assertFalse(result)
        status = hub._servers["missing-token"]
        self.assertEqual(status.status, "error")
        self.assertEqual(status.error_code, "ARCPY_MCP_TOKEN_MISSING")
        self.assertEqual(status.error_message, "MCP credential is not available")
        self.assertIsNone(status.toolset)
        self.assertEqual(status.runtime_secrets, ())

    def test_test_connection_returns_machine_actionable_configuration_error(self):
        from data_agent.mcp_hub import McpHubManager, McpServerConfig

        config = McpServerConfig(
            name="__test__",
            transport="streamable_http",
            url="https://host/mcp",
            bearer_token_env_var="DEFINITELY_MISSING_MCP_TOKEN",
        )

        with patch.dict(
            os.environ, {"DEFINITELY_MISSING_MCP_TOKEN": ""}, clear=False
        ):
            result = _run(McpHubManager().test_connection(config))

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error_code"], "ARCPY_MCP_TOKEN_MISSING")
        self.assertEqual(result["message"], "MCP credential is not available")

    def test_connect_server_cancellation_cleans_probe_and_registry(self):
        from data_agent.mcp_hub import McpHubManager, McpServerConfig, McpServerStatus
        from data_agent.mcp_transport import current_runtime_secrets

        token = "cancelled-connect-token"
        probe_started = asyncio.Event()
        toolset = MagicMock()

        async def blocked_get_tools():
            probe_started.set()
            await asyncio.Future()

        toolset.get_tools = AsyncMock(side_effect=blocked_get_tools)
        toolset.close = AsyncMock()
        config = McpServerConfig(
            name="cancelled-connect",
            transport="streamable_http",
            url="https://host/mcp",
            bearer_token_env_var="ARCPY_TOKEN",
        )
        status = McpServerStatus(config=config)
        hub = McpHubManager()
        hub._servers = {config.name: status}

        async def scenario():
            with (
                patch.dict(os.environ, {"ARCPY_TOKEN": token}, clear=False),
                patch(
                    "google.adk.tools.mcp_tool.mcp_toolset.McpToolset",
                    return_value=toolset,
                ),
            ):
                task = asyncio.create_task(hub.connect_server(config.name))
                await probe_started.wait()
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task

        _run(scenario())

        toolset.close.assert_awaited_once()
        self.assertEqual(current_runtime_secrets(), ())
        self.assertIsNone(status.toolset)
        self.assertEqual(status.runtime_secrets, ())

    def test_concurrent_connects_create_one_owned_session(self):
        from data_agent.mcp_hub import McpHubManager, McpServerConfig, McpServerStatus
        from data_agent.mcp_transport import current_runtime_secrets

        token = "concurrent-connect-token"
        probe_started = asyncio.Event()
        release_probe = asyncio.Event()
        created_toolsets = []

        def create_toolset(**_kwargs):
            toolset = MagicMock()

            async def blocked_get_tools():
                probe_started.set()
                await release_probe.wait()
                return []

            toolset.get_tools = AsyncMock(side_effect=blocked_get_tools)
            toolset.close = AsyncMock()
            created_toolsets.append(toolset)
            return toolset

        config = McpServerConfig(
            name="concurrent",
            transport="streamable_http",
            url="https://host/mcp",
            bearer_token_env_var="ARCPY_TOKEN",
        )
        status = McpServerStatus(config=config)
        hub = McpHubManager()
        hub._servers = {config.name: status}

        async def scenario():
            with (
                patch.dict(os.environ, {"ARCPY_TOKEN": token}, clear=False),
                patch(
                    "google.adk.tools.mcp_tool.mcp_toolset.McpToolset",
                    side_effect=create_toolset,
                ) as toolset_cls,
            ):
                first = asyncio.create_task(hub.connect_server(config.name))
                await probe_started.wait()
                second = asyncio.create_task(hub.connect_server(config.name))
                await asyncio.sleep(0)
                release_probe.set()
                results = await asyncio.gather(first, second)
                self.assertEqual(results, [True, True])
                self.assertEqual(toolset_cls.call_count, 1)

                await hub.disconnect_server(config.name)

        _run(scenario())

        self.assertEqual(len(created_toolsets), 1)
        created_toolsets[0].close.assert_awaited_once()
        self.assertIsNone(status.toolset)
        self.assertEqual(status.runtime_secrets, ())
        self.assertEqual(current_runtime_secrets(), ())

    def test_disconnect_waits_for_in_progress_reconnect(self):
        from data_agent.mcp_hub import McpHubManager, McpServerConfig, McpServerStatus

        reconnect_probe_started = asyncio.Event()
        release_reconnect_probe = asyncio.Event()
        initial_toolset = MagicMock()
        initial_toolset.close = AsyncMock()
        replacement_toolset = MagicMock()

        async def blocked_get_tools():
            reconnect_probe_started.set()
            await release_reconnect_probe.wait()
            return []

        replacement_toolset.get_tools = AsyncMock(side_effect=blocked_get_tools)
        replacement_toolset.close = AsyncMock()
        config = McpServerConfig(
            name="reconnect-race",
            transport="streamable_http",
            url="https://host/mcp",
        )
        status = McpServerStatus(
            config=config,
            status="connected",
            toolset=initial_toolset,
        )
        hub = McpHubManager()
        hub._servers = {config.name: status}

        async def scenario():
            with patch(
                "google.adk.tools.mcp_tool.mcp_toolset.McpToolset",
                return_value=replacement_toolset,
            ):
                reconnect = asyncio.create_task(hub.reconnect_server(config.name))
                await reconnect_probe_started.wait()
                disconnect = asyncio.create_task(hub.disconnect_server(config.name))
                await asyncio.sleep(0)
                release_reconnect_probe.set()
                reconnect_result, disconnect_result = await asyncio.gather(
                    reconnect, disconnect
                )
                self.assertEqual(reconnect_result["status"], "ok")
                self.assertTrue(disconnect_result)

        _run(scenario())

        initial_toolset.close.assert_awaited_once()
        replacement_toolset.close.assert_awaited_once()
        self.assertEqual(status.status, "disconnected")
        self.assertIsNone(status.toolset)

    def test_test_connection_cancellation_cleans_probe_and_registry(self):
        from data_agent.mcp_hub import McpHubManager, McpServerConfig
        from data_agent.mcp_transport import current_runtime_secrets

        token = "cancelled-test-token"
        probe_started = asyncio.Event()
        toolset = MagicMock()

        async def blocked_get_tools():
            probe_started.set()
            await asyncio.Future()

        toolset.get_tools = AsyncMock(side_effect=blocked_get_tools)
        toolset.close = AsyncMock()
        config = McpServerConfig(
            name="__test__",
            transport="streamable_http",
            url="https://host/mcp",
            bearer_token_env_var="ARCPY_TOKEN",
        )

        async def scenario():
            with (
                patch.dict(os.environ, {"ARCPY_TOKEN": token}, clear=False),
                patch(
                    "google.adk.tools.mcp_tool.mcp_toolset.McpToolset",
                    return_value=toolset,
                ),
            ):
                task = asyncio.create_task(McpHubManager().test_connection(config))
                await probe_started.wait()
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task

        _run(scenario())

        toolset.close.assert_awaited_once()
        self.assertEqual(current_runtime_secrets(), ())

    def test_aggregate_lookup_failure_does_not_clobber_reconnected_session(self):
        from data_agent.mcp_hub import McpHubManager, McpServerConfig, McpServerStatus
        from data_agent.mcp_transport import (
            current_runtime_secrets,
            register_runtime_secrets,
        )

        old_token = "stale-aggregate-token"
        new_token = "replacement-aggregate-token"
        lookup_started = asyncio.Event()
        release_lookup = asyncio.Event()
        old_toolset = MagicMock()

        async def blocked_old_lookup():
            lookup_started.set()
            await release_lookup.wait()
            raise RuntimeError(f"old aggregate lookup exposed {old_token}")

        old_toolset.get_tools = AsyncMock(side_effect=blocked_old_lookup)
        old_toolset.close = AsyncMock()
        new_toolset = MagicMock()
        new_toolset.get_tools = AsyncMock(return_value=[])
        new_toolset.close = AsyncMock()
        config = McpServerConfig(
            name="aggregate-race",
            transport="streamable_http",
            url="https://host/mcp",
            bearer_token_env_var="ARCPY_TOKEN",
            pipelines=["general"],
        )
        status = McpServerStatus(
            config=config,
            status="connected",
            toolset=old_toolset,
            runtime_secrets=(old_token,),
        )
        hub = McpHubManager()
        hub._servers = {config.name: status}
        register_runtime_secrets([old_token])

        async def scenario():
            with (
                patch.dict(os.environ, {"ARCPY_TOKEN": new_token}, clear=False),
                patch(
                    "google.adk.tools.mcp_tool.mcp_toolset.McpToolset",
                    return_value=new_toolset,
                ),
                patch("data_agent.mcp_hub.logger.warning") as warning,
            ):
                lookup = asyncio.create_task(hub.get_all_tools(pipeline="general"))
                await lookup_started.wait()
                reconnect = asyncio.create_task(hub.reconnect_server(config.name))
                await asyncio.sleep(0)
                release_lookup.set()
                lookup_result, reconnect_result = await asyncio.gather(
                    lookup, reconnect
                )

                self.assertEqual(lookup_result, [])
                self.assertEqual(reconnect_result["status"], "ok")
                self.assertNotIn(old_token, repr(warning.call_args_list))
                self.assertEqual(status.status, "connected")
                self.assertIs(status.toolset, new_toolset)
                self.assertEqual(status.runtime_secrets, (new_token,))
                self.assertEqual(current_runtime_secrets(), (new_token,))
                new_toolset.close.assert_not_awaited()

                await hub.disconnect_server(config.name)

        _run(scenario())

        old_toolset.close.assert_awaited_once()
        new_toolset.close.assert_awaited_once()
        self.assertEqual(current_runtime_secrets(), ())

    def test_single_lookup_failure_does_not_clobber_reconnected_session(self):
        from data_agent.mcp_hub import McpHubManager, McpServerConfig, McpServerStatus
        from data_agent.mcp_transport import (
            current_runtime_secrets,
            register_runtime_secrets,
        )

        old_token = "stale-single-token"
        new_token = "replacement-single-token"
        lookup_started = asyncio.Event()
        release_lookup = asyncio.Event()
        old_toolset = MagicMock()

        async def blocked_old_lookup():
            lookup_started.set()
            await release_lookup.wait()
            raise RuntimeError(f"old single lookup exposed {old_token}")

        old_toolset.get_tools = AsyncMock(side_effect=blocked_old_lookup)
        old_toolset.close = AsyncMock()
        new_toolset = MagicMock()
        new_toolset.get_tools = AsyncMock(return_value=[])
        new_toolset.close = AsyncMock()
        config = McpServerConfig(
            name="single-race",
            transport="streamable_http",
            url="https://host/mcp",
            bearer_token_env_var="ARCPY_TOKEN",
        )
        status = McpServerStatus(
            config=config,
            status="connected",
            toolset=old_toolset,
            runtime_secrets=(old_token,),
        )
        hub = McpHubManager()
        hub._servers = {config.name: status}
        register_runtime_secrets([old_token])

        async def scenario():
            with (
                patch.dict(os.environ, {"ARCPY_TOKEN": new_token}, clear=False),
                patch(
                    "google.adk.tools.mcp_tool.mcp_toolset.McpToolset",
                    return_value=new_toolset,
                ),
                patch("data_agent.mcp_hub.logger.warning") as warning,
            ):
                lookup = asyncio.create_task(hub.get_tools_for_server(config.name))
                await lookup_started.wait()
                reconnect = asyncio.create_task(hub.reconnect_server(config.name))
                await asyncio.sleep(0)
                release_lookup.set()
                lookup_result, reconnect_result = await asyncio.gather(
                    lookup, reconnect
                )

                self.assertEqual(lookup_result, [])
                self.assertEqual(reconnect_result["status"], "ok")
                self.assertNotIn(old_token, repr(warning.call_args_list))
                self.assertEqual(status.status, "connected")
                self.assertIs(status.toolset, new_toolset)
                self.assertEqual(status.runtime_secrets, (new_token,))
                self.assertEqual(current_runtime_secrets(), (new_token,))
                new_toolset.close.assert_not_awaited()

                await hub.disconnect_server(config.name)

        _run(scenario())

        old_toolset.close.assert_awaited_once()
        new_toolset.close.assert_awaited_once()
        self.assertEqual(current_runtime_secrets(), ())

    def test_remove_waits_for_in_progress_connect_and_cleans_owned_session(self):
        from data_agent.mcp_hub import McpHubManager, McpServerConfig, McpServerStatus
        from data_agent.mcp_transport import current_runtime_secrets

        token = "remove-race-token"
        probe_started = asyncio.Event()
        release_probe = asyncio.Event()
        toolset = MagicMock()

        async def blocked_get_tools():
            probe_started.set()
            await release_probe.wait()
            return []

        toolset.get_tools = AsyncMock(side_effect=blocked_get_tools)
        toolset.close = AsyncMock()
        config = McpServerConfig(
            name="remove-race",
            transport="streamable_http",
            url="https://host/mcp",
            bearer_token_env_var="ARCPY_TOKEN",
        )
        status = McpServerStatus(config=config)
        hub = McpHubManager()
        hub._servers = {config.name: status}
        hub._delete_from_db = MagicMock(return_value=True)

        async def scenario():
            with (
                patch.dict(os.environ, {"ARCPY_TOKEN": token}, clear=False),
                patch(
                    "google.adk.tools.mcp_tool.mcp_toolset.McpToolset",
                    return_value=toolset,
                ),
            ):
                connect = asyncio.create_task(hub.connect_server(config.name))
                await probe_started.wait()
                remove = asyncio.create_task(hub.remove_server(config.name))
                await asyncio.sleep(0)
                release_probe.set()
                connect_result, remove_result = await asyncio.gather(
                    connect, remove
                )
                self.assertTrue(connect_result)
                self.assertEqual(remove_result["status"], "ok")

        _run(scenario())

        self.assertNotIn(config.name, hub._servers)
        toolset.close.assert_awaited_once()
        self.assertEqual(current_runtime_secrets(), ())
        hub._delete_from_db.assert_called_once_with(config.name)

    def test_update_waits_for_connect_then_reconnects_with_updated_config(self):
        from data_agent.mcp_hub import McpHubManager, McpServerConfig, McpServerStatus
        from data_agent.mcp_transport import current_runtime_secrets

        old_token = "update-old-token"
        new_token = "update-new-token"
        old_probe_started = asyncio.Event()
        release_old_probe = asyncio.Event()
        old_toolset = MagicMock()

        async def blocked_old_get_tools():
            old_probe_started.set()
            await release_old_probe.wait()
            return []

        old_toolset.get_tools = AsyncMock(side_effect=blocked_old_get_tools)
        old_toolset.close = AsyncMock()
        new_toolset = MagicMock()
        new_toolset.get_tools = AsyncMock(return_value=[])
        new_toolset.close = AsyncMock()
        config = McpServerConfig(
            name="update-race",
            transport="streamable_http",
            url="https://old.host/mcp",
            bearer_token_env_var="OLD_TOKEN",
        )
        status = McpServerStatus(config=config)
        hub = McpHubManager()
        hub._servers = {config.name: status}
        hub._save_to_db = MagicMock(return_value=True)

        async def scenario():
            with (
                patch.dict(
                    os.environ,
                    {"OLD_TOKEN": old_token, "NEW_TOKEN": new_token},
                    clear=False,
                ),
                patch(
                    "google.adk.tools.mcp_tool.mcp_toolset.McpToolset",
                    side_effect=[old_toolset, new_toolset],
                ),
                patch(
                    "google.adk.tools.mcp_tool.mcp_session_manager."
                    "StreamableHTTPConnectionParams",
                    side_effect=lambda **kwargs: MagicMock(**kwargs),
                ) as params_cls,
            ):
                connect = asyncio.create_task(hub.connect_server(config.name))
                await old_probe_started.wait()
                update = asyncio.create_task(hub.update_server(config.name, {
                    "url": "https://new.host/mcp",
                    "bearer_token_env_var": "NEW_TOKEN",
                }))
                await asyncio.sleep(0)
                release_old_probe.set()
                connect_result, update_result = await asyncio.gather(
                    connect, update
                )

                self.assertTrue(connect_result)
                self.assertEqual(update_result["status"], "ok")
                self.assertEqual(params_cls.call_count, 2)
                self.assertEqual(
                    params_cls.call_args_list[0].kwargs["url"],
                    "https://old.host/mcp",
                )
                self.assertEqual(
                    params_cls.call_args_list[1].kwargs["url"],
                    "https://new.host/mcp",
                )
                self.assertEqual(status.status, "connected")
                self.assertIs(status.toolset, new_toolset)
                self.assertEqual(status.runtime_secrets, (new_token,))
                self.assertEqual(current_runtime_secrets(), (new_token,))
                old_toolset.close.assert_awaited_once()
                new_toolset.close.assert_not_awaited()

                await hub.disconnect_server(config.name)

        _run(scenario())

        self.assertEqual(config.url, "https://new.host/mcp")
        self.assertEqual(config.bearer_token_env_var, "NEW_TOKEN")
        new_toolset.close.assert_awaited_once()
        self.assertEqual(current_runtime_secrets(), ())

    def test_concurrent_adds_create_one_server_and_one_session(self):
        from data_agent.mcp_hub import McpHubManager, McpServerConfig
        from data_agent.mcp_transport import current_runtime_secrets

        token = "concurrent-add-token"
        probe_started = asyncio.Event()
        release_probe = asyncio.Event()
        toolset = MagicMock()

        async def blocked_get_tools():
            probe_started.set()
            await release_probe.wait()
            return []

        toolset.get_tools = AsyncMock(side_effect=blocked_get_tools)
        toolset.close = AsyncMock()
        first_config = McpServerConfig(
            name="concurrent-add",
            transport="streamable_http",
            url="https://host/mcp",
            bearer_token_env_var="ARCPY_TOKEN",
            enabled=True,
        )
        second_config = McpServerConfig(
            name="concurrent-add",
            transport="streamable_http",
            url="https://host/mcp",
            bearer_token_env_var="ARCPY_TOKEN",
            enabled=True,
        )
        hub = McpHubManager()
        hub._save_to_db = MagicMock(return_value=True)

        async def scenario():
            with (
                patch.dict(os.environ, {"ARCPY_TOKEN": token}, clear=False),
                patch(
                    "google.adk.tools.mcp_tool.mcp_toolset.McpToolset",
                    return_value=toolset,
                ) as toolset_cls,
            ):
                first = asyncio.create_task(hub.add_server(first_config))
                await probe_started.wait()
                second = asyncio.create_task(hub.add_server(second_config))
                await asyncio.sleep(0)
                release_probe.set()
                results = await asyncio.gather(first, second)

                self.assertEqual(
                    sorted(result["status"] for result in results),
                    ["error", "ok"],
                )
                duplicate = next(
                    result for result in results if result["status"] == "error"
                )
                self.assertIn("already exists", duplicate["message"])
                self.assertEqual(toolset_cls.call_count, 1)
                self.assertEqual(list(hub._servers), [first_config.name])
                self.assertIs(hub._servers[first_config.name].toolset, toolset)

                await hub.disconnect_server(first_config.name)

        _run(scenario())

        hub._save_to_db.assert_called_once()
        toolset.close.assert_awaited_once()
        self.assertEqual(current_runtime_secrets(), ())

    def test_test_connection_redacts_runtime_secret_from_returned_error(self):
        from data_agent.mcp_hub import McpHubManager, McpServerConfig

        token = "test-connection-secret"
        toolset = MagicMock()
        toolset.get_tools = AsyncMock(side_effect=RuntimeError(
            f"Bearer {token} rejected at https://host/mcp?signature=signed-value"
        ))
        toolset.close = AsyncMock(side_effect=RuntimeError(
            f"test cleanup failed with exact credential {token}"
        ))
        config = McpServerConfig(
            name="__test__",
            transport="streamable_http",
            url="https://host/mcp",
            bearer_token_env_var="ARCPY_TOKEN",
        )

        with (
            patch.dict(os.environ, {"ARCPY_TOKEN": token}, clear=False),
            patch(
                "google.adk.tools.mcp_tool.mcp_toolset.McpToolset",
                return_value=toolset,
            ),
            patch("data_agent.mcp_hub.logger.warning") as warning,
        ):
            result = _run(McpHubManager().test_connection(config))

        self.assertEqual(result["status"], "error")
        self.assertNotIn(token, result["message"])
        self.assertNotIn("signed-value", result["message"])
        self.assertIn("rejected", result["message"])
        self.assertNotIn("cleanup failed", result["message"])
        self.assertNotIn(token, repr(warning.call_args))
        toolset.close.assert_awaited_once()
        from data_agent.mcp_transport import current_runtime_secrets
        self.assertEqual(current_runtime_secrets(), ())


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
        self.assertIn("/api/mcp/servers/{name:path}/toggle", paths)
        self.assertIn("/api/mcp/servers/{name:path}/reconnect", paths)
        self.assertIn("/api/mcp/servers/{name:path}", paths)  # PUT + DELETE


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

    @patch("data_agent.mcp_hub.McpHubManager._save_to_db", return_value=True)
    def test_update_server_applies_security_reference_and_management_fields(self, mock_save):
        from data_agent.mcp_hub import McpHubManager, McpServerConfig, McpServerStatus

        hub = McpHubManager()
        config = McpServerConfig(name="s1", transport="streamable_http")
        hub._servers["s1"] = McpServerStatus(config=config)
        updates = {
            "bearer_token_env_var": "NEW_TOKEN",
            "bearer_token_file_env_var": "NEW_TOKEN_FILE",
            "ca_bundle_env_var": "NEW_CA_FILE",
            "system_managed": True,
            "expose_raw_tools": False,
            "is_shared": False,
        }

        result = _run(hub.update_server("s1", updates))

        self.assertEqual(result["status"], "ok")
        for field_name, value in updates.items():
            self.assertEqual(getattr(config, field_name), value)
        mock_save.assert_called_once_with(config)

    @patch("data_agent.mcp_hub.McpHubManager._save_to_db", return_value=True)
    @patch("data_agent.mcp_hub.McpHubManager._connect_server_unlocked", new_callable=AsyncMock)
    @patch("data_agent.mcp_hub.McpHubManager._disconnect_server_unlocked", new_callable=AsyncMock)
    def test_update_server_reconnects_for_runtime_security_reference_change(
        self, disconnect, connect, _save
    ):
        from data_agent.mcp_hub import McpHubManager, McpServerConfig, McpServerStatus

        hub = McpHubManager()
        config = McpServerConfig(name="s1", transport="streamable_http")
        hub._servers["s1"] = McpServerStatus(config=config, status="connected")

        result = _run(hub.update_server("s1", {"ca_bundle_env_var": "NEW_CA"}))

        self.assertEqual(result["status"], "ok")
        disconnect.assert_awaited_once_with("s1")
        connect.assert_awaited_once_with("s1")

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
    @patch("data_agent.mcp_hub.McpHubManager._cleanup_runtime", new_callable=AsyncMock)
    def test_remove_server_cleans_runtime_first(self, cleanup_runtime, _mock_del):
        from data_agent.mcp_hub import McpHubManager, McpServerConfig, McpServerStatus
        hub = McpHubManager()
        cfg = McpServerConfig(name="s1")
        status = McpServerStatus(config=cfg, status="connected")
        hub._servers["s1"] = status
        _run(hub.remove_server("s1"))
        cleanup_runtime.assert_awaited_once_with("s1", status)


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

    def test_ensure_table_creates_security_reference_columns_idempotently(self):
        from data_agent.mcp_hub import McpHubManager

        connection = MagicMock()
        connection.__enter__.return_value = connection
        engine = MagicMock()
        engine.connect.return_value = connection

        with patch("data_agent.db_engine.get_engine", return_value=engine):
            result = McpHubManager()._ensure_table()

        self.assertTrue(result)
        sql = "\n".join(str(call.args[0]) for call in connection.execute.call_args_list)
        for column in (
            "bearer_token_env_var",
            "bearer_token_file_env_var",
            "ca_bundle_env_var",
            "system_managed",
            "expose_raw_tools",
        ):
            self.assertIn(column, sql)
            self.assertIn(f"ADD COLUMN IF NOT EXISTS {column}", sql)

    def test_load_from_db_maps_security_reference_columns(self):
        from data_agent.mcp_hub import McpHubManager

        row = (
            "arcpy", "Private ArcPy", "streamable_http", True, "gis",
            ["general"], "", [], {}, None, "https://arcpy.internal/mcp",
            {"X-Service": "arcpy"}, 7.5,
            "ARCPY_TOKEN", "ARCPY_TOKEN_FILE", "ARCPY_CA_FILE",
            True, False, "admin", True,
        )
        result_proxy = MagicMock()
        result_proxy.fetchall.return_value = [row]
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.execute.return_value = result_proxy
        engine = MagicMock()
        engine.connect.return_value = connection

        with patch("data_agent.db_engine.get_engine", return_value=engine):
            configs = McpHubManager()._load_from_db()

        self.assertEqual(len(configs), 1)
        config = configs[0]
        self.assertEqual(config.bearer_token_env_var, "ARCPY_TOKEN")
        self.assertEqual(config.bearer_token_file_env_var, "ARCPY_TOKEN_FILE")
        self.assertEqual(config.ca_bundle_env_var, "ARCPY_CA_FILE")
        self.assertTrue(config.system_managed)
        self.assertFalse(config.expose_raw_tools)
        self.assertEqual(config.owner_username, "admin")
        self.assertTrue(config.is_shared)

    def test_save_to_db_persists_reference_names_not_resolved_values(self):
        from data_agent.mcp_hub import McpHubManager, McpServerConfig

        connection = MagicMock()
        connection.__enter__.return_value = connection
        engine = MagicMock()
        engine.connect.return_value = connection
        config = McpServerConfig(
            name="arcpy",
            transport="streamable_http",
            url="https://arcpy.internal/mcp",
            bearer_token_env_var="ARCPY_TOKEN",
            bearer_token_file_env_var="ARCPY_TOKEN_FILE",
            ca_bundle_env_var="ARCPY_CA_FILE",
            system_managed=True,
            expose_raw_tools=False,
        )

        with (
            patch("data_agent.db_engine.get_engine", return_value=engine),
            patch.dict(os.environ, {"ARCPY_TOKEN": "resolved-secret-value"}, clear=False),
        ):
            result = McpHubManager()._save_to_db(config)

        self.assertTrue(result)
        sql, params = connection.execute.call_args.args
        self.assertIn("bearer_token_env_var", str(sql))
        self.assertEqual(params["bearer_token_env_var"], "ARCPY_TOKEN")
        self.assertEqual(params["bearer_token_file_env_var"], "ARCPY_TOKEN_FILE")
        self.assertEqual(params["ca_bundle_env_var"], "ARCPY_CA_FILE")
        self.assertTrue(params["system_managed"])
        self.assertFalse(params["expose_raw_tools"])
        self.assertNotIn("resolved-secret-value", repr(params))


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
        self.assertIn("/api/mcp/servers/{name:path}/share", paths)

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

        # Build mock result rows: 20 columns each
        #  0:name 1:desc 2:transport 3:enabled 4:category 5:pipelines
        #  6:command 7:args 8:env 9:cwd 10:url 11:headers 12:timeout
        #  13:token env 14:token file env 15:CA env 16:system 17:raw tools
        #  18:owner_username 19:is_shared
        mock_rows = [
            ("shared-srv", "", "stdio", True, "", '["general"]', "", "[]", "{}", None, "", "{}", 5.0,
             "", "", "", False, True, "admin", True),
            ("alice-srv", "", "stdio", True, "", '["general"]', "", "[]", "{}", None, "", "{}", 5.0,
             "", "", "", False, True, "alice", False),
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

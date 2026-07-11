"""Contract tests for the system-managed remote ArcPy MCP registration."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from data_agent.mcp_hub import McpHubManager, McpServerConfig, McpServerStatus


ARCPY_ENV_KEYS = (
    "ARCPY_MCP_ENABLED",
    "ARCPY_MCP_URL",
    "ARCPY_MCP_CONNECT_TIMEOUT",
    "ARCPY_MCP_TOKEN",
    "ARCPY_MCP_TOKEN_FILE",
    "ARCPY_MCP_CA_BUNDLE",
)


def _clear_arcpy_environment(monkeypatch):
    for key in ARCPY_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def _config_only_hub():
    hub = McpHubManager()
    hub._ensure_table = MagicMock(return_value=False)
    hub._load_from_db = MagicMock(return_value=[])
    hub._load_yaml = MagicMock(return_value=[])
    return hub


def test_environment_registers_system_managed_arcpy(monkeypatch):
    _clear_arcpy_environment(monkeypatch)
    monkeypatch.setenv("ARCPY_MCP_ENABLED", "true")
    monkeypatch.setenv("ARCPY_MCP_URL", "https://arcpy.internal/mcp")
    hub = _config_only_hub()

    configs = hub.load_config()

    assert len(configs) == 1
    config = hub._servers["arcpy-remote"].config
    assert config == McpServerConfig(
        name="arcpy-remote",
        description="Private ArcGIS Pro 3.7.1 ArcPy MCP service",
        transport="streamable_http",
        enabled=True,
        category="gis",
        pipelines=["general", "planner", "governance"],
        url="https://arcpy.internal/mcp",
        timeout=10.0,
        bearer_token_env_var="ARCPY_MCP_TOKEN",
        bearer_token_file_env_var="ARCPY_MCP_TOKEN_FILE",
        ca_bundle_env_var="ARCPY_MCP_CA_BUNDLE",
        system_managed=True,
        expose_raw_tools=False,
        source="environment",
        is_shared=True,
    )


def test_environment_connect_timeout_is_configurable(monkeypatch):
    _clear_arcpy_environment(monkeypatch)
    monkeypatch.setenv("ARCPY_MCP_ENABLED", "yes")
    monkeypatch.setenv("ARCPY_MCP_URL", "https://arcpy.internal/mcp")
    monkeypatch.setenv("ARCPY_MCP_CONNECT_TIMEOUT", "12.5")
    hub = _config_only_hub()

    hub.load_config()

    assert hub._servers["arcpy-remote"].config.timeout == 12.5


@pytest.mark.parametrize("value", ["false", "0", "no"])
def test_false_values_do_not_register_system_config(monkeypatch, value):
    _clear_arcpy_environment(monkeypatch)
    monkeypatch.setenv("ARCPY_MCP_ENABLED", value)
    monkeypatch.setenv("ARCPY_MCP_URL", "https://arcpy.internal/mcp")
    hub = _config_only_hub()

    assert hub.load_config() == []
    assert "arcpy-remote" not in hub._servers


def test_environment_arcpy_overrides_same_name_db_and_yaml(monkeypatch):
    _clear_arcpy_environment(monkeypatch)
    monkeypatch.setenv("ARCPY_MCP_ENABLED", "1")
    monkeypatch.setenv("ARCPY_MCP_URL", "https://environment.example/mcp")
    db_config = McpServerConfig(
        name="arcpy-remote", url="https://database.example/mcp", source="db"
    )
    yaml_config = McpServerConfig(
        name="arcpy-remote", url="https://yaml.example/mcp", source="yaml"
    )
    hub = McpHubManager()
    hub._ensure_table = MagicMock(return_value=True)
    hub._load_from_db = MagicMock(return_value=[db_config])
    hub._load_yaml = MagicMock(return_value=[yaml_config])

    configs = hub.load_config()

    assert [config.name for config in configs].count("arcpy-remote") == 1
    config = hub._servers["arcpy-remote"].config
    assert config.url == "https://environment.example/mcp"
    assert config.source == "environment"
    assert config.system_managed is True


def test_enabled_without_url_registers_and_reports_stable_config_error(monkeypatch):
    _clear_arcpy_environment(monkeypatch)
    monkeypatch.setenv("ARCPY_MCP_ENABLED", "true")
    hub = _config_only_hub()

    hub.load_config()
    success = asyncio.run(hub.connect_server("arcpy-remote"))

    status = hub._servers["arcpy-remote"]
    assert success is False
    assert status.config.url == ""
    assert status.error_code == "ARCPY_MCP_URL_MISSING"
    assert status.error_message == "ArcPy MCP URL is not configured"


def test_remote_disables_only_legacy_windows_stdio_configuration(monkeypatch):
    _clear_arcpy_environment(monkeypatch)
    monkeypatch.setenv("ARCPY_MCP_ENABLED", "true")
    monkeypatch.setenv("ARCPY_MCP_URL", "https://arcpy.internal/mcp")
    legacy = McpServerConfig(
        name="arcgis-pro-tools",
        description="Old ArcPy tools",
        transport="stdio",
        command=r"D:\\ArcGIS\\Python\\python.exe",
        enabled=True,
        source="db",
    )
    other_stdio = McpServerConfig(
        name="portable-tools",
        transport="stdio",
        command="python",
        enabled=True,
        source="db",
    )
    hub = McpHubManager()
    hub._ensure_table = MagicMock(return_value=True)
    hub._load_from_db = MagicMock(return_value=[legacy, other_stdio])
    hub._load_yaml = MagicMock(return_value=[])
    hub._update_enabled_in_db = MagicMock()

    hub.load_config()

    legacy_runtime = hub._servers["arcgis-pro-tools"].config
    assert legacy_runtime.enabled is False
    assert "Legacy Windows stdio configuration" in legacy_runtime.description
    assert hub._servers["portable-tools"].config.enabled is True
    hub._update_enabled_in_db.assert_called_once_with("arcgis-pro-tools", False)

    hub.connect_server = AsyncMock(return_value=True)
    assert asyncio.run(hub.startup()) is True
    started_names = [call.args[0] for call in hub.connect_server.await_args_list]
    assert "arcgis-pro-tools" not in started_names
    assert set(started_names) == {"portable-tools", "arcpy-remote"}


def test_non_windows_or_non_stdio_legacy_row_is_not_forced_disabled(monkeypatch):
    _clear_arcpy_environment(monkeypatch)
    monkeypatch.setenv("ARCPY_MCP_ENABLED", "true")
    monkeypatch.setenv("ARCPY_MCP_URL", "https://arcpy.internal/mcp")
    configs = [
        McpServerConfig(
            name="arcgis-pro-tools",
            transport="stdio",
            command="python",
            enabled=True,
            source="db",
        ),
        McpServerConfig(
            name="arcgis-pro-tools-http",
            transport="streamable_http",
            url="https://legacy.example/mcp",
            enabled=True,
            source="db",
        ),
    ]
    hub = McpHubManager()
    hub._ensure_table = MagicMock(return_value=True)
    hub._load_from_db = MagicMock(return_value=configs)
    hub._load_yaml = MagicMock(return_value=[])
    hub._update_enabled_in_db = MagicMock()

    hub.load_config()

    assert hub._servers["arcgis-pro-tools"].config.enabled is True
    assert hub._servers["arcgis-pro-tools-http"].config.enabled is True
    hub._update_enabled_in_db.assert_not_called()


def test_raw_arcpy_tools_are_not_returned_by_generic_endpoints():
    raw_tool = MagicMock(name="raw_arcpy_tool")
    toolset = MagicMock()
    toolset.get_tools = AsyncMock(return_value=[raw_tool])
    config = McpServerConfig(
        name="arcpy-remote",
        enabled=True,
        pipelines=["general"],
        expose_raw_tools=False,
    )
    hub = McpHubManager()
    hub._servers = {
        "arcpy-remote": McpServerStatus(
            config=config,
            toolset=toolset,
            status="connected",
            tool_count=1,
        )
    }

    assert asyncio.run(hub.get_all_tools(pipeline="general")) == []
    assert asyncio.run(hub.get_tools_for_server("arcpy-remote")) == []
    toolset.get_tools.assert_not_awaited()


def test_failed_startup_remains_retryable():
    hub = McpHubManager()
    hub._servers = {
        "remote": McpServerStatus(
            config=McpServerConfig(name="remote", enabled=True)
        )
    }
    hub.connect_server = AsyncMock(return_value=False)

    result = asyncio.run(hub.startup())

    assert result is False
    assert hub._started is False


@pytest.mark.parametrize("enabled", [False, True])
def test_successful_or_empty_startup_becomes_started(enabled):
    hub = McpHubManager()
    if enabled:
        hub._servers = {
            "remote": McpServerStatus(
                config=McpServerConfig(name="remote", enabled=True)
            )
        }
    else:
        hub._servers = {
            "disabled": McpServerStatus(
                config=McpServerConfig(name="disabled", enabled=False)
            )
        }
    hub.connect_server = AsyncMock(return_value=True)

    result = asyncio.run(hub.startup())

    assert result is True
    assert hub._started is True


def test_retry_failed_servers_uses_bounded_delays_and_stops_on_success():
    hub = McpHubManager()
    status = McpServerStatus(
        config=McpServerConfig(name="remote", enabled=True), status="error"
    )
    hub._servers = {"remote": status}
    attempts = iter([False, False, True])

    async def connect(name):
        connected = next(attempts)
        if connected:
            status.status = "connected"
            status.toolset = object()
        return connected

    delays = []

    async def sleep(delay):
        delays.append(delay)

    hub.connect_server = AsyncMock(side_effect=connect)

    result = asyncio.run(
        hub.retry_failed_servers(delays=(2, 5, 10, 20), sleep=sleep)
    )

    assert result is True
    assert hub._started is True
    assert delays == [2, 5, 10]
    assert hub.connect_server.await_count == 3


def test_retry_failed_servers_exhausts_exact_default_schedule():
    hub = McpHubManager()
    hub._servers = {
        "remote": McpServerStatus(
            config=McpServerConfig(name="remote", enabled=True), status="error"
        )
    }
    hub.connect_server = AsyncMock(return_value=False)
    delays = []

    async def sleep(delay):
        delays.append(delay)

    result = asyncio.run(hub.retry_failed_servers(sleep=sleep))

    assert result is False
    assert hub._started is False
    assert delays == [2, 5, 10, 20]
    assert hub.connect_server.await_count == 4


def test_retry_failed_servers_retries_only_enabled_non_connected_servers():
    hub = McpHubManager()
    hub._servers = {
        "failed": McpServerStatus(
            config=McpServerConfig(name="failed", enabled=True), status="error"
        ),
        "disabled": McpServerStatus(
            config=McpServerConfig(name="disabled", enabled=False), status="error"
        ),
        "connected": McpServerStatus(
            config=McpServerConfig(name="connected", enabled=True),
            status="connected",
            toolset=object(),
        ),
    }

    async def connect(name):
        hub._servers[name].status = "connected"
        hub._servers[name].toolset = object()
        return True

    hub.connect_server = AsyncMock(side_effect=connect)

    async def no_wait(_delay):
        return None

    assert asyncio.run(hub.retry_failed_servers(sleep=no_wait)) is True
    hub.connect_server.assert_awaited_once_with("failed")


def test_retry_failed_servers_is_cancellation_safe():
    hub = McpHubManager()
    hub._servers = {
        "remote": McpServerStatus(
            config=McpServerConfig(name="remote", enabled=True), status="error"
        )
    }
    sleep_started = asyncio.Event()

    async def blocked_sleep(_delay):
        sleep_started.set()
        await asyncio.Future()

    hub.connect_server = AsyncMock(return_value=False)

    async def scenario():
        task = asyncio.create_task(hub.retry_failed_servers(sleep=blocked_sleep))
        await sleep_started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())

    assert hub._started is False
    hub.connect_server.assert_not_awaited()


@pytest.mark.parametrize("operation", ["toggle", "update", "remove"])
def test_system_managed_server_rejects_hub_mutation(operation):
    hub = McpHubManager()
    hub._servers = {
        "arcpy-remote": McpServerStatus(
            config=McpServerConfig(
                name="arcpy-remote", enabled=True, system_managed=True
            )
        )
    }

    if operation == "toggle":
        result = asyncio.run(hub.toggle_server("arcpy-remote", False))
    elif operation == "update":
        result = asyncio.run(
            hub.update_server("arcpy-remote", {"description": "changed"})
        )
    else:
        result = asyncio.run(hub.remove_server("arcpy-remote"))

    assert result["status"] == "forbidden"
    assert "system-managed" in result["message"].lower()


def test_system_managed_server_reconnect_remains_allowed():
    hub = McpHubManager()
    hub._servers = {
        "arcpy-remote": McpServerStatus(
            config=McpServerConfig(
                name="arcpy-remote", enabled=True, system_managed=True
            )
        )
    }
    hub._disconnect_server_unlocked = AsyncMock(return_value=True)
    hub._connect_server_unlocked = AsyncMock(return_value=True)

    result = asyncio.run(hub.reconnect_server("arcpy-remote"))

    assert result["status"] == "ok"
    assert result["connected"] is True


def test_shutdown_bridge_is_sync_and_idempotent_without_running_loop():
    from data_agent.mcp_hub import McpShutdownBridge

    hub = MagicMock()
    hub.shutdown = AsyncMock()
    client = MagicMock()
    client.close = AsyncMock()
    bridge = McpShutdownBridge(
        hub_getter=lambda: hub,
        client_getter=lambda: client,
    )

    bridge()
    bridge()

    hub.shutdown.assert_awaited_once()
    client.close.assert_awaited_once()


def test_shutdown_bridge_schedules_cleanup_on_running_loop():
    from data_agent.mcp_hub import McpShutdownBridge

    hub = MagicMock()
    hub.shutdown = AsyncMock()
    bridge = McpShutdownBridge(
        hub_getter=lambda: hub,
        client_getter=lambda: None,
    )

    async def scenario():
        bridge()
        await asyncio.sleep(0)

    asyncio.run(scenario())

    hub.shutdown.assert_awaited_once()
    assert bridge._cleanup_task is not None


def test_app_uses_single_retry_task_and_success_gated_startup():
    app_source = Path(__file__).with_name("app.py").read_text(encoding="utf-8")
    retry_body = app_source.split(
        "async def _retry_mcp_hub_startup", 1
    )[1].split("async def _ensure_mcp_hub_started", 1)[0]

    assert "async def _ensure_mcp_hub_started" in app_source
    assert "_mcp_retry_task" in app_source
    assert "if startup_succeeded:" in app_source
    assert "_mcp_started = True" in app_source
    assert "retry_failed_servers" in app_source
    assert "_mcp_retry_task = None" not in retry_body
    assert "if _mcp_retry_task is not None:" in app_source


def test_app_registers_idempotent_mcp_shutdown_bridge():
    app_source = Path(__file__).with_name("app.py").read_text(encoding="utf-8")

    assert "McpShutdownBridge" in app_source
    assert "atexit.register(_mcp_shutdown_bridge)" in app_source

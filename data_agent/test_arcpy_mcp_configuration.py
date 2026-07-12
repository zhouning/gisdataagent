"""Contract tests for the system-managed remote ArcPy MCP registration."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

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


@pytest.mark.parametrize("value", ["false", "0", "no"])
def test_explicit_false_disables_stale_db_arcpy(monkeypatch, value):
    _clear_arcpy_environment(monkeypatch)
    monkeypatch.setenv("ARCPY_MCP_ENABLED", value)
    stale = McpServerConfig(
        name="arcpy-remote",
        transport="streamable_http",
        enabled=True,
        url="https://stale-database.example/mcp",
        source="db",
    )
    hub = McpHubManager()
    hub._ensure_table = MagicMock(return_value=True)
    hub._load_from_db = MagicMock(return_value=[stale])
    hub._load_yaml = MagicMock(return_value=[])
    hub._update_enabled_in_db = MagicMock()

    configs = hub.load_config()

    assert configs == [stale]
    assert hub._servers["arcpy-remote"].config.enabled is False
    assert hub._servers["arcpy-remote"].config.source == "db"
    hub._update_enabled_in_db.assert_called_once_with("arcpy-remote", False)
    hub.connect_server = AsyncMock(return_value=True)
    assert asyncio.run(hub.startup()) is True
    hub.connect_server.assert_not_awaited()


def test_explicit_false_disables_stale_yaml_arcpy_without_persisting(monkeypatch):
    _clear_arcpy_environment(monkeypatch)
    monkeypatch.setenv("ARCPY_MCP_ENABLED", "false")
    stale = McpServerConfig(
        name="arcpy-remote",
        transport="streamable_http",
        enabled=True,
        url="https://stale-yaml.example/mcp",
        source="yaml",
    )
    hub = McpHubManager()
    hub._ensure_table = MagicMock(return_value=False)
    hub._load_from_db = MagicMock(return_value=[])
    hub._load_yaml = MagicMock(return_value=[stale])
    hub._update_enabled_in_db = MagicMock()

    configs = hub.load_config()

    assert configs == [stale]
    assert hub._servers["arcpy-remote"].config.enabled is False
    assert hub._servers["arcpy-remote"].config.source == "yaml"
    hub._update_enabled_in_db.assert_not_called()
    hub.connect_server = AsyncMock(return_value=True)
    assert asyncio.run(hub.startup()) is True
    hub.connect_server.assert_not_awaited()


def test_unset_enabled_does_not_override_stale_persisted_arcpy(monkeypatch):
    _clear_arcpy_environment(monkeypatch)
    stale = McpServerConfig(
        name="arcpy-remote",
        transport="streamable_http",
        enabled=True,
        url="https://persisted.example/mcp",
        source="db",
    )
    hub = McpHubManager()
    hub._ensure_table = MagicMock(return_value=True)
    hub._load_from_db = MagicMock(return_value=[stale])
    hub._load_yaml = MagicMock(return_value=[])
    hub._update_enabled_in_db = MagicMock()

    hub.load_config()

    assert hub._servers["arcpy-remote"].config.enabled is True
    hub._update_enabled_in_db.assert_not_called()


@pytest.mark.parametrize("value", ["", "tru", "enabled", "2"])
def test_invalid_enablement_suppresses_stale_config_with_stable_error(
    monkeypatch, value
):
    _clear_arcpy_environment(monkeypatch)
    monkeypatch.setenv("ARCPY_MCP_ENABLED", value)
    stale = McpServerConfig(
        name="arcpy-remote",
        transport="streamable_http",
        enabled=True,
        url="https://stale.example/mcp",
        source="db",
    )
    hub = McpHubManager()
    hub._ensure_table = MagicMock(return_value=True)
    hub._load_from_db = MagicMock(return_value=[stale])
    hub._load_yaml = MagicMock(return_value=[])
    hub._update_enabled_in_db = MagicMock()

    hub.load_config()

    status = hub._servers["arcpy-remote"]
    assert status.config.source == "environment"
    assert status.config.enabled is False
    assert status.config.system_managed is True
    assert status.config.expose_raw_tools is False
    assert status.status == "error"
    assert status.error_code == "ARCPY_MCP_ENABLED_INVALID"
    hub._update_enabled_in_db.assert_called_once_with("arcpy-remote", False)


def test_invalid_enablement_suppresses_stale_yaml_without_persisting(monkeypatch):
    _clear_arcpy_environment(monkeypatch)
    monkeypatch.setenv("ARCPY_MCP_ENABLED", "tru")
    stale = McpServerConfig(
        name="arcpy-remote",
        transport="streamable_http",
        enabled=True,
        url="https://stale-yaml.example/mcp",
        source="yaml",
    )
    hub = McpHubManager()
    hub._ensure_table = MagicMock(return_value=False)
    hub._load_from_db = MagicMock(return_value=[])
    hub._load_yaml = MagicMock(return_value=[stale])
    hub._update_enabled_in_db = MagicMock()

    hub.load_config()

    status = hub._servers["arcpy-remote"]
    assert status.config.source == "environment"
    assert status.config.enabled is False
    assert status.error_code == "ARCPY_MCP_ENABLED_INVALID"
    hub._update_enabled_in_db.assert_not_called()


@pytest.mark.parametrize("url", ["ftp://arcpy.internal/mcp", "arcpy.internal/mcp"])
def test_invalid_system_url_is_disabled_with_stable_error(monkeypatch, url):
    _clear_arcpy_environment(monkeypatch)
    monkeypatch.setenv("ARCPY_MCP_ENABLED", "true")
    monkeypatch.setenv("ARCPY_MCP_URL", url)
    hub = _config_only_hub()

    hub.load_config()

    status = hub._servers["arcpy-remote"]
    assert status.config.enabled is False
    assert status.config.expose_raw_tools is False
    assert status.status == "error"
    assert status.error_code == "ARCPY_MCP_URL_INVALID"


@pytest.mark.parametrize("timeout", ["nan", "inf", "0", "-1", "301", "slow"])
def test_invalid_system_timeout_is_disabled_with_stable_error(
    monkeypatch, timeout
):
    _clear_arcpy_environment(monkeypatch)
    monkeypatch.setenv("ARCPY_MCP_ENABLED", "true")
    monkeypatch.setenv("ARCPY_MCP_URL", "https://arcpy.internal/mcp")
    monkeypatch.setenv("ARCPY_MCP_CONNECT_TIMEOUT", timeout)
    hub = _config_only_hub()

    hub.load_config()

    status = hub._servers["arcpy-remote"]
    assert status.config.enabled is False
    assert status.status == "error"
    assert status.error_code == "ARCPY_MCP_CONNECT_TIMEOUT_INVALID"


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


def test_persisted_db_and_yaml_configs_cannot_claim_managed_provenance(monkeypatch):
    _clear_arcpy_environment(monkeypatch)
    db_config = McpServerConfig(
        name="db-managed",
        enabled=False,
        system_managed=True,
        source="db",
    )
    yaml_config = McpServerConfig(
        name="yaml-managed",
        enabled=False,
        system_managed=True,
        source="yaml",
    )
    hub = McpHubManager()
    hub._ensure_table = MagicMock(return_value=True)
    hub._load_from_db = MagicMock(return_value=[db_config])
    hub._load_yaml = MagicMock(return_value=[yaml_config])

    hub.load_config()

    assert hub._servers["db-managed"].config.system_managed is False
    assert hub._servers["yaml-managed"].config.system_managed is False
    assert hub._can_manage_server("db-managed", "admin", "admin") is True
    assert hub._can_manage_server("yaml-managed", "admin", "admin") is True


def test_malformed_system_url_fails_closed_without_raising(monkeypatch):
    _clear_arcpy_environment(monkeypatch)
    monkeypatch.setenv("ARCPY_MCP_ENABLED", "true")
    monkeypatch.setenv("ARCPY_MCP_URL", "http://[")
    hub = _config_only_hub()

    configs = hub.load_config()

    assert len(configs) == 1
    status = hub._servers["arcpy-remote"]
    assert status.config.enabled is False
    assert status.status == "error"
    assert status.error_code == "ARCPY_MCP_URL_INVALID"
    assert status.error_message == "ArcPy MCP URL configuration is invalid"
    assert "http://[" not in repr(hub.get_server_statuses())


def test_closed_hub_cannot_be_reopened_by_startup_retry_or_connect():
    hub = McpHubManager()
    config = McpServerConfig(name="remote", enabled=True)
    hub._servers = {"remote": McpServerStatus(config=config)}

    async def scenario():
        await hub.shutdown()
        hub._servers["remote"].status = "disconnected"
        startup = await hub.startup()
        retry = await hub.retry_failed_servers(delays=(), sleep=AsyncMock())
        connect = await hub.connect_server("remote")
        return startup, retry, connect

    startup, retry, connect = asyncio.run(scenario())

    assert startup is False
    assert retry is False
    assert connect is False
    assert hub._closing is True
    assert hub._started is False


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


def test_retry_stops_after_hub_begins_closing():
    hub = McpHubManager()
    hub._servers = {
        "remote": McpServerStatus(
            config=McpServerConfig(name="remote", enabled=True), status="error"
        )
    }
    sleep_started = asyncio.Event()
    release_sleep = asyncio.Event()

    async def blocked_sleep(_delay):
        sleep_started.set()
        await release_sleep.wait()

    hub.connect_server = AsyncMock(return_value=True)

    async def scenario():
        retry = asyncio.create_task(hub.retry_failed_servers(sleep=blocked_sleep))
        await sleep_started.wait()
        await hub.shutdown()
        release_sleep.set()
        assert await retry is False

    asyncio.run(scenario())

    hub.connect_server.assert_not_awaited()
    assert hub._started is False
    assert hub._closing is True


def test_toggle_disable_wins_against_stale_queued_connect():
    hub = McpHubManager()
    config = McpServerConfig(name="remote", enabled=True)
    hub._servers = {"remote": McpServerStatus(config=config)}
    hub._update_enabled_in_db = MagicMock()

    async def scenario():
        lock = hub._get_lifecycle_lock("remote")
        await lock.acquire()
        try:
            disable = asyncio.create_task(hub.toggle_server("remote", False))
            await asyncio.sleep(0)
            stale_connect = asyncio.create_task(hub.connect_server("remote"))
            await asyncio.sleep(0)
        finally:
            lock.release()
        return await disable, await stale_connect

    disabled, connected = asyncio.run(scenario())

    assert disabled["status"] == "ok"
    assert config.enabled is False
    assert connected is False
    assert hub._servers["remote"].toolset is None
    assert hub._started is True


def test_shutdown_barrier_rejects_toolset_ownership_from_inflight_connect():
    hub = McpHubManager()
    probe_started = asyncio.Event()
    release_probe = asyncio.Event()
    toolset = MagicMock()

    async def blocked_get_tools():
        probe_started.set()
        await release_probe.wait()
        return [MagicMock(name="raw-tool")]

    toolset.get_tools = AsyncMock(side_effect=blocked_get_tools)
    toolset.close = AsyncMock()
    config = McpServerConfig(
        name="remote",
        transport="streamable_http",
        enabled=True,
        url="https://remote.example/mcp",
    )
    hub._servers = {"remote": McpServerStatus(config=config)}

    async def scenario():
        with patch(
            "google.adk.tools.mcp_tool.mcp_toolset.McpToolset",
            return_value=toolset,
        ):
            connecting = asyncio.create_task(hub.connect_server("remote"))
            await probe_started.wait()
            shutting_down = asyncio.create_task(hub.shutdown())
            await asyncio.sleep(0)
            assert hub._closing is True
            release_probe.set()
            return await connecting, await shutting_down

    connected, _ = asyncio.run(scenario())

    assert connected is False
    assert hub._started is False
    assert hub._servers["remote"].toolset is None
    toolset.close.assert_awaited_once()


def test_public_status_sanitizes_detailed_connection_error():
    hub = McpHubManager()
    detailed = (
        "connection failed for https://10.1.2.3/mcp "
        "using certificate /private/ca.pem"
    )
    status = McpServerStatus(
        config=McpServerConfig(name="remote", enabled=True),
        status="error",
        error_code="",
        error_message=detailed,
    )
    hub._servers = {"remote": status}

    public = hub.get_server_statuses()[0]

    assert public["error_code"] == "MCP_CONNECTION_FAILED"
    assert public["error_message"] == "MCP server connection failed"
    assert "10.1.2.3" not in repr(public)
    assert "/private/ca.pem" not in repr(public)
    assert status.error_message == detailed


def test_connection_log_keeps_redacted_detail_while_public_status_is_generic(
    monkeypatch,
):
    token = "private-runtime-token"
    monkeypatch.setenv("ARCPY_TEST_TOKEN", token)
    detailed = (
        f"Authorization: Bearer {token}; failed https://10.1.2.3/mcp "
        "with /private/ca.pem"
    )
    toolset = MagicMock()
    toolset.get_tools = AsyncMock(side_effect=RuntimeError(detailed))
    toolset.close = AsyncMock()
    config = McpServerConfig(
        name="remote",
        transport="streamable_http",
        enabled=True,
        url="https://remote.example/mcp",
        bearer_token_env_var="ARCPY_TEST_TOKEN",
    )
    hub = McpHubManager()
    hub._servers = {"remote": McpServerStatus(config=config)}

    with (
        patch(
            "google.adk.tools.mcp_tool.mcp_toolset.McpToolset",
            return_value=toolset,
        ),
        patch("data_agent.mcp_hub.logger.warning") as warning,
    ):
        assert asyncio.run(hub.connect_server("remote")) is False

    internal = hub._servers["remote"].error_message
    assert token not in internal
    assert "[REDACTED]" in internal
    assert "10.1.2.3" in internal
    assert "/private/ca.pem" in internal
    assert token not in repr(warning.call_args)
    assert "[REDACTED]" in repr(warning.call_args)
    public = hub.get_server_statuses()[0]
    assert "10.1.2.3" not in repr(public)
    assert "/private/ca.pem" not in repr(public)


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


def test_failed_reconnect_invalidates_hub_readiness():
    hub = McpHubManager()
    hub._servers = {
        "arcpy-remote": McpServerStatus(
            config=McpServerConfig(name="arcpy-remote", enabled=True),
            status="connected",
            toolset=object(),
        )
    }
    hub._started = True
    hub._disconnect_server_unlocked = AsyncMock(return_value=True)
    hub._connect_server_unlocked = AsyncMock(return_value=False)

    result = asyncio.run(hub.reconnect_server("arcpy-remote"))

    assert result["status"] == "error"
    assert hub._started is False


def test_successful_reconnect_is_ready_only_when_all_enabled_are_connected():
    hub = McpHubManager()
    reconnecting = McpServerStatus(
        config=McpServerConfig(name="arcpy-remote", enabled=True),
        status="error",
    )
    other = McpServerStatus(
        config=McpServerConfig(name="other", enabled=True),
        status="error",
    )
    hub._servers = {"arcpy-remote": reconnecting, "other": other}

    async def connect(_name):
        reconnecting.status = "connected"
        reconnecting.toolset = object()
        return True

    hub._disconnect_server_unlocked = AsyncMock(return_value=True)
    hub._connect_server_unlocked = AsyncMock(side_effect=connect)

    result = asyncio.run(hub.reconnect_server("arcpy-remote"))

    assert result["status"] == "ok"
    assert hub._started is False

    other.status = "connected"
    other.toolset = object()
    result = asyncio.run(hub.reconnect_server("arcpy-remote"))

    assert result["status"] == "ok"
    assert hub._started is True


def test_app_uses_behaviorally_tested_mcp_runtime_coordinator():
    app_source = Path(__file__).with_name("app.py").read_text(encoding="utf-8")

    assert "McpRuntimeCoordinator" in app_source
    assert "McpRuntimeExitBridge" in app_source
    assert "_mcp_runtime = McpRuntimeCoordinator" in app_source
    assert "await _mcp_runtime.ensure_started()" in app_source
    assert "@cl.on_app_shutdown" in app_source
    assert "await _mcp_runtime.shutdown()" in app_source
    assert "atexit.register(_mcp_exit_bridge)" in app_source
    assert "async def _retry_mcp_hub_startup" not in app_source

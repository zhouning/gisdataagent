"""Contract tests for the active MCP REST route module."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from data_agent.api.mcp_routes import (
    get_mcp_routes,
    mcp_server_create,
    mcp_test_connection,
)
from data_agent.mcp_hub import McpServerConfig


def _make_request(body: dict):
    request = MagicMock()
    request.cookies = {"access_token": "token"}
    request.json = AsyncMock(return_value=body)
    return request


def _make_user(username: str = "admin-user", role: str = "admin"):
    user = MagicMock()
    user.identifier = username
    user.metadata = {"role": role}
    return user


def test_routes_expose_canonical_connection_test_endpoint():
    paths = {route.path for route in get_mcp_routes()}

    assert "/api/mcp/servers/test" in paths
    assert "/api/mcp/test" not in paths


@pytest.mark.asyncio
async def test_connection_requires_admin_and_passes_complete_config_to_hub():
    body = {
        "transport": "streamable_http",
        "command": "python",
        "args": ["-m", "example.server"],
        "env": {"API_TOKEN": "secret"},
        "cwd": "/srv/mcp",
        "url": "https://example.test/mcp",
        "headers": {"Authorization": "Bearer secret"},
        "timeout": "12.5",
    }
    user = _make_user()
    hub = MagicMock()
    hub.test_connection = AsyncMock(return_value={"status": "ok"})

    with (
        patch(
            "data_agent.api.mcp_routes._require_admin",
            return_value=(user, "admin-user", "admin", None),
        ) as require_admin,
        patch("data_agent.api.mcp_routes._get_user_from_request", return_value=user),
        patch("data_agent.mcp_hub.get_mcp_hub", return_value=hub),
    ):
        response = await mcp_test_connection(_make_request(body))

    assert response.status_code == 200
    require_admin.assert_called_once()
    hub.test_connection.assert_awaited_once()
    config = hub.test_connection.await_args.args[0]
    assert isinstance(config, McpServerConfig)
    assert config.name == "__test__"
    assert config.transport == "streamable_http"
    assert config.command == "python"
    assert config.args == ["-m", "example.server"]
    assert config.env == {"API_TOKEN": "secret"}
    assert config.cwd == "/srv/mcp"
    assert config.url == "https://example.test/mcp"
    assert config.headers == {"Authorization": "Bearer secret"}
    assert config.timeout == 12.5
    assert isinstance(config.timeout, float)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("role", "requested_shared", "expected_shared"),
    [("admin", True, True), ("analyst", True, False)],
)
async def test_create_passes_complete_config_and_enforces_sharing_rules(
    role, requested_shared, expected_shared
):
    body = {
        "name": "complete-server",
        "description": "Complete MCP config",
        "transport": "streamable_http",
        "enabled": True,
        "category": "gis",
        "pipelines": ["general", "planner", "analysis"],
        "command": "python",
        "args": ["-m", "example.server"],
        "env": {"API_TOKEN": "secret"},
        "cwd": "/srv/mcp",
        "url": "https://example.test/mcp",
        "headers": {"Authorization": "Bearer secret"},
        "timeout": "18.25",
        "is_shared": requested_shared,
    }
    user = _make_user(username="route-owner", role=role)
    hub = MagicMock()
    hub.add_server = AsyncMock(return_value={"status": "ok", "server": body["name"]})

    with (
        patch("data_agent.api.mcp_routes._get_user_from_request", return_value=user),
        patch(
            "data_agent.api.mcp_routes._set_user_context",
            return_value=("route-owner", role),
        ),
        patch("data_agent.mcp_hub.get_mcp_hub", return_value=hub),
        patch("data_agent.audit_logger.record_audit"),
    ):
        response = await mcp_server_create(_make_request(body))

    assert response.status_code == 201
    assert json.loads(response.body) == {"status": "ok", "server": "complete-server"}
    hub.add_server.assert_awaited_once()
    config = hub.add_server.await_args.args[0]
    assert isinstance(config, McpServerConfig)
    assert config.name == "complete-server"
    assert config.description == "Complete MCP config"
    assert config.transport == "streamable_http"
    assert config.enabled is True
    assert config.category == "gis"
    assert config.pipelines == ["general", "planner", "analysis"]
    assert config.command == "python"
    assert config.args == ["-m", "example.server"]
    assert config.env == {"API_TOKEN": "secret"}
    assert config.cwd == "/srv/mcp"
    assert config.url == "https://example.test/mcp"
    assert config.headers == {"Authorization": "Bearer secret"}
    assert config.timeout == 18.25
    assert isinstance(config.timeout, float)
    assert config.owner_username == "route-owner"
    assert config.is_shared is expected_shared

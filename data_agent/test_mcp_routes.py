"""Contract tests for the active MCP REST route module."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from data_agent.api.mcp_routes import (
    get_mcp_routes,
    mcp_server_create,
    mcp_server_update,
    mcp_test_connection,
)
from data_agent.mcp_hub import McpServerConfig


def _make_request(body, path_params=None):
    request = MagicMock()
    request.cookies = {"access_token": "token"}
    request.path_params = path_params or {}
    request.json = AsyncMock(return_value=body)
    return request


def _make_user(username: str = "admin-user", role: str = "admin"):
    user = MagicMock()
    user.identifier = username
    user.metadata = {"role": role}
    return user


def _valid_server_body():
    return {
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
        "is_shared": True,
    }


def _existing_config(transport="stdio"):
    return McpServerConfig(
        name="owned-server",
        description="Existing server",
        transport=transport,
        enabled=False,
        category="gis",
        pipelines=["general", "planner"],
        command="python" if transport == "stdio" else "",
        args=["-m", "example.server"] if transport == "stdio" else [],
        env={"MODE": "safe"},
        cwd="/srv/mcp",
        url="https://example.test/mcp" if transport != "stdio" else "",
        headers={"X-Test": "true"},
        timeout=10.0,
        owner_username="route-owner",
        is_shared=False,
    )


def _server_status(config):
    status = MagicMock()
    status.config = config
    return status


def test_routes_expose_canonical_connection_test_endpoint():
    routes = get_mcp_routes()
    paths = {route.path for route in routes}
    matches = [route for route in routes if route.path == "/api/mcp/servers/test"]

    assert "/api/mcp/servers/test" in paths
    assert "/api/mcp/test" not in paths
    assert len(matches) == 1
    assert matches[0].methods == {"POST"}
    assert matches[0].endpoint is mcp_test_connection


@pytest.mark.asyncio
async def test_connection_rejects_unauthenticated_user_without_calling_hub():
    with (
        patch("data_agent.api.helpers._get_user_from_request", return_value=None),
        patch("data_agent.mcp_hub.get_mcp_hub") as get_hub,
    ):
        response = await mcp_test_connection(_make_request(_valid_server_body()))

    assert response.status_code == 401
    get_hub.assert_not_called()


@pytest.mark.asyncio
async def test_connection_rejects_non_admin_without_calling_hub():
    user = _make_user(username="analyst-user", role="analyst")
    with (
        patch("data_agent.api.helpers._get_user_from_request", return_value=user),
        patch("data_agent.mcp_hub.get_mcp_hub") as get_hub,
    ):
        response = await mcp_test_connection(_make_request(_valid_server_body()))

    assert response.status_code == 403
    get_hub.assert_not_called()


@pytest.mark.asyncio
async def test_connection_requires_admin_and_passes_complete_config_to_hub():
    body = _valid_server_body()
    body["timeout"] = "12.5"
    user = _make_user()
    hub = MagicMock()
    hub.test_connection = AsyncMock(return_value={"status": "ok"})

    with (
        patch("data_agent.api.helpers._get_user_from_request", return_value=user),
        patch("data_agent.mcp_hub.get_mcp_hub", return_value=hub),
    ):
        response = await mcp_test_connection(_make_request(body))

    assert response.status_code == 200
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
async def test_connection_maps_hub_error_to_bad_request():
    user = _make_user()
    hub = MagicMock()
    hub.test_connection = AsyncMock(return_value={"status": "error", "error": "offline"})

    with (
        patch("data_agent.api.helpers._get_user_from_request", return_value=user),
        patch("data_agent.mcp_hub.get_mcp_hub", return_value=hub),
    ):
        response = await mcp_test_connection(_make_request(_valid_server_body()))

    assert response.status_code == 400
    hub.test_connection.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_rejects_unauthenticated_user_without_calling_hub():
    with (
        patch("data_agent.api.helpers._get_user_from_request", return_value=None),
        patch("data_agent.mcp_hub.get_mcp_hub") as get_hub,
    ):
        response = await mcp_server_create(_make_request(_valid_server_body()))

    assert response.status_code == 401
    get_hub.assert_not_called()


@pytest.mark.asyncio
async def test_create_rejects_non_admin_without_calling_hub():
    user = _make_user(username="analyst-user", role="analyst")
    with (
        patch("data_agent.api.helpers._get_user_from_request", return_value=user),
        patch("data_agent.mcp_hub.get_mcp_hub") as get_hub,
    ):
        response = await mcp_server_create(_make_request(_valid_server_body()))

    assert response.status_code == 403
    get_hub.assert_not_called()


@pytest.mark.asyncio
async def test_admin_create_passes_complete_config_and_preserves_sharing():
    body = _valid_server_body()
    user = _make_user(username="route-owner", role="admin")
    hub = MagicMock()
    hub.add_server = AsyncMock(return_value={"status": "ok", "server": body["name"]})

    with (
        patch("data_agent.api.helpers._get_user_from_request", return_value=user),
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
    assert config.is_shared is True


@pytest.mark.asyncio
@pytest.mark.parametrize("handler", [mcp_test_connection, mcp_server_create])
@pytest.mark.parametrize("body", [None, [], "not-an-object"])
async def test_routes_reject_non_object_json_without_calling_hub(handler, body):
    user = _make_user()
    with (
        patch("data_agent.api.helpers._get_user_from_request", return_value=user),
        patch("data_agent.mcp_hub.get_mcp_hub") as get_hub,
    ):
        response = await handler(_make_request(body))

    assert response.status_code == 400
    get_hub.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("handler", [mcp_test_connection, mcp_server_create])
@pytest.mark.parametrize(
    "invalid_timeout",
    ["slow", None, True, 0, -1, float("inf"), float("nan"), 301],
)
async def test_routes_reject_invalid_timeout_without_calling_hub(
    handler, invalid_timeout
):
    body = _valid_server_body()
    body["timeout"] = invalid_timeout
    user = _make_user()
    hub = MagicMock()
    hub.test_connection = AsyncMock(return_value={"status": "error"})
    hub.add_server = AsyncMock(return_value={"status": "error"})

    with (
        patch("data_agent.api.helpers._get_user_from_request", return_value=user),
        patch("data_agent.mcp_hub.get_mcp_hub", return_value=hub) as get_hub,
    ):
        response = await handler(_make_request(body))

    assert response.status_code == 400
    get_hub.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("handler", [mcp_test_connection, mcp_server_create])
@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("transport", "websocket"),
        ("transport", None),
        ("transport", 7),
        ("transport", []),
        ("enabled", 1),
        ("is_shared", "yes"),
        ("pipelines", "general"),
        ("pipelines", ["general", 3]),
        ("args", "--serve"),
        ("args", ["--serve", 3]),
        ("env", {"PORT": 8080}),
        ("headers", {"Authorization": 42}),
        ("description", None),
        ("category", 7),
        ("command", None),
        ("url", 42),
        ("cwd", []),
    ],
)
async def test_routes_reject_invalid_typed_fields_without_calling_hub(
    handler, field, invalid_value
):
    body = _valid_server_body()
    body[field] = invalid_value
    user = _make_user()
    hub = MagicMock()
    hub.test_connection = AsyncMock(return_value={"status": "error"})
    hub.add_server = AsyncMock(return_value={"status": "error"})

    with (
        patch("data_agent.api.helpers._get_user_from_request", return_value=user),
        patch("data_agent.mcp_hub.get_mcp_hub", return_value=hub) as get_hub,
    ):
        response = await handler(_make_request(body))

    assert response.status_code == 400
    get_hub.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("handler", [mcp_test_connection, mcp_server_create])
@pytest.mark.parametrize(
    "body_updates",
    [
        {"transport": "streamable_http", "command": None},
        {"transport": "stdio", "command": "python", "url": None},
    ],
)
async def test_routes_reject_invalid_scalar_fields_for_inactive_transport(
    handler, body_updates
):
    body = _valid_server_body()
    body.update(body_updates)
    user = _make_user()
    hub = MagicMock()
    hub.test_connection = AsyncMock(return_value={"status": "error"})
    hub.add_server = AsyncMock(return_value={"status": "error"})

    with (
        patch("data_agent.api.helpers._get_user_from_request", return_value=user),
        patch("data_agent.mcp_hub.get_mcp_hub", return_value=hub) as get_hub,
    ):
        response = await handler(_make_request(body))

    assert response.status_code == 400
    get_hub.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {"transport": "websocket"},
        {"timeout": "slow"},
        {"enabled": 1},
        {"is_shared": "yes"},
        {"pipelines": ["general", 3]},
        {"args": ["--serve", 3]},
        {"env": {"PORT": 8080}},
        {"headers": {"Authorization": 42}},
        {"description": None},
        {"category": 7},
        {"cwd": []},
        {
            "transport": "streamable_http",
            "url": "https://example.test/mcp",
            "command": None,
        },
        {"transport": "stdio", "command": "python", "url": None},
    ],
)
async def test_update_rejects_invalid_typed_fields_without_updating_hub(body):
    user = _make_user(username="admin-user", role="admin")
    hub = MagicMock()
    hub._can_manage_server.return_value = True
    hub._servers = {"owned-server": _server_status(_existing_config())}
    hub.update_server = AsyncMock(return_value={"status": "error"})
    request = _make_request(body, path_params={"name": "owned-server"})

    with (
        patch("data_agent.api.mcp_routes._get_user_from_request", return_value=user),
        patch(
            "data_agent.api.mcp_routes._set_user_context",
            return_value=("admin-user", "admin"),
        ),
        patch("data_agent.mcp_hub.get_mcp_hub", return_value=hub),
    ):
        response = await mcp_server_update(request)

    assert response.status_code == 400
    hub.update_server.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {"transport": "streamable_http"},
        {"command": "python"},
        {"args": ["-c", "print('unsafe')"]},
        {"env": {"TOKEN": "secret"}},
        {"cwd": "/tmp"},
        {"url": "http://127.0.0.1/internal"},
        {"headers": {"Authorization": "Bearer secret"}},
        {"timeout": 30},
        {"enabled": True},
        {"is_shared": True},
        {"bearer": "secret"},
        {"security": {"token": "secret"}},
        {"unknown_field": "value"},
    ],
)
async def test_non_admin_owner_cannot_update_privileged_or_unknown_fields(body):
    user = _make_user(username="route-owner", role="analyst")
    request = _make_request(body, path_params={"name": "owned-server"})

    with (
        patch("data_agent.api.mcp_routes._get_user_from_request", return_value=user),
        patch(
            "data_agent.api.mcp_routes._set_user_context",
            return_value=("route-owner", "analyst"),
        ),
        patch("data_agent.mcp_hub.get_mcp_hub") as get_hub,
    ):
        response = await mcp_server_update(request)

    assert response.status_code == 403
    get_hub.assert_not_called()


@pytest.mark.asyncio
async def test_admin_unknown_update_field_is_bad_request_without_hub_access():
    user = _make_user(username="admin-user", role="admin")
    request = _make_request(
        {"unknown_field": "value"}, path_params={"name": "owned-server"}
    )

    with (
        patch("data_agent.api.mcp_routes._get_user_from_request", return_value=user),
        patch(
            "data_agent.api.mcp_routes._set_user_context",
            return_value=("admin-user", "admin"),
        ),
        patch("data_agent.mcp_hub.get_mcp_hub") as get_hub,
    ):
        response = await mcp_server_update(request)

    assert response.status_code == 400
    get_hub.assert_not_called()


@pytest.mark.asyncio
async def test_non_admin_owner_can_update_metadata_only():
    body = {
        "description": "Updated description",
        "category": "analysis",
        "pipelines": ["general"],
    }
    user = _make_user(username="route-owner", role="analyst")
    hub = MagicMock()
    hub._can_manage_server.return_value = True
    hub._servers = {"owned-server": _server_status(_existing_config())}
    hub.update_server = AsyncMock(return_value={"status": "ok", "server": "owned-server"})
    request = _make_request(body, path_params={"name": "owned-server"})

    with (
        patch("data_agent.api.mcp_routes._get_user_from_request", return_value=user),
        patch(
            "data_agent.api.mcp_routes._set_user_context",
            return_value=("route-owner", "analyst"),
        ),
        patch("data_agent.mcp_hub.get_mcp_hub", return_value=hub),
        patch("data_agent.audit_logger.record_audit"),
    ):
        response = await mcp_server_update(request)

    assert response.status_code == 200
    hub.update_server.assert_awaited_once_with("owned-server", body)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("existing_transport", "body"),
    [
        ("stdio", {"transport": "streamable_http"}),
        ("streamable_http", {"transport": "stdio"}),
    ],
)
async def test_admin_transport_transition_requires_complete_candidate_config(
    existing_transport, body
):
    user = _make_user(username="admin-user", role="admin")
    hub = MagicMock()
    hub._can_manage_server.return_value = True
    hub._servers = {
        "owned-server": _server_status(_existing_config(existing_transport))
    }
    hub.update_server = AsyncMock(return_value={"status": "ok"})
    request = _make_request(body, path_params={"name": "owned-server"})

    with (
        patch("data_agent.api.mcp_routes._get_user_from_request", return_value=user),
        patch(
            "data_agent.api.mcp_routes._set_user_context",
            return_value=("admin-user", "admin"),
        ),
        patch("data_agent.mcp_hub.get_mcp_hub", return_value=hub),
    ):
        response = await mcp_server_update(request)

    assert response.status_code == 400
    hub.update_server.assert_not_awaited()


@pytest.mark.asyncio
async def test_admin_partial_metadata_update_preserves_existing_connection_config():
    body = {"description": "Admin metadata update"}
    user = _make_user(username="admin-user", role="admin")
    hub = MagicMock()
    hub._can_manage_server.return_value = True
    hub._servers = {"owned-server": _server_status(_existing_config())}
    hub.update_server = AsyncMock(return_value={"status": "ok", "server": "owned-server"})
    request = _make_request(body, path_params={"name": "owned-server"})

    with (
        patch("data_agent.api.mcp_routes._get_user_from_request", return_value=user),
        patch(
            "data_agent.api.mcp_routes._set_user_context",
            return_value=("admin-user", "admin"),
        ),
        patch("data_agent.mcp_hub.get_mcp_hub", return_value=hub),
        patch("data_agent.audit_logger.record_audit"),
    ):
        response = await mcp_server_update(request)

    assert response.status_code == 200
    hub.update_server.assert_awaited_once_with("owned-server", body)


@pytest.mark.asyncio
async def test_admin_update_normalizes_numeric_timeout_before_hub_call():
    body = {"timeout": "12.5"}
    user = _make_user(username="admin-user", role="admin")
    hub = MagicMock()
    hub._can_manage_server.return_value = True
    hub._servers = {"owned-server": _server_status(_existing_config())}
    hub.update_server = AsyncMock(return_value={"status": "ok", "server": "owned-server"})
    request = _make_request(body, path_params={"name": "owned-server"})

    with (
        patch("data_agent.api.mcp_routes._get_user_from_request", return_value=user),
        patch(
            "data_agent.api.mcp_routes._set_user_context",
            return_value=("admin-user", "admin"),
        ),
        patch("data_agent.mcp_hub.get_mcp_hub", return_value=hub),
        patch("data_agent.audit_logger.record_audit"),
    ):
        response = await mcp_server_update(request)

    assert response.status_code == 200
    updates = hub.update_server.await_args.args[1]
    assert updates == {"timeout": 12.5}
    assert isinstance(updates["timeout"], float)

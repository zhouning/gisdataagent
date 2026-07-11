# ArcPy MCP End-to-End Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect GIS Data Agent to the private ArcPy MCP service on macOS and Docker so all three Agent pipelines can securely upload local GIS inputs, run allowlisted ArcPy jobs, download verified results, and return map-ready artifacts.

**Architecture:** Repair the active MCP Hub REST contract and add environment-referenced bearer authentication plus per-server CA trust. Keep generic MCP discovery in `McpHubManager`, but expose ArcPy through a dedicated `ArcPyMcpClient` and high-level `ArcPyMcpToolset` so the model never handles signed URLs, upload offsets, artifact lifetimes, or raw job polling.

**Tech Stack:** Python 3.11+, Google ADK 2.3, MCP Python SDK 1.28, httpx, Starlette, pytest/unittest, GeoPandas, Docker Compose, React/Vite contract tests.

---

## File Structure

- Create `data_agent/mcp_transport.py`: secret-reference resolution, private-CA HTTP client factories, and MCP error redaction.
- Create `data_agent/test_mcp_transport.py`: transport security and redaction tests.
- Modify `data_agent/mcp_hub.py`: secure config fields, database persistence, system-managed ArcPy config, retryable startup, raw-tool filtering.
- Modify `data_agent/api/mcp_routes.py`: make the extracted route module match the frontend and construct `McpServerConfig` correctly.
- Create `data_agent/test_mcp_routes.py`: tests for the active route module rather than dead compatibility functions in `frontend_api.py`.
- Create `data_agent/arcpy_mcp_client.py`: persistent MCP session, artifact transfers, dataset inspection, jobs, downloads, safe extraction, and result assembly.
- Create `data_agent/test_arcpy_mcp_client.py`: unit tests with fake MCP calls and HTTP transports.
- Create `data_agent/toolsets/arcpy_mcp_toolset.py`: explicit high-level ArcPy ADK tools.
- Create `data_agent/test_arcpy_mcp_toolset.py`: schemas, delegation, map-ready results, and graceful degradation.
- Modify `data_agent/toolsets/__init__.py`: lazy export for `ArcPyMcpToolset`.
- Modify `data_agent/agent.py`: register independent ArcPy toolsets in general, planner, and governance.
- Modify `data_agent/hitl_approval.py`: classify the four CPU deep-learning tools as high-risk long-running operations.
- Modify `data_agent/health.py`: report sanitized ArcPy MCP readiness details.
- Modify `data_agent/mcp_servers.yaml`: remove the unusable Windows ArcPy seed for new installations.
- Modify `data_agent/.env.example`: document macOS and common ArcPy MCP variables without secret values.
- Create `docker-compose.arcpy-mcp.yml`: optional Docker secret and CA override.
- Create `scripts/smoke_arcpy_mcp.py`: live health, upload, buffer, poll, download, and checksum smoke test.
- Create `data_agent/test_arcpy_mcp_smoke_contract.py`: smoke-script ordering and CLI security contract.
- Modify `docs/mcp-integration-guide.md`: deployment and troubleshooting instructions.

## Task 1: Repair the Active MCP REST Contract

**Files:**
- Create: `data_agent/test_mcp_routes.py`
- Modify: `data_agent/api/mcp_routes.py:117-171, 326-345`
- Test: `data_agent/test_mcp_routes.py`

- [ ] **Step 1: Write failing tests against the active route module**

```python
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

from data_agent.api.mcp_routes import get_mcp_routes, mcp_server_create, mcp_test_connection


def run(coro):
    return asyncio.run(coro)


def request(body):
    req = MagicMock()
    req.json = AsyncMock(return_value=body)
    req.cookies = {}
    req.path_params = {}
    req.query_params = {}
    return req


def user():
    value = MagicMock()
    value.identifier = "admin"
    value.metadata = {"role": "admin"}
    return value


def test_active_routes_register_frontend_connection_test_path():
    paths = [route.path for route in get_mcp_routes()]
    assert "/api/mcp/servers/test" in paths
    assert "/api/mcp/test" not in paths


@patch("data_agent.api.mcp_routes._require_admin", return_value=(user(), "admin", "admin", None))
@patch("data_agent.mcp_hub.McpHubManager.test_connection", new_callable=AsyncMock)
def test_connection_builds_mcp_server_config(test_connection, _require_admin):
    test_connection.return_value = {"status": "ok", "tool_count": 3, "message": "connected"}
    response = run(mcp_test_connection(request({
        "transport": "streamable_http",
        "url": "https://mcp.internal/mcp",
        "timeout": 9,
    })))
    config = test_connection.await_args.args[0]
    assert response.status_code == 200
    assert config.name == "__test__"
    assert config.transport == "streamable_http"
    assert config.timeout == 9.0


@patch("data_agent.api.mcp_routes._get_user_from_request", return_value=user())
@patch("data_agent.mcp_hub.McpHubManager.add_server", new_callable=AsyncMock)
def test_create_uses_real_config_class_and_preserves_fields(add_server, _get_user):
    add_server.return_value = {"status": "ok", "server": "remote", "connected": False}
    response = run(mcp_server_create(request({
        "name": "remote",
        "transport": "streamable_http",
        "url": "https://mcp.internal/mcp",
        "enabled": True,
        "category": "gis",
        "pipelines": ["general"],
        "timeout": 12,
    })))
    config = add_server.await_args.args[0]
    assert response.status_code == 201
    assert config.name == "remote"
    assert config.enabled is True
    assert config.category == "gis"
    assert config.pipelines == ["general"]
```

- [ ] **Step 2: Run the tests and verify the three regressions fail**

Run: `.venv/bin/python -m pytest data_agent/test_mcp_routes.py -q`

Expected: failures show the missing `/api/mcp/servers/test` route, raw `dict` passed to `test_connection`, and import error for `MCPServerConfig`.

- [ ] **Step 3: Restore the correct active route behavior**

```python
async def mcp_test_connection(request: Request):
    user, username, role, err = _require_admin(request)
    if err:
        return err
    body = await request.json()
    transport = body.get("transport", "stdio")
    validation_error = _validate_mcp_config(body, transport)
    if validation_error:
        return JSONResponse({"error": validation_error}, status_code=400)

    from ..mcp_hub import McpServerConfig, get_mcp_hub
    config = McpServerConfig(
        name="__test__",
        transport=transport,
        command=body.get("command", ""),
        args=body.get("args", []),
        env=body.get("env", {}),
        cwd=body.get("cwd"),
        url=body.get("url", ""),
        headers=body.get("headers", {}),
        timeout=float(body.get("timeout", 5.0)),
    )
    result = await get_mcp_hub().test_connection(config)
    return JSONResponse(result, status_code=200 if result.get("status") == "ok" else 400)
```

Use `McpServerConfig` in `mcp_server_create`, preserve every current configuration field, enforce the existing admin/shared-server rules, and register:

```python
Route("/api/mcp/servers/test", mcp_test_connection, methods=["POST"])
```

- [ ] **Step 4: Run focused and route-registration tests**

Run: `.venv/bin/python -m pytest data_agent/test_mcp_routes.py data_agent/test_mcp_hub.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit the route repair**

```bash
git add data_agent/api/mcp_routes.py data_agent/test_mcp_routes.py data_agent/test_mcp_hub.py
git commit -m "fix: repair active MCP routes"
```

## Task 2: Add Secret References, Private CA Trust, and Redaction

**Files:**
- Create: `data_agent/mcp_transport.py`
- Create: `data_agent/test_mcp_transport.py`
- Modify: `data_agent/mcp_hub.py:87-108, 150-290, 370-435, 559-586`
- Test: `data_agent/test_mcp_transport.py`
- Test: `data_agent/test_mcp_hub.py`

- [ ] **Step 1: Write failing transport-security tests**

```python
import os
from pathlib import Path

import pytest
from unittest.mock import patch

from data_agent.mcp_transport import (
    McpConfigurationError,
    build_httpx_client_factory,
    redact_mcp_text,
    resolve_secret_reference,
)


def test_token_file_takes_precedence(tmp_path, monkeypatch):
    secret_file = tmp_path / "token"
    secret_file.write_text("file-token\n", encoding="utf-8")
    monkeypatch.setenv("TOKEN_VALUE", "env-token")
    monkeypatch.setenv("TOKEN_FILE", str(secret_file))
    assert resolve_secret_reference("TOKEN_VALUE", "TOKEN_FILE") == "file-token"


def test_missing_secret_raises_stable_error(monkeypatch):
    monkeypatch.delenv("TOKEN_VALUE", raising=False)
    monkeypatch.delenv("TOKEN_FILE", raising=False)
    with pytest.raises(McpConfigurationError) as exc:
        resolve_secret_reference("TOKEN_VALUE", "TOKEN_FILE")
    assert exc.value.code == "ARCPY_MCP_TOKEN_MISSING"


def test_client_factory_uses_only_server_ca(tmp_path):
    ca = tmp_path / "ca.crt"
    ca.write_text("CERTIFICATE", encoding="utf-8")
    factory = build_httpx_client_factory(str(ca))
    with patch("data_agent.mcp_transport.httpx.AsyncClient") as async_client:
        factory(headers={"X-Test": "1"}, timeout="timeout", auth=None)
    async_client.assert_called_once_with(
        headers={"X-Test": "1"},
        timeout="timeout",
        auth=None,
        verify=str(ca),
        follow_redirects=True,
    )


def test_redaction_removes_credentials_and_signed_url():
    raw = "Authorization: Bearer abc upload_url=https://host/upload?signature=secret"
    clean = redact_mcp_text(raw, secrets=["abc"])
    assert "abc" not in clean
    assert "signature=secret" not in clean
```

- [ ] **Step 2: Verify the tests fail before implementation**

Run: `.venv/bin/python -m pytest data_agent/test_mcp_transport.py -q`

Expected: import failure for `data_agent.mcp_transport`.

- [ ] **Step 3: Implement the transport helpers**

```python
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable

import httpx


class McpConfigurationError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def resolve_secret_reference(value_env: str, file_env: str) -> str:
    file_name = os.environ.get(file_env, "").strip()
    if file_name:
        path = Path(file_name)
        if not path.is_file():
            raise McpConfigurationError("ARCPY_MCP_TOKEN_MISSING", "Configured token file does not exist")
        value = path.read_text(encoding="utf-8").strip()
        if value:
            return value
    value = os.environ.get(value_env, "").strip()
    if value:
        return value
    raise McpConfigurationError("ARCPY_MCP_TOKEN_MISSING", "ArcPy MCP token is not configured")


def resolve_ca_bundle(env_name: str) -> str:
    path = Path(os.environ.get(env_name, "").strip())
    if not path.is_file():
        raise McpConfigurationError("ARCPY_MCP_CA_MISSING", "ArcPy MCP CA bundle is not configured")
    if "PRIVATE KEY" in path.read_text(encoding="utf-8", errors="ignore"):
        raise McpConfigurationError("ARCPY_MCP_CA_MISSING", "CA bundle must not contain a private key")
    return str(path)


def build_httpx_client_factory(ca_bundle: str):
    def factory(headers=None, timeout=None, auth=None):
        return httpx.AsyncClient(
            headers=headers,
            timeout=timeout,
            auth=auth,
            verify=ca_bundle,
            follow_redirects=True,
        )
    return factory


def redact_mcp_text(value: object, secrets: Iterable[str] = ()) -> str:
    text = str(value)
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[REDACTED]")
    text = re.sub(r"(?i)(authorization:\s*bearer\s+)[^\s]+", r"\1[REDACTED]", text)
    text = re.sub(r"(?i)(signature|token|sig)=([^&\s]+)", r"\1=[REDACTED]", text)
    return text
```

- [ ] **Step 4: Extend `McpServerConfig` and HTTP connection creation**

Add these fields with empty/default values:

```python
bearer_token_env_var: str = ""
bearer_token_file_env_var: str = ""
ca_bundle_env_var: str = ""
system_managed: bool = False
expose_raw_tools: bool = True
```

Add matching nullable/default columns to `_ensure_table`, load/save them in the DB methods, and parse them from YAML. Before constructing `StreamableHTTPConnectionParams`, resolve references and set:

```python
headers = dict(config.headers)
if config.bearer_token_env_var or config.bearer_token_file_env_var:
    token = resolve_secret_reference(
        config.bearer_token_env_var,
        config.bearer_token_file_env_var,
    )
    headers["Authorization"] = f"Bearer {token}"

httpx_factory = create_mcp_http_client
if config.ca_bundle_env_var:
    httpx_factory = build_httpx_client_factory(resolve_ca_bundle(config.ca_bundle_env_var))

conn_params = StreamableHTTPConnectionParams(
    url=config.url,
    headers=headers or None,
    timeout=config.timeout,
    httpx_client_factory=httpx_factory,
)
```

Redact all stored `error_message` values with `redact_mcp_text`.

- [ ] **Step 5: Run secure transport and Hub tests**

Run: `.venv/bin/python -m pytest data_agent/test_mcp_transport.py data_agent/test_mcp_hub.py -q`

Expected: all tests pass and no test output contains token fixtures.

- [ ] **Step 6: Commit secure transport support**

```bash
git add data_agent/mcp_transport.py data_agent/test_mcp_transport.py data_agent/mcp_hub.py data_agent/test_mcp_hub.py
git commit -m "feat: secure HTTP MCP connections"
```

## Task 3: Register a System-Managed ArcPy Server and Make Startup Retryable

**Files:**
- Modify: `data_agent/mcp_hub.py:340-405, 466-505, 689-738`
- Modify: `data_agent/app.py:244-254, 3002-3014`
- Modify: `data_agent/health.py:135-158`
- Modify: `data_agent/test_mcp_hub.py`
- Create: `data_agent/test_arcpy_mcp_configuration.py`

- [ ] **Step 1: Write failing configuration and retry tests**

```python
import asyncio
from unittest.mock import AsyncMock

from data_agent.mcp_hub import McpHubManager


def test_environment_registers_system_managed_arcpy(monkeypatch):
    monkeypatch.setenv("ARCPY_MCP_ENABLED", "true")
    monkeypatch.setenv("ARCPY_MCP_URL", "https://arcpy.internal/mcp")
    hub = McpHubManager()
    hub._ensure_table = lambda: False
    hub._load_from_db = lambda: []
    hub._load_yaml = lambda: []
    hub.load_config()
    status = hub._servers["arcpy-remote"]
    assert status.config.system_managed is True
    assert status.config.expose_raw_tools is False
    assert status.config.pipelines == ["general", "planner", "governance"]
    assert status.config.bearer_token_env_var == "ARCPY_MCP_TOKEN"
    assert status.config.bearer_token_file_env_var == "ARCPY_MCP_TOKEN_FILE"
    assert status.config.ca_bundle_env_var == "ARCPY_MCP_CA_BUNDLE"


def test_failed_startup_remains_retryable(monkeypatch):
    from data_agent.mcp_hub import McpServerConfig, McpServerStatus
    hub = McpHubManager()
    hub._servers = {
        "remote": McpServerStatus(config=McpServerConfig(name="remote", enabled=True))
    }
    hub.connect_server = AsyncMock(return_value=False)
    asyncio.run(hub.startup())
    assert hub._started is False


def test_raw_arcpy_tools_are_not_returned_to_generic_agents(monkeypatch):
    from data_agent.mcp_hub import McpServerConfig, McpServerStatus
    toolset = type("FakeToolset", (), {"get_tools": AsyncMock(return_value=[object()])})()
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
        )
    }
    assert asyncio.run(hub.get_all_tools(pipeline="general")) == []
```

- [ ] **Step 2: Run tests and verify missing behavior**

Run: `.venv/bin/python -m pytest data_agent/test_arcpy_mcp_configuration.py -q`

Expected: no `arcpy-remote` runtime config and startup incorrectly marks itself complete.

- [ ] **Step 3: Implement runtime configuration precedence**

Add `_load_system_configs()` returning this exact configuration when enabled:

```python
McpServerConfig(
    name="arcpy-remote",
    description="Private ArcGIS Pro 3.7.1 ArcPy MCP service",
    transport="streamable_http",
    enabled=True,
    category="gis",
    pipelines=["general", "planner", "governance"],
    url=os.environ.get("ARCPY_MCP_URL", "").strip(),
    timeout=float(os.environ.get("ARCPY_MCP_CONNECT_TIMEOUT", "10")),
    source="environment",
    is_shared=True,
    bearer_token_env_var="ARCPY_MCP_TOKEN",
    bearer_token_file_env_var="ARCPY_MCP_TOKEN_FILE",
    ca_bundle_env_var="ARCPY_MCP_CA_BUNDLE",
    system_managed=True,
    expose_raw_tools=False,
)
```

Merge system configs after DB and YAML so they win by name. If `arcpy-remote` is enabled, mark an existing `arcgis-pro-tools` Windows `stdio` status disabled and append `Legacy Windows stdio configuration` to its description without deleting user data.

In `get_all_tools`, skip a connected server when `config.expose_raw_tools` is false. In update/delete routes, return HTTP 403 for `system_managed` servers except reconnect.

- [ ] **Step 4: Make startup success conditional and retryable**

Set `_started=True` only when every enabled server either connects or is deliberately skipped as disabled. Add `retry_failed_servers()` with delays `[2, 5, 10, 20]`, stopping once the server connects. In `app.py`, do not set `_mcp_started=True` after timeout or exception; schedule a bounded retry task instead. Register a synchronous `atexit` bridge that calls `asyncio.run(get_mcp_hub().shutdown())` when no event loop is running and closes the ArcPy client singleton through the same shutdown path.

- [ ] **Step 5: Add sanitized ArcPy health detail**

Extend `check_mcp_hub()` with:

```python
arcpy = next((s for s in statuses if s["name"] == "arcpy-remote"), None)
result["arcpy"] = None if arcpy is None else {
    "status": arcpy["status"],
    "tool_count": arcpy["tool_count"],
    "connected_at": arcpy["connected_at"],
    "error_message": arcpy["error_message"],
}
```

Do not add URL, headers, environment variable values, or CA paths.

- [ ] **Step 6: Run configuration, Hub, app-contract, and health tests**

Run: `.venv/bin/python -m pytest data_agent/test_arcpy_mcp_configuration.py data_agent/test_mcp_hub.py data_agent/test_health.py -q`

Expected: all pass.

- [ ] **Step 7: Commit system-managed lifecycle support**

```bash
git add data_agent/mcp_hub.py data_agent/app.py data_agent/health.py data_agent/test_mcp_hub.py data_agent/test_arcpy_mcp_configuration.py data_agent/test_health.py
git commit -m "feat: register managed ArcPy MCP service"
```

## Task 4: Implement the ArcPy MCP Session and Stable Errors

**Files:**
- Create: `data_agent/arcpy_mcp_client.py`
- Create: `data_agent/test_arcpy_mcp_client.py`

- [ ] **Step 1: Write failing session and error tests**

```python
import pytest

from data_agent.arcpy_mcp_client import ArcPyMcpClient, ArcPyMcpError
from data_agent.mcp_hub import McpServerConfig


class FakeSession:
    async def call_tool(self, name, arguments):
        if name == "health_check":
            return type("Result", (), {
                "isError": False,
                "structuredContent": {"status": "healthy", "worker": {"product": "ArcInfo"}},
                "content": [],
            })()
        raise RuntimeError("Authorization: Bearer test-secret")


@pytest.mark.asyncio
async def test_health_check_returns_structured_content():
    client = ArcPyMcpClient(McpServerConfig(name="arcpy", url="https://x/mcp"))
    client._session = FakeSession()
    assert (await client.health_check())["status"] == "healthy"


@pytest.mark.asyncio
async def test_call_tool_maps_and_redacts_transport_failure():
    client = ArcPyMcpClient(McpServerConfig(name="arcpy", url="https://x/mcp"))
    client._session = FakeSession()
    client._resolved_token = "test-secret"
    with pytest.raises(ArcPyMcpError) as exc:
        await client.call_tool("get_capabilities", {})
    assert exc.value.code == "ARCPY_MCP_UNREACHABLE"
    assert "test-secret" not in str(exc.value)
```

- [ ] **Step 2: Verify the test module fails to import**

Run: `.venv/bin/python -m pytest data_agent/test_arcpy_mcp_client.py -q`

Expected: import failure for `ArcPyMcpClient`.

- [ ] **Step 3: Implement a persistent official MCP session**

Use `AsyncExitStack`, `httpx.AsyncClient`, `mcp.ClientSession`, and `mcp.client.streamable_http.streamable_http_client`. `connect()` must resolve the token and CA, create one authenticated client, enter the transport and `ClientSession`, then call `initialize()`. `close()` must close the exit stack and clear all session state.

Implement:

```python
class ArcPyMcpError(RuntimeError):
    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


async def call_tool(self, name: str, arguments: dict) -> dict:
    if name not in self.allowed_tools:
        raise ArcPyMcpError("ARCPY_TOOL_NOT_ALLOWED", f"ArcPy MCP tool is not allowed: {name}")
    await self.connect()
    try:
        result = await self._session.call_tool(name, arguments)
    except Exception as exc:
        raise ArcPyMcpError(
            "ARCPY_MCP_UNREACHABLE",
            redact_mcp_text(exc, [self._resolved_token]),
        ) from exc
    if result.isError:
        raise ArcPyMcpError("ARCPY_JOB_FAILED", self._result_text(result))
    if result.structuredContent is not None:
        return dict(result.structuredContent)
    return json.loads(self._result_text(result))
```

The allowlist contains every tool exposed by the current private service named in the design, including artifact, job, vector, raster, map, and four deep-learning tools. Do not permit `TrainDeepLearningModel`.

- [ ] **Step 4: Add cached health and capability checks**

Cache successful results for 30 seconds. `health_check()` raises `ARCPY_WORKER_UNAVAILABLE` unless status is `healthy` and a worker object is present. `get_capabilities(required_extension)` raises `ARCPY_EXTENSION_UNAVAILABLE` if Spatial or ImageAnalyst is not `Available`.

- [ ] **Step 5: Run session tests**

Run: `.venv/bin/python -m pytest data_agent/test_arcpy_mcp_client.py -q`

Expected: session, structured-result, redaction, allowlist, health, and capability tests pass.

- [ ] **Step 6: Commit the session client**

```bash
git add data_agent/arcpy_mcp_client.py data_agent/test_arcpy_mcp_client.py
git commit -m "feat: add ArcPy MCP client session"
```

## Task 5: Implement Artifact Packaging, Upload, Inspection, and Resume

**Files:**
- Modify: `data_agent/arcpy_mcp_client.py`
- Modify: `data_agent/test_arcpy_mcp_client.py`

- [ ] **Step 1: Add failing sandbox and packaging tests**

```python
import zipfile
from pathlib import Path

import pytest

from data_agent.arcpy_mcp_client import ArcPyMcpClient, ArcPyMcpError, package_local_dataset
from data_agent.mcp_hub import McpServerConfig
from data_agent.user_context import current_user_id, get_user_upload_dir


@pytest.fixture
def user_upload_dir(tmp_path, monkeypatch):
    base = tmp_path / "uploads"
    base.mkdir()
    monkeypatch.setattr("data_agent.user_context._BASE_UPLOAD_DIR", str(base))
    monkeypatch.setattr("data_agent.gis_processors._BASE_UPLOAD_DIR", str(base))
    token = current_user_id.set("arcpy-test-user")
    try:
        yield Path(get_user_upload_dir())
    finally:
        current_user_id.reset(token)


def configured_client():
    return ArcPyMcpClient(McpServerConfig(
        name="arcpy-remote",
        transport="streamable_http",
        url="https://arcpy.internal/mcp",
    ))


@pytest.mark.asyncio
async def test_prepare_input_rejects_path_outside_user_sandbox(tmp_path, user_upload_dir):
    outside = tmp_path / "outside.geojson"
    outside.write_text('{"type":"FeatureCollection","features":[]}', encoding="utf-8")
    client = configured_client()
    with pytest.raises(ArcPyMcpError) as exc:
        await client.prepare_input(str(outside))
    assert exc.value.code == "ARCPY_INPUT_OUTSIDE_SANDBOX"


def test_package_shapefile_includes_required_sidecars(user_upload_dir):
    for suffix in (".shp", ".shx", ".dbf", ".prj"):
        (user_upload_dir / f"roads{suffix}").write_bytes(b"x")
    package = package_local_dataset(user_upload_dir / "roads.shp")
    with zipfile.ZipFile(package.upload_path) as archive:
        assert set(archive.namelist()) == {"roads.shp", "roads.shx", "roads.dbf", "roads.prj"}
```

- [ ] **Step 2: Add failing upload-resume tests with fake HTTP responses**

Test that `create_upload` receives logical name, exact size, lowercase hash, and media type; a new upload sends `Upload-Offset: 0`; an interrupted upload calls `get_upload_status` and resumes from `committed_size`; expired URLs call `renew_upload`; and `complete_upload` must return `state=ready` plus the matching verified hash.

- [ ] **Step 3: Verify artifact tests fail**

Run: `.venv/bin/python -m pytest data_agent/test_arcpy_mcp_client.py -k 'prepare_input or package or upload' -q`

Expected: missing packaging and upload methods.

- [ ] **Step 4: Implement safe local preparation**

Resolve the path through `gis_processors._resolve_path`, then require `user_context.is_path_in_sandbox(resolved)`. Reject symlinks whose real path escapes the sandbox. ZIP all shapefile sidecars sharing the stem and recursively ZIP `.gdb` directories. Create temporary ZIPs inside `get_user_upload_dir()`.

`package_local_dataset()` returns `PreparedLocalUpload(upload_path, source_path, logical_name, media_type, size, sha256, delete_after_upload)`. `prepare_input()` completes upload and inspection, then returns `UploadedArtifact(artifact_id, artifact_path, source_path, local_package_path, delete_local_package)`.

- [ ] **Step 5: Implement resumable upload and inspection**

Use an unauthenticated HTTP client for signed URLs:

```python
async with httpx.AsyncClient(verify=self.ca_bundle, follow_redirects=True) as client:
    with open(path, "rb") as stream:
        stream.seek(offset)
        response = await client.put(
            signed_url,
            headers={"Upload-Offset": str(offset)},
            content=stream,
            timeout=self.upload_timeout,
        )
        response.raise_for_status()
```

Never copy the MCP Authorization header into this client. After `complete_upload`, call `inspect_dataset`, poll its job, and derive the artifact-relative path only from the succeeded inspection result.

- [ ] **Step 6: Run artifact tests**

Run: `.venv/bin/python -m pytest data_agent/test_arcpy_mcp_client.py -k 'prepare_input or package or upload or inspect' -q`

Expected: all selected tests pass.

- [ ] **Step 7: Commit artifact ingestion**

```bash
git add data_agent/arcpy_mcp_client.py data_agent/test_arcpy_mcp_client.py
git commit -m "feat: upload and inspect ArcPy artifacts"
```

## Task 6: Implement Jobs, Downloads, Safe Extraction, and Result Registration

**Files:**
- Modify: `data_agent/arcpy_mcp_client.py`
- Modify: `data_agent/test_arcpy_mcp_client.py`

- [ ] **Step 1: Write failing poll, failure-log, download, and archive tests**

Create tests that inject a fake sleep function and assert delays `[2, 5, 10, 20]`; verify `failed` calls `get_job_log`; verify success is not returned before `status=succeeded`; verify a checksum mismatch deletes the partial download and raises `ARCPY_DOWNLOAD_CHECKSUM_MISMATCH`; verify ZIP entries `../escape.shp` and `/absolute.shp` raise `ARCPY_UNSAFE_ARCHIVE`.

- [ ] **Step 2: Run the selected tests and verify failure**

Run: `.venv/bin/python -m pytest data_agent/test_arcpy_mcp_client.py -k 'poll or download or archive or job_log' -q`

Expected: missing job and download methods.

- [ ] **Step 3: Implement terminal-state polling**

```python
async def wait_for_job(self, job_id: str, timeout: float) -> dict:
    started = time.monotonic()
    delays = (2, 5, 10)
    attempt = 0
    while True:
        if time.monotonic() - started > timeout:
            raise ArcPyMcpError("ARCPY_JOB_TIMED_OUT", f"ArcPy job timed out: {job_id}")
        await self._sleep(delays[attempt] if attempt < len(delays) else 20)
        attempt += 1
        job = await self.call_tool("get_job", {"job_id": job_id})
        status = job.get("status")
        if status == "succeeded":
            return job
        if status in {"failed", "timed_out", "cancelled", "interrupted"}:
            logs = await self.call_tool("get_job_log", {"job_id": job_id})
            raise ArcPyMcpError(_job_error_code(status), _final_messages(logs), {"status": status})


async def cancel_job(self, job_id: str) -> dict:
    await self.call_tool("cancel_job", {"job_id": job_id})
    return await self.wait_for_job(job_id, self.job_timeout)
```

The cancellation test must assert exactly one `cancel_job` call and continued polling until `cancelled`, `failed`, `timed_out`, `interrupted`, or `succeeded`.

- [ ] **Step 4: Implement resumable verified download**

Use `create_download`, write to a `.part` file under the current user directory, send `Range: bytes=<existing_size>-` when resuming, stream chunks without bearer auth, compare `shasum` through `hashlib.sha256`, then atomically rename the verified file.

Use `zipfile.Path`/`ZipInfo` checks before extraction: reject absolute paths, drive prefixes, `..` components, and real output paths outside the selected extraction directory.

- [ ] **Step 5: Assemble the standard result and map metadata**

For every verified output call `data_catalog.register_tool_output(local_path, tool_name, tool_params, source_paths)`. If a vector result can be opened by GeoPandas, export a GeoJSON sibling into the user directory and build `map_update` with `artifact_handler.build_map_update_from_geojson`.

Return:

```python
{
    "status": "success",
    "operation": operation,
    "message": message,
    "local_outputs": local_outputs,
    "dataset_summary": dataset_summary,
    "arcgis_product": health["worker"]["product"],
    "arcgis_version": health["worker"]["install"]["Version"],
    "duration_seconds": round(duration, 3),
    "lineage": {"source_paths": source_paths, "tool": operation},
    "map_update": map_update,
}
```

Add the four orchestration primitives used by the toolset with these stable signatures:

```python
async def run_dedicated(
    self,
    remote_tool: str,
    local_inputs: dict[str, str],
    parameters: dict,
) -> dict:
    return await self._execute_operation(
        remote_tool=remote_tool,
        local_inputs=local_inputs,
        parameters=parameters,
        deep_learning=False,
    )

async def run_multi_input(
    self,
    remote_tool: str,
    local_inputs: list[str],
    parameters: dict,
) -> dict:
    prepared = [await self.prepare_input(path) for path in local_inputs]
    arguments = dict(parameters)
    arguments["inputs"] = [
        {"artifact_id": item.artifact_id, "path": item.artifact_path}
        for item in prepared
    ]
    return await self._submit_wait_download(remote_tool, arguments, local_inputs)

async def run_deep_learning(
    self,
    remote_tool: str,
    imagery_inputs: dict[str, str],
    model_path: str,
    parameters: dict,
) -> dict:
    await self.get_capabilities(required_extension="ImageAnalyst")
    return await self._execute_operation(
        remote_tool=remote_tool,
        local_inputs={**imagery_inputs, "model": model_path},
        parameters=parameters,
        deep_learning=True,
    )

async def run_catalog_tool(
    self,
    query: str,
    category: str,
    local_inputs: dict[str, str],
    parameters: dict,
) -> dict:
    matches = await self.call_tool("search_tools", {"query": query, "category": category or None})
    tool_id = self._select_exact_tool_id(matches, query)
    description = await self.call_tool("describe_tool", {"tool_id": tool_id})
    self._validate_catalog_parameters(parameters, description["input_schema"])
    prepared = {name: await self.prepare_input(path) for name, path in local_inputs.items()}
    arguments = self._bind_prepared_inputs(parameters, prepared)
    submission = await self.call_tool("submit_job", {"tool_id": tool_id, "parameters": arguments})
    job = await self.wait_for_job(submission["job_id"], self.job_timeout)
    return await self.download_job_results(tool_id, job, list(local_inputs.values()))
```

`_execute_operation` first calls `health_check`, prepares every named local input, binds `<prefix>_artifact_id` and `<prefix>_path`, calls the dedicated remote tool, waits using `dl_job_timeout` only when `deep_learning=True`, downloads verified outputs, registers results, and deletes temporary remote input artifacts in `finally`. `_submit_wait_download` performs the same submit/wait/download/finally sequence for the already-bound multi-input case.

Implement the referenced helpers with these exact contracts:

```python
def _select_exact_tool_id(self, matches: dict, query: str) -> str:
    rows = list(matches.get("result") or matches.get("tools") or [])
    exact = [row["tool_id"] for row in rows if row.get("tool_id") == query]
    if len(exact) == 1:
        return exact[0]
    raise ArcPyMcpError("ARCPY_TOOL_NOT_ALLOWED", f"No exact allowlisted ArcPy tool for: {query}")


def _validate_catalog_parameters(self, parameters: dict, schema: dict) -> None:
    try:
        jsonschema.validate(parameters, schema)
    except jsonschema.ValidationError as exc:
        raise ArcPyMcpError("ARCPY_TOOL_NOT_ALLOWED", exc.message) from exc


def _bind_prepared_inputs(
    self,
    parameters: dict,
    prepared: dict[str, UploadedArtifact],
) -> dict:
    arguments = dict(parameters)
    for prefix, artifact in prepared.items():
        arguments[f"{prefix}_artifact_id"] = artifact.artifact_id
        arguments[f"{prefix}_path"] = artifact.artifact_path
    return arguments
```

`_submit_wait_download(remote_tool, arguments, source_paths)` requires the dedicated call result to contain `job_id`, calls `wait_for_job`, then calls `download_job_results`. `download_job_results(operation, job, source_paths)` extracts result artifact IDs only from the succeeded job, downloads each result, registers each verified local path, and returns the standard result contract. Both helpers raise stable errors when required fields are missing.

- [ ] **Step 6: Run all ArcPy client tests**

Run: `.venv/bin/python -m pytest data_agent/test_arcpy_mcp_client.py -q`

Expected: all pass.

- [ ] **Step 7: Commit job and result handling**

```bash
git add data_agent/arcpy_mcp_client.py data_agent/test_arcpy_mcp_client.py
git commit -m "feat: complete ArcPy job artifact workflow"
```

## Task 7: Add the High-Level ArcPy Toolset

**Files:**
- Create: `data_agent/toolsets/arcpy_mcp_toolset.py`
- Create: `data_agent/test_arcpy_mcp_toolset.py`
- Modify: `data_agent/toolsets/__init__.py:10-55`

- [ ] **Step 1: Write failing tool discovery and delegation tests**

```python
import asyncio
from unittest.mock import AsyncMock, patch

from data_agent.toolsets.arcpy_mcp_toolset import ArcPyMcpToolset


def test_toolset_exposes_complete_high_level_surface():
    names = {tool.name for tool in asyncio.run(ArcPyMcpToolset().get_tools())}
    assert {
        "arcpy_service_status", "arcpy_inspect_dataset", "arcpy_buffer_features",
        "arcpy_clip_features", "arcpy_clip_raster", "arcpy_dissolve_features",
        "arcpy_intersect_features", "arcpy_spatial_join", "arcpy_project_features",
        "arcpy_project_raster", "arcpy_check_geometry", "arcpy_repair_geometry",
        "arcpy_calculate_slope", "arcpy_zonal_statistics", "arcpy_export_map_layout",
        "arcpy_detect_objects", "arcpy_classify_pixels", "arcpy_classify_objects",
        "arcpy_detect_change", "arcpy_run_catalog_tool",
    } <= names


@patch("data_agent.toolsets.arcpy_mcp_toolset.get_arcpy_mcp_client")
def test_buffer_delegates_local_path_and_domain_arguments(get_client):
    client = get_client.return_value
    client.run_dedicated = AsyncMock(return_value={"status": "success"})
    from data_agent.toolsets.arcpy_mcp_toolset import arcpy_buffer_features
    result = asyncio.run(arcpy_buffer_features("roads.shp", "100 Meters", "buffer.zip", "ALL"))
    assert result["status"] == "success"
    client.run_dedicated.assert_awaited_once()
```

- [ ] **Step 2: Verify toolset tests fail**

Run: `.venv/bin/python -m pytest data_agent/test_arcpy_mcp_toolset.py -q`

Expected: import failure.

- [ ] **Step 3: Implement explicit wrapper functions**

Each wrapper has a domain-specific signature and delegates to one of four client primitives: `run_dedicated`, `run_multi_input`, `run_deep_learning`, or `run_catalog_tool`.

Representative wrapper:

```python
async def arcpy_buffer_features(
    input_path: str,
    distance: str,
    output_name: str = "buffer_result.zip",
    dissolve_option: str = "NONE",
) -> dict:
    """Buffer a local vector dataset with ArcGIS Pro and return verified local outputs."""
    return await get_arcpy_mcp_client().run_dedicated(
        remote_tool="buffer_features",
        local_inputs={"input": input_path},
        parameters={
            "distance": distance,
            "output_name": output_name,
            "dissolve_option": dissolve_option,
        },
    )
```

Implement all names asserted in Step 1. Map local inputs to the remote prefixes exactly: `input`, `clip`, `template`, `target`, `join`, `zone`, `value`, `model`, `from`, and `to`. `arcpy_intersect_features` prepares a list of uploaded inputs. `arcpy_run_catalog_tool` always calls `search_tools` and `describe_tool` before `submit_job` and rejects parameters outside the described JSON Schema.

- [ ] **Step 4: Implement the BaseToolset**

```python
_ALL_FUNCS = [
    arcpy_service_status,
    arcpy_inspect_dataset,
    arcpy_buffer_features,
    arcpy_clip_features,
    arcpy_clip_raster,
    arcpy_dissolve_features,
    arcpy_intersect_features,
    arcpy_spatial_join,
    arcpy_project_features,
    arcpy_project_raster,
    arcpy_check_geometry,
    arcpy_repair_geometry,
    arcpy_calculate_slope,
    arcpy_zonal_statistics,
    arcpy_export_map_layout,
    arcpy_detect_objects,
    arcpy_classify_pixels,
    arcpy_classify_objects,
    arcpy_detect_change,
    arcpy_run_catalog_tool,
]


class ArcPyMcpToolset(BaseToolset):
    async def get_tools(self, readonly_context=None):
        tools = [FunctionTool(function) for function in _ALL_FUNCS]
        if self.tool_filter is None:
            return tools
        return [tool for tool in tools if self._is_tool_selected(tool, readonly_context)]
```

Add `"ArcPyMcpToolset": ".arcpy_mcp_toolset"` to the lazy export map.

- [ ] **Step 5: Run toolset tests**

Run: `.venv/bin/python -m pytest data_agent/test_arcpy_mcp_toolset.py data_agent/test_toolsets.py -q`

Expected: all pass.

- [ ] **Step 6: Commit the ArcPy toolset**

```bash
git add data_agent/toolsets/arcpy_mcp_toolset.py data_agent/toolsets/__init__.py data_agent/test_arcpy_mcp_toolset.py data_agent/test_toolsets.py
git commit -m "feat: expose high-level ArcPy MCP tools"
```

## Task 8: Register Three Pipelines and Deep-Learning HITL

**Files:**
- Modify: `data_agent/agent.py:35-70, 493-535, 585-635, 690-742`
- Modify: `data_agent/hitl_approval.py:35-112`
- Create: `data_agent/test_arcpy_mcp_agent_integration.py`
- Modify: `data_agent/test_hitl_approval.py`

- [ ] **Step 1: Write failing pipeline and risk tests**

```python
from data_agent.hitl_approval import RiskLevel, assess_risk


def test_all_deep_learning_tools_require_critical_confirmation():
    for name in (
        "arcpy_detect_objects",
        "arcpy_classify_pixels",
        "arcpy_classify_objects",
        "arcpy_detect_change",
    ):
        risk = assess_risk(name, {"input_path": "image.tif"})
        assert risk["level"] == RiskLevel.CRITICAL
        assert "CPU" in risk["impact"]


def test_requested_pipelines_include_arcpy_mcp_toolset():
    from data_agent.agent import general_processing_agent, governance_processing_agent
    general_types = {type(tool).__name__ for tool in general_processing_agent.tools}
    governance_types = {type(tool).__name__ for tool in governance_processing_agent.tools}
    assert "ArcPyMcpToolset" in general_types
    assert "ArcPyMcpToolset" in governance_types
```

Also instantiate `_make_planner_processor("ArcPyPlannerTest")` and assert `ArcPyMcpToolset` is present.

- [ ] **Step 2: Run tests and verify missing registration**

Run: `.venv/bin/python -m pytest data_agent/test_arcpy_mcp_agent_integration.py data_agent/test_hitl_approval.py -q`

Expected: missing toolset and risk entries.

- [ ] **Step 3: Register independent toolsets**

Import `ArcPyMcpToolset` from `.toolsets`. Add a new instance to:

- `general_processing_agent.tools`;
- `governance_exploration_agent.tools` with status, inspect, geometry check, slope, and zonal-statistics filters;
- `governance_processing_agent.tools` with repair and transformation filters;
- `_make_planner_processor("PlannerProcessor").tools` with the full surface.

Do not reuse one `ArcPyMcpToolset` object across agents.

- [ ] **Step 4: Add critical HITL entries**

Add all four names to `_RISK_REGISTRY` with `RiskLevel.CRITICAL`, descriptions naming the inference type, and impact text stating that ArcGIS Pro 3.7.1 CPU inference may be long-running and will create remote/local result artifacts.

- [ ] **Step 5: Run agent and HITL tests**

Run: `.venv/bin/python -m pytest data_agent/test_arcpy_mcp_agent_integration.py data_agent/test_hitl_approval.py data_agent/test_multi_agent.py -q`

Expected: all pass.

- [ ] **Step 6: Commit pipeline integration**

```bash
git add data_agent/agent.py data_agent/hitl_approval.py data_agent/test_arcpy_mcp_agent_integration.py data_agent/test_hitl_approval.py
git commit -m "feat: route Agent pipelines to ArcPy MCP"
```

## Task 9: Add macOS and Docker Configuration

**Files:**
- Modify: `data_agent/mcp_servers.yaml:55-90`
- Modify: `data_agent/.env.example:145-165`
- Create: `docker-compose.arcpy-mcp.yml`
- Create: `data_agent/test_arcpy_mcp_deployment_contract.py`

- [ ] **Step 1: Write failing deployment contract tests**

```python
from pathlib import Path
import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_legacy_windows_arcpy_seed_is_not_enabled():
    data = yaml.safe_load((ROOT / "data_agent/mcp_servers.yaml").read_text(encoding="utf-8"))
    legacy = [row for row in data["servers"] if row["name"] == "arcgis-pro-tools"]
    assert not legacy or legacy[0]["enabled"] is False


def test_arcpy_compose_override_uses_secret_and_read_only_ca():
    data = yaml.safe_load((ROOT / "docker-compose.arcpy-mcp.yml").read_text(encoding="utf-8"))
    app = data["services"]["app"]
    assert "arcpy_mcp_token" in app["secrets"]
    assert app["environment"]["ARCPY_MCP_TOKEN_FILE"] == "/run/secrets/arcpy_mcp_token"
    assert app["environment"]["ARCPY_MCP_CA_BUNDLE"] == "/run/secrets/arcpy_mcp_ca"
```

- [ ] **Step 2: Run deployment tests and verify the override is absent**

Run: `.venv/bin/python -m pytest data_agent/test_arcpy_mcp_deployment_contract.py -q`

Expected: missing Compose override.

- [ ] **Step 3: Replace the new-install Windows seed**

Remove the `arcgis-pro-tools` YAML block or retain it only as `enabled: false` with `description` beginning `Legacy Windows-local ArcPy bridge`. Do not include the remote bearer token or CA location in YAML.

- [ ] **Step 4: Add exact environment documentation**

Document `ARCPY_MCP_ENABLED`, `ARCPY_MCP_URL`, `ARCPY_MCP_CA_BUNDLE`, `ARCPY_MCP_TOKEN`, `ARCPY_MCP_TOKEN_FILE`, and all five timeout variables. State that token file wins over token environment and neither value is committed.

- [ ] **Step 5: Add the optional Compose override**

```yaml
services:
  app:
    environment:
      ARCPY_MCP_ENABLED: "true"
      ARCPY_MCP_URL: ${ARCPY_MCP_URL}
      ARCPY_MCP_TOKEN_FILE: /run/secrets/arcpy_mcp_token
      ARCPY_MCP_CA_BUNDLE: /run/secrets/arcpy_mcp_ca
      NO_PROXY: ${NO_PROXY:-localhost,127.0.0.1},192.168.25.228
    secrets:
      - arcpy_mcp_token
      - arcpy_mcp_ca

secrets:
  arcpy_mcp_token:
    file: ${ARCPY_MCP_TOKEN_HOST_FILE}
  arcpy_mcp_ca:
    file: ${ARCPY_MCP_CA_HOST_FILE}
```

- [ ] **Step 6: Run deployment contract and Compose validation**

Run: `.venv/bin/python -m pytest data_agent/test_arcpy_mcp_deployment_contract.py -q`

Run: `docker compose -f docker-compose.yml -f docker-compose.arcpy-mcp.yml config --quiet`

Expected: tests pass and Compose config exits 0 when the two host-file variables point to existing test files.

- [ ] **Step 7: Commit deployment configuration**

```bash
git add data_agent/mcp_servers.yaml data_agent/.env.example docker-compose.arcpy-mcp.yml data_agent/test_arcpy_mcp_deployment_contract.py
git commit -m "feat: configure ArcPy MCP deployment"
```

## Task 10: Add Live Smoke Verification and Documentation

**Files:**
- Create: `scripts/smoke_arcpy_mcp.py`
- Create: `data_agent/test_data/arcpy_mcp_smoke.geojson`
- Create: `data_agent/test_arcpy_mcp_smoke_contract.py`
- Modify: `docs/mcp-integration-guide.md`
- Modify: `README_en.md`

- [ ] **Step 1: Add a smoke-script contract test**

Create `data_agent/test_arcpy_mcp_smoke_contract.py` with a fake client that records calls. Assert `run_smoke(input_path, output_dir, client=fake)` calls `health_check` first, copies the source fixture into the user output directory before upload, calls the buffer workflow, and returns only `status`, `arcgis_version`, `local_outputs`, and `duration_seconds`. Inspect `build_parser()` and assert its option strings are exactly `--input` and `--output-dir`.

- [ ] **Step 2: Run the contract test and verify the script is missing**

Run: `.venv/bin/python -m pytest data_agent/test_arcpy_mcp_smoke_contract.py -q`

Expected: import failure.

- [ ] **Step 3: Implement the live smoke script**

Add a tracked GeoJSON fixture containing one WGS84 square polygon:

```json
{"type":"FeatureCollection","name":"arcpy_mcp_smoke","crs":{"type":"name","properties":{"name":"urn:ogc:def:crs:OGC:1.3:CRS84"}},"features":[{"type":"Feature","properties":{"id":1},"geometry":{"type":"Polygon","coordinates":[[[106.50,29.50],[106.51,29.50],[106.51,29.51],[106.50,29.51],[106.50,29.50]]]}}]}
```

The CLI accepts only `--input` and `--output-dir`. It reads service configuration from environment, copies the fixture into the requested output directory inside the current user sandbox, uses `ArcPyMcpClient`, performs health and capabilities checks, runs `buffer_features` with `10 Meters`, polls to `succeeded`, downloads the output, verifies SHA-256, and prints only a sanitized JSON summary with status, ArcGIS version, local output names, and duration.

- [ ] **Step 4: Document operations and troubleshooting**

Update the guide with:

- macOS Keychain/launch environment injection;
- external CA path setup;
- Docker Compose override invocation;
- UI connection test and reconnect behavior;
- stable error-code troubleshooting;
- CPU deep-learning confirmation and compatible ArcGIS Pro 3.7.1 DLPK/EMD requirement;
- explicit warning never to paste the token into the MCP UI headers field.

- [ ] **Step 5: Run the contract tests**

Run: `.venv/bin/python -m pytest data_agent/test_arcpy_mcp_smoke_contract.py -q`

Expected: pass.

- [ ] **Step 6: Run the real macOS smoke test**

Run: `.venv/bin/python scripts/smoke_arcpy_mcp.py --input data_agent/test_data/arcpy_mcp_smoke.geojson --output-dir data_agent/uploads/anonymous/arcpy-smoke`

Expected: final JSON has `status: success`; the polled job reached `succeeded`; every local output exists and matches the remote checksum. Do not report success for queued or running jobs.

- [ ] **Step 7: Run the Docker smoke test**

Run: `docker compose -f docker-compose.yml -f docker-compose.arcpy-mcp.yml up -d --build app`

Run: `docker compose -f docker-compose.yml -f docker-compose.arcpy-mcp.yml exec app python scripts/smoke_arcpy_mcp.py --input data_agent/test_data/arcpy_mcp_smoke.geojson --output-dir data_agent/uploads/anonymous/arcpy-smoke-docker`

Expected: the same verified success contract. If the container cannot route to the private endpoint, inspect `NO_PROXY` and host routing before changing application code.

- [ ] **Step 8: Verify deep-learning readiness**

Call live `get_capabilities` and `list_artifacts`. If a compatible DLPK or EMD is present, submit one minimal inference only after explicit confirmation and poll to a terminal state. If no model exists, record `live_model_artifact_missing` in the verification report and run the deep-learning wrapper tests against the fake MCP service.

- [ ] **Step 9: Commit smoke tooling and docs**

```bash
git add scripts/smoke_arcpy_mcp.py data_agent/test_data/arcpy_mcp_smoke.geojson data_agent/test_arcpy_mcp_smoke_contract.py docs/mcp-integration-guide.md README_en.md
git commit -m "test: add ArcPy MCP smoke verification"
```

## Task 11: Final Regression and Security Verification

**Files:**
- Verify all files changed in Tasks 1-10.

- [ ] **Step 1: Run focused backend tests**

Run: `.venv/bin/python -m pytest data_agent/test_mcp_routes.py data_agent/test_mcp_transport.py data_agent/test_mcp_hub.py data_agent/test_arcpy_mcp_configuration.py data_agent/test_arcpy_mcp_client.py data_agent/test_arcpy_mcp_toolset.py data_agent/test_arcpy_mcp_agent_integration.py data_agent/test_arcpy_mcp_deployment_contract.py data_agent/test_arcpy_mcp_smoke_contract.py data_agent/test_hitl_approval.py data_agent/test_health.py -q`

Expected: all pass.

- [ ] **Step 2: Run existing MCP, Agent, catalog, and artifact regressions**

Run: `.venv/bin/python -m pytest data_agent/test_frontend_api.py data_agent/test_toolsets.py data_agent/test_multi_agent.py data_agent/test_data_catalog.py data_agent/test_mcp_server.py -q`

Expected: all pass.

- [ ] **Step 3: Build the frontend**

Run: `npm run build`

Working directory: `frontend`

Expected: Vite production build exits 0 with no TypeScript errors.

- [ ] **Step 4: Scan tracked changes for secret leakage**

Run: `git diff --check`

Run: `git diff --cached --check`

Run: `rg -n "Authorization: Bearer [A-Za-z0-9]|ARCPY_MCP_TOKEN=.+|signature=[^\[]" data_agent scripts docker-compose.arcpy-mcp.yml -g '!test_*.py'`

Expected: no resolved token, bearer value, or signed URL. Documentation may mention variable names only.

- [ ] **Step 5: Review final scope and dirty worktree**

Run: `git status --short`

Expected: ArcPy integration changes are understood and unrelated pre-existing user changes remain untouched.

- [ ] **Step 6: Create the final integration commit if verification produced follow-up edits**

```bash
git add data_agent/mcp_transport.py data_agent/mcp_hub.py data_agent/api/mcp_routes.py data_agent/arcpy_mcp_client.py data_agent/toolsets/arcpy_mcp_toolset.py data_agent/toolsets/__init__.py data_agent/agent.py data_agent/hitl_approval.py data_agent/health.py data_agent/mcp_servers.yaml data_agent/.env.example docker-compose.arcpy-mcp.yml scripts/smoke_arcpy_mcp.py data_agent/test_data/arcpy_mcp_smoke.geojson docs/mcp-integration-guide.md README_en.md data_agent/test_mcp_routes.py data_agent/test_mcp_transport.py data_agent/test_mcp_hub.py data_agent/test_arcpy_mcp_configuration.py data_agent/test_arcpy_mcp_client.py data_agent/test_arcpy_mcp_toolset.py data_agent/test_arcpy_mcp_agent_integration.py data_agent/test_arcpy_mcp_deployment_contract.py data_agent/test_arcpy_mcp_smoke_contract.py data_agent/test_hitl_approval.py data_agent/test_health.py
git commit -m "feat: complete ArcPy MCP integration"
```

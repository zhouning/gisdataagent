"""Tests for the private ArcPy MCP client."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from data_agent.arcpy_mcp_client import ArcPyMcpClient, ArcPyMcpError
from data_agent.mcp_hub import McpServerConfig


def test_client_api_is_importable():
    assert ArcPyMcpClient is not None
    assert ArcPyMcpError is not None


def _client() -> ArcPyMcpClient:
    return ArcPyMcpClient(
        McpServerConfig(name="arcpy", url="https://service.example/mcp")
    )


def _result(*, structured=None, text=None, error=False, snake_case=False):
    attributes = {"content": [] if text is None else [SimpleNamespace(text=text)]}
    if snake_case:
        attributes.update(is_error=error, structured_content=structured)
    else:
        attributes.update(isError=error, structuredContent=structured)
    return SimpleNamespace(**attributes)


def test_error_has_stable_code_dict_details_and_sanitized_repr():
    error = ArcPyMcpError(
        "ARCPY_TEST",
        "Authorization: Bearer fixture-credential",
        {
            "url": "https://download.example/item?signature=fixture-signature",
            "Authorization: Bearer fixture-key-credential": RuntimeError(
                "Authorization: Bearer fixture-value-credential"
            ),
        },
    )

    assert error.code == "ARCPY_TEST"
    assert error.details["url"] == (
        "https://download.example/item?signature=[REDACTED]"
    )
    assert "fixture-credential" not in str(error)
    assert "fixture-signature" not in repr(error)
    assert "fixture-key-credential" not in repr(error.details)
    assert "fixture-value-credential" not in repr(error.details)


@pytest.mark.asyncio
async def test_unknown_tool_is_rejected_before_connect():
    client = _client()
    client.connect = AsyncMock()

    with pytest.raises(ArcPyMcpError) as exc_info:
        await client.call_tool("execute_python", {})

    assert exc_info.value.code == "ARCPY_TOOL_NOT_ALLOWED"
    client.connect.assert_not_awaited()


@pytest.mark.asyncio
async def test_train_deep_learning_model_is_rejected_before_connect():
    client = _client()
    client.connect = AsyncMock()

    with pytest.raises(ArcPyMcpError) as exc_info:
        await client.call_tool("TrainDeepLearningModel", {})

    assert exc_info.value.code == "ARCPY_TOOL_NOT_ALLOWED"
    client.connect.assert_not_awaited()


def test_allowlist_matches_private_service_contract_exactly():
    assert ArcPyMcpClient.allowed_tools == frozenset(
        {
            "health_check",
            "get_capabilities",
            "create_upload",
            "get_upload_status",
            "renew_upload",
            "complete_upload",
            "list_artifacts",
            "delete_artifact",
            "inspect_dataset",
            "get_job",
            "list_jobs",
            "cancel_job",
            "get_job_log",
            "create_download",
            "search_tools",
            "describe_tool",
            "submit_job",
            "buffer_features",
            "clip_features",
            "clip_raster",
            "dissolve_features",
            "intersect_features",
            "spatial_join",
            "project_features",
            "project_raster",
            "check_geometry",
            "repair_geometry",
            "calculate_slope",
            "zonal_statistics",
            "export_map_layout",
            "detect_objects",
            "classify_pixels",
            "classify_objects",
            "detect_change",
        }
    )


@pytest.mark.asyncio
async def test_call_tool_returns_a_copy_of_structured_content():
    payload = {"status": "ok", "nested": {"count": 1}}
    client = _client()
    client._session = SimpleNamespace(
        call_tool=AsyncMock(return_value=_result(structured=payload))
    )

    returned = await client.call_tool("get_job", {"job_id": "job-1"})

    assert returned == payload
    assert returned is not payload


@pytest.mark.asyncio
async def test_call_tool_supports_snake_case_sdk_result_attributes():
    client = _client()
    client._session = SimpleNamespace(
        call_tool=AsyncMock(
            return_value=_result(structured={"status": "ok"}, snake_case=True)
        )
    )

    assert await client.call_tool("get_job", {}) == {"status": "ok"}


@pytest.mark.asyncio
async def test_call_tool_parses_text_json_object_fallback():
    client = _client()
    client._session = SimpleNamespace(
        call_tool=AsyncMock(return_value=_result(text='{"status": "ok"}'))
    )

    assert await client.call_tool("get_job", {}) == {"status": "ok"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "result",
    [
        _result(text="not json"),
        _result(text="[]"),
        _result(structured=["not", "an", "object"]),
        _result(),
    ],
)
async def test_call_tool_rejects_invalid_or_non_object_response(result):
    client = _client()
    client._session = SimpleNamespace(call_tool=AsyncMock(return_value=result))

    with pytest.raises(ArcPyMcpError) as exc_info:
        await client.call_tool("get_job", {})

    assert exc_info.value.code == "ARCPY_RESPONSE_INVALID"
    assert "JSONDecodeError" not in str(exc_info.value)
    assert exc_info.value.__cause__ is None


@pytest.mark.asyncio
async def test_call_tool_maps_transport_failure_without_exception_chain_secrets():
    credential = "fixture-runtime-credential"
    signed_value = "fixture-signed-value"
    client = _client()
    client._resolved_token = credential
    client._session = SimpleNamespace(
        call_tool=AsyncMock(
            side_effect=RuntimeError(
                "Authorization: Bearer "
                f"{credential}; https://download.example/item?signature={signed_value}"
            )
        )
    )

    with pytest.raises(ArcPyMcpError) as exc_info:
        await client.call_tool("get_capabilities", {})

    error = exc_info.value
    assert error.code == "ARCPY_MCP_UNREACHABLE"
    assert str(error) == "ArcPy MCP service is unreachable"
    assert credential not in str(error)
    assert signed_value not in repr(error)
    assert error.__cause__ is None
    assert error.__context__ is None


@pytest.mark.asyncio
async def test_call_tool_maps_sanitized_result_error():
    credential = "fixture-runtime-credential"
    signed_value = "fixture-signed-value"
    client = _client()
    client._resolved_token = credential
    client._session = SimpleNamespace(
        call_tool=AsyncMock(
            return_value=_result(
                error=True,
                text=(
                    "Authorization: Bearer "
                    f"{credential}; https://download.example/item?sig={signed_value}"
                ),
            )
        )
    )

    with pytest.raises(ArcPyMcpError) as exc_info:
        await client.call_tool("submit_job", {})

    assert exc_info.value.code == "ARCPY_JOB_FAILED"
    assert str(exc_info.value) == "ArcPy MCP tool reported a failure"
    assert credential not in str(exc_info.value)
    assert signed_value not in repr(exc_info.value)


class FakeContext:
    def __init__(self, name, value, events):
        self.name = name
        self.value = value
        self.events = events
        self.enter_count = 0
        self.exit_count = 0

    async def __aenter__(self):
        self.enter_count += 1
        self.events.append(f"enter:{self.name}")
        return self.value

    async def __aexit__(self, exc_type, exc, traceback):
        self.exit_count += 1
        self.events.append(f"exit:{self.name}")


class FakeSdkSession:
    def __init__(self, events, *, initialize_error=None, call_result=None):
        self.events = events
        self.initialize_error = initialize_error
        self.call_result = call_result or _result(structured={"status": "ok"})
        self.initialize_count = 0
        self.exit_count = 0

    async def __aenter__(self):
        self.events.append("enter:session")
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        self.exit_count += 1
        self.events.append("exit:session")

    async def initialize(self):
        self.initialize_count += 1
        self.events.append("initialize")
        if self.initialize_error:
            raise self.initialize_error

    async def call_tool(self, name, arguments):
        return self.call_result


def _install_fake_sdk(monkeypatch, sessions):
    import data_agent.arcpy_mcp_client as client_module

    events = sessions[0].events
    http_contexts = []
    transport_contexts = []

    def make_http_client(**kwargs):
        context = FakeContext("http", object(), events)
        http_contexts.append(context)
        return context

    def make_transport(url, *, http_client, terminate_on_close=True):
        context = FakeContext(
            "transport", ("read", "write", lambda: "session-id"), events
        )
        transport_contexts.append(context)
        return context

    http_factory = MagicMock(side_effect=make_http_client)
    transport_factory = MagicMock(side_effect=make_transport)
    session_factory = MagicMock(side_effect=sessions)
    monkeypatch.setattr(client_module.httpx, "AsyncClient", http_factory)
    monkeypatch.setattr(client_module, "streamable_http_client", transport_factory)
    monkeypatch.setattr(client_module, "ClientSession", session_factory)
    return SimpleNamespace(
        events=events,
        http_factory=http_factory,
        http_contexts=http_contexts,
        transport_factory=transport_factory,
        transport_contexts=transport_contexts,
        session_factory=session_factory,
    )


@pytest.mark.asyncio
async def test_connect_builds_one_authenticated_official_session_and_initializes(
    monkeypatch,
):
    from data_agent.mcp_transport import current_runtime_secrets

    events = []
    session = FakeSdkSession(events)
    sdk = _install_fake_sdk(monkeypatch, [session])
    sdk.events = events
    monkeypatch.setenv("ARCPY_CLIENT_TEST_TOKEN", "fixture-connect-credential")
    config = McpServerConfig(
        name="arcpy",
        url="https://service.example/mcp",
        timeout=7,
        bearer_token_env_var="ARCPY_CLIENT_TEST_TOKEN",
    )
    client = ArcPyMcpClient(config)

    await client.connect()
    await client.connect()

    sdk.http_factory.assert_called_once_with(
        headers={"Authorization": "Bearer fixture-connect-credential"},
        timeout=7,
        follow_redirects=True,
    )
    sdk.transport_factory.assert_called_once()
    assert sdk.transport_factory.call_args.kwargs["http_client"] is not None
    assert sdk.session_factory.call_count == 1
    assert session.initialize_count == 1
    assert client._session is session
    assert current_runtime_secrets() == ("fixture-connect-credential",)

    await client.close()
    assert current_runtime_secrets() == ()


@pytest.mark.asyncio
async def test_secret_file_precedence_and_ca_factory_are_wired(
    monkeypatch, tmp_path
):
    import data_agent.arcpy_mcp_client as client_module

    events = []
    session = FakeSdkSession(events)
    http_context = FakeContext("http", object(), events)
    client_factory = MagicMock(return_value=http_context)
    ca_factory_builder = MagicMock(return_value=client_factory)
    monkeypatch.setattr(
        client_module, "build_httpx_client_factory", ca_factory_builder
    )
    transport_context = FakeContext(
        "transport", ("read", "write", lambda: None), events
    )
    monkeypatch.setattr(
        client_module,
        "streamable_http_client",
        MagicMock(return_value=transport_context),
    )
    monkeypatch.setattr(
        client_module, "ClientSession", MagicMock(return_value=session)
    )
    token_file = tmp_path / "credential"
    token_file.write_text("fixture-file-credential\n", encoding="utf-8")
    ca_file = tmp_path / "ca.pem"
    ca_file.write_text(
        "-----BEGIN CERTIFICATE-----\nfixture\n-----END CERTIFICATE-----\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ARCPY_CLIENT_TEST_TOKEN", "fixture-env-credential")
    monkeypatch.setenv("ARCPY_CLIENT_TEST_TOKEN_FILE", str(token_file))
    monkeypatch.setenv("ARCPY_CLIENT_TEST_CA", str(ca_file))
    client = ArcPyMcpClient(
        McpServerConfig(
            name="arcpy",
            url="https://service.example/mcp",
            bearer_token_env_var="ARCPY_CLIENT_TEST_TOKEN",
            bearer_token_file_env_var="ARCPY_CLIENT_TEST_TOKEN_FILE",
            ca_bundle_env_var="ARCPY_CLIENT_TEST_CA",
        )
    )

    await client.connect()

    ca_factory_builder.assert_called_once_with(str(ca_file))
    client_factory.assert_called_once_with(
        headers={"Authorization": "Bearer fixture-file-credential"},
        timeout=5.0,
    )
    assert "fixture-env-credential" not in repr(client)
    assert "fixture-file-credential" not in repr(client)
    assert str(ca_file) not in repr(client)
    await client.close()


@pytest.mark.asyncio
async def test_close_exits_all_contexts_in_reverse_order_and_is_idempotent(
    monkeypatch,
):
    events = []
    session = FakeSdkSession(events)
    sdk = _install_fake_sdk(monkeypatch, [session])
    sdk.events = events
    monkeypatch.setenv("ARCPY_CLIENT_TEST_TOKEN", "fixture-close-credential")
    client = ArcPyMcpClient(
        McpServerConfig(
            name="arcpy",
            url="https://service.example/mcp",
            bearer_token_env_var="ARCPY_CLIENT_TEST_TOKEN",
        )
    )
    await client.connect()

    await client.close()
    await client.close()

    assert session.exit_count == 1
    assert sdk.transport_contexts[0].exit_count == 1
    assert sdk.http_contexts[0].exit_count == 1
    assert events[-3:] == ["exit:session", "exit:transport", "exit:http"]
    assert client._session is None
    assert client._resolved_token is None
    assert client._stack is None


@pytest.mark.asyncio
async def test_half_connect_failure_cleans_up_and_allows_retry(monkeypatch):
    from data_agent.mcp_transport import current_runtime_secrets

    first_events = []
    second_events = []
    first_session = FakeSdkSession(
        first_events,
        initialize_error=RuntimeError(
            "Authorization: Bearer fixture-failed-connect-credential"
        ),
    )
    second_session = FakeSdkSession(second_events)
    sdk = _install_fake_sdk(monkeypatch, [first_session, second_session])
    monkeypatch.setenv(
        "ARCPY_CLIENT_TEST_TOKEN", "fixture-failed-connect-credential"
    )
    client = ArcPyMcpClient(
        McpServerConfig(
            name="arcpy",
            url="https://service.example/mcp",
            bearer_token_env_var="ARCPY_CLIENT_TEST_TOKEN",
        )
    )

    with pytest.raises(ArcPyMcpError) as exc_info:
        await client.connect()

    assert exc_info.value.code == "ARCPY_MCP_UNREACHABLE"
    assert "fixture-failed-connect-credential" not in repr(exc_info.value)
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None
    assert first_session.exit_count == 1
    assert sdk.transport_contexts[0].exit_count == 1
    assert sdk.http_contexts[0].exit_count == 1
    assert client._session is None
    assert client._resolved_token is None
    assert client._stack is None
    assert current_runtime_secrets() == ()

    await client.connect()
    assert client._session is second_session
    assert second_session.initialize_count == 1
    await client.close()


@pytest.mark.asyncio
async def test_cancelled_half_connect_cleans_up_and_remains_retryable(monkeypatch):
    from data_agent.mcp_transport import current_runtime_secrets

    initialize_started = asyncio.Event()
    release_initialize = asyncio.Event()

    class BlockingInitializeSession(FakeSdkSession):
        async def initialize(self):
            self.initialize_count += 1
            initialize_started.set()
            await release_initialize.wait()

    first_session = BlockingInitializeSession([])
    second_session = FakeSdkSession([])
    sdk = _install_fake_sdk(monkeypatch, [first_session, second_session])
    monkeypatch.setenv("ARCPY_CLIENT_TEST_TOKEN", "fixture-cancel-credential")
    client = ArcPyMcpClient(
        McpServerConfig(
            name="arcpy",
            url="https://service.example/mcp",
            bearer_token_env_var="ARCPY_CLIENT_TEST_TOKEN",
        )
    )

    connect_task = asyncio.create_task(client.connect())
    await initialize_started.wait()
    connect_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await connect_task

    assert first_session.exit_count == 1
    assert sdk.transport_contexts[0].exit_count == 1
    assert sdk.http_contexts[0].exit_count == 1
    assert client._session is None
    assert client._stack is None
    assert client._resolved_token is None
    assert current_runtime_secrets() == ()

    release_initialize.set()
    await client.connect()
    assert client._session is second_session
    await client.close()


@pytest.mark.asyncio
async def test_concurrent_connect_creates_a_single_session(monkeypatch):
    events = []
    session = FakeSdkSession(events)
    sdk = _install_fake_sdk(monkeypatch, [session])
    monkeypatch.setenv("ARCPY_CLIENT_TEST_TOKEN", "fixture-concurrent-credential")
    client = ArcPyMcpClient(
        McpServerConfig(
            name="arcpy",
            url="https://service.example/mcp",
            bearer_token_env_var="ARCPY_CLIENT_TEST_TOKEN",
        )
    )

    await asyncio.gather(*(client.connect() for _ in range(8)))

    assert sdk.http_factory.call_count == 1
    assert sdk.transport_factory.call_count == 1
    assert sdk.session_factory.call_count == 1
    assert session.initialize_count == 1
    await client.close()


@pytest.mark.asyncio
async def test_missing_url_and_credentials_have_stable_configuration_errors(
    monkeypatch,
):
    monkeypatch.delenv("ARCPY_CLIENT_TEST_TOKEN", raising=False)
    no_url = ArcPyMcpClient(
        McpServerConfig(
            name="arcpy", bearer_token_env_var="ARCPY_CLIENT_TEST_TOKEN"
        )
    )
    no_credential = ArcPyMcpClient(
        McpServerConfig(
            name="arcpy",
            url="https://service.example/mcp",
            bearer_token_env_var="ARCPY_CLIENT_TEST_TOKEN",
        )
    )

    with pytest.raises(ArcPyMcpError) as url_error:
        await no_url.connect()
    with pytest.raises(ArcPyMcpError) as credential_error:
        await no_credential.connect()

    assert url_error.value.code == "ARCPY_MCP_URL_MISSING"
    assert credential_error.value.code == "ARCPY_MCP_TOKEN_MISSING"


class FakeClock:
    def __init__(self):
        self.value = 100.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


@pytest.mark.asyncio
async def test_close_waits_for_an_owned_call_and_then_clears_state():
    started = asyncio.Event()
    release = asyncio.Event()

    class BlockingSession:
        async def call_tool(self, name, arguments):
            started.set()
            await release.wait()
            return _result(structured={"status": "ok"})

    client = _client()
    client._session = BlockingSession()
    call_task = asyncio.create_task(client.call_tool("get_job", {}))
    await started.wait()
    close_task = asyncio.create_task(client.close())
    await asyncio.sleep(0)

    assert not close_task.done()
    assert client._session is not None

    release.set()
    assert await call_task == {"status": "ok"}
    await close_task
    assert client._session is None


@pytest.mark.asyncio
async def test_health_check_requires_healthy_status_and_worker_dict():
    invalid_results = [
        {"status": "degraded", "worker": {"detail": "private-host"}},
        {"status": "healthy"},
        {"status": "healthy", "worker": "not-an-object"},
    ]
    for payload in invalid_results:
        client = _client()
        client._session = SimpleNamespace(
            call_tool=AsyncMock(return_value=_result(structured=payload))
        )

        with pytest.raises(ArcPyMcpError) as exc_info:
            await client.health_check()

        assert exc_info.value.code == "ARCPY_WORKER_UNAVAILABLE"
        assert str(exc_info.value) == "ArcPy worker is unavailable"
        assert "private-host" not in repr(exc_info.value)


@pytest.mark.asyncio
async def test_health_check_caches_only_success_for_thirty_seconds():
    clock = FakeClock()
    session = SimpleNamespace(
        call_tool=AsyncMock(
            side_effect=[
                _result(structured={"status": "unhealthy", "worker": {}}),
                _result(
                    structured={"status": "healthy", "worker": {"mode": "cpu"}}
                ),
                _result(
                    structured={
                        "status": "healthy",
                        "worker": {"mode": "cpu", "generation": 2},
                    }
                ),
            ]
        )
    )
    client = ArcPyMcpClient(
        McpServerConfig(name="arcpy", url="https://service.example/mcp"),
        clock=clock,
    )
    client._session = session

    with pytest.raises(ArcPyMcpError):
        await client.health_check()
    first = await client.health_check()
    first["worker"]["mode"] = "mutated"
    clock.advance(29.9)
    cached = await client.health_check()
    clock.advance(0.1)
    refreshed = await client.health_check()

    assert cached["worker"]["mode"] == "cpu"
    assert refreshed["worker"]["generation"] == 2
    assert session.call_tool.await_count == 3


@pytest.mark.asyncio
async def test_health_transport_failure_is_not_cached():
    session = SimpleNamespace(
        call_tool=AsyncMock(
            side_effect=[
                RuntimeError("temporary transport failure"),
                _result(
                    structured={"status": "healthy", "worker": {"mode": "cpu"}}
                ),
            ]
        )
    )
    client = _client()
    client._session = session

    with pytest.raises(ArcPyMcpError) as exc_info:
        await client.health_check()
    result = await client.health_check()

    assert exc_info.value.code == "ARCPY_MCP_UNREACHABLE"
    assert result["status"] == "healthy"
    assert session.call_tool.await_count == 2


@pytest.mark.asyncio
async def test_capabilities_accepts_only_available_supported_extension():
    client = _client()
    client._session = SimpleNamespace(
        call_tool=AsyncMock(
            return_value=_result(
                structured={
                    "worker": {
                        "extensions": {
                            "Spatial": "Available",
                            "ImageAnalyst": "Unavailable",
                        }
                    }
                }
            )
        )
    )

    result = await client.get_capabilities("spatial analyst")
    with pytest.raises(ArcPyMcpError) as unavailable:
        await client.get_capabilities("image_analyst")
    with pytest.raises(ArcPyMcpError) as invalid:
        await client.get_capabilities("Network")

    assert result["worker"]["extensions"]["Spatial"] == "Available"
    assert unavailable.value.code == "ARCPY_EXTENSION_UNAVAILABLE"
    assert str(unavailable.value) == "Required ArcPy extension is unavailable"
    assert invalid.value.code == "ARCPY_INVALID_ARGUMENT"


@pytest.mark.asyncio
async def test_capabilities_cache_has_independent_thirty_second_ttl():
    clock = FakeClock()
    session = SimpleNamespace(
        call_tool=AsyncMock(
            side_effect=[
                _result(
                    structured={
                        "worker": {"extensions": {"Spatial": "Available"}},
                        "generation": 1,
                    }
                ),
                _result(
                    structured={
                        "worker": {"extensions": {"Spatial": "Available"}},
                        "generation": 2,
                    }
                ),
            ]
        )
    )
    client = ArcPyMcpClient(
        McpServerConfig(name="arcpy", url="https://service.example/mcp"),
        clock=clock,
    )
    client._session = session

    first = await client.get_capabilities("Spatial")
    clock.advance(29.9)
    cached = await client.get_capabilities()
    clock.advance(0.1)
    refreshed = await client.get_capabilities("Spatial")

    assert first["generation"] == cached["generation"] == 1
    assert refreshed["generation"] == 2
    assert session.call_tool.await_count == 2


@pytest.mark.asyncio
async def test_close_clears_health_and_capability_caches():
    session = SimpleNamespace(
        call_tool=AsyncMock(
            side_effect=[
                _result(structured={"status": "healthy", "worker": {}}),
                _result(structured={"worker": {"extensions": {}}}),
                _result(structured={"status": "healthy", "worker": {}}),
                _result(structured={"worker": {"extensions": {}}}),
            ]
        )
    )
    client = _client()
    client._session = session
    await client.health_check()
    await client.get_capabilities()

    await client.close()
    client._session = session
    await client.health_check()
    await client.get_capabilities()

    assert session.call_tool.await_count == 4

"""Tests for the private ArcPy MCP client."""

import asyncio
import gc
import threading
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
    assert error.details["url"] == "[REDACTED]"
    assert "fixture-credential" not in str(error)
    assert "fixture-signature" not in repr(error)
    assert "fixture-key-credential" not in repr(error.details)
    assert "fixture-value-credential" not in repr(error.details)


def test_error_redacts_runtime_secret_private_url_and_absolute_paths():
    from data_agent.mcp_transport import (
        register_runtime_secrets,
        unregister_runtime_secrets,
    )

    credential = "fixture-bare-runtime-credential"
    private_url = "https://10.1.2.3/private/service"
    unix_path = "/private/ca.pem"
    windows_path = "C:\\private\\ca.pem"
    register_runtime_secrets([credential])
    try:
        error = ArcPyMcpError(
            "ARCPY_TEST",
            f"failure {credential} {private_url} {unix_path} {windows_path}",
            {
                f"key-{credential}": private_url,
                "unix": unix_path,
                "windows": windows_path,
            },
        )
    finally:
        unregister_runtime_secrets([credential])

    public_state = f"{error!s} {error.details!r}"
    for sensitive in (
        credential,
        private_url,
        "10.1.2.3",
        unix_path,
        windows_path,
    ):
        assert sensitive not in public_state


def test_error_strictly_redacts_ipv6_unc_and_paths_with_spaces():
    ipv6 = "fd00::1234"
    unc_path = "\\\\server\\share\\private-ca.pem"
    unix_path = "/private/ca bundles/root.pem"
    windows_path = "C:\\private ca\\root.pem"
    error = ArcPyMcpError(
        "ARCPY_TEST",
        f"unsafe {ipv6} {unc_path} {unix_path} {windows_path}",
        {
            "safe-key": ipv6,
            unc_path: "unsafe-key",
            "unix": unix_path,
            "windows": windows_path,
        },
    )

    assert str(error) == "[REDACTED]"
    assert error.details["safe-key"] == "[REDACTED]"
    public_details = repr(error.details)
    for fragment in (
        "fd00",
        "server",
        "share",
        "private-ca",
        "ca bundles",
        "private ca",
        "root.pem",
    ):
        assert fragment not in public_details


@pytest.mark.parametrize(
    "sensitive",
    [
        "host=fd00::1234",
        "host=10.0.0.8:8443",
        "path=C:\\private ca\\root.pem",
        "path=C:/private ca/root.pem",
    ],
)
def test_error_redacts_embedded_location_tokens_as_whole_strings(sensitive):
    error = ArcPyMcpError(
        "ARCPY_TEST",
        sensitive,
        {sensitive: sensitive},
    )

    assert str(error) == "[REDACTED]"
    assert error.details == {"[REDACTED]": "[REDACTED]"}
    assert sensitive not in repr(error.details)


@pytest.mark.parametrize(
    "unsafe",
    [
        "worker=10.0.0.8:8443.",
        "worker=fd00::1234.",
        "endpoint=redis://internal-host:6379/0",
        "path:/private/ca.pem",
        "path:C:\\private\\ca.pem",
    ],
)
def test_unknown_error_code_fails_closed_for_message_and_details(unsafe):
    error = ArcPyMcpError("ARCPY_UNKNOWN", unsafe, {unsafe: unsafe})

    assert str(error) == "[REDACTED]"
    assert error.details == {"[REDACTED]": "[REDACTED]"}
    assert unsafe not in repr(error.details)


def test_known_error_code_ignores_caller_supplied_message():
    error = ArcPyMcpError(
        "ARCPY_MCP_UNREACHABLE",
        "caller supplied diagnostic must not be public",
    )

    assert str(error) == "ArcPy MCP service is unreachable"


def test_error_details_preserve_only_safe_identifiers_and_scalar_values():
    error = ArcPyMcpError(
        "ARCPY_JOB_FAILED",
        "ignored",
        {
            "count": 3,
            "enabled": True,
            "ratio": 1.25,
            "missing": None,
            "nested": {"attempt": 2, "diagnostic": "not public"},
        },
    )

    assert error.details == {
        "count": 3,
        "enabled": True,
        "ratio": 1.25,
        "missing": None,
        "nested": {"attempt": 2, "diagnostic": "[REDACTED]"},
    }


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


class TaskAffineContext(FakeContext):
    def __init__(self, name, value, events):
        super().__init__(name, value, events)
        self.enter_task = None
        self.affinity_violation = False

    async def __aenter__(self):
        self.enter_task = asyncio.current_task()
        return await super().__aenter__()

    async def __aexit__(self, exc_type, exc, traceback):
        if asyncio.current_task() is not self.enter_task:
            self.affinity_violation = True
            raise RuntimeError("context exited from a different task")
        await super().__aexit__(exc_type, exc, traceback)


class SensitiveFailingExitContext(TaskAffineContext):
    def __init__(self, name, value, events, message):
        super().__init__(name, value, events)
        self.message = message

    async def __aexit__(self, exc_type, exc, traceback):
        await super().__aexit__(exc_type, exc, traceback)
        raise RuntimeError(self.message)


class BlockingExitContext(TaskAffineContext):
    def __init__(self, name, value, events, exit_started, release_exit):
        super().__init__(name, value, events)
        self.exit_started = exit_started
        self.release_exit = release_exit

    async def __aexit__(self, exc_type, exc, traceback):
        self.exit_started.set()
        await self.release_exit.wait()
        await super().__aexit__(exc_type, exc, traceback)


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
        context = TaskAffineContext("http", object(), events)
        http_contexts.append(context)
        return context

    def make_transport(url, *, http_client, terminate_on_close=True):
        context = TaskAffineContext(
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


def _install_blocking_exit_sdk(monkeypatch):
    import data_agent.arcpy_mcp_client as client_module

    events = []
    exit_started = asyncio.Event()
    release_exit = asyncio.Event()
    sessions = [FakeSdkSession(events), FakeSdkSession(events)]
    http_contexts = []
    transport_contexts = []

    def make_http_client(**kwargs):
        context = FakeContext("http", object(), events)
        http_contexts.append(context)
        return context

    def make_transport(url, *, http_client, terminate_on_close=True):
        value = ("read", "write", lambda: None)
        if not transport_contexts:
            context = BlockingExitContext(
                "transport", value, events, exit_started, release_exit
            )
        else:
            context = FakeContext("transport", value, events)
        transport_contexts.append(context)
        return context

    monkeypatch.setattr(
        client_module.httpx,
        "AsyncClient",
        MagicMock(side_effect=make_http_client),
    )
    monkeypatch.setattr(
        client_module,
        "streamable_http_client",
        MagicMock(side_effect=make_transport),
    )
    monkeypatch.setattr(
        client_module,
        "ClientSession",
        MagicMock(side_effect=sessions),
    )
    return SimpleNamespace(
        events=events,
        exit_started=exit_started,
        release_exit=release_exit,
        sessions=sessions,
        http_contexts=http_contexts,
        transport_contexts=transport_contexts,
    )


async def _cancel_and_consume(task):
    if not task.done():
        task.cancel()
    try:
        await task
    except BaseException:
        pass


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
async def test_session_contexts_exit_in_the_same_owner_task(monkeypatch):
    import data_agent.arcpy_mcp_client as client_module

    events = []
    http_context = TaskAffineContext("http", object(), events)
    transport_context = TaskAffineContext(
        "transport", ("read", "write", lambda: None), events
    )
    session = FakeSdkSession(events)
    session_context = TaskAffineContext("session", session, events)
    monkeypatch.setattr(
        client_module.httpx,
        "AsyncClient",
        MagicMock(return_value=http_context),
    )
    monkeypatch.setattr(
        client_module,
        "streamable_http_client",
        MagicMock(return_value=transport_context),
    )
    monkeypatch.setattr(
        client_module,
        "ClientSession",
        MagicMock(return_value=session_context),
    )
    monkeypatch.setenv("ARCPY_CLIENT_TEST_TOKEN", "fixture-affinity-credential")
    client = ArcPyMcpClient(
        McpServerConfig(
            name="arcpy",
            url="https://service.example/mcp",
            bearer_token_env_var="ARCPY_CLIENT_TEST_TOKEN",
        )
    )

    await client.connect()
    close_task = asyncio.create_task(client.close())
    await close_task

    assert http_context.affinity_violation is False
    assert transport_context.affinity_violation is False
    assert session_context.affinity_violation is False
    assert http_context.exit_count == 1
    assert transport_context.exit_count == 1
    assert session_context.exit_count == 1


@pytest.mark.asyncio
async def test_close_maps_sensitive_owner_cleanup_failure_and_remains_idempotent(
    monkeypatch,
):
    import data_agent.arcpy_mcp_client as client_module
    from data_agent.mcp_transport import current_runtime_secrets

    credential = "fixture-cleanup-runtime-credential"
    private_url = "https://10.1.2.3/private/service"
    ca_path = "/private/ca bundles/root.pem"
    events = []
    http_context = TaskAffineContext("http", object(), events)
    transport_context = SensitiveFailingExitContext(
        "transport",
        ("read", "write", lambda: None),
        events,
        f"Authorization: Bearer {credential} {private_url} {ca_path}",
    )
    session = FakeSdkSession(events)
    monkeypatch.setattr(
        client_module.httpx,
        "AsyncClient",
        MagicMock(return_value=http_context),
    )
    monkeypatch.setattr(
        client_module,
        "streamable_http_client",
        MagicMock(return_value=transport_context),
    )
    monkeypatch.setattr(
        client_module,
        "ClientSession",
        MagicMock(return_value=session),
    )
    monkeypatch.setenv("ARCPY_CLIENT_TEST_TOKEN", credential)
    client = ArcPyMcpClient(
        McpServerConfig(
            name="arcpy",
            url="https://service.example/mcp",
            bearer_token_env_var="ARCPY_CLIENT_TEST_TOKEN",
        )
    )
    await client.connect()

    with pytest.raises(ArcPyMcpError) as exc_info:
        await client.close()

    error = exc_info.value
    assert error.code == "ARCPY_MCP_UNREACHABLE"
    assert str(error) == "ArcPy MCP service is unreachable"
    assert credential not in repr(error)
    assert private_url not in repr(error)
    assert ca_path not in repr(error)
    assert current_runtime_secrets() == ()
    assert client._session is None
    assert client._stack is None
    await client.close()


@pytest.mark.asyncio
async def test_close_from_foreign_running_owner_loop(monkeypatch):
    events = []
    session = FakeSdkSession(events)
    sdk = _install_fake_sdk(monkeypatch, [session])
    monkeypatch.setenv("ARCPY_CLIENT_TEST_TOKEN", "fixture-running-loop-credential")
    owner_loop = asyncio.new_event_loop()
    loop_started = threading.Event()

    def run_loop():
        asyncio.set_event_loop(owner_loop)
        loop_started.set()
        owner_loop.run_forever()

    thread = threading.Thread(target=run_loop)
    thread.start()
    loop_started.wait()
    client = ArcPyMcpClient(
        McpServerConfig(
            name="arcpy",
            url="https://service.example/mcp",
            bearer_token_env_var="ARCPY_CLIENT_TEST_TOKEN",
        )
    )
    connect_future = asyncio.run_coroutine_threadsafe(client.connect(), owner_loop)
    await asyncio.to_thread(connect_future.result, 2)
    owner = client._owner_task

    try:
        await client.close()
        assert owner.done()
        assert all(not context.affinity_violation for context in sdk.http_contexts)
        assert all(
            not context.affinity_violation for context in sdk.transport_contexts
        )
    finally:
        if not owner.done():
            cleanup = asyncio.run_coroutine_threadsafe(
                _cancel_and_consume(owner), owner_loop
            )
            await asyncio.to_thread(cleanup.result, 2)
        owner_loop.call_soon_threadsafe(owner_loop.stop)
        await asyncio.to_thread(thread.join, 2)
        assert not thread.is_alive()
        owner_loop.close()


@pytest.mark.asyncio
async def test_close_from_foreign_stopped_owner_loop(monkeypatch):
    events = []
    session = FakeSdkSession(events)
    sdk = _install_fake_sdk(monkeypatch, [session])
    monkeypatch.setenv("ARCPY_CLIENT_TEST_TOKEN", "fixture-stopped-loop-credential")
    owner_loop = asyncio.new_event_loop()
    client = ArcPyMcpClient(
        McpServerConfig(
            name="arcpy",
            url="https://service.example/mcp",
            bearer_token_env_var="ARCPY_CLIENT_TEST_TOKEN",
        )
    )
    setup_errors = []

    def connect_then_stop():
        asyncio.set_event_loop(owner_loop)
        try:
            owner_loop.run_until_complete(client.connect())
        except BaseException as exc:
            setup_errors.append(exc)

    setup_thread = threading.Thread(target=connect_then_stop)
    setup_thread.start()
    await asyncio.to_thread(setup_thread.join, 2)
    assert not setup_thread.is_alive()
    assert setup_errors == []
    owner = client._owner_task

    try:
        await client.close()
        assert owner.done()
        assert all(not context.affinity_violation for context in sdk.http_contexts)
        assert all(
            not context.affinity_violation for context in sdk.transport_contexts
        )
    finally:
        if not owner.done():
            await asyncio.to_thread(
                owner_loop.run_until_complete,
                _cancel_and_consume(owner),
            )
        owner_loop.close()


@pytest.mark.asyncio
async def test_close_with_closed_owner_loop_is_sanitized_and_warning_free(
    caplog, recwarn
):
    from data_agent.mcp_transport import (
        current_runtime_secrets,
        register_runtime_secrets,
        unregister_runtime_secrets,
    )

    credential = "fixture-closed-loop-credential"
    register_runtime_secrets([credential])
    owner_loop = asyncio.new_event_loop()
    client = _client()
    client._resolved_token = credential
    client._session = SimpleNamespace(
        call_tool=AsyncMock(return_value=_result(structured={"status": "ok"}))
    )
    setup_errors = []
    pending_responses = []

    def connect_then_close_loop():
        asyncio.set_event_loop(owner_loop)
        try:
            owner_loop.run_until_complete(client.connect())
            response = owner_loop.create_future()
            response.add_done_callback(lambda future: future.cancelled())
            client._commands.put_nowait(("call", "submit_job", {}, response))
            pending_responses.append(response)
        except BaseException as exc:
            setup_errors.append(exc)
        finally:
            owner_loop.close()

    setup_thread = threading.Thread(target=connect_then_close_loop)
    setup_thread.start()
    await asyncio.to_thread(setup_thread.join, 2)
    assert not setup_thread.is_alive()
    assert setup_errors == []
    owner = client._owner_task

    try:
        with caplog.at_level("WARNING", logger="data_agent.arcpy_mcp_client"):
            await client.close()
        gc.collect()

        assert current_runtime_secrets() == ()
        assert client._owner_task is None
        assert client._owner_loop is None
        assert client._session is None
        assert client._resolved_token is None
        assert (
            pending_responses[0].cancelled()
            or not pending_responses[0].done()
        )
        assert getattr(owner, "_log_destroy_pending", False) is False
        assert not any(
            "Task was destroyed" in record.message for record in caplog.records
        )
        assert not any("coroutine" in str(warning.message) for warning in recwarn)
    finally:
        if credential in current_runtime_secrets():
            unregister_runtime_secrets([credential])
        if not owner.done():
            coroutine = owner.get_coro()
            try:
                coroutine.close()
            except BaseException:
                pass
            if hasattr(owner, "_log_destroy_pending"):
                owner._log_destroy_pending = False


@pytest.mark.asyncio
async def test_call_during_owner_cleanup_is_rejected_then_retry_uses_new_owner(
    monkeypatch,
):
    sdk = _install_blocking_exit_sdk(monkeypatch)
    monkeypatch.setenv("ARCPY_CLIENT_TEST_TOKEN", "fixture-generation-credential")
    client = ArcPyMcpClient(
        McpServerConfig(
            name="arcpy",
            url="https://service.example/mcp",
            bearer_token_env_var="ARCPY_CLIENT_TEST_TOKEN",
        )
    )
    await client.connect()
    first_owner = client._owner_task
    client._commands.put_nowait(("shutdown",))
    await sdk.exit_started.wait()

    retry_during_cleanup = asyncio.create_task(client.call_tool("get_job", {}))
    for _ in range(10):
        if retry_during_cleanup.done():
            break
        await asyncio.sleep(0)
    was_rejected = retry_during_cleanup.done()
    rejection = None
    if was_rejected:
        try:
            await retry_during_cleanup
        except ArcPyMcpError as exc:
            rejection = exc
    if not was_rejected:
        retry_during_cleanup.cancel()
        with pytest.raises(asyncio.CancelledError):
            await retry_during_cleanup

    sdk.release_exit.set()
    await first_owner
    assert was_rejected is True
    assert rejection is not None
    assert rejection.code == "ARCPY_MCP_UNREACHABLE"
    result = await client.call_tool("get_job", {})
    assert result == {"status": "ok"}
    assert client._owner_task is not first_owner
    await client.close()


@pytest.mark.asyncio
async def test_cancelled_close_waiter_recovers_after_owner_finishes(monkeypatch):
    sdk = _install_blocking_exit_sdk(monkeypatch)
    monkeypatch.setenv("ARCPY_CLIENT_TEST_TOKEN", "fixture-close-caller-credential")
    client = ArcPyMcpClient(
        McpServerConfig(
            name="arcpy",
            url="https://service.example/mcp",
            bearer_token_env_var="ARCPY_CLIENT_TEST_TOKEN",
        )
    )
    await client.connect()
    owner = client._owner_task
    close_task = asyncio.create_task(client.close())
    await sdk.exit_started.wait()
    close_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await close_task

    assert client._closing is True
    sdk.release_exit.set()
    with pytest.raises(asyncio.CancelledError):
        await owner
    await asyncio.sleep(0)

    assert client._closing is False
    assert client._owner_task is None
    await client.connect()
    await client.close()


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
async def test_cancelled_connect_caller_does_not_cancel_session_owner(monkeypatch):
    from data_agent.mcp_transport import current_runtime_secrets

    initialize_started = asyncio.Event()
    release_initialize = asyncio.Event()

    class BlockingInitializeSession(FakeSdkSession):
        async def initialize(self):
            self.initialize_count += 1
            initialize_started.set()
            await release_initialize.wait()

    session = BlockingInitializeSession([])
    sdk = _install_fake_sdk(monkeypatch, [session])
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

    assert session.exit_count == 0
    assert sdk.transport_contexts[0].exit_count == 0
    assert sdk.http_contexts[0].exit_count == 0
    assert current_runtime_secrets() == ("fixture-cancel-credential",)

    release_initialize.set()
    await client.connect()
    assert client._session is session
    await client.close()
    assert session.exit_count == 1
    assert current_runtime_secrets() == ()


@pytest.mark.asyncio
async def test_owner_cancelled_before_start_resolves_connect_waiter():
    client = _client()
    connect_task = asyncio.create_task(client.connect())
    await asyncio.sleep(0)
    owner = client._owner_task
    owner.cancel()
    await client.close()

    with pytest.raises(ArcPyMcpError) as exc_info:
        await asyncio.wait_for(connect_task, timeout=2.0)

    assert exc_info.value.code == "ARCPY_MCP_UNREACHABLE"


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
async def test_close_cancels_an_owned_call_without_deadlock():
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
    try:
        await asyncio.wait_for(close_task, timeout=2.0)
    except asyncio.TimeoutError:
        release.set()
        await close_task
        raise

    with pytest.raises(ArcPyMcpError) as exc_info:
        await call_task
    assert exc_info.value.code == "ARCPY_MCP_UNREACHABLE"
    assert client._session is None


@pytest.mark.asyncio
async def test_cancelled_call_waiter_does_not_cancel_owner_or_next_call():
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    first_completed = asyncio.Event()

    class RecordingSession:
        def __init__(self):
            self.call_tasks = []
            self.call_count = 0

        async def call_tool(self, name, arguments):
            self.call_tasks.append(asyncio.current_task())
            self.call_count += 1
            if self.call_count == 1:
                first_started.set()
                await release_first.wait()
                first_completed.set()
            return _result(structured={"call": self.call_count})

    session = RecordingSession()
    client = _client()
    client._session = session
    first_call = asyncio.create_task(client.call_tool("get_job", {}))
    await first_started.wait()
    first_call.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first_call

    release_first.set()
    await first_completed.wait()
    second = await client.call_tool("get_job", {})

    assert second == {"call": 2}
    assert session.call_tasks == [client._owner_task, client._owner_task]
    await client.close()


@pytest.mark.asyncio
async def test_cancelled_queued_call_is_not_invoked_remotely():
    first_started = asyncio.Event()
    release_first = asyncio.Event()

    class RecordingSession:
        def __init__(self):
            self.names = []

        async def call_tool(self, name, arguments):
            self.names.append(name)
            if len(self.names) == 1:
                first_started.set()
                await release_first.wait()
            return _result(structured={"name": name})

    session = RecordingSession()
    client = _client()
    client._session = session
    first_call = asyncio.create_task(client.call_tool("get_job", {}))
    await first_started.wait()
    queued_call = asyncio.create_task(client.call_tool("submit_job", {}))
    for _ in range(10):
        if client._commands.qsize() == 1:
            break
        await asyncio.sleep(0)
    assert client._commands.qsize() == 1

    queued_call.cancel()
    with pytest.raises(asyncio.CancelledError):
        await queued_call
    release_first.set()
    assert await first_call == {"name": "get_job"}
    for _ in range(10):
        await asyncio.sleep(0)

    assert session.names == ["get_job"]
    await client.close()


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
async def test_health_check_cold_cache_is_single_flight():
    calls = 0

    class HealthSession:
        async def call_tool(self, name, arguments):
            nonlocal calls
            calls += 1
            await asyncio.sleep(0)
            return _result(structured={"status": "healthy", "worker": {}})

    client = _client()
    client._session = HealthSession()

    results = await asyncio.gather(*(client.health_check() for _ in range(12)))

    assert calls == 1
    assert all(result["status"] == "healthy" for result in results)


@pytest.mark.asyncio
async def test_health_result_after_close_does_not_repopulate_cache():
    started = asyncio.Event()
    release = asyncio.Event()
    client = _client()
    client.connect = AsyncMock()

    async def delayed_call(name, arguments):
        started.set()
        await release.wait()
        return {"status": "healthy", "worker": {}}

    client.call_tool = delayed_call
    health_task = asyncio.create_task(client.health_check())
    await started.wait()
    await client.close()
    release.set()

    assert (await health_task)["status"] == "healthy"
    assert client._health_cache is None


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
async def test_capabilities_cold_cache_is_single_flight():
    calls = 0

    class CapabilitiesSession:
        async def call_tool(self, name, arguments):
            nonlocal calls
            calls += 1
            await asyncio.sleep(0)
            return _result(
                structured={"worker": {"extensions": {"Spatial": "Available"}}}
            )

    client = _client()
    client._session = CapabilitiesSession()

    results = await asyncio.gather(
        *(client.get_capabilities("Spatial") for _ in range(12))
    )

    assert calls == 1
    assert all(
        result["worker"]["extensions"]["Spatial"] == "Available"
        for result in results
    )


@pytest.mark.asyncio
async def test_capability_result_after_close_does_not_repopulate_cache():
    started = asyncio.Event()
    release = asyncio.Event()
    client = _client()
    client.connect = AsyncMock()

    async def delayed_call(name, arguments):
        started.set()
        await release.wait()
        return {"worker": {"extensions": {}}}

    client.call_tool = delayed_call
    capability_task = asyncio.create_task(client.get_capabilities())
    await started.wait()
    await client.close()
    release.set()

    assert "worker" in await capability_task
    assert client._capabilities_cache is None


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

"""Behavioral tests for application-level MCP startup and shutdown coordination."""

import asyncio
import gc
from unittest.mock import AsyncMock

import pytest

from data_agent.mcp_runtime import McpRuntimeCoordinator, McpRuntimeExitBridge


class FakeHub:
    def __init__(self):
        self._started = False
        self.startup = AsyncMock(side_effect=self._startup)
        self.shutdown = AsyncMock(side_effect=self._shutdown)
        self.retry_started = asyncio.Event()
        self.retry_cancelled = asyncio.Event()
        self.retry_failed_servers = AsyncMock(side_effect=self._retry)

    async def _startup(self):
        return self._started

    async def _retry(self):
        self.retry_started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            self.retry_cancelled.set()
            raise

    async def _shutdown(self):
        self._started = False


@pytest.mark.asyncio
async def test_concurrent_ensure_started_creates_one_retry_task():
    hub = FakeHub()
    coordinator = McpRuntimeCoordinator(lambda: hub, startup_timeout=0.1)

    results = await asyncio.gather(
        coordinator.ensure_started(),
        coordinator.ensure_started(),
    )
    await hub.retry_started.wait()

    assert results == [False, False]
    hub.startup.assert_awaited_once()
    hub.retry_failed_servers.assert_awaited_once()
    assert coordinator.retry_task is not None

    await coordinator.shutdown()


@pytest.mark.asyncio
async def test_completed_retry_allows_a_new_startup_and_retry_episode():
    hub = FakeHub()
    hub.retry_failed_servers.side_effect = None
    hub.retry_failed_servers.return_value = False
    coordinator = McpRuntimeCoordinator(lambda: hub, startup_timeout=0.1)

    assert await coordinator.ensure_started() is False
    first_retry = coordinator.retry_task
    assert first_retry is not None
    await first_retry
    assert coordinator.retry_task is None

    hub._started = False
    assert await coordinator.ensure_started() is False
    second_retry = coordinator.retry_task
    assert second_retry is not None
    assert second_retry is not first_retry
    await second_retry

    assert hub.startup.await_count == 2
    assert hub.retry_failed_servers.await_count == 2
    await coordinator.shutdown()


@pytest.mark.asyncio
async def test_shutdown_cancels_sleeping_retry_before_hub_shutdown():
    hub = FakeHub()
    shutdown_order = []

    async def shutdown():
        shutdown_order.append("hub")
        hub._started = False

    hub.shutdown.side_effect = shutdown
    coordinator = McpRuntimeCoordinator(lambda: hub, startup_timeout=0.1)

    assert await coordinator.ensure_started() is False
    await hub.retry_started.wait()
    await coordinator.shutdown()

    assert hub.retry_cancelled.is_set()
    assert shutdown_order == ["hub"]
    assert coordinator.retry_task is None
    assert coordinator.started is False
    assert coordinator.closing is True


@pytest.mark.asyncio
async def test_shutdown_closes_existing_arcpy_client_after_hub():
    hub = FakeHub()
    order = []
    client = type("Client", (), {})()

    async def hub_shutdown():
        order.append("hub")

    async def client_close():
        order.append("client")

    hub.shutdown.side_effect = hub_shutdown
    client.close = client_close
    coordinator = McpRuntimeCoordinator(
        lambda: hub,
        startup_timeout=0.1,
        client_getter=lambda: client,
    )

    await coordinator.shutdown()
    await coordinator.shutdown()

    assert order == ["hub", "client"]


@pytest.mark.asyncio
async def test_failed_hub_readiness_clears_coordinator_started_flag():
    hub = FakeHub()
    hub._started = True
    coordinator = McpRuntimeCoordinator(lambda: hub, startup_timeout=0.1)

    assert await coordinator.ensure_started() is True
    assert coordinator.started is True

    hub._started = False
    assert await coordinator.ensure_started() is False
    assert coordinator.started is False

    await hub.retry_started.wait()
    await coordinator.shutdown()


@pytest.mark.asyncio
async def test_shutdown_during_retry_never_marks_runtime_started():
    hub = FakeHub()
    coordinator = McpRuntimeCoordinator(lambda: hub, startup_timeout=0.1)

    await coordinator.ensure_started()
    await hub.retry_started.wait()
    shutdown_task = asyncio.create_task(coordinator.shutdown())
    await shutdown_task

    hub._started = True
    await asyncio.sleep(0)
    assert coordinator.started is False


@pytest.mark.asyncio
async def test_exit_bridge_schedules_shutdown_on_owning_loop():
    hub = FakeHub()
    coordinator = McpRuntimeCoordinator(lambda: hub, startup_timeout=0.1)
    coordinator._owning_loop = asyncio.get_running_loop()
    bridge = McpRuntimeExitBridge(coordinator)

    bridge()
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    hub.shutdown.assert_awaited_once()
    assert bridge.cleanup_handle is not None


@pytest.mark.parametrize("closed", [False, True])
def test_exit_bridge_never_awaits_retry_task_from_stopped_owner_loop(closed):
    owner_loop = asyncio.new_event_loop()
    if closed:
        owner_loop.close()

    class ForeignRetryTask:
        def __init__(self):
            self.cancel_called = False

        def done(self):
            return False

        def get_loop(self):
            return owner_loop

        def cancel(self):
            self.cancel_called = True
            if owner_loop.is_closed():
                raise RuntimeError("Event loop is closed")

        def __await__(self):
            raise AssertionError("foreign-loop task must not be awaited")

    order = []
    hub = FakeHub()

    async def hub_shutdown():
        order.append("hub")

    client = type("Client", (), {})()

    async def client_close():
        order.append("client")

    hub.shutdown.side_effect = hub_shutdown
    client.close = client_close
    coordinator = McpRuntimeCoordinator(
        lambda: hub, client_getter=lambda: client
    )
    foreign_task = ForeignRetryTask()
    coordinator._retry_task = foreign_task
    coordinator._owning_loop = owner_loop
    bridge = McpRuntimeExitBridge(coordinator)

    bridge()

    assert foreign_task.cancel_called is True
    assert order == ["hub", "client"]
    assert coordinator.shutdown_complete is True
    if not owner_loop.is_closed():
        owner_loop.close()


@pytest.mark.parametrize("closed", [False, True])
def test_exit_bridge_consumes_real_pending_retry_task_from_foreign_loop(
    closed, recwarn
):
    owner_loop = asyncio.new_event_loop()
    errors = []
    owner_loop.set_exception_handler(
        lambda loop, context: errors.append(context)
    )

    async def pending_retry():
        await asyncio.Future()

    retry_task = owner_loop.create_task(pending_retry())
    owner_loop.run_until_complete(asyncio.sleep(0))
    if closed:
        owner_loop.close()

    order = []
    hub = FakeHub()
    client = type("Client", (), {})()

    async def hub_shutdown():
        order.append("hub")

    async def client_close():
        order.append("client")

    hub.shutdown.side_effect = hub_shutdown
    client.close = client_close
    coordinator = McpRuntimeCoordinator(
        lambda: hub, client_getter=lambda: client
    )
    coordinator._retry_task = retry_task
    coordinator._owning_loop = owner_loop
    bridge = McpRuntimeExitBridge(coordinator)

    bridge()
    del retry_task
    gc.collect()

    assert coordinator.shutdown_complete is True
    assert order == ["hub", "client"]
    assert not [
        context for context in errors
        if context.get("message") == "Task was destroyed but it is pending!"
    ]
    assert not [
        warning for warning in recwarn
        if "was never awaited" in str(warning.message)
    ]
    if not owner_loop.is_closed():
        owner_loop.close()


@pytest.mark.parametrize("has_owner_loop", [False, True])
@pytest.mark.asyncio
async def test_exit_bridge_retries_after_create_task_scheduling_failure(
    monkeypatch, has_owner_loop, recwarn
):
    loop = asyncio.get_running_loop()
    hub = FakeHub()
    coordinator = McpRuntimeCoordinator(lambda: hub)
    coordinator._owning_loop = loop if has_owner_loop else None
    bridge = McpRuntimeExitBridge(coordinator)
    original_create_task = loop.create_task

    def fail_create_task(coro, *args, **kwargs):
        raise RuntimeError("create_task failed")

    monkeypatch.setattr(loop, "create_task", fail_create_task)
    bridge()
    gc.collect()

    assert bridge._called is False
    assert not [
        warning for warning in recwarn
        if "was never awaited" in str(warning.message)
    ]

    monkeypatch.setattr(loop, "create_task", original_create_task)
    bridge()
    awaitable = bridge.cleanup_handle
    if awaitable is not None:
        await asyncio.sleep(0)
        await asyncio.sleep(0)
    assert hub.shutdown.await_count == 1

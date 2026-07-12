"""Application-level MCP startup, retry, and shutdown coordination."""

from __future__ import annotations

import asyncio
import inspect
import logging
import sys
from contextlib import suppress
from typing import Callable


logger = logging.getLogger("data_agent.mcp_runtime")


def _get_existing_arcpy_client():
    """Return an already-created ArcPy client without constructing one."""
    for module_name in (
        "data_agent.arcpy_mcp_client",
        "data_agent.toolsets.arcpy_mcp_toolset",
    ):
        module = sys.modules.get(module_name)
        if module is None:
            continue
        for attribute in (
            "_arcpy_mcp_client",
            "_arcpy_client",
            "_client",
            "_ARCPY_MCP_CLIENT",
        ):
            client = getattr(module, attribute, None)
            if client is not None:
                return client
    return None


class McpRuntimeCoordinator:
    """Own one process-bounded MCP startup/retry lifecycle."""

    def __init__(
        self,
        hub_getter: Callable,
        startup_timeout: float = 15.0,
        client_getter: Callable | None = None,
    ):
        self._hub_getter = hub_getter
        self._client_getter = client_getter or _get_existing_arcpy_client
        self._startup_timeout = startup_timeout
        self._started = False
        self._closing = False
        self._retry_started = False
        self._retry_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._shutdown_lock = asyncio.Lock()
        self._shutdown_complete = False
        self._owning_loop: asyncio.AbstractEventLoop | None = None

    @property
    def started(self) -> bool:
        return self._started

    @property
    def closing(self) -> bool:
        return self._closing

    @property
    def shutdown_complete(self) -> bool:
        return self._shutdown_complete

    @property
    def retry_task(self):
        return self._retry_task

    @property
    def owning_loop(self):
        return self._owning_loop

    async def ensure_started(self) -> bool:
        """Start the Hub once and schedule at most one bounded retry task."""
        if self._closing:
            return False
        self._owning_loop = asyncio.get_running_loop()
        hub = self._hub_getter()
        if self._started and hub._started:
            return True
        self._started = False

        async with self._lock:
            if self._closing:
                return False
            if self._started and hub._started:
                return True
            self._started = False
            if self._retry_task is not None:
                return False

            startup_succeeded = False
            try:
                startup_succeeded = bool(await asyncio.wait_for(
                    hub.startup(), timeout=self._startup_timeout
                ))
            except asyncio.TimeoutError:
                logger.warning("MCP Hub startup timed out; scheduling bounded retry")
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("MCP Hub startup failed; scheduling bounded retry")

            if self._closing:
                return False
            if startup_succeeded and hub._started:
                self._started = True
                return True

            if not self._retry_started:
                self._retry_started = True
                self._retry_task = asyncio.create_task(
                    self._run_retry(), name="mcp-hub-startup-retry"
                )
            return False

    async def _run_retry(self):
        try:
            retry_succeeded = await self._hub_getter().retry_failed_servers()
            if (
                retry_succeeded
                and not self._closing
                and self._hub_getter()._started
            ):
                self._started = True
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("MCP Hub background retry failed")

    async def shutdown(self):
        """Cancel retry activity before closing Hub-owned connections."""
        async with self._shutdown_lock:
            if self._shutdown_complete:
                return
            self._closing = True
            self._started = False
            retry_task = self._retry_task
            if retry_task is not None and not retry_task.done():
                retry_task.cancel()
                with suppress(asyncio.CancelledError):
                    await retry_task
            self._retry_task = None
            await self._hub_getter().shutdown()
            client = self._client_getter()
            close = getattr(client, "close", None) if client is not None else None
            if close is not None:
                try:
                    result = close()
                    if inspect.isawaitable(result):
                        await result
                except Exception:
                    logger.warning("ArcPy MCP client shutdown cleanup failed")
            self._shutdown_complete = True


class McpRuntimeExitBridge:
    """Idempotent synchronous fallback that delegates runtime shutdown."""

    def __init__(self, coordinator: McpRuntimeCoordinator):
        self._coordinator = coordinator
        self._called = False
        self.cleanup_handle = None

    def __call__(self):
        if self._called:
            return
        self._called = True
        if self._coordinator.shutdown_complete:
            return

        owning_loop = self._coordinator.owning_loop
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        if owning_loop is not None and owning_loop.is_running():
            if owning_loop is running_loop:
                self.cleanup_handle = owning_loop.create_task(
                    self._coordinator.shutdown()
                )
            else:
                self.cleanup_handle = asyncio.run_coroutine_threadsafe(
                    self._coordinator.shutdown(), owning_loop
                )
        elif running_loop is not None:
            self.cleanup_handle = running_loop.create_task(
                self._coordinator.shutdown()
            )
        else:
            asyncio.run(self._coordinator.shutdown())

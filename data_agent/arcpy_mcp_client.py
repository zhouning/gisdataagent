"""Persistent client for the private ArcPy MCP service."""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import re
import threading
import time
from contextlib import AsyncExitStack
from datetime import timedelta
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from data_agent.mcp_transport import (
    McpConfigurationError,
    build_httpx_client_factory,
    current_runtime_secrets,
    install_runtime_secret_log_filter,
    redact_mcp_text,
    register_runtime_secrets,
    resolve_ca_bundle,
    resolve_secret_reference,
    unregister_runtime_secrets,
)


logger = logging.getLogger("data_agent.arcpy_mcp_client")


_PUBLIC_ERROR_MESSAGES = {
    "ARCPY_MCP_URL_MISSING": "ArcPy MCP URL is not configured",
    "ARCPY_MCP_TOKEN_MISSING": "MCP credential is not available",
    "ARCPY_MCP_CA_MISSING": "MCP CA bundle is not available",
    "ARCPY_MCP_UNREACHABLE": "ArcPy MCP service is unreachable",
    "ARCPY_TOOL_NOT_ALLOWED": "Requested ArcPy MCP tool is not allowed",
    "ARCPY_JOB_FAILED": "ArcPy MCP tool reported a failure",
    "ARCPY_RESPONSE_INVALID": "ArcPy MCP response is invalid",
    "ARCPY_WORKER_UNAVAILABLE": "ArcPy worker is unavailable",
    "ARCPY_INVALID_ARGUMENT": "Required extension is invalid",
    "ARCPY_EXTENSION_UNAVAILABLE": "Required ArcPy extension is unavailable",
}
_SAFE_DETAIL_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,63}$")


def _sanitize_detail_key(key: Any) -> str:
    if not isinstance(key, str) or _SAFE_DETAIL_KEY_RE.fullmatch(key) is None:
        return "[REDACTED]"
    if any(secret and secret in key for secret in current_runtime_secrets()):
        return "[REDACTED]"
    return key


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, str):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {
            _sanitize_detail_key(key): _sanitize_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_sanitize_value(item) for item in value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return "[REDACTED]"


class ArcPyMcpError(RuntimeError):
    """ArcPy MCP failure with a stable machine-readable code."""

    def __init__(
        self, code: str, message: str, details: dict | None = None
    ) -> None:
        super().__init__(_PUBLIC_ERROR_MESSAGES.get(code, "[REDACTED]"))
        self.code = code
        self.details = _sanitize_value(dict(details or {}))


class ArcPyMcpClient:
    """Persistent official MCP SDK session for the private ArcPy service."""

    allowed_tools = frozenset(
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

    def __init__(self, config, *, clock=time.monotonic) -> None:
        self._config = config
        self._clock = clock
        self._thread_lock = threading.RLock()
        self._worker_thread: threading.Thread | None = None
        self._worker_loop: asyncio.AbstractEventLoop | None = None
        self._worker_started: threading.Event | None = None
        self._worker_start_error: BaseException | None = None
        self._worker_closing = False
        self._shutdown_future = None
        self._session = None
        self._resolved_token: str | None = None
        self._stack: AsyncExitStack | None = None
        self._owner_task: asyncio.Task | None = None
        self._owner_loop: asyncio.AbstractEventLoop | None = None
        self._ready: asyncio.Future | None = None
        self._commands: asyncio.Queue | None = None
        self._closing = False
        self._accepting_calls = False
        self._generation = 0
        self._health_cache: tuple[float, dict] | None = None
        self._capabilities_cache: tuple[float, dict] | None = None
        self._health_cache_lock: asyncio.Lock | None = None
        self._capabilities_cache_lock: asyncio.Lock | None = None
        self._session_close_lock: asyncio.Lock | None = None

    async def connect(self) -> None:
        await self._submit_to_worker(self._worker_connect)

    def _ensure_worker_loop(self) -> asyncio.AbstractEventLoop:
        while True:
            thread_to_join = None
            with self._thread_lock:
                thread = self._worker_thread
                loop = self._worker_loop
                if (
                    thread is not None
                    and thread.is_alive()
                    and loop is not None
                    and not self._worker_closing
                ):
                    return loop
                if thread is not None and thread.is_alive():
                    if self._worker_closing:
                        thread_to_join = thread
                    else:
                        started = self._worker_started
                else:
                    started = threading.Event()
                    thread = threading.Thread(
                        target=self._worker_thread_main,
                        args=(started,),
                        name="arcpy-mcp-worker",
                        daemon=True,
                    )
                    self._worker_thread = thread
                    self._worker_started = started
                    self._worker_start_error = None
                    self._worker_closing = False
                    self._shutdown_future = None
                    thread.start()
            if thread_to_join is not None:
                thread_to_join.join()
                continue
            started.wait()
            with self._thread_lock:
                if self._worker_start_error is not None:
                    raise ArcPyMcpError(
                        "ARCPY_MCP_UNREACHABLE",
                        "ArcPy MCP service is unreachable",
                    )
                if self._worker_loop is not None:
                    return self._worker_loop

    def _worker_thread_main(self, started: threading.Event) -> None:
        loop = None
        current_thread = threading.current_thread()
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._health_cache_lock = asyncio.Lock()
            self._capabilities_cache_lock = asyncio.Lock()
            self._session_close_lock = asyncio.Lock()
            with self._thread_lock:
                self._worker_loop = loop
                self._owner_loop = loop
            started.set()
            loop.run_forever()
        except BaseException as exc:
            with self._thread_lock:
                self._worker_start_error = exc
            started.set()
        finally:
            if loop is not None and not loop.is_closed():
                try:
                    loop.run_until_complete(self._worker_final_cleanup())
                    loop.run_until_complete(loop.shutdown_asyncgens())
                    loop.run_until_complete(loop.shutdown_default_executor())
                except BaseException:
                    logger.warning("ArcPy MCP worker cleanup failed")
                finally:
                    loop.close()
            with self._thread_lock:
                if self._worker_thread is current_thread:
                    self._worker_thread = None
                    self._worker_loop = None
                    self._owner_loop = None
                    self._worker_started = None
                    self._worker_closing = False
                    self._shutdown_future = None
                    self._health_cache_lock = None
                    self._capabilities_cache_lock = None
                    self._session_close_lock = None

    async def _worker_final_cleanup(self) -> None:
        try:
            await self._worker_close_session()
        except BaseException:
            logger.warning("ArcPy MCP session cleanup failed")
        current = asyncio.current_task()
        pending = [
            task for task in asyncio.all_tasks()
            if task is not current and not task.done()
        ]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    async def _submit_to_worker(
        self, coroutine_factory, *, cancel_on_caller_cancel: bool = True
    ):
        try:
            loop = await asyncio.to_thread(self._ensure_worker_loop)
        except asyncio.CancelledError:
            raise
        except Exception:
            raise ArcPyMcpError(
                "ARCPY_MCP_UNREACHABLE", "ArcPy MCP service is unreachable"
            ) from None

        coroutine = coroutine_factory()
        try:
            future = asyncio.run_coroutine_threadsafe(coroutine, loop)
        except Exception:
            coroutine.close()
            raise ArcPyMcpError(
                "ARCPY_MCP_UNREACHABLE", "ArcPy MCP service is unreachable"
            ) from None
        wrapped = asyncio.wrap_future(future)
        try:
            if cancel_on_caller_cancel:
                return await wrapped
            return await asyncio.shield(wrapped)
        except asyncio.CancelledError:
            if cancel_on_caller_cancel:
                future.cancel()
            else:
                future.add_done_callback(self._consume_concurrent_future)
            raise
        except ArcPyMcpError:
            raise
        except Exception:
            raise ArcPyMcpError(
                "ARCPY_MCP_UNREACHABLE", "ArcPy MCP service is unreachable"
            ) from None

    @staticmethod
    def _consume_concurrent_future(future) -> None:
        try:
            future.exception()
        except BaseException:
            pass

    async def _worker_connect(self) -> None:
        if self._closing:
            raise ArcPyMcpError(
                "ARCPY_MCP_UNREACHABLE", "ArcPy MCP service is unreachable"
            )
        owner = self._owner_task
        if owner is None or owner.done():
            seed_session = self._session if owner is None else None
            commands = asyncio.Queue()
            ready = asyncio.get_running_loop().create_future()
            ready.add_done_callback(self._consume_future)
            owner = asyncio.create_task(
                self._session_owner(ready, commands, seed_session),
                name="arcpy-mcp-session-owner",
            )
            owner.add_done_callback(
                lambda task, waiter=ready: self._owner_finished(task, waiter)
            )
            self._owner_task = owner
            self._ready = ready
            self._commands = commands
            self._accepting_calls = False
            self._generation += 1
        await asyncio.shield(self._ready)

    @staticmethod
    def _consume_future(future) -> None:
        try:
            future.exception()
        except BaseException:
            pass

    def _owner_finished(self, owner, ready) -> None:
        if not ready.done():
            ready.set_exception(
                ArcPyMcpError(
                    "ARCPY_MCP_UNREACHABLE", "ArcPy MCP service is unreachable"
                )
            )
        should_stop_idle_worker = self._owner_task is owner and not self._worker_closing
        self._finalize_owner(owner)
        self._consume_future(owner)
        if should_stop_idle_worker:
            with self._thread_lock:
                self._worker_closing = True
                loop = self._worker_loop
            if loop is not None:
                loop.call_soon(loop.stop)

    def _finalize_owner(self, owner) -> None:
        if self._owner_task is not owner:
            return
        self._accepting_calls = False
        self._owner_task = None
        self._ready = None
        self._commands = None
        self._closing = False
        self._generation += 1
        self._clear_runtime_state()

    @staticmethod
    def _connection_failure(exc: BaseException, token: str | None):
        if isinstance(exc, ArcPyMcpError):
            return exc
        if isinstance(exc, McpConfigurationError):
            return ArcPyMcpError(exc.code, str(exc))
        if isinstance(exc, asyncio.CancelledError):
            return exc
        if isinstance(exc, Exception):
            redact_mcp_text(str(exc), [token or ""])
            return ArcPyMcpError(
                "ARCPY_MCP_UNREACHABLE", "ArcPy MCP service is unreachable"
            )
        return exc

    async def _session_owner(
        self,
        ready: asyncio.Future,
        commands: asyncio.Queue,
        seed_session,
    ) -> None:
        stack = AsyncExitStack()
        token = self._resolved_token if seed_session is not None else None
        session = seed_session
        failure = None

        if session is None:
            try:
                if not str(self._config.url).strip():
                    raise ArcPyMcpError(
                        "ARCPY_MCP_URL_MISSING",
                        "ArcPy MCP URL is not configured",
                    )
                token = resolve_secret_reference(
                    self._config.bearer_token_env_var,
                    self._config.bearer_token_file_env_var,
                )
                register_runtime_secrets([token])
                stack.callback(unregister_runtime_secrets, [token])
                install_runtime_secret_log_filter()
                headers = {"Authorization": f"Bearer {token}"}
                if self._config.ca_bundle_env_var:
                    ca_bundle = resolve_ca_bundle(self._config.ca_bundle_env_var)
                    client_context = build_httpx_client_factory(ca_bundle)(
                        headers=headers,
                        timeout=self._config.timeout,
                    )
                else:
                    client_context = httpx.AsyncClient(
                        headers=headers,
                        timeout=self._config.timeout,
                        follow_redirects=True,
                    )
                http_client = await stack.enter_async_context(client_context)
                transport_context = streamable_http_client(
                    self._config.url,
                    http_client=http_client,
                )
                read_stream, write_stream, _ = await stack.enter_async_context(
                    transport_context
                )
                session = await stack.enter_async_context(
                    ClientSession(
                        read_stream,
                        write_stream,
                        read_timeout_seconds=timedelta(
                            seconds=self._config.timeout
                        ),
                    )
                )
                await session.initialize()
            except BaseException as exc:
                failure = self._connection_failure(exc, token)

        if failure is not None:
            cleanup_failure = None
            try:
                await stack.aclose()
            except BaseException as exc:
                cleanup_failure = exc
            finally:
                self._clear_runtime_state()

            public_failure = failure
            if not isinstance(public_failure, ArcPyMcpError):
                public_failure = ArcPyMcpError(
                    "ARCPY_MCP_UNREACHABLE",
                    "ArcPy MCP service is unreachable",
                )
            if cleanup_failure is not None:
                public_failure = ArcPyMcpError(
                    "ARCPY_MCP_UNREACHABLE",
                    "ArcPy MCP service is unreachable",
                )
            if not ready.done():
                ready.set_exception(public_failure)
            if cleanup_failure is not None:
                raise public_failure
            if isinstance(failure, asyncio.CancelledError):
                raise failure
            if not isinstance(failure, Exception):
                raise failure
            return

        self._stack = stack if seed_session is None else None
        self._session = session
        self._resolved_token = token
        if self._owner_task is asyncio.current_task():
            self._accepting_calls = True
        if not ready.done():
            ready.set_result(None)

        active_response = None
        try:
            while True:
                command = await commands.get()
                kind = command[0]
                if kind == "shutdown":
                    return
                _, name, arguments, response = command
                if response.cancelled():
                    continue
                active_response = response
                try:
                    result = await self._invoke_tool(name, arguments)
                except asyncio.CancelledError:
                    raise
                except ArcPyMcpError as exc:
                    if not response.done():
                        response.set_exception(exc)
                except Exception:
                    if not response.done():
                        response.set_exception(
                            ArcPyMcpError(
                                "ARCPY_MCP_UNREACHABLE",
                                "ArcPy MCP service is unreachable",
                            )
                        )
                else:
                    if not response.done():
                        response.set_result(result)
                active_response = None
        finally:
            if self._owner_task is asyncio.current_task():
                self._accepting_calls = False
            closed_error = ArcPyMcpError(
                "ARCPY_MCP_UNREACHABLE", "ArcPy MCP service is unreachable"
            )
            if active_response is not None and not active_response.done():
                active_response.set_exception(closed_error)
            while not commands.empty():
                command = commands.get_nowait()
                if command[0] == "call" and not command[3].done():
                    command[3].set_exception(closed_error)
            cleanup_failure = None
            try:
                if seed_session is None:
                    await stack.aclose()
            except BaseException:
                cleanup_failure = ArcPyMcpError(
                    "ARCPY_MCP_UNREACHABLE",
                    "ArcPy MCP service is unreachable",
                )
            finally:
                self._clear_runtime_state()
            if cleanup_failure is not None:
                raise cleanup_failure

    def _clear_runtime_state(self) -> None:
        self._stack = None
        self._session = None
        self._resolved_token = None
        self._clear_caches()

    def _clear_caches(self) -> None:
        self._health_cache = None
        self._capabilities_cache = None

    async def close(self) -> None:
        with self._thread_lock:
            thread = self._worker_thread
            loop = self._worker_loop
            shutdown_future = self._shutdown_future
            if thread is None:
                self._clear_runtime_state()
                return
            if loop is None:
                thread_to_join = thread
            else:
                thread_to_join = None
                if shutdown_future is None:
                    coroutine = self._worker_close_session()
                    try:
                        shutdown_future = asyncio.run_coroutine_threadsafe(
                            coroutine, loop
                        )
                    except Exception:
                        coroutine.close()
                        raise ArcPyMcpError(
                            "ARCPY_MCP_UNREACHABLE",
                            "ArcPy MCP service is unreachable",
                        ) from None
                    self._shutdown_future = shutdown_future
                    self._worker_closing = True

        if thread_to_join is not None:
            await asyncio.to_thread(thread_to_join.join)
            return

        wrapped = asyncio.wrap_future(shutdown_future)
        try:
            await asyncio.shield(wrapped)
        except asyncio.CancelledError:
            shutdown_future.add_done_callback(
                lambda future: self._request_worker_stop(loop)
            )
            raise
        except ArcPyMcpError as exc:
            error = exc
        except Exception:
            error = ArcPyMcpError(
                "ARCPY_MCP_UNREACHABLE", "ArcPy MCP service is unreachable"
            )
        else:
            error = None

        self._request_worker_stop(loop)
        await asyncio.to_thread(thread.join)
        if error is not None:
            raise error

    @staticmethod
    def _request_worker_stop(loop: asyncio.AbstractEventLoop) -> None:
        try:
            loop.call_soon_threadsafe(loop.stop)
        except RuntimeError:
            pass

    async def _worker_close_session(self) -> None:
        close_lock = self._session_close_lock
        if close_lock is None:
            self._clear_runtime_state()
            return
        async with close_lock:
            owner = self._owner_task
            if owner is None:
                self._generation += 1
                self._clear_runtime_state()
                return
            if not self._closing and not owner.done():
                self._closing = True
                self._generation += 1
                self._clear_caches()
                if self._commands is not None:
                    self._commands.put_nowait(("shutdown",))
                owner.cancel()

        try:
            await asyncio.shield(owner)
        except asyncio.CancelledError:
            if not owner.cancelled():
                raise
        self._finalize_owner(owner)

    @staticmethod
    def _result_attribute(result, camel_case: str, snake_case: str, default=None):
        if hasattr(result, camel_case):
            return getattr(result, camel_case)
        return getattr(result, snake_case, default)

    @staticmethod
    def _result_text(result) -> str:
        parts = []
        for item in getattr(result, "content", ()) or ():
            text = getattr(item, "text", None)
            if isinstance(text, str):
                parts.append(text)
        return "\n".join(parts)

    def _sanitized_result_text(self, result) -> str:
        return redact_mcp_text(
            self._result_text(result), [self._resolved_token or ""]
        )

    async def call_tool(self, name: str, arguments: dict) -> dict:
        if name not in self.allowed_tools:
            raise ArcPyMcpError(
                "ARCPY_TOOL_NOT_ALLOWED",
                "Requested ArcPy MCP tool is not allowed",
            )
        return await self._submit_to_worker(
            lambda: self._worker_call_tool(name, arguments)
        )

    async def _worker_call_tool(self, name: str, arguments: dict) -> dict:
        await self._worker_connect()
        owner = self._owner_task
        commands = self._commands
        if (
            self._closing
            or owner is None
            or owner.done()
            or commands is None
            or not self._accepting_calls
        ):
            raise ArcPyMcpError(
                "ARCPY_MCP_UNREACHABLE", "ArcPy MCP service is unreachable"
            )
        response = asyncio.get_running_loop().create_future()
        response.add_done_callback(self._consume_future)
        commands.put_nowait(("call", name, arguments, response))
        try:
            return await asyncio.shield(response)
        except asyncio.CancelledError:
            response.cancel()
            raise

    async def _invoke_tool(self, name: str, arguments: dict) -> dict:
        transport_message = None
        try:
            result = await self._session.call_tool(name, arguments)
        except Exception as exc:
            transport_message = redact_mcp_text(
                str(exc), [self._resolved_token or ""]
            )
        if transport_message is not None:
            raise ArcPyMcpError(
                "ARCPY_MCP_UNREACHABLE", "ArcPy MCP service is unreachable"
            )

        is_error = self._result_attribute(result, "isError", "is_error", False)
        if is_error:
            self._sanitized_result_text(result)
            raise ArcPyMcpError(
                "ARCPY_JOB_FAILED", "ArcPy MCP tool reported a failure"
            )

        structured = self._result_attribute(
            result, "structuredContent", "structured_content"
        )
        if structured is not None:
            if not isinstance(structured, dict):
                raise ArcPyMcpError(
                    "ARCPY_RESPONSE_INVALID", "ArcPy MCP response is invalid"
                )
            return dict(structured)

        text = self._result_text(result)
        try:
            payload = json.loads(text)
        except (TypeError, ValueError):
            payload = None
        if not isinstance(payload, dict):
            raise ArcPyMcpError(
                "ARCPY_RESPONSE_INVALID", "ArcPy MCP response is invalid"
            )
        return payload

    def _cached(self, cache: tuple[float, dict] | None) -> dict | None:
        if cache is None:
            return None
        cached_at, value = cache
        if self._clock() - cached_at >= 30.0:
            return None
        return copy.deepcopy(value)

    async def health_check(self) -> dict:
        return await self._submit_to_worker(
            self._worker_health_check,
            cancel_on_caller_cancel=False,
        )

    async def _worker_health_check(self) -> dict:
        cached = self._cached(self._health_cache)
        if cached is not None:
            return cached

        async with self._health_cache_lock:
            cached = self._cached(self._health_cache)
            if cached is not None:
                return cached
            await self._worker_connect()
            generation = self._generation
            result = await self._worker_call_tool("health_check", {})
            if result.get("status") != "healthy" or not isinstance(
                result.get("worker"), dict
            ):
                raise ArcPyMcpError(
                    "ARCPY_WORKER_UNAVAILABLE", "ArcPy worker is unavailable"
                )
            if generation == self._generation and self._accepting_calls:
                self._health_cache = (self._clock(), copy.deepcopy(result))
            return copy.deepcopy(result)

    @staticmethod
    def _normalize_extension(required_extension: str | None) -> str | None:
        if required_extension is None:
            return None
        if not isinstance(required_extension, str):
            raise ArcPyMcpError(
                "ARCPY_INVALID_ARGUMENT", "Required extension is invalid"
            )
        normalized = "".join(
            character for character in required_extension.lower()
            if character.isalnum()
        )
        aliases = {
            "spatial": "Spatial",
            "spatialanalyst": "Spatial",
            "imageanalyst": "ImageAnalyst",
        }
        try:
            return aliases[normalized]
        except KeyError:
            raise ArcPyMcpError(
                "ARCPY_INVALID_ARGUMENT", "Required extension is invalid"
            ) from None

    async def get_capabilities(
        self, required_extension: str | None = None
    ) -> dict:
        extension = self._normalize_extension(required_extension)
        return await self._submit_to_worker(
            lambda: self._worker_get_capabilities(extension),
            cancel_on_caller_cancel=False,
        )

    async def _worker_get_capabilities(self, extension: str | None) -> dict:
        result = self._cached(self._capabilities_cache)
        if result is None:
            async with self._capabilities_cache_lock:
                result = self._cached(self._capabilities_cache)
                if result is None:
                    await self._worker_connect()
                    generation = self._generation
                    result = await self._worker_call_tool(
                        "get_capabilities", {}
                    )
                    if generation == self._generation and self._accepting_calls:
                        self._capabilities_cache = (
                            self._clock(),
                            copy.deepcopy(result),
                        )

        if extension is not None:
            worker = result.get("worker")
            extensions = worker.get("extensions") if isinstance(worker, dict) else None
            if (
                not isinstance(extensions, dict)
                or extensions.get(extension) != "Available"
            ):
                raise ArcPyMcpError(
                    "ARCPY_EXTENSION_UNAVAILABLE",
                    "Required ArcPy extension is unavailable",
                )
        return copy.deepcopy(result)

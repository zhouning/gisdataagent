"""Persistent client for the private ArcPy MCP service."""

from __future__ import annotations

import asyncio
import copy
import json
import time
from contextlib import AsyncExitStack, suppress
from datetime import timedelta
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from data_agent.mcp_transport import (
    McpConfigurationError,
    build_httpx_client_factory,
    install_runtime_secret_log_filter,
    redact_mcp_text,
    register_runtime_secrets,
    resolve_ca_bundle,
    resolve_secret_reference,
    unregister_runtime_secrets,
)


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact_mcp_text(value)
    if isinstance(value, dict):
        return {
            redact_mcp_text(str(key)): _sanitize_value(item)
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
        super().__init__(redact_mcp_text(message))
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
        self._session = None
        self._resolved_token: str | None = None
        self._stack: AsyncExitStack | None = None
        self._lock = asyncio.Lock()
        self._clock = clock
        self._health_cache: tuple[float, dict] | None = None
        self._capabilities_cache: tuple[float, dict] | None = None

    async def connect(self) -> None:
        async with self._lock:
            await self._connect_locked()

    async def _connect_locked(self) -> None:
        if self._session is not None:
            return
        if not str(self._config.url).strip():
            raise ArcPyMcpError(
                "ARCPY_MCP_URL_MISSING", "ArcPy MCP URL is not configured"
            )

        stack = AsyncExitStack()
        token = None
        session = None
        failure = None
        try:
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
                    read_timeout_seconds=timedelta(seconds=self._config.timeout),
                )
            )
            await session.initialize()
        except BaseException as exc:
            if isinstance(exc, McpConfigurationError):
                failure = ArcPyMcpError(exc.code, str(exc))
            elif isinstance(exc, Exception):
                redact_mcp_text(str(exc), [token or ""])
                failure = ArcPyMcpError(
                    "ARCPY_MCP_UNREACHABLE",
                    "ArcPy MCP service is unreachable",
                )
            else:
                failure = exc

        if failure is not None:
            with suppress(Exception):
                await stack.aclose()
            self._clear_runtime_state()
            raise failure

        self._stack = stack
        self._session = session
        self._resolved_token = token

    def _clear_runtime_state(self) -> None:
        self._stack = None
        self._session = None
        self._resolved_token = None
        self._health_cache = None
        self._capabilities_cache = None

    async def close(self) -> None:
        async with self._lock:
            stack = self._stack
            try:
                if stack is not None:
                    with suppress(Exception):
                        await stack.aclose()
            finally:
                self._clear_runtime_state()

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

        async with self._lock:
            await self._connect_locked()
            return await self._call_tool_locked(name, arguments)

    async def _call_tool_locked(self, name: str, arguments: dict) -> dict:
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
        cached = self._cached(self._health_cache)
        if cached is not None:
            return cached

        result = await self.call_tool("health_check", {})
        if result.get("status") != "healthy" or not isinstance(
            result.get("worker"), dict
        ):
            raise ArcPyMcpError(
                "ARCPY_WORKER_UNAVAILABLE", "ArcPy worker is unavailable"
            )
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
        result = self._cached(self._capabilities_cache)
        if result is None:
            result = await self.call_tool("get_capabilities", {})
            self._capabilities_cache = (self._clock(), copy.deepcopy(result))

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

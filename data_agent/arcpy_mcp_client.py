"""Persistent client for the private ArcPy MCP service."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import logging
import os
import re
import tempfile
import threading
import time
import zipfile
from contextlib import AsyncExitStack
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any
from urllib.parse import urlparse

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from data_agent.mcp_transport import (
    McpConfigurationError,
    RuntimeSecretRedactionFilter,
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
_SIGNED_TRANSFER_LOG_FILTER = RuntimeSecretRedactionFilter()


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
    "ARCPY_INPUT_NOT_FOUND": "ArcPy input dataset was not found",
    "ARCPY_INPUT_INVALID": "ArcPy input dataset is invalid",
    "ARCPY_INPUT_OUTSIDE_SANDBOX": "ArcPy input dataset is outside the user sandbox",
    "ARCPY_INPUT_INCOMPLETE": "ArcPy input dataset is incomplete",
    "ARCPY_INPUT_PACKAGE_FAILED": "ArcPy input dataset could not be packaged",
    "ARCPY_UPLOAD_FAILED": "ArcPy artifact upload failed",
    "ARCPY_UPLOAD_VERIFICATION_FAILED": "ArcPy artifact upload verification failed",
    "ARCPY_INSPECTION_FAILED": "ArcPy dataset inspection failed",
    "ARCPY_JOB_TIMED_OUT": "ArcPy job timed out",
}
_SAFE_DETAIL_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,63}$")


@dataclass(frozen=True)
class PreparedLocalUpload:
    upload_path: Path
    source_path: Path
    logical_name: str
    media_type: str
    size: int
    sha256: str
    delete_after_upload: bool


@dataclass(frozen=True)
class UploadedArtifact:
    artifact_id: str
    artifact_path: str
    source_path: Path
    local_package_path: Path
    delete_local_package: bool


def _input_error(code: str) -> ArcPyMcpError:
    return ArcPyMcpError(code, _PUBLIC_ERROR_MESSAGES[code])


def _has_unsafe_caller_syntax(path: str) -> bool:
    if not path or "\x00" in path:
        return True
    if re.match(r"^[A-Za-z]:[\\/]", path) or path.startswith("\\\\"):
        return True
    if path.startswith("//"):
        return True
    normalized_parts = path.replace("\\", "/").split("/")
    windows_path = PureWindowsPath(path)
    return (
        ".." in normalized_parts
        or windows_path.is_absolute()
        or bool(windows_path.drive)
    )


def _resolve_local_input(path: str | os.PathLike[str]) -> Path:
    from data_agent import gis_processors, user_context

    caller_path = os.fspath(path)
    if _has_unsafe_caller_syntax(caller_path):
        raise _input_error("ARCPY_INPUT_OUTSIDE_SANDBOX")
    direct_candidate = Path(caller_path)
    user_candidate = Path(user_context.get_user_upload_dir()) / caller_path
    if direct_candidate.is_symlink() or user_candidate.is_symlink():
        raise _input_error("ARCPY_INPUT_OUTSIDE_SANDBOX")
    try:
        resolved_candidate = Path(gis_processors._resolve_path(caller_path))
    except Exception:
        raise _input_error("ARCPY_INPUT_NOT_FOUND") from None
    if not resolved_candidate.exists():
        raise _input_error("ARCPY_INPUT_NOT_FOUND")
    if resolved_candidate.is_symlink():
        raise _input_error("ARCPY_INPUT_OUTSIDE_SANDBOX")
    try:
        resolved = resolved_candidate.resolve(strict=True)
    except (OSError, RuntimeError):
        raise _input_error("ARCPY_INPUT_NOT_FOUND") from None
    if not user_context.is_path_in_sandbox(str(resolved)):
        raise _input_error("ARCPY_INPUT_OUTSIDE_SANDBOX")
    return resolved


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().lower()


def _media_type(path: Path) -> str:
    return {
        ".zip": "application/zip",
        ".geojson": "application/geo+json",
        ".json": "application/json",
        ".gpkg": "application/geopackage+sqlite3",
        ".tif": "image/tiff",
        ".tiff": "image/tiff",
    }.get(path.suffix.lower(), "application/octet-stream")


_SHAPEFILE_SIDECAR_EXTENSIONS = frozenset(
    {
        ".shp",
        ".shx",
        ".dbf",
        ".prj",
        ".cpg",
        ".sbn",
        ".sbx",
        ".qix",
        ".ain",
        ".aih",
        ".ixs",
        ".mxs",
        ".atx",
        ".fbn",
        ".fbx",
        ".xml",
    }
)


def _is_shapefile_sidecar_name(name: str, stem: str) -> bool:
    normalized = name.casefold()
    exact_names = {
        f"{stem}{extension}" for extension in _SHAPEFILE_SIDECAR_EXTENSIONS
    }
    if normalized in exact_names or normalized == f"{stem}.shp.xml":
        return True
    prefix = f"{stem}."
    suffix = ".atx"
    if not normalized.startswith(prefix) or not normalized.endswith(suffix):
        return False
    field_name = normalized[len(prefix) : -len(suffix)]
    return (
        bool(field_name)
        and "/" not in field_name
        and "\\" not in field_name
    )


def _checked_archive_file(path: Path) -> Path:
    from data_agent import user_context

    if path.is_symlink():
        raise _input_error("ARCPY_INPUT_OUTSIDE_SANDBOX")
    if not path.is_file():
        raise _input_error("ARCPY_INPUT_INVALID")
    try:
        real_path = path.resolve(strict=True)
    except (OSError, RuntimeError):
        raise _input_error("ARCPY_INPUT_INVALID") from None
    if not user_context.is_path_in_sandbox(str(real_path)):
        raise _input_error("ARCPY_INPUT_OUTSIDE_SANDBOX")
    return real_path


def _new_package_path() -> Path:
    from data_agent.user_context import get_user_upload_dir

    upload_dir = Path(get_user_upload_dir()).resolve()
    upload_dir.mkdir(parents=True, exist_ok=True)
    descriptor, filename = tempfile.mkstemp(
        prefix="arcpy-input-", suffix=".zip", dir=upload_dir
    )
    os.close(descriptor)
    return Path(filename)


def _write_package(entries: list[tuple[Path, str]]) -> Path:
    package_path = _new_package_path()
    try:
        with zipfile.ZipFile(
            package_path, mode="w", compression=zipfile.ZIP_DEFLATED
        ) as archive:
            for source, archive_name in sorted(
                entries, key=lambda item: item[1].casefold()
            ):
                archive.write(source, arcname=archive_name)
        return package_path
    except Exception:
        try:
            package_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise _input_error("ARCPY_INPUT_PACKAGE_FAILED") from None


def package_local_dataset(
    path: str | os.PathLike[str],
) -> PreparedLocalUpload:
    source = _resolve_local_input(path)
    upload_path = source
    logical_name = source.name
    media_type = _media_type(source)
    delete_after_upload = False

    if source.is_dir():
        if source.suffix.lower() != ".gdb":
            raise _input_error("ARCPY_INPUT_INVALID")
        entries = []
        try:
            for root, directory_names, file_names in os.walk(
                source, followlinks=False
            ):
                root_path = Path(root)
                for name in directory_names:
                    if (root_path / name).is_symlink():
                        raise _input_error("ARCPY_INPUT_OUTSIDE_SANDBOX")
                for name in file_names:
                    item = _checked_archive_file(root_path / name)
                    relative = item.relative_to(source)
                    entries.append((item, (Path(source.name) / relative).as_posix()))
        except ArcPyMcpError:
            raise
        except Exception:
            raise _input_error("ARCPY_INPUT_PACKAGE_FAILED") from None
        if not entries:
            raise _input_error("ARCPY_INPUT_INCOMPLETE")
        upload_path = _write_package(entries)
        logical_name = f"{source.name}.zip"
        media_type = "application/zip"
        delete_after_upload = True
    elif source.is_file() and source.suffix.lower() == ".shp":
        stem = source.stem.casefold()
        candidates = [
            item
            for item in source.parent.iterdir()
            if _is_shapefile_sidecar_name(item.name, stem)
        ]
        entries = [
            (_checked_archive_file(item), item.name) for item in candidates
        ]
        packaged_names = {name.casefold() for _, name in entries}
        required_names = {
            f"{stem}{extension}"
            for extension in (".shp", ".shx", ".dbf")
        }
        if not required_names.issubset(packaged_names):
            raise _input_error("ARCPY_INPUT_INCOMPLETE")
        upload_path = _write_package(entries)
        logical_name = f"{source.stem}.zip"
        media_type = "application/zip"
        delete_after_upload = True
    elif not source.is_file():
        raise _input_error("ARCPY_INPUT_INVALID")

    try:
        size = upload_path.stat().st_size
        sha256 = _hash_file(upload_path)
    except Exception:
        if delete_after_upload:
            upload_path.unlink(missing_ok=True)
        raise _input_error("ARCPY_INPUT_PACKAGE_FAILED") from None
    return PreparedLocalUpload(
        upload_path=upload_path,
        source_path=source,
        logical_name=logical_name,
        media_type=media_type,
        size=size,
        sha256=sha256,
        delete_after_upload=delete_after_upload,
    )


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

    def __init__(
        self,
        config,
        *,
        clock=time.monotonic,
        signed_http_client_factory=httpx.AsyncClient,
        upload_timeout: float = 120.0,
        upload_attempts: int = 3,
        sleep=asyncio.sleep,
        inspection_timeout: float = 120.0,
    ) -> None:
        self._config = config
        self._clock = clock
        self._signed_http_client_factory = signed_http_client_factory
        self._upload_timeout = upload_timeout
        self._upload_attempts = max(1, int(upload_attempts))
        self._sleep = sleep
        self._inspection_timeout = inspection_timeout
        self._thread_lock = threading.RLock()
        self._worker_thread: threading.Thread | None = None
        self._worker_loop: asyncio.AbstractEventLoop | None = None
        self._worker_started: threading.Event | None = None
        self._worker_stop_requested: threading.Event | None = None
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
                        stop_requested = self._worker_stop_requested
                else:
                    started = threading.Event()
                    stop_requested = threading.Event()
                    thread = threading.Thread(
                        target=self._worker_thread_main,
                        args=(started,),
                        name="arcpy-mcp-worker",
                        daemon=True,
                    )
                    self._worker_thread = thread
                    self._worker_started = started
                    self._worker_stop_requested = stop_requested
                    self._worker_start_error = None
                    self._worker_closing = False
                    self._shutdown_future = None
                    try:
                        thread.start()
                    except BaseException as exc:
                        if self._worker_thread is thread:
                            self._worker_thread = None
                            self._worker_loop = None
                            self._owner_loop = None
                            self._worker_started = None
                            self._worker_stop_requested = None
                            self._worker_closing = False
                            self._shutdown_future = None
                            self._worker_start_error = exc
                        stop_requested.set()
                        started.set()
                        raise ArcPyMcpError(
                            "ARCPY_MCP_UNREACHABLE",
                            "ArcPy MCP service is unreachable",
                        ) from None
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
                closing = self._worker_closing or (
                    stop_requested is not None and stop_requested.is_set()
                )
                if self._worker_loop is not None and not closing:
                    return self._worker_loop
            if closing:
                if thread.ident is not None:
                    thread.join()
                raise ArcPyMcpError(
                    "ARCPY_MCP_UNREACHABLE",
                    "ArcPy MCP service is unreachable",
                )

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
                stop_requested = self._worker_stop_requested
                should_stop = self._worker_closing or (
                    stop_requested is not None and stop_requested.is_set()
                )
            started.set()
            if not should_stop:
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
                    self._worker_stop_requested = None
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
                if thread.ident is None or not thread.is_alive():
                    if self._worker_thread is thread:
                        self._worker_thread = None
                        self._worker_started = None
                        self._worker_stop_requested = None
                        self._worker_closing = False
                        self._shutdown_future = None
                    self._clear_runtime_state()
                    return
                self._worker_closing = True
                if self._worker_stop_requested is not None:
                    self._worker_stop_requested.set()
                startup_handshake = self._worker_started
                thread_to_join = thread
            else:
                startup_handshake = None
                thread_to_join = None
                if shutdown_future is None:
                    self._worker_closing = True
                    if self._worker_stop_requested is not None:
                        self._worker_stop_requested.set()
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

        if thread_to_join is not None:
            if startup_handshake is not None:
                await asyncio.to_thread(startup_handshake.wait)
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

    @staticmethod
    def _required_identifier(payload: dict, field: str) -> str:
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ArcPyMcpError(
                "ARCPY_RESPONSE_INVALID", "ArcPy MCP response is invalid"
            )
        return value.strip()

    @staticmethod
    def _validate_signed_url(value: Any) -> str:
        if isinstance(value, str) and value.strip():
            candidate = value.strip()
            try:
                parsed = urlparse(candidate)
                valid = (
                    parsed.scheme == "https"
                    and parsed.hostname is not None
                    and parsed.username is None
                    and parsed.password is None
                )
            except (TypeError, ValueError):
                valid = False
            if valid:
                return candidate
        raise ArcPyMcpError(
            "ARCPY_UPLOAD_FAILED", "ArcPy artifact upload failed"
        )

    @classmethod
    def _signed_url(cls, payload: dict) -> str:
        value = payload.get("upload_url")
        if value is None:
            value = payload.get("signed_url")
        return cls._validate_signed_url(value)

    @staticmethod
    def _validate_optional_artifact_id(
        payload: dict, artifact_id: str
    ) -> None:
        response_artifact_id = payload.get("artifact_id")
        if (
            response_artifact_id is not None
            and response_artifact_id != artifact_id
        ):
            raise ArcPyMcpError(
                "ARCPY_RESPONSE_INVALID", "ArcPy MCP response is invalid"
            )

    def _signed_http_options(self) -> dict:
        options = {"follow_redirects": True}
        if self._config.ca_bundle_env_var:
            try:
                options["verify"] = resolve_ca_bundle(
                    self._config.ca_bundle_env_var
                )
            except McpConfigurationError as exc:
                raise ArcPyMcpError(exc.code, str(exc)) from None
        return options

    @staticmethod
    def _install_signed_transfer_log_filter() -> None:
        install_runtime_secret_log_filter()
        logger_names = {"httpx", "httpcore"}
        logger_names.update(
            name
            for name, logger_object in logging.Logger.manager.loggerDict.items()
            if isinstance(logger_object, logging.Logger)
            and (name.startswith("httpx.") or name.startswith("httpcore."))
        )
        for name in logger_names:
            for handler in logging.getLogger(name).handlers:
                if _SIGNED_TRANSFER_LOG_FILTER not in handler.filters:
                    handler.addFilter(_SIGNED_TRANSFER_LOG_FILTER)

    @staticmethod
    def _signed_transfer_secrets(signed_url: str) -> set[str]:
        try:
            normalized_url = str(httpx.URL(signed_url))
        except (TypeError, ValueError):
            raise ArcPyMcpError(
                "ARCPY_UPLOAD_FAILED", "ArcPy artifact upload failed"
            ) from None
        return {signed_url, normalized_url}

    @staticmethod
    def _committed_offset(
        status: dict, artifact_id: str, expected_size: int
    ) -> int:
        response_artifact_id = status.get("artifact_id")
        if (
            response_artifact_id is not None
            and response_artifact_id != artifact_id
        ):
            raise ArcPyMcpError(
                "ARCPY_RESPONSE_INVALID", "ArcPy MCP response is invalid"
            )
        committed_size = status.get("committed_size")
        if (
            isinstance(committed_size, bool)
            or not isinstance(committed_size, int)
            or committed_size < 0
            or committed_size > expected_size
        ):
            raise ArcPyMcpError(
                "ARCPY_RESPONSE_INVALID", "ArcPy MCP response is invalid"
            )
        return committed_size

    @staticmethod
    def _verify_completed_upload(
        completion: dict,
        artifact_id: str,
        prepared: PreparedLocalUpload,
    ) -> None:
        valid = (
            completion.get("state") == "ready"
            and completion.get("artifact_id") == artifact_id
        )

        hash_values = [
            completion[field]
            for field in ("verified_sha256", "actual_sha256")
            if field in completion
        ]
        valid = valid and bool(hash_values) and all(
            isinstance(value, str)
            and value.lower() == prepared.sha256
            for value in hash_values
        )
        size_values = [
            completion[field]
            for field in ("size", "actual_size", "actual_size_bytes")
            if field in completion
        ]
        valid = valid and bool(size_values) and all(
            isinstance(value, int)
            and not isinstance(value, bool)
            and value == prepared.size
            for value in size_values
        )
        if not valid:
            raise ArcPyMcpError(
                "ARCPY_UPLOAD_VERIFICATION_FAILED",
                "ArcPy artifact upload verification failed",
            )

    async def _best_effort_delete_artifact(self, artifact_id: str) -> None:
        try:
            await self.call_tool(
                "delete_artifact", {"artifact_id": artifact_id}
            )
        except BaseException:
            pass

    async def _upload_prepared(
        self, prepared: PreparedLocalUpload
    ) -> str:
        artifact_id = None
        try:
            created = await self.call_tool(
                "create_upload",
                {
                    "logical_name": prepared.logical_name,
                    "expected_size": prepared.size,
                    "expected_sha256": prepared.sha256,
                    "media_type": prepared.media_type,
                },
            )
            artifact_id = self._required_identifier(created, "artifact_id")
            signed_url = self._signed_url(created)
            offset = 0
            uploaded = False

            async with self._signed_http_client_factory(
                **self._signed_http_options()
            ) as http_client:
                for attempt in range(self._upload_attempts):
                    try:
                        with prepared.upload_path.open("rb") as stream:
                            stream.seek(offset)
                            signed_url_secrets = self._signed_transfer_secrets(
                                signed_url
                            )
                            self._install_signed_transfer_log_filter()
                            register_runtime_secrets(signed_url_secrets)
                            try:
                                response = await http_client.put(
                                    signed_url,
                                    headers={"Upload-Offset": str(offset)},
                                    content=stream,
                                    timeout=self._upload_timeout,
                                )
                            finally:
                                unregister_runtime_secrets(
                                    signed_url_secrets
                                )
                    except httpx.RequestError:
                        if attempt + 1 >= self._upload_attempts:
                            raise ArcPyMcpError(
                                "ARCPY_UPLOAD_FAILED",
                                "ArcPy artifact upload failed",
                            ) from None
                        status = await self.call_tool(
                            "get_upload_status",
                            {"artifact_id": artifact_id},
                        )
                        offset = self._committed_offset(
                            status, artifact_id, prepared.size
                        )
                        continue
                    except ArcPyMcpError:
                        raise
                    except Exception:
                        raise ArcPyMcpError(
                            "ARCPY_UPLOAD_FAILED",
                            "ArcPy artifact upload failed",
                        ) from None

                    status_code = getattr(response, "status_code", None)
                    if isinstance(status_code, int) and 200 <= status_code < 300:
                        uploaded = True
                        break
                    if status_code in {401, 403}:
                        if attempt + 1 >= self._upload_attempts:
                            raise ArcPyMcpError(
                                "ARCPY_UPLOAD_FAILED",
                                "ArcPy artifact upload failed",
                            )
                        status = await self.call_tool(
                            "get_upload_status",
                            {"artifact_id": artifact_id},
                        )
                        offset = self._committed_offset(
                            status, artifact_id, prepared.size
                        )
                        renewed = await self.call_tool(
                            "renew_upload", {"artifact_id": artifact_id}
                        )
                        self._validate_optional_artifact_id(
                            renewed, artifact_id
                        )
                        signed_url = self._signed_url(renewed)
                        continue
                    raise ArcPyMcpError(
                        "ARCPY_UPLOAD_FAILED", "ArcPy artifact upload failed"
                    )

            if not uploaded:
                raise ArcPyMcpError(
                    "ARCPY_UPLOAD_FAILED", "ArcPy artifact upload failed"
                )
            completion = await self.call_tool(
                "complete_upload", {"artifact_id": artifact_id}
            )
            self._verify_completed_upload(completion, artifact_id, prepared)
            return artifact_id
        except BaseException:
            if artifact_id is not None:
                await self._best_effort_delete_artifact(artifact_id)
            raise

    @staticmethod
    def _artifact_relative_path(job: dict, artifact_id: str) -> str:
        response_artifact_id = job.get("artifact_id")
        if (
            response_artifact_id is not None
            and response_artifact_id != artifact_id
        ):
            raise ArcPyMcpError(
                "ARCPY_RESPONSE_INVALID", "ArcPy MCP response is invalid"
            )
        bound_to_artifact = response_artifact_id == artifact_id
        result = job.get("result")
        if not isinstance(result, dict):
            raise ArcPyMcpError(
                "ARCPY_RESPONSE_INVALID", "ArcPy MCP response is invalid"
            )
        dataset = result.get("dataset")
        if isinstance(dataset, dict):
            owner = dataset.get("artifact_id")
            if owner is not None and owner != artifact_id:
                raise ArcPyMcpError(
                    "ARCPY_RESPONSE_INVALID", "ArcPy MCP response is invalid"
                )
            bound_to_artifact = bound_to_artifact or owner == artifact_id
            value = dataset.get("path")
        else:
            owner = result.get("artifact_id")
            if owner is not None and owner != artifact_id:
                raise ArcPyMcpError(
                    "ARCPY_RESPONSE_INVALID", "ArcPy MCP response is invalid"
                )
            bound_to_artifact = bound_to_artifact or owner == artifact_id
            value = result.get("artifact_path")

        if (
            not bound_to_artifact
            or not isinstance(value, str)
            or not value
            or value == "."
        ):
            raise ArcPyMcpError(
                "ARCPY_RESPONSE_INVALID", "ArcPy MCP response is invalid"
            )
        if "\\" in value or "://" in value:
            raise ArcPyMcpError(
                "ARCPY_RESPONSE_INVALID", "ArcPy MCP response is invalid"
            )
        posix_path = PurePosixPath(value)
        windows_path = PureWindowsPath(value)
        if (
            posix_path.is_absolute()
            or windows_path.is_absolute()
            or windows_path.drive
            or ".." in posix_path.parts
            or any(part in {"", "."} for part in posix_path.parts)
        ):
            raise ArcPyMcpError(
                "ARCPY_RESPONSE_INVALID", "ArcPy MCP response is invalid"
            )
        return posix_path.as_posix()

    async def _inspect_uploaded_artifact(self, artifact_id: str) -> str:
        if not isinstance(artifact_id, str) or not artifact_id.strip():
            raise ArcPyMcpError(
                "ARCPY_RESPONSE_INVALID", "ArcPy MCP response is invalid"
            )
        inspection = await self.call_tool(
            "inspect_dataset",
            {"artifact_id": artifact_id, "path": "."},
        )
        job_id = self._required_identifier(inspection, "job_id")
        started = self._clock()
        delays = (2, 5, 10)
        attempt = 0
        terminal_failures = {
            "failed",
            "timed_out",
            "cancelled",
            "interrupted",
        }

        while True:
            delay = delays[attempt] if attempt < len(delays) else 20
            attempt += 1
            await self._sleep(delay)
            if self._clock() - started > self._inspection_timeout:
                raise ArcPyMcpError(
                    "ARCPY_JOB_TIMED_OUT", "ArcPy job timed out"
                )
            job = await self.call_tool("get_job", {"job_id": job_id})
            response_job_id = job.get("job_id")
            if response_job_id is not None and response_job_id != job_id:
                raise ArcPyMcpError(
                    "ARCPY_RESPONSE_INVALID", "ArcPy MCP response is invalid"
                )
            status = job.get("status")
            if status == "succeeded":
                return self._artifact_relative_path(job, artifact_id)
            if status in terminal_failures:
                try:
                    await self.call_tool(
                        "get_job_log", {"job_id": job_id}
                    )
                except BaseException:
                    pass
                raise ArcPyMcpError(
                    "ARCPY_INSPECTION_FAILED",
                    "ArcPy dataset inspection failed",
                )
            if status not in {"queued", "running", "pending"}:
                raise ArcPyMcpError(
                    "ARCPY_RESPONSE_INVALID", "ArcPy MCP response is invalid"
                )

    async def prepare_input(
        self, local_path: str | os.PathLike[str]
    ) -> UploadedArtifact:
        prepared = await asyncio.to_thread(package_local_dataset, local_path)
        artifact_id = None
        try:
            artifact_id = await self._upload_prepared(prepared)
            artifact_path = await self._inspect_uploaded_artifact(artifact_id)
            return UploadedArtifact(
                artifact_id=artifact_id,
                artifact_path=artifact_path,
                source_path=prepared.source_path,
                local_package_path=prepared.upload_path,
                delete_local_package=prepared.delete_after_upload,
            )
        except BaseException:
            if artifact_id is not None:
                await self._best_effort_delete_artifact(artifact_id)
            if prepared.delete_after_upload:
                try:
                    await asyncio.to_thread(
                        prepared.upload_path.unlink, missing_ok=True
                    )
                except OSError:
                    pass
            raise

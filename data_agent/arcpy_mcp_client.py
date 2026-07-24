"""Persistent client for the private ArcPy MCP service."""

from __future__ import annotations

import asyncio
import copy
import errno
import hashlib
import io
import ipaddress
import json
import logging
import math
import os
import re
import secrets
import shutil
import stat
import threading
import time
import zipfile
from contextlib import AsyncExitStack
from dataclasses import InitVar, dataclass
from datetime import timedelta
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Callable
from urllib.parse import urljoin, urlparse

import httpx
import jsonschema
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
_SIGNED_TRANSFER_ACTIVE = 0
_SIGNED_TRANSFER_ACTIVE_LOCK = threading.Lock()


class _SignedTransferLogFilter(RuntimeSecretRedactionFilter):
    def filter(self, record: logging.LogRecord) -> bool:
        super().filter(record)
        with _SIGNED_TRANSFER_ACTIVE_LOCK:
            active = _SIGNED_TRANSFER_ACTIVE > 0
        if active:
            record.msg = "[REDACTED]"
            record.args = ()
        return True


_SIGNED_TRANSFER_LOG_FILTER = _SignedTransferLogFilter()


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
    "ARCPY_JOB_CANCELLED": "ArcPy job was cancelled",
    "ARCPY_JOB_INTERRUPTED": "ArcPy job was interrupted",
    "ARCPY_DOWNLOAD_FAILED": "ArcPy result download failed",
    "ARCPY_DOWNLOAD_CHECKSUM_MISMATCH": "ArcPy result checksum mismatch",
    "ARCPY_UNSAFE_ARCHIVE": "ArcPy result archive is unsafe",
}
_SAFE_DETAIL_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,63}$")
_DNS_HOST_LABEL_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
_WINDOWS_RESERVED_COMPONENT_RE = re.compile(
    r"^(?:CON|PRN|AUX|NUL|COM[1-9\u00b9\u00b2\u00b3]|"
    r"LPT[1-9\u00b9\u00b2\u00b3]|CONIN\$|CONOUT\$)$",
    re.IGNORECASE,
)
_MAX_ARCHIVE_ENTRIES = 10_000
_MAX_ARCHIVE_PATH_DEPTH = 64
_MAX_ARCHIVE_UNCOMPRESSED_BYTES = 20 * 1024 * 1024 * 1024
_MAX_ARCHIVE_COMPRESSION_RATIO = 1_000
_MAX_VECTOR_SNAPSHOT_BYTES = 512 * 1024 * 1024


@dataclass(frozen=True)
class PreparedLocalUpload:
    upload_path: Path
    source_path: Path
    logical_name: str
    media_type: str
    size: int
    sha256: str
    delete_after_upload: bool
    _lease_init: InitVar[Any] = None

    def __post_init__(self, _lease_init: Any) -> None:
        object.__setattr__(self, "_lease", _lease_init)

    def _close_lease(self) -> None:
        if self._lease is not None:
            self._lease.close()

    def _take_lease(self):
        lease = self._lease
        object.__setattr__(self, "_lease", None)
        return lease

    def _cleanup_local_package(self) -> None:
        if self.delete_after_upload and self._lease is not None:
            _retry_package_cleanup(self._lease, self.upload_path)
        elif self.delete_after_upload:
            _best_effort_unlink_current_user_file(self.upload_path)


@dataclass(frozen=True)
class UploadedArtifact:
    artifact_id: str
    artifact_path: str
    source_path: Path
    local_package_path: Path
    delete_local_package: bool
    _lease_init: InitVar[Any] = None

    def __post_init__(self, _lease_init: Any) -> None:
        object.__setattr__(self, "_lease", _lease_init)

    def _cleanup_local_package(self) -> None:
        if self.delete_local_package and self._lease is not None:
            _retry_package_cleanup(self._lease, self.local_package_path)

    def _close_lease(self) -> None:
        if self._lease is not None:
            self._lease.close()
            object.__setattr__(self, "_lease", None)

    def __del__(self) -> None:
        try:
            self._close_lease()
        except Exception:
            pass


class _PreparedUploadLease:
    def __init__(
        self,
        tenant_fd: int,
        file_fd: int,
        identity: tuple[int, ...],
        user_upload_dir: Path,
        private_dir_fd: int | None = None,
        private_dir_name: str | None = None,
        private_entry_name: str | None = None,
    ):
        self._tenant_fd = tenant_fd
        self._file_fd = file_fd
        self._identity = identity
        self._object_identity = (
            identity[0],
            identity[1],
            stat.S_IFMT(identity[2]),
        )
        self._user_upload_dir = user_upload_dir
        self._private_dir_fd = private_dir_fd
        self._private_dir_name = private_dir_name
        self._private_entry_name = private_entry_name
        self._closed = False
        self._lock = threading.Lock()

    @staticmethod
    def _file_identity(file_stat: os.stat_result) -> tuple[int, ...]:
        return (
            file_stat.st_dev,
            file_stat.st_ino,
            file_stat.st_mode,
            file_stat.st_size,
            file_stat.st_mtime_ns,
            file_stat.st_ctime_ns,
        )

    @staticmethod
    def _file_object_identity(file_stat: os.stat_result) -> tuple[int, ...]:
        return (
            file_stat.st_dev,
            file_stat.st_ino,
            stat.S_IFMT(file_stat.st_mode),
        )

    def validate(self) -> None:
        with self._lock:
            if self._closed:
                raise _input_error("ARCPY_INPUT_INVALID")
            current = self._file_identity(os.fstat(self._file_fd))
            if current != self._identity:
                raise _input_error("ARCPY_INPUT_INVALID")

    def open_stream(self):
        self.validate()
        with self._lock:
            if self._closed:
                raise _input_error("ARCPY_INPUT_INVALID")
            descriptor = os.dup(self._file_fd)
        return os.fdopen(descriptor, "rb")

    def metadata(self) -> tuple[int, str]:
        digest = hashlib.sha256()
        with self.open_stream() as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        self.validate()
        return self._identity[3], digest.hexdigest().lower()

    def seal(self) -> None:
        with self._lock:
            if self._closed:
                raise _input_error("ARCPY_INPUT_INVALID")
            current_stat = os.fstat(self._file_fd)
            if (
                self._file_object_identity(current_stat)
                != self._object_identity
            ):
                raise _input_error("ARCPY_INPUT_INVALID")
            self._identity = self._file_identity(current_stat)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            file_fd = self._file_fd
            tenant_fd = self._tenant_fd
            private_dir_fd = self._private_dir_fd
            self._file_fd = -1
            self._tenant_fd = -1
            self._private_dir_fd = None
        try:
            os.close(file_fd)
        finally:
            try:
                if private_dir_fd is not None:
                    os.close(private_dir_fd)
            finally:
                os.close(tenant_fd)

    def unlink(self, path: Path) -> bool:
        with self._lock:
            if self._closed:
                return False
            if (
                self._private_dir_fd is None
                or self._private_dir_name is None
                or self._private_entry_name is None
            ):
                return False
            try:
                relative_path = path.relative_to(self._user_upload_dir)
            except ValueError:
                return False
            if relative_path.parts != (
                self._private_dir_name,
                self._private_entry_name,
            ):
                return False

            try:
                current_stat = os.stat(
                    self._private_entry_name,
                    dir_fd=self._private_dir_fd,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                pass
            except OSError:
                return False
            else:
                if (
                    self._file_object_identity(current_stat)
                    != self._object_identity
                ):
                    return False
                try:
                    os.unlink(
                        self._private_entry_name,
                        dir_fd=self._private_dir_fd,
                    )
                except FileNotFoundError:
                    pass
                except OSError:
                    return False
            try:
                os.rmdir(
                    self._private_dir_name,
                    dir_fd=self._tenant_fd,
                )
            except FileNotFoundError:
                return True
            except OSError:
                return False
            return True

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


def _retry_cleanup(cleanup: Callable[[], bool], attempts: int = 3) -> None:
    for _ in range(attempts):
        try:
            if cleanup():
                return
        except Exception:
            pass


def _retry_package_cleanup(
    lease: _PreparedUploadLease, path: Path, attempts: int = 3
) -> None:
    _retry_cleanup(lambda: lease.unlink(path), attempts)


def _cleanup_unleased_package_once(
    tenant_fd: int,
    private_dir_fd: int,
    private_dir_name: str,
    entry_name: str,
) -> bool:
    try:
        os.unlink(entry_name, dir_fd=private_dir_fd)
    except FileNotFoundError:
        pass
    except OSError:
        return False
    return _remove_empty_private_dir_once(tenant_fd, private_dir_name)


def _remove_empty_private_dir_once(
    tenant_fd: int, private_dir_name: str
) -> bool:
    try:
        os.rmdir(private_dir_name, dir_fd=tenant_fd)
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return True


def _retry_empty_private_dir_cleanup(
    tenant_fd: int,
    private_dir_name: str,
    attempts: int = 3,
) -> None:
    _retry_cleanup(
        lambda: _remove_empty_private_dir_once(
            tenant_fd, private_dir_name
        ),
        attempts,
    )


def _retry_unleased_package_cleanup(
    tenant_fd: int,
    private_dir_fd: int,
    private_dir_name: str,
    entry_name: str,
    attempts: int = 3,
) -> None:
    _retry_cleanup(
        lambda: _cleanup_unleased_package_once(
            tenant_fd,
            private_dir_fd,
            private_dir_name,
            entry_name,
        ),
        attempts,
    )


async def _drain_shielded_task(task: asyncio.Task[Any]) -> Any:
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            if task.done():
                break
    return task.result()


async def _cleanup_mvt_layer(tile_server: Any, metadata: dict) -> None:
    layer_id = metadata.get("layer_id") if isinstance(metadata, dict) else None
    if not isinstance(layer_id, str) or not layer_id:
        return
    cleanup_task = asyncio.create_task(
        asyncio.to_thread(tile_server.cleanup_tile_layer, layer_id)
    )
    try:
        await asyncio.shield(cleanup_task)
    except asyncio.CancelledError:
        try:
            await _drain_shielded_task(cleanup_task)
        except Exception:
            logger.warning("Failed to clean up ArcPy MVT layer")
        raise
    except Exception:
        logger.warning("Failed to clean up ArcPy MVT layer")


async def _cleanup_mvt_layers(
    tile_server: Any, layers: list[dict]
) -> None:
    cancelled = False
    for metadata in reversed(layers):
        try:
            await _cleanup_mvt_layer(tile_server, metadata)
        except asyncio.CancelledError:
            cancelled = True
    if cancelled:
        raise asyncio.CancelledError


class _AsyncFileByteStream:
    def __init__(
        self,
        lease: _PreparedUploadLease,
        offset: int,
        chunk_size: int = 1024 * 1024,
    ):
        self._lease = lease
        self._offset = offset
        self._chunk_size = chunk_size
        self._stream = None

    async def __aenter__(self):
        self._stream = self._lease.open_stream()
        return self

    async def __aexit__(self, *args):
        stream = self._stream
        self._stream = None
        if stream is not None:
            exc_type = args[0] if args else None
            cancelled = isinstance(exc_type, type) and issubclass(
                exc_type, asyncio.CancelledError
            )
            validation_error = None
            close_error = None
            try:
                self._lease.validate()
            except Exception as exc:
                validation_error = exc
            try:
                stream.close()
            except Exception as exc:
                close_error = exc
            if not cancelled:
                if validation_error is not None:
                    raise validation_error
                if close_error is not None:
                    raise close_error
        return False

    def __aiter__(self):
        return self._read_chunks()

    async def _file_operation(self, operation, *args):
        operation_task = asyncio.create_task(
            asyncio.to_thread(operation, *args)
        )
        try:
            return await asyncio.shield(operation_task)
        except asyncio.CancelledError:
            try:
                await operation_task
            except Exception:
                pass
            raise

    async def _read_chunks(self):
        if self._stream is None:
            return
        await self._file_operation(self._stream.seek, self._offset)
        while True:
            chunk = await self._file_operation(
                self._stream.read, self._chunk_size
            )
            if not chunk:
                self._lease.validate()
                return
            yield chunk


def _input_error(code: str) -> ArcPyMcpError:
    return ArcPyMcpError(code, _PUBLIC_ERROR_MESSAGES[code])


def _begin_signed_transfer() -> None:
    global _SIGNED_TRANSFER_ACTIVE
    with _SIGNED_TRANSFER_ACTIVE_LOCK:
        _SIGNED_TRANSFER_ACTIVE += 1


def _end_signed_transfer() -> None:
    global _SIGNED_TRANSFER_ACTIVE
    with _SIGNED_TRANSFER_ACTIVE_LOCK:
        _SIGNED_TRANSFER_ACTIVE = max(0, _SIGNED_TRANSFER_ACTIVE - 1)


@dataclass
class _DownloadWorkspace:
    tenant_fd: int
    directory_fd: int
    tenant_identity: tuple[int, int]
    directory_identity: tuple[int, int]
    directory_name: str
    path: Path
    closed: bool = False

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            os.close(self.directory_fd)
        finally:
            os.close(self.tenant_fd)

    def validate_path(self) -> None:
        current_tenant_fd = None
        try:
            current_tenant_fd, _ = _open_current_user_upload_dir(
                self.tenant_identity
            )
            current_tenant = os.fstat(current_tenant_fd)
            pinned_tenant = os.fstat(self.tenant_fd)
            current = os.stat(
                self.directory_name,
                dir_fd=self.tenant_fd,
                follow_symlinks=False,
            )
            pinned = os.fstat(self.directory_fd)
            valid = (
                stat.S_ISDIR(current_tenant.st_mode)
                and stat.S_ISDIR(pinned_tenant.st_mode)
                and current_tenant.st_mode == pinned_tenant.st_mode
                and current_tenant.st_dev == pinned_tenant.st_dev
                and current_tenant.st_ino == pinned_tenant.st_ino
                and current_tenant.st_size == pinned_tenant.st_size
                and current_tenant.st_mtime_ns == pinned_tenant.st_mtime_ns
                and current_tenant.st_ctime_ns == pinned_tenant.st_ctime_ns
                and current_tenant.st_nlink == pinned_tenant.st_nlink
                and stat.S_ISDIR(current.st_mode)
                and current.st_mode == pinned.st_mode
                and current.st_dev == pinned.st_dev
                and current.st_ino == pinned.st_ino
                and current.st_size == pinned.st_size
                and current.st_mtime_ns == pinned.st_mtime_ns
                and current.st_ctime_ns == pinned.st_ctime_ns
                and current.st_nlink == pinned.st_nlink
            )
        except (ArcPyMcpError, OSError):
            valid = False
        finally:
            if current_tenant_fd is not None:
                os.close(current_tenant_fd)
        if not valid:
            raise ArcPyMcpError(
                "ARCPY_DOWNLOAD_FAILED", "ArcPy result download failed"
            )

    def cleanup(self) -> None:
        if self.closed:
            return
        try:
            for _ in range(3):
                _remove_directory_contents(self.directory_fd)
                try:
                    current = os.stat(
                        self.directory_name,
                        dir_fd=self.tenant_fd,
                        follow_symlinks=False,
                    )
                    if (
                        stat.S_ISDIR(current.st_mode)
                        and (current.st_dev, current.st_ino)
                        == self.directory_identity
                    ):
                        os.rmdir(
                            self.directory_name, dir_fd=self.tenant_fd
                        )
                    break
                except FileNotFoundError:
                    break
                except OSError:
                    continue
        except BaseException:
            pass
        finally:
            self.close()


@dataclass
class _PinnedDownloadEntry:
    parts: tuple[str, ...]
    descriptor: int
    identity: os.stat_result


@dataclass
class _ConsumerSnapshot:
    descriptor: int
    archived: bool
    logical_size: int
    closed: bool = False

    @property
    def path(self) -> str:
        if self.closed:
            raise ArcPyMcpError(
                "ARCPY_DOWNLOAD_FAILED", "ArcPy result download failed"
            )
        return f"/dev/fd/{self.descriptor}"

    def read_bytes(self, limit: int) -> bytes | None:
        if self.closed or os.fstat(self.descriptor).st_size > limit:
            return None
        stream = os.fdopen(os.dup(self.descriptor), "rb")
        try:
            stream.seek(0)
            payload = stream.read(limit + 1)
        finally:
            stream.close()
        return payload if len(payload) <= limit else None

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        os.close(self.descriptor)

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass


class _VerifiedDownload:
    def __init__(
        self,
        paths: list[Path],
        verification_paths: list[Path],
        workspace: _DownloadWorkspace,
    ) -> None:
        self.paths = list(paths)
        self._workspace = workspace
        self._entries: dict[tuple[str, ...], _PinnedDownloadEntry] = {}
        self._closed = False
        self._tenant_identity = None
        self._workspace_identity = None
        try:
            for path in verification_paths:
                self.pin_path(path)
            self._tenant_identity = os.fstat(workspace.tenant_fd)
            self._workspace_identity = os.fstat(workspace.directory_fd)
            self.validate()
        except BaseException:
            self._close_entries()
            raise

    @staticmethod
    def _same_identity(left, right) -> bool:
        same_kind = (
            stat.S_ISDIR(left.st_mode) and stat.S_ISDIR(right.st_mode)
        ) or (
            stat.S_ISREG(left.st_mode) and stat.S_ISREG(right.st_mode)
        )
        return (
            same_kind
            and left.st_mode == right.st_mode
            and left.st_dev == right.st_dev
            and left.st_ino == right.st_ino
            and left.st_size == right.st_size
            and left.st_mtime_ns == right.st_mtime_ns
            and left.st_ctime_ns == right.st_ctime_ns
            and left.st_nlink == right.st_nlink
        )

    @staticmethod
    def _same_directory(left, right) -> bool:
        return (
            stat.S_ISDIR(left.st_mode)
            and stat.S_ISDIR(right.st_mode)
            and left.st_mode == right.st_mode
            and left.st_dev == right.st_dev
            and left.st_ino == right.st_ino
        )

    def _relative_parts(self, path: Path) -> tuple[str, ...]:
        try:
            relative = path.relative_to(self._workspace.path)
        except ValueError:
            raise ArcPyMcpError(
                "ARCPY_DOWNLOAD_FAILED", "ArcPy result download failed"
            ) from None
        if not relative.parts or any(
            part in {"", ".", ".."} for part in relative.parts
        ):
            raise ArcPyMcpError(
                "ARCPY_DOWNLOAD_FAILED", "ArcPy result download failed"
            )
        return tuple(relative.parts)

    def _open_parts(
        self, parts: tuple[str, ...], *, directory: bool
    ) -> int:
        current_fd = os.dup(self._workspace.directory_fd)
        try:
            for index, part in enumerate(parts):
                is_last = index == len(parts) - 1
                if not is_last or directory:
                    flags = _directory_open_flags()
                else:
                    flags = os.O_RDONLY
                    flags |= getattr(os, "O_CLOEXEC", 0)
                    flags |= getattr(os, "O_NOFOLLOW", 0)
                next_fd = os.open(part, flags, dir_fd=current_fd)
                os.close(current_fd)
                current_fd = next_fd
            result = current_fd
            current_fd = None
            return result
        except OSError:
            raise ArcPyMcpError(
                "ARCPY_DOWNLOAD_FAILED", "ArcPy result download failed"
            ) from None
        finally:
            if current_fd is not None:
                os.close(current_fd)

    def _pin_parts(self, parts: tuple[str, ...], *, directory: bool) -> None:
        existing = self._entries.get(parts)
        if existing is not None:
            if not directory or not stat.S_ISDIR(existing.identity.st_mode):
                return
            pinned_now = os.fstat(existing.descriptor)
            current_fd = self._open_parts(parts, directory=True)
            try:
                current = os.fstat(current_fd)
            finally:
                os.close(current_fd)
            if not self._same_directory(
                existing.identity, pinned_now
            ) or not self._same_identity(pinned_now, current):
                raise ArcPyMcpError(
                    "ARCPY_DOWNLOAD_FAILED",
                    "ArcPy result download failed",
                )
            existing.identity = pinned_now
            return
        descriptor = self._open_parts(parts, directory=directory)
        identity = os.fstat(descriptor)
        valid = stat.S_ISDIR(identity.st_mode) if directory else stat.S_ISREG(
            identity.st_mode
        )
        if not valid:
            os.close(descriptor)
            raise ArcPyMcpError(
                "ARCPY_DOWNLOAD_FAILED", "ArcPy result download failed"
            )
        self._entries[parts] = _PinnedDownloadEntry(
            parts, descriptor, identity
        )

    def pin_path(self, path: Path) -> None:
        parts = self._relative_parts(path)
        if self._closed:
            raise ArcPyMcpError(
                "ARCPY_DOWNLOAD_FAILED", "ArcPy result download failed"
            )
        self._workspace.validate_path()
        if self._workspace_identity is not None:
            pinned_workspace = os.fstat(self._workspace.directory_fd)
            if not self._same_directory(
                self._workspace_identity, pinned_workspace
            ):
                raise ArcPyMcpError(
                    "ARCPY_DOWNLOAD_FAILED",
                    "ArcPy result download failed",
                )
            self._workspace_identity = pinned_workspace
        try:
            is_directory = path.is_dir()
        except OSError:
            is_directory = False
        directory_count = len(parts) if is_directory else len(parts) - 1
        for index in range(1, directory_count + 1):
            self._pin_parts(parts[:index], directory=True)
        if not is_directory:
            self._pin_parts(parts, directory=False)

    def validate(self) -> None:
        if self._closed:
            raise ArcPyMcpError(
                "ARCPY_DOWNLOAD_FAILED", "ArcPy result download failed"
            )
        self._workspace.validate_path()
        tenant_now = os.fstat(self._workspace.tenant_fd)
        workspace_now = os.fstat(self._workspace.directory_fd)
        if (
            self._tenant_identity is None
            or self._workspace_identity is None
            or not self._same_identity(self._tenant_identity, tenant_now)
            or not self._same_identity(
                self._workspace_identity, workspace_now
            )
        ):
            raise ArcPyMcpError(
                "ARCPY_DOWNLOAD_FAILED", "ArcPy result download failed"
            )
        for entry in self._entries.values():
            pinned_now = os.fstat(entry.descriptor)
            directory = stat.S_ISDIR(entry.identity.st_mode)
            current_fd = self._open_parts(
                entry.parts, directory=directory
            )
            try:
                current = os.fstat(current_fd)
            finally:
                os.close(current_fd)
            if not self._same_identity(entry.identity, pinned_now) or not (
                self._same_identity(entry.identity, current)
            ):
                raise ArcPyMcpError(
                    "ARCPY_DOWNLOAD_FAILED",
                    "ArcPy result download failed",
                )

    def _refresh_modified_directory(
        self, parts: tuple[str, ...], descriptor: int
    ) -> None:
        current = os.fstat(descriptor)
        if parts:
            entry = self._entries.get(parts)
            if entry is None or not self._same_directory(
                entry.identity, current
            ):
                raise ArcPyMcpError(
                    "ARCPY_DOWNLOAD_FAILED",
                    "ArcPy result download failed",
                )
            entry.identity = current
            return
        if self._workspace_identity is None or not self._same_directory(
            self._workspace_identity, current
        ):
            raise ArcPyMcpError(
                "ARCPY_DOWNLOAD_FAILED", "ArcPy result download failed"
            )
        self._workspace_identity = current

    def _new_anonymous_file(self) -> int:
        descriptor = None
        candidate = None
        try:
            for _ in range(100):
                candidate = f".consumer-{secrets.token_hex(16)}"
                flags = os.O_RDWR | os.O_CREAT | os.O_EXCL
                flags |= getattr(os, "O_CLOEXEC", 0)
                flags |= getattr(os, "O_NOFOLLOW", 0)
                try:
                    descriptor = os.open(
                        candidate,
                        flags,
                        0o600,
                        dir_fd=self._workspace.directory_fd,
                    )
                    break
                except FileExistsError:
                    continue
            if descriptor is None or candidate is None:
                raise OSError("could not allocate consumer snapshot")
            os.unlink(candidate, dir_fd=self._workspace.directory_fd)
            self._refresh_modified_directory(
                (), self._workspace.directory_fd
            )
            return descriptor
        except BaseException:
            if descriptor is not None:
                os.close(descriptor)
            if candidate is not None:
                try:
                    os.unlink(candidate, dir_fd=self._workspace.directory_fd)
                except OSError:
                    pass
            raise

    def _snapshot_entries(
        self, path: Path
    ) -> tuple[list[_PinnedDownloadEntry], tuple[str, ...], bool]:
        parts = self._relative_parts(path)
        entry = self._entries.get(parts)
        if entry is None:
            raise ArcPyMcpError(
                "ARCPY_DOWNLOAD_FAILED", "ArcPy result download failed"
            )
        if path.suffix.lower() == ".shp":
            parent = parts[:-1]
            stem = path.stem.casefold()
            selected = [
                candidate
                for candidate in self._entries.values()
                if len(candidate.parts) == len(parts)
                and candidate.parts[:-1] == parent
                and stat.S_ISREG(candidate.identity.st_mode)
                and _is_shapefile_sidecar_name(
                    candidate.parts[-1], stem
                )
            ]
            archived = True
            base_parts = parent
        elif stat.S_ISDIR(entry.identity.st_mode):
            selected = [
                candidate
                for candidate in self._entries.values()
                if len(candidate.parts) > len(parts)
                and candidate.parts[: len(parts)] == parts
                and stat.S_ISREG(candidate.identity.st_mode)
            ]
            archived = True
            base_parts = parts[:-1]
        else:
            selected = [entry]
            archived = False
            base_parts = parts[:-1]
        if not selected:
            raise ArcPyMcpError(
                "ARCPY_DOWNLOAD_FAILED", "ArcPy result download failed"
            )
        return sorted(selected, key=lambda item: item.parts), base_parts, archived

    @staticmethod
    def _copy_entry(source_fd: int, destination) -> None:
        source = os.fdopen(os.dup(source_fd), "rb")
        try:
            source.seek(0)
            shutil.copyfileobj(source, destination, 1024 * 1024)
        finally:
            source.close()

    def consumer_snapshot(self, path: Path) -> _ConsumerSnapshot:
        self.validate()
        entries, base_parts, archived = self._snapshot_entries(path)
        descriptor = self._new_anonymous_file()
        read_descriptor = None
        try:
            if archived:
                target = os.fdopen(os.dup(descriptor), "w+b")
                try:
                    with zipfile.ZipFile(
                        target, "w", compression=zipfile.ZIP_STORED
                    ) as archive:
                        for entry in entries:
                            relative = entry.parts[len(base_parts) :]
                            archive_name = PurePosixPath(*relative).as_posix()
                            with archive.open(archive_name, "w") as output:
                                self._copy_entry(entry.descriptor, output)
                    target.flush()
                    os.fsync(target.fileno())
                finally:
                    target.close()
            else:
                target = os.fdopen(os.dup(descriptor), "r+b")
                try:
                    self._copy_entry(entries[0].descriptor, target)
                    target.flush()
                    os.fsync(target.fileno())
                finally:
                    target.close()
            os.fchmod(descriptor, 0o400)
            read_descriptor = os.open(
                f"/dev/fd/{descriptor}",
                os.O_RDONLY | getattr(os, "O_CLOEXEC", 0),
            )
            os.lseek(read_descriptor, 0, os.SEEK_SET)
            os.close(descriptor)
            descriptor = None
            self.validate()
            snapshot = _ConsumerSnapshot(
                descriptor=read_descriptor,
                archived=archived,
                logical_size=sum(entry.identity.st_size for entry in entries),
            )
            read_descriptor = None
            return snapshot
        except BaseException:
            if read_descriptor is not None:
                os.close(read_descriptor)
            if descriptor is not None:
                os.close(descriptor)
            raise

    def _write_generated_file(
        self, source_path: Path, extension: str, writer
    ) -> Path:
        source_parts = self._relative_parts(source_path)
        parent_parts = source_parts[:-1]
        if parent_parts:
            parent_entry = self._entries.get(parent_parts)
            if parent_entry is None or not stat.S_ISDIR(
                parent_entry.identity.st_mode
            ):
                raise ArcPyMcpError(
                    "ARCPY_DOWNLOAD_FAILED",
                    "ArcPy result download failed",
                )
            parent_fd = parent_entry.descriptor
        else:
            parent_fd = self._workspace.directory_fd
        descriptor = None
        read_descriptor = None
        candidate = None
        parts = None
        try:
            for _ in range(100):
                candidate = (
                    f"{source_path.stem}-map-"
                    f"{secrets.token_hex(8)}{extension}"
                )
                flags = os.O_RDWR | os.O_CREAT | os.O_EXCL
                flags |= getattr(os, "O_CLOEXEC", 0)
                flags |= getattr(os, "O_NOFOLLOW", 0)
                try:
                    descriptor = os.open(
                        candidate, flags, 0o600, dir_fd=parent_fd
                    )
                    break
                except FileExistsError:
                    continue
            if descriptor is None or candidate is None:
                raise OSError("could not allocate map output")
            writer(descriptor)
            os.fsync(descriptor)
            os.fchmod(descriptor, 0o600)
            read_descriptor = os.open(
                f"/dev/fd/{descriptor}",
                os.O_RDONLY | getattr(os, "O_CLOEXEC", 0),
            )
            os.close(descriptor)
            descriptor = None
            self._refresh_modified_directory(parent_parts, parent_fd)
            parts = (*parent_parts, candidate)
            current_fd = self._open_parts(parts, directory=False)
            try:
                identity = os.fstat(read_descriptor)
                current = os.fstat(current_fd)
            finally:
                os.close(current_fd)
            if not self._same_identity(identity, current):
                raise ArcPyMcpError(
                    "ARCPY_DOWNLOAD_FAILED",
                    "ArcPy result download failed",
                )
            self._entries[parts] = _PinnedDownloadEntry(
                parts, read_descriptor, identity
            )
            read_descriptor = None
            self.validate()
            return source_path.parent / candidate
        except BaseException:
            if parts is not None:
                entry = self._entries.pop(parts, None)
                if entry is not None:
                    os.close(entry.descriptor)
            if read_descriptor is not None:
                os.close(read_descriptor)
            if descriptor is not None:
                os.close(descriptor)
            if candidate is not None:
                try:
                    os.unlink(candidate, dir_fd=parent_fd)
                    self._refresh_modified_directory(
                        parent_parts, parent_fd
                    )
                except OSError:
                    pass
            raise

    def write_geojson(self, frame, source_path: Path) -> Path:
        def write(descriptor: int) -> None:
            stream = os.fdopen(
                os.dup(descriptor), "w", encoding="utf-8"
            )
            try:
                stream.write('{"type":"FeatureCollection","features":[')
                first = True
                for feature in frame.iterfeatures():
                    if not first:
                        stream.write(",")
                    json.dump(feature, stream, allow_nan=False)
                    first = False
                stream.write("]}")
                stream.flush()
            finally:
                stream.close()

        return self._write_generated_file(source_path, ".geojson", write)

    def write_flatgeobuf(self, frame, source_path: Path) -> Path:
        buffer = io.BytesIO()
        frame.to_file(buffer, driver="FlatGeobuf")
        payload = buffer.getvalue()

        def write(descriptor: int) -> None:
            stream = os.fdopen(os.dup(descriptor), "wb")
            try:
                stream.write(payload)
                stream.flush()
            finally:
                stream.close()

        return self._write_generated_file(source_path, ".fgb", write)

    def user_relative_path(self, path: Path) -> str:
        parts = self._relative_parts(path)
        return PurePosixPath(
            self._workspace.directory_name, *parts
        ).as_posix()

    def _close_entries(self) -> None:
        for entry in self._entries.values():
            try:
                os.close(entry.descriptor)
            except OSError:
                pass
        self._entries.clear()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._close_entries()
        self._workspace.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass


def _remove_directory_contents(directory_fd: int) -> None:
    root_fd = os.dup(directory_fd)
    try:
        root_names = iter(os.listdir(root_fd))
    except OSError:
        os.close(root_fd)
        return
    stack = [(root_fd, None, None, root_names)]
    try:
        while stack:
            current_fd, parent_fd, name, names = stack[-1]
            try:
                child_name = next(names)
            except StopIteration:
                stack.pop()
                if parent_fd is not None and name is not None:
                    try:
                        os.rmdir(name, dir_fd=parent_fd)
                    except OSError:
                        pass
                os.close(current_fd)
                continue

            try:
                item_stat = os.stat(
                    child_name,
                    dir_fd=current_fd,
                    follow_symlinks=False,
                )
                if not stat.S_ISDIR(item_stat.st_mode):
                    os.unlink(child_name, dir_fd=current_fd)
                    continue
                child_fd = os.open(
                    child_name,
                    _directory_open_flags(),
                    dir_fd=current_fd,
                )
                try:
                    child_names = iter(os.listdir(child_fd))
                except OSError:
                    os.close(child_fd)
                    try:
                        os.rmdir(child_name, dir_fd=current_fd)
                    except OSError:
                        pass
                    continue
                stack.append(
                    (child_fd, current_fd, child_name, child_names)
                )
            except OSError:
                continue
    finally:
        while stack:
            current_fd, _, _, _ = stack.pop()
            try:
                os.close(current_fd)
            except OSError:
                pass


def _new_download_workspace() -> _DownloadWorkspace:
    tenant_fd, user_upload_dir = _open_current_user_upload_dir()
    directory_fd = None
    directory_name = None
    try:
        for _ in range(100):
            candidate = f".arcpy-result-{secrets.token_hex(16)}"
            try:
                os.mkdir(candidate, 0o700, dir_fd=tenant_fd)
                directory_name = candidate
                break
            except FileExistsError:
                continue
        if directory_name is None:
            raise ArcPyMcpError(
                "ARCPY_DOWNLOAD_FAILED", "ArcPy result download failed"
            )
        directory_fd = os.open(
            directory_name, _directory_open_flags(), dir_fd=tenant_fd
        )
        workspace = _DownloadWorkspace(
            tenant_fd=tenant_fd,
            directory_fd=directory_fd,
            tenant_identity=_directory_identity(tenant_fd),
            directory_identity=_directory_identity(directory_fd),
            directory_name=directory_name,
            path=user_upload_dir / directory_name,
        )
        tenant_fd = None
        directory_fd = None
        return workspace
    except ArcPyMcpError:
        raise
    except OSError:
        raise ArcPyMcpError(
            "ARCPY_DOWNLOAD_FAILED", "ArcPy result download failed"
        ) from None
    finally:
        if directory_fd is not None:
            os.close(directory_fd)
        if tenant_fd is not None:
            if directory_name is not None:
                try:
                    os.rmdir(directory_name, dir_fd=tenant_fd)
                except OSError:
                    pass
            os.close(tenant_fd)


def _safe_archive_parts(name: str) -> tuple[str, ...]:
    if (
        not isinstance(name, str)
        or not name
        or "\x00" in name
        or "\\" in name
    ):
        raise ArcPyMcpError(
            "ARCPY_UNSAFE_ARCHIVE", "ArcPy result archive is unsafe"
        )
    posix_path = PurePosixPath(name)
    windows_path = PureWindowsPath(name)
    parts = posix_path.parts
    if (
        posix_path.is_absolute()
        or windows_path.is_absolute()
        or bool(windows_path.drive)
        or not parts
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise ArcPyMcpError(
            "ARCPY_UNSAFE_ARCHIVE", "ArcPy result archive is unsafe"
        )
    if (
        len(name.encode("utf-8")) > 4096
        or len(parts) > _MAX_ARCHIVE_PATH_DEPTH
        or any(len(part.encode("utf-8")) > 255 for part in parts)
    ):
        raise ArcPyMcpError(
            "ARCPY_UNSAFE_ARCHIVE", "ArcPy result archive is unsafe"
        )
    for part in parts:
        reserved_stem = part.split(".", 1)[0].rstrip(" .")
        if (
            ":" in part
            or part.endswith((".", " "))
            or any(ord(character) < 32 or ord(character) == 127 for character in part)
            or _WINDOWS_RESERVED_COMPONENT_RE.fullmatch(reserved_stem)
            is not None
        ):
            raise ArcPyMcpError(
                "ARCPY_UNSAFE_ARCHIVE", "ArcPy result archive is unsafe"
            )
    return tuple(parts)


def _zip_entry_kind(info: zipfile.ZipInfo) -> str:
    unix_mode = (info.external_attr >> 16) & 0xFFFF
    file_type = stat.S_IFMT(unix_mode)
    if stat.S_ISLNK(unix_mode):
        raise ArcPyMcpError(
            "ARCPY_UNSAFE_ARCHIVE", "ArcPy result archive is unsafe"
        )
    if info.is_dir():
        if file_type not in {0, stat.S_IFDIR}:
            raise ArcPyMcpError(
                "ARCPY_UNSAFE_ARCHIVE", "ArcPy result archive is unsafe"
            )
        return "directory"
    if file_type not in {0, stat.S_IFREG}:
        raise ArcPyMcpError(
            "ARCPY_UNSAFE_ARCHIVE", "ArcPy result archive is unsafe"
        )
    return "file"


def _validate_zip_entries(
    archive: zipfile.ZipFile,
) -> list[tuple[zipfile.ZipInfo, tuple[str, ...], str]]:
    infos = archive.infolist()
    if len(infos) > _MAX_ARCHIVE_ENTRIES:
        raise ArcPyMcpError(
            "ARCPY_UNSAFE_ARCHIVE", "ArcPy result archive is unsafe"
        )
    if not infos:
        raise ArcPyMcpError(
            "ARCPY_UNSAFE_ARCHIVE", "ArcPy result archive is unsafe"
        )
    checked = []
    seen: dict[tuple[str, ...], str] = {}
    total_size = 0
    for info in infos:
        parts = _safe_archive_parts(info.filename.rstrip("/"))
        kind = _zip_entry_kind(info)
        if info.file_size < 0 or info.compress_size < 0:
            raise ArcPyMcpError(
                "ARCPY_UNSAFE_ARCHIVE", "ArcPy result archive is unsafe"
            )
        total_size += info.file_size
        if total_size > _MAX_ARCHIVE_UNCOMPRESSED_BYTES:
            raise ArcPyMcpError(
                "ARCPY_UNSAFE_ARCHIVE", "ArcPy result archive is unsafe"
            )
        if (
            info.file_size > 0
            and (
                info.compress_size == 0
                or info.file_size
                > info.compress_size * _MAX_ARCHIVE_COMPRESSION_RATIO
            )
        ):
            raise ArcPyMcpError(
                "ARCPY_UNSAFE_ARCHIVE", "ArcPy result archive is unsafe"
            )
        folded = tuple(part.casefold() for part in parts)
        if folded in seen:
            raise ArcPyMcpError(
                "ARCPY_UNSAFE_ARCHIVE", "ArcPy result archive is unsafe"
            )
        for index in range(1, len(folded)):
            if seen.get(folded[:index]) == "file":
                raise ArcPyMcpError(
                    "ARCPY_UNSAFE_ARCHIVE", "ArcPy result archive is unsafe"
                )
        if kind == "file" and any(
            existing[: len(folded)] == folded
            for existing in seen
            if len(existing) > len(folded)
        ):
            raise ArcPyMcpError(
                "ARCPY_UNSAFE_ARCHIVE", "ArcPy result archive is unsafe"
            )
        seen[folded] = kind
        checked.append((info, parts, kind))
    return checked


def _ensure_archive_directory(root_fd: int, parts: tuple[str, ...]) -> int:
    current_fd = os.dup(root_fd)
    try:
        for part in parts:
            try:
                os.mkdir(part, 0o700, dir_fd=current_fd)
            except FileExistsError:
                pass
            next_fd = os.open(
                part, _directory_open_flags(), dir_fd=current_fd
            )
            os.close(current_fd)
            current_fd = next_fd
        result = current_fd
        current_fd = None
        return result
    except OSError:
        raise ArcPyMcpError(
            "ARCPY_UNSAFE_ARCHIVE", "ArcPy result archive is unsafe"
        ) from None
    finally:
        if current_fd is not None:
            os.close(current_fd)


def _extract_verified_zip(
    archive_source, workspace: _DownloadWorkspace
) -> list[Path]:
    extraction_name = "extracted"
    try:
        os.mkdir(extraction_name, 0o700, dir_fd=workspace.directory_fd)
        extraction_fd = os.open(
            extraction_name,
            _directory_open_flags(),
            dir_fd=workspace.directory_fd,
        )
    except OSError:
        raise ArcPyMcpError(
            "ARCPY_UNSAFE_ARCHIVE", "ArcPy result archive is unsafe"
        ) from None
    extracted_files = []
    try:
        try:
            archive = zipfile.ZipFile(archive_source, "r")
        except (OSError, zipfile.BadZipFile):
            raise ArcPyMcpError(
                "ARCPY_UNSAFE_ARCHIVE", "ArcPy result archive is unsafe"
            ) from None
        with archive:
            checked = _validate_zip_entries(archive)
            extracted_size = 0
            for info, parts, kind in checked:
                if kind == "directory":
                    directory_fd = _ensure_archive_directory(
                        extraction_fd, parts
                    )
                    os.close(directory_fd)
                    continue
                parent_fd = _ensure_archive_directory(
                    extraction_fd, parts[:-1]
                )
                output_fd = None
                try:
                    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
                    flags |= getattr(os, "O_CLOEXEC", 0)
                    flags |= getattr(os, "O_NOFOLLOW", 0)
                    output_fd = os.open(
                        parts[-1], flags, 0o600, dir_fd=parent_fd
                    )
                    with archive.open(info, "r") as source:
                        with os.fdopen(output_fd, "wb") as destination:
                            output_fd = None
                            while True:
                                chunk = source.read(1024 * 1024)
                                if not chunk:
                                    break
                                extracted_size += len(chunk)
                                if (
                                    extracted_size
                                    > _MAX_ARCHIVE_UNCOMPRESSED_BYTES
                                ):
                                    raise ArcPyMcpError(
                                        "ARCPY_UNSAFE_ARCHIVE",
                                        "ArcPy result archive is unsafe",
                                    )
                                destination.write(chunk)
                    extracted_files.append(
                        workspace.path / extraction_name / Path(*parts)
                    )
                except (OSError, RuntimeError, zipfile.BadZipFile):
                    raise ArcPyMcpError(
                        "ARCPY_UNSAFE_ARCHIVE",
                        "ArcPy result archive is unsafe",
                    ) from None
                finally:
                    if output_fd is not None:
                        os.close(output_fd)
                    os.close(parent_fd)
    finally:
        os.close(extraction_fd)
    if not extracted_files:
        raise ArcPyMcpError(
            "ARCPY_UNSAFE_ARCHIVE", "ArcPy result archive is unsafe"
        )
    return extracted_files


def _extracted_dataset_paths(paths: list[Path]) -> list[Path]:
    gdb_roots = set()
    for path in paths:
        for parent in (path, *path.parents):
            if parent.suffix.lower() == ".gdb":
                gdb_roots.add(parent)
                break
    shapefiles = {path for path in paths if path.suffix.lower() == ".shp"}
    outputs = set(gdb_roots) | shapefiles
    for path in paths:
        if any(root == path or root in path.parents for root in gdb_roots):
            continue
        is_sidecar = any(
            path.parent == shapefile.parent
            and _is_shapefile_sidecar_name(
                path.name, shapefile.stem.casefold()
            )
            for shapefile in shapefiles
        )
        if is_sidecar and path not in shapefiles:
            continue
        outputs.add(path)
    return sorted(outputs, key=lambda item: str(item).casefold())


def _frame_metadata(frame, file_size: int) -> dict:
    metadata = {
        "file_size_bytes": max(0, int(file_size)),
        "crs": "",
        "srid": 0,
        "feature_count": len(frame),
        "spatial_extent": None,
        "column_schema": [
            {"name": str(column), "type": str(frame[column].dtype)}
            for column in frame.columns
        ],
    }
    if frame.crs:
        metadata["crs"] = str(frame.crs)
        try:
            metadata["srid"] = frame.crs.to_epsg() or 0
        except Exception:
            pass
    if not frame.empty:
        bounds = [float(value) for value in frame.total_bounds]
        if all(math.isfinite(value) for value in bounds):
            metadata["spatial_extent"] = {
                "minx": round(bounds[0], 6),
                "miny": round(bounds[1], 6),
                "maxx": round(bounds[2], 6),
                "maxy": round(bounds[3], 6),
            }
    return metadata


def _map_frame(frame):
    if frame.crs and frame.crs.to_epsg() != 4326:
        return frame.to_crs(epsg=4326)
    return frame


def _map_update_from_frame(
    frame, geojson_path: Path, relative_path: str
) -> dict:
    bounds = [float(value) for value in frame.total_bounds]
    if len(bounds) != 4 or not all(math.isfinite(value) for value in bounds):
        raise ArcPyMcpError(
            "ARCPY_DOWNLOAD_FAILED", "ArcPy result download failed"
        )
    geometry_types = set(frame.geom_type.dropna().unique())
    if geometry_types & {"Point", "MultiPoint"}:
        layer_type = "point"
    elif geometry_types & {"LineString", "MultiLineString"}:
        layer_type = "line"
    else:
        layer_type = "polygon"
    label = geojson_path.stem.replace("_", " ").title()
    return {
        "layers": [
            {
                "name": label,
                "type": layer_type,
                "geojson": relative_path,
            }
        ],
        "center": [
            (bounds[1] + bounds[3]) / 2,
            (bounds[0] + bounds[2]) / 2,
        ],
        "zoom": 13,
    }


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


def _current_user_upload_location() -> tuple[Path, Path, str]:
    from data_agent import user_context

    try:
        shared_upload_dir = Path(
            os.path.abspath(os.fspath(user_context._BASE_UPLOAD_DIR))
        )
        user_upload_dir = Path(
            os.path.abspath(os.fspath(user_context.get_user_upload_dir()))
        )
        relative_user_dir = user_upload_dir.relative_to(shared_upload_dir)
    except Exception:
        raise _input_error("ARCPY_INPUT_OUTSIDE_SANDBOX") from None
    if len(relative_user_dir.parts) != 1:
        raise _input_error("ARCPY_INPUT_OUTSIDE_SANDBOX")
    return shared_upload_dir, user_upload_dir, relative_user_dir.parts[0]


def _directory_open_flags() -> int:
    flags = os.O_RDONLY
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    return flags


def _directory_identity(descriptor: int) -> tuple[int, int]:
    directory_stat = os.fstat(descriptor)
    return directory_stat.st_dev, directory_stat.st_ino


def _open_current_user_upload_dir(
    expected_identity: tuple[int, int] | None = None,
) -> tuple[int, Path]:
    shared_upload_dir, user_upload_dir, user_dir_name = (
        _current_user_upload_location()
    )
    shared_fd = None
    try:
        shared_fd = os.open(shared_upload_dir, _directory_open_flags())
        user_fd = os.open(
            user_dir_name,
            _directory_open_flags(),
            dir_fd=shared_fd,
        )
        if (
            expected_identity is not None
            and _directory_identity(user_fd) != expected_identity
        ):
            os.close(user_fd)
            raise _input_error("ARCPY_INPUT_OUTSIDE_SANDBOX")
        return user_fd, user_upload_dir
    except OSError as exc:
        if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
            raise _input_error("ARCPY_INPUT_OUTSIDE_SANDBOX") from None
        raise _input_error("ARCPY_INPUT_INVALID") from None
    finally:
        if shared_fd is not None:
            os.close(shared_fd)


def _is_in_current_user_upload_dir(
    path: Path, expected_identity: tuple[int, int] | None = None
) -> bool:
    user_fd, user_upload_dir = _open_current_user_upload_dir(
        expected_identity
    )
    os.close(user_fd)
    try:
        path.relative_to(user_upload_dir)
    except ValueError:
        return False
    return True


def _open_current_user_file(
    path: Path, expected_identity: tuple[int, int] | None = None
):
    user_fd, user_upload_dir = _open_current_user_upload_dir(
        expected_identity
    )
    try:
        relative_path = path.relative_to(user_upload_dir)
    except ValueError:
        os.close(user_fd)
        raise _input_error("ARCPY_INPUT_OUTSIDE_SANDBOX") from None
    if not relative_path.parts:
        os.close(user_fd)
        raise _input_error("ARCPY_INPUT_INVALID")

    file_flags = os.O_RDONLY
    file_flags |= getattr(os, "O_CLOEXEC", 0)
    file_flags |= getattr(os, "O_NOFOLLOW", 0)
    directory_fds = [user_fd]
    file_fd = None
    try:
        for part in relative_path.parts[:-1]:
            directory_fds.append(
                os.open(
                    part,
                    _directory_open_flags(),
                    dir_fd=directory_fds[-1],
                )
            )
        file_fd = os.open(
            relative_path.parts[-1], file_flags, dir_fd=directory_fds[-1]
        )
        if not stat.S_ISREG(os.fstat(file_fd).st_mode):
            raise _input_error("ARCPY_INPUT_INVALID")
        stream = os.fdopen(file_fd, "rb")
        file_fd = None
        return stream
    except ArcPyMcpError:
        raise
    except OSError as exc:
        if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
            raise _input_error("ARCPY_INPUT_OUTSIDE_SANDBOX") from None
        raise _input_error("ARCPY_INPUT_INVALID") from None
    finally:
        if file_fd is not None:
            os.close(file_fd)
        for directory_fd in reversed(directory_fds):
            os.close(directory_fd)


def _pin_current_user_file(
    path: Path,
    tenant_fd: int,
    user_upload_dir: Path,
) -> _PreparedUploadLease:
    try:
        relative_path = path.relative_to(user_upload_dir)
    except ValueError:
        raise _input_error("ARCPY_INPUT_OUTSIDE_SANDBOX") from None
    if not relative_path.parts:
        raise _input_error("ARCPY_INPUT_INVALID")

    file_flags = os.O_RDONLY
    file_flags |= getattr(os, "O_CLOEXEC", 0)
    file_flags |= getattr(os, "O_NOFOLLOW", 0)
    directory_fds = [os.dup(tenant_fd)]
    file_fd = None
    try:
        for part in relative_path.parts[:-1]:
            directory_fds.append(
                os.open(
                    part,
                    _directory_open_flags(),
                    dir_fd=directory_fds[-1],
                )
            )
        file_fd = os.open(
            relative_path.parts[-1],
            file_flags,
            dir_fd=directory_fds[-1],
        )
        file_stat = os.fstat(file_fd)
        if not stat.S_ISREG(file_stat.st_mode):
            raise _input_error("ARCPY_INPUT_INVALID")
        lease = _PreparedUploadLease(
            tenant_fd,
            file_fd,
            _PreparedUploadLease._file_identity(file_stat),
            user_upload_dir,
        )
        file_fd = None
        return lease
    except ArcPyMcpError:
        raise
    except OSError as exc:
        if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
            raise _input_error("ARCPY_INPUT_OUTSIDE_SANDBOX") from None
        raise _input_error("ARCPY_INPUT_INVALID") from None
    finally:
        if file_fd is not None:
            os.close(file_fd)
        for directory_fd in reversed(directory_fds):
            os.close(directory_fd)


def _best_effort_unlink_current_user_file(path: Path) -> None:
    directory_fds = []
    try:
        user_fd, user_upload_dir = _open_current_user_upload_dir()
        directory_fds.append(user_fd)
        relative_path = path.relative_to(user_upload_dir)
        if not relative_path.parts:
            return
        for part in relative_path.parts[:-1]:
            directory_fds.append(
                os.open(
                    part,
                    _directory_open_flags(),
                    dir_fd=directory_fds[-1],
                )
            )
        os.unlink(relative_path.parts[-1], dir_fd=directory_fds[-1])
    except (ArcPyMcpError, OSError, ValueError):
        pass
    finally:
        for directory_fd in reversed(directory_fds):
            os.close(directory_fd)


def _best_effort_unlink_from_tenant(
    tenant_fd: int, user_upload_dir: Path, path: Path
) -> None:
    directory_fds = [os.dup(tenant_fd)]
    try:
        relative_path = path.relative_to(user_upload_dir)
        if not relative_path.parts:
            return
        for part in relative_path.parts[:-1]:
            directory_fds.append(
                os.open(
                    part,
                    _directory_open_flags(),
                    dir_fd=directory_fds[-1],
                )
            )
        os.unlink(relative_path.parts[-1], dir_fd=directory_fds[-1])
    except (OSError, ValueError):
        pass
    finally:
        for directory_fd in reversed(directory_fds):
            os.close(directory_fd)


def _resolve_local_input(
    path: str | os.PathLike[str],
    expected_tenant_identity: tuple[int, int] | None = None,
) -> Path:
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
    if (
        not user_context.is_path_in_sandbox(str(resolved))
        or not _is_in_current_user_upload_dir(
            resolved, expected_tenant_identity
        )
    ):
        raise _input_error("ARCPY_INPUT_OUTSIDE_SANDBOX")
    return resolved


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with _open_current_user_file(path) as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().lower()


def _hash_file_descriptor(descriptor: int) -> str:
    digest = hashlib.sha256()
    try:
        with os.fdopen(descriptor, "rb") as stream:
            stream.seek(0)
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise
    return digest.hexdigest().lower()


def _same_regular_file(left, right) -> bool:
    return (
        stat.S_ISREG(left.st_mode)
        and stat.S_ISREG(right.st_mode)
        and left.st_mode == right.st_mode
        and left.st_dev == right.st_dev
        and left.st_ino == right.st_ino
        and left.st_size == right.st_size
    )


def _same_regular_file_state(left, right) -> bool:
    return (
        _same_regular_file(left, right)
        and left.st_mtime_ns == right.st_mtime_ns
        and left.st_ctime_ns == right.st_ctime_ns
        and left.st_nlink == right.st_nlink
    )


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
        ".ain",
        ".aih",
        ".ixs",
        ".mxs",
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


def _checked_archive_file(
    path: Path,
    expected_tenant_identity: tuple[int, int] | None = None,
) -> Path:
    from data_agent import user_context

    if path.is_symlink():
        raise _input_error("ARCPY_INPUT_OUTSIDE_SANDBOX")
    if not path.is_file():
        raise _input_error("ARCPY_INPUT_INVALID")
    try:
        real_path = path.resolve(strict=True)
    except (OSError, RuntimeError):
        raise _input_error("ARCPY_INPUT_INVALID") from None
    if (
        not user_context.is_path_in_sandbox(str(real_path))
        or not _is_in_current_user_upload_dir(
            real_path, expected_tenant_identity
        )
    ):
        raise _input_error("ARCPY_INPUT_OUTSIDE_SANDBOX")
    return real_path


def _new_package_file(
    expected_tenant_identity: tuple[int, int] | None = None,
):
    user_fd, user_upload_dir = _open_current_user_upload_dir(
        expected_tenant_identity
    )
    descriptor = None
    private_dir_fd = None
    private_dir_name = None
    lease_file_fd = None
    lease = None
    entry_name = "entry.zip"
    package_path = None
    try:
        for _ in range(100):
            candidate = f".arcpy-package-{secrets.token_hex(16)}"
            try:
                os.mkdir(candidate, 0o700, dir_fd=user_fd)
                private_dir_name = candidate
                break
            except FileExistsError:
                continue
        if private_dir_name is None:
            raise _input_error("ARCPY_INPUT_PACKAGE_FAILED")
        private_dir_fd = os.open(
            private_dir_name,
            _directory_open_flags(),
            dir_fd=user_fd,
        )
        create_flags = os.O_RDWR | os.O_CREAT | os.O_EXCL
        create_flags |= getattr(os, "O_CLOEXEC", 0)
        create_flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(
            entry_name,
            create_flags,
            0o600,
            dir_fd=private_dir_fd,
        )
        file_stat = os.fstat(descriptor)
        lease_file_fd = os.dup(descriptor)
        package_path = user_upload_dir / private_dir_name / entry_name
        lease = _PreparedUploadLease(
            user_fd,
            lease_file_fd,
            _PreparedUploadLease._file_identity(file_stat),
            user_upload_dir,
            private_dir_fd,
            private_dir_name,
            entry_name,
        )
        user_fd = None
        private_dir_fd = None
        lease_file_fd = None
        try:
            stream = os.fdopen(descriptor, "w+b")
        except Exception:
            os.close(descriptor)
            descriptor = None
            raise
        descriptor = None
        return package_path, stream, lease
    except BaseException:
        if lease is not None:
            if package_path is not None:
                _retry_package_cleanup(lease, package_path)
            lease.close()
            lease = None
        raise
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if lease_file_fd is not None:
            os.close(lease_file_fd)
        if private_dir_fd is not None:
            if private_dir_name is not None and user_fd is not None:
                _retry_unleased_package_cleanup(
                    user_fd,
                    private_dir_fd,
                    private_dir_name,
                    entry_name,
                )
            os.close(private_dir_fd)
        elif private_dir_name is not None and user_fd is not None:
            _retry_empty_private_dir_cleanup(user_fd, private_dir_name)
        if user_fd is not None:
            os.close(user_fd)


def _write_package(
    entries: list[tuple[Path, str]],
    expected_tenant_identity: tuple[int, int] | None = None,
) -> tuple[Path, _PreparedUploadLease]:
    package_path, package_stream, lease = _new_package_file(
        expected_tenant_identity
    )
    try:
        with package_stream:
            with zipfile.ZipFile(
                package_stream,
                mode="w",
                compression=zipfile.ZIP_DEFLATED,
            ) as archive:
                for source, archive_name in sorted(
                    entries, key=lambda item: item[1].casefold()
                ):
                    with _open_current_user_file(
                        source, expected_tenant_identity
                    ) as source_stream:
                        with archive.open(
                            archive_name, mode="w"
                        ) as target_stream:
                            for chunk in iter(
                                lambda: source_stream.read(1024 * 1024), b""
                            ):
                                target_stream.write(chunk)
            package_stream.flush()
            lease.seal()
        return package_path, lease
    except ArcPyMcpError:
        _retry_package_cleanup(lease, package_path)
        lease.close()
        raise
    except Exception:
        _retry_package_cleanup(lease, package_path)
        lease.close()
        raise _input_error("ARCPY_INPUT_PACKAGE_FAILED") from None


def package_local_dataset(
    path: str | os.PathLike[str],
) -> PreparedLocalUpload:
    tenant_fd, user_upload_dir = _open_current_user_upload_dir()
    tenant_identity = _directory_identity(tenant_fd)
    lease = None
    upload_path = None
    delete_after_upload = False
    try:
        source = _resolve_local_input(path, tenant_identity)
        upload_path = source
        logical_name = source.name
        media_type = _media_type(source)

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
                            raise _input_error(
                                "ARCPY_INPUT_OUTSIDE_SANDBOX"
                            )
                    for name in file_names:
                        item = _checked_archive_file(
                            root_path / name, tenant_identity
                        )
                        relative = item.relative_to(source)
                        entries.append(
                            (
                                item,
                                (Path(source.name) / relative).as_posix(),
                            )
                        )
            except ArcPyMcpError:
                raise
            except Exception:
                raise _input_error("ARCPY_INPUT_PACKAGE_FAILED") from None
            if not entries:
                raise _input_error("ARCPY_INPUT_INCOMPLETE")
            upload_path, lease = _write_package(entries, tenant_identity)
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
                (
                    _checked_archive_file(item, tenant_identity),
                    item.name,
                )
                for item in candidates
            ]
            packaged_names = {name.casefold() for _, name in entries}
            required_names = {
                f"{stem}{extension}"
                for extension in (".shp", ".shx", ".dbf")
            }
            if not required_names.issubset(packaged_names):
                raise _input_error("ARCPY_INPUT_INCOMPLETE")
            upload_path, lease = _write_package(entries, tenant_identity)
            logical_name = f"{source.stem}.zip"
            media_type = "application/zip"
            delete_after_upload = True
        elif not source.is_file():
            raise _input_error("ARCPY_INPUT_INVALID")

        if lease is None:
            lease = _pin_current_user_file(
                upload_path, tenant_fd, user_upload_dir
            )
            tenant_fd = None
        else:
            os.close(tenant_fd)
            tenant_fd = None
        size, sha256 = lease.metadata()
        return PreparedLocalUpload(
            upload_path=upload_path,
            source_path=source,
            logical_name=logical_name,
            media_type=media_type,
            size=size,
            sha256=sha256,
            delete_after_upload=delete_after_upload,
            _lease_init=lease,
        )
    except ArcPyMcpError:
        if delete_after_upload and upload_path is not None:
            if lease is not None:
                _retry_package_cleanup(lease, upload_path)
            elif tenant_fd is not None:
                _best_effort_unlink_from_tenant(
                    tenant_fd, user_upload_dir, upload_path
                )
        if lease is not None:
            lease.close()
            lease = None
        raise
    except Exception:
        if delete_after_upload and upload_path is not None:
            if lease is not None:
                _retry_package_cleanup(lease, upload_path)
            elif tenant_fd is not None:
                _best_effort_unlink_from_tenant(
                    tenant_fd, user_upload_dir, upload_path
                )
        if lease is not None:
            lease.close()
            lease = None
        raise _input_error("ARCPY_INPUT_PACKAGE_FAILED") from None
    finally:
        if lease is None and tenant_fd is not None:
            os.close(tenant_fd)


def _sanitize_detail_key(key: Any) -> str:
    if not isinstance(key, str) or _SAFE_DETAIL_KEY_RE.fullmatch(key) is None:
        return "[REDACTED]"
    if any(secret and secret in key for secret in current_runtime_secrets()):
        return "[REDACTED]"
    return key


class _SafeDetailString(str):
    pass


class _RetryableDownloadError(Exception):
    pass


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, _SafeDetailString):
        return str(value)
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
    if isinstance(value, float) and not math.isfinite(value):
        return "[REDACTED]"
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
        job_timeout: float = 900.0,
        dl_job_timeout: float = 3600.0,
        download_timeout: float = 120.0,
        download_attempts: int = 3,
    ) -> None:
        self._config = config
        self._clock = clock
        self._signed_http_client_factory = signed_http_client_factory
        self._upload_timeout = upload_timeout
        self._upload_attempts = max(1, int(upload_attempts))
        self._sleep = sleep
        self._inspection_timeout = inspection_timeout
        self.job_timeout = max(0.0, float(job_timeout))
        self.dl_job_timeout = max(0.0, float(dl_job_timeout))
        self._download_timeout = max(0.0, float(download_timeout))
        self._download_attempts = max(1, int(download_attempts))
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

    @classmethod
    def _catalog_required_extensions(cls, description: dict) -> list[str]:
        declared = description.get("required_extensions", [])
        if not isinstance(declared, list):
            raise ArcPyMcpError(
                "ARCPY_RESPONSE_INVALID", "ArcPy MCP response is invalid"
            )
        normalized: list[str] = []
        for item in declared:
            try:
                extension = cls._normalize_extension(item)
            except ArcPyMcpError:
                raise ArcPyMcpError(
                    "ARCPY_RESPONSE_INVALID", "ArcPy MCP response is invalid"
                ) from None
            if extension is None:
                raise ArcPyMcpError(
                    "ARCPY_RESPONSE_INVALID", "ArcPy MCP response is invalid"
                )
            normalized.append(extension)
        return normalized

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
                hostname = parsed.hostname
                _ = parsed.port
                valid_host = False
                if hostname:
                    try:
                        ipaddress.ip_address(hostname)
                        valid_host = True
                    except ValueError:
                        if not (
                            hostname.count(".") == 3
                            and all(part.isdigit() for part in hostname.split("."))
                        ):
                            ascii_hostname = hostname.encode("idna").decode(
                                "ascii"
                            )
                            if ascii_hostname.endswith("."):
                                ascii_hostname = ascii_hostname[:-1]
                            valid_host = (
                                bool(ascii_hostname)
                                and len(ascii_hostname) <= 253
                                and all(
                                    _DNS_HOST_LABEL_RE.fullmatch(label)
                                    is not None
                                    for label in ascii_hostname.split(".")
                                )
                            )
                valid = (
                    parsed.scheme == "https"
                    and valid_host
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
        options = {"follow_redirects": False}
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
        logger_names = {"", "httpx", "httpcore"}
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

    async def _send_signed_put(
        self,
        http_client,
        signed_url: str,
        prepared: PreparedLocalUpload,
        offset: int,
    ):
        if prepared._lease is None:
            raise ArcPyMcpError(
                "ARCPY_UPLOAD_FAILED", "ArcPy artifact upload failed"
            )
        current_url = signed_url
        registered_secrets = set()
        self._install_signed_transfer_log_filter()
        _begin_signed_transfer()
        try:
            for redirect_count in range(4):
                current_secrets = self._signed_transfer_secrets(current_url)
                new_secrets = current_secrets - registered_secrets
                if new_secrets:
                    register_runtime_secrets(new_secrets)
                    registered_secrets.update(new_secrets)
                async with _AsyncFileByteStream(
                    prepared._lease, offset
                ) as stream:
                    response = await http_client.put(
                        current_url,
                        headers={"Upload-Offset": str(offset)},
                        content=stream,
                        timeout=self._upload_timeout,
                    )
                status_code = getattr(response, "status_code", None)
                if status_code not in {307, 308}:
                    if isinstance(status_code, int) and 300 <= status_code < 400:
                        raise ArcPyMcpError(
                            "ARCPY_UPLOAD_FAILED",
                            "ArcPy artifact upload failed",
                        )
                    return response
                if redirect_count >= 3:
                    raise ArcPyMcpError(
                        "ARCPY_UPLOAD_FAILED", "ArcPy artifact upload failed"
                    )
                location = getattr(response, "headers", {}).get("Location")
                if not isinstance(location, str) or not location.strip():
                    raise ArcPyMcpError(
                        "ARCPY_UPLOAD_FAILED", "ArcPy artifact upload failed"
                    )
                current_url = self._validate_signed_url(
                    urljoin(current_url, location.strip())
                )
            raise ArcPyMcpError(
                "ARCPY_UPLOAD_FAILED", "ArcPy artifact upload failed"
            )
        finally:
            if registered_secrets:
                unregister_runtime_secrets(registered_secrets)
            _end_signed_transfer()

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
        self,
        prepared: PreparedLocalUpload,
        *,
        retain_cleanup_lease: bool = False,
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
                        response = await self._send_signed_put(
                            http_client,
                            signed_url,
                            prepared,
                            offset,
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
        finally:
            if not retain_cleanup_lease:
                prepared._close_lease()

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
        for part in posix_path.parts:
            reserved_stem = part.split(".", 1)[0].rstrip(" .")
            if (
                ":" in part
                or part.endswith((".", " "))
                or any(
                    ord(character) < 32 or ord(character) == 127
                    for character in part
                )
                or _WINDOWS_RESERVED_COMPONENT_RE.fullmatch(reserved_stem)
                is not None
            ):
                raise ArcPyMcpError(
                    "ARCPY_RESPONSE_INVALID", "ArcPy MCP response is invalid"
                )
        return posix_path.as_posix()

    def _inspection_cleanup_deadline(self) -> float:
        cleanup_timeout = max(0.0, float(self._inspection_timeout))
        return self._clock() + cleanup_timeout

    async def _await_inspection_cleanup_task(
        self, task: asyncio.Task, deadline: float
    ) -> tuple[bool, Any]:
        remaining = deadline - self._clock()
        if remaining <= 0:
            task.cancel()
            task.add_done_callback(self._consume_background_task)
            return False, None
        caller_task = asyncio.current_task()
        cancellation_count = (
            caller_task.cancelling() if caller_task is not None else 0
        )
        try:
            return True, await asyncio.wait_for(
                asyncio.shield(task), timeout=remaining
            )
        except asyncio.TimeoutError:
            task.cancel()
            task.add_done_callback(self._consume_background_task)
            return False, None
        except asyncio.CancelledError:
            task.cancel()
            task.add_done_callback(self._consume_background_task)
            if (
                caller_task is not None
                and caller_task.cancelling() > cancellation_count
            ):
                raise
            return False, None
        except Exception:
            return False, None

    async def _inspection_cleanup_call(
        self, name: str, arguments: dict, deadline: float
    ) -> tuple[bool, Any]:
        if deadline - self._clock() <= 0:
            return False, None
        task = asyncio.create_task(self.call_tool(name, arguments))
        return await self._await_inspection_cleanup_task(task, deadline)

    @staticmethod
    def _consume_background_task(task: asyncio.Task) -> None:
        try:
            task.result()
        except BaseException:
            pass

    async def _await_cancelled_inspection_call(
        self, task: asyncio.Task, deadline: float
    ) -> Any:
        completed, response = await self._await_inspection_cleanup_task(
            task, deadline
        )
        return response if completed else None

    async def _cancel_and_drain_inspection_job(
        self, job_id: str, *, _deadline: float | None = None
    ) -> None:
        own_deadline = self._inspection_cleanup_deadline()
        deadline = (
            own_deadline
            if _deadline is None
            else min(_deadline, own_deadline)
        )
        await self._inspection_cleanup_call(
            "cancel_job", {"job_id": job_id}, deadline
        )

        delays = (2, 5, 10, 20)
        terminal_statuses = {
            "succeeded",
            "failed",
            "timed_out",
            "cancelled",
            "interrupted",
        }
        for attempt in range(8):
            completed, job = await self._inspection_cleanup_call(
                "get_job", {"job_id": job_id}, deadline
            )
            if not completed and self._clock() >= deadline:
                return
            if not isinstance(job, dict):
                pass
            else:
                response_job_id = job.get("job_id")
                if (
                    response_job_id is None
                    or response_job_id == job_id
                ) and job.get("status") in terminal_statuses:
                    return
            remaining = deadline - self._clock()
            if remaining <= 0:
                return
            delay = min(
                delays[min(attempt, len(delays) - 1)], remaining
            )
            sleep_task = asyncio.create_task(self._sleep(delay))
            completed, _ = await self._await_inspection_cleanup_task(
                sleep_task, deadline
            )
            if not completed:
                return

    async def _submit_job_without_orphaning(
        self, tool_name: str, arguments: dict
    ) -> str:
        submission_task = asyncio.create_task(
            self.call_tool(tool_name, arguments)
        )
        try:
            submission = await asyncio.shield(submission_task)
        except asyncio.CancelledError:
            cleanup_deadline = self._inspection_cleanup_deadline()
            submission = await self._await_cancelled_inspection_call(
                submission_task, cleanup_deadline
            )
            try:
                job_id = self._required_identifier(submission, "job_id")
            except Exception:
                job_id = None
            if job_id is not None:
                try:
                    await self._cancel_and_drain_inspection_job(
                        job_id, _deadline=cleanup_deadline
                    )
                except Exception:
                    pass
            raise
        return self._required_identifier(submission, "job_id")

    async def _inspect_uploaded_artifact(self, artifact_id: str) -> str:
        if not isinstance(artifact_id, str) or not artifact_id.strip():
            raise ArcPyMcpError(
                "ARCPY_RESPONSE_INVALID", "ArcPy MCP response is invalid"
            )
        job_id = None
        terminal = False
        inspection_task = asyncio.create_task(
            self.call_tool(
                "inspect_dataset",
                {
                    "input_artifact_id": artifact_id,
                    "input_path": ".",
                },
            )
        )
        try:
            inspection = await asyncio.shield(inspection_task)
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
                        "ARCPY_RESPONSE_INVALID",
                        "ArcPy MCP response is invalid",
                    )
                status = job.get("status")
                if status == "succeeded":
                    terminal = True
                    return self._artifact_relative_path(job, artifact_id)
                if status in terminal_failures:
                    terminal = True
                    try:
                        await self.call_tool(
                            "get_job_log", {"job_id": job_id}
                        )
                    except Exception:
                        pass
                    raise ArcPyMcpError(
                        "ARCPY_INSPECTION_FAILED",
                        "ArcPy dataset inspection failed",
                    )
                if status not in {"queued", "running", "pending"}:
                    raise ArcPyMcpError(
                        "ARCPY_RESPONSE_INVALID",
                        "ArcPy MCP response is invalid",
                    )
        except asyncio.CancelledError:
            cleanup_deadline = self._inspection_cleanup_deadline()
            if job_id is None:
                inspection = await self._await_cancelled_inspection_call(
                    inspection_task, cleanup_deadline
                )
                try:
                    job_id = self._required_identifier(
                        inspection, "job_id"
                    )
                except Exception:
                    job_id = None
            if job_id is not None and not terminal:
                try:
                    await self._cancel_and_drain_inspection_job(
                        job_id, _deadline=cleanup_deadline
                    )
                except Exception:
                    pass
            raise
        except Exception:
            if job_id is not None and not terminal:
                await self._cancel_and_drain_inspection_job(job_id)
            raise

    async def prepare_input(
        self, local_path: str | os.PathLike[str]
    ) -> UploadedArtifact:
        packaging_task = asyncio.create_task(
            asyncio.to_thread(package_local_dataset, local_path)
        )
        try:
            prepared = await asyncio.shield(packaging_task)
        except asyncio.CancelledError:
            prepared = None
            try:
                prepared = await _drain_shielded_task(packaging_task)
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
            if prepared is not None:
                cleanup_task = asyncio.create_task(
                    asyncio.to_thread(prepared._cleanup_local_package)
                )
                try:
                    await _drain_shielded_task(cleanup_task)
                finally:
                    prepared._close_lease()
            raise
        artifact_id = None
        try:
            artifact_id = await self._upload_prepared(
                prepared, retain_cleanup_lease=True
            )
            artifact_path = await self._inspect_uploaded_artifact(artifact_id)
            return UploadedArtifact(
                artifact_id=artifact_id,
                artifact_path=artifact_path,
                source_path=prepared.source_path,
                local_package_path=prepared.upload_path,
                delete_local_package=prepared.delete_after_upload,
                _lease_init=prepared._take_lease(),
            )
        except BaseException:
            async def cleanup_failed_input() -> None:
                if artifact_id is not None:
                    await self._best_effort_delete_artifact(artifact_id)
                if prepared.delete_after_upload:
                    await asyncio.to_thread(
                        prepared._cleanup_local_package
                    )

            cleanup_task = asyncio.create_task(cleanup_failed_input())
            await _drain_shielded_task(cleanup_task)
            raise
        finally:
            prepared._close_lease()

    @staticmethod
    def _validate_job_response(job: Any, job_id: str) -> dict:
        if not isinstance(job, dict):
            raise ArcPyMcpError(
                "ARCPY_RESPONSE_INVALID", "ArcPy MCP response is invalid"
            )
        response_id = job.get("job_id")
        if response_id is None:
            response_id = job.get("id")
        if response_id is not None and response_id != job_id:
            raise ArcPyMcpError(
                "ARCPY_RESPONSE_INVALID", "ArcPy MCP response is invalid"
            )
        return job

    @staticmethod
    def _job_error_code(status: str) -> str:
        return {
            "failed": "ARCPY_JOB_FAILED",
            "timed_out": "ARCPY_JOB_TIMED_OUT",
            "cancelled": "ARCPY_JOB_CANCELLED",
            "interrupted": "ARCPY_JOB_INTERRUPTED",
        }.get(status, "ARCPY_JOB_FAILED")

    @staticmethod
    def _sanitize_job_message(value: Any) -> _SafeDetailString | None:
        if not isinstance(value, str) or not value.strip():
            return None
        message = redact_mcp_text(
            value.strip(), current_runtime_secrets()
        )
        message = re.sub(
            r"(?i)https?://[^\s\"']+", "[REDACTED]", message
        )
        message = re.sub(
            r"(?i)(?:[A-Z]:[\\/]|\\\\)[^\r\n]*",
            "[REDACTED]",
            message,
        )
        message = re.sub(
            r"(?<![A-Za-z0-9])/(?!\s)[^\r\n\"']*",
            "[REDACTED]",
            message,
        )
        return _SafeDetailString(message[:2048])

    @classmethod
    def _final_job_messages(cls, logs: Any) -> list[_SafeDetailString]:
        if not isinstance(logs, dict):
            return []
        rows = logs.get("result", logs.get("events", []))
        if not isinstance(rows, list):
            return []
        messages = []
        for row in rows[-20:]:
            if isinstance(row, dict):
                value = row.get("message", row.get("text"))
            else:
                value = row
            message = cls._sanitize_job_message(value)
            if message is not None:
                messages.append(message)
        return messages

    @staticmethod
    def _job_timeout_error() -> ArcPyMcpError:
        return ArcPyMcpError("ARCPY_JOB_TIMED_OUT", "ArcPy job timed out")

    async def _await_job_operation(self, awaitable, deadline: float):
        remaining = deadline - self._clock()
        if remaining <= 0:
            if asyncio.iscoroutine(awaitable):
                awaitable.close()
            raise self._job_timeout_error()
        try:
            return await asyncio.wait_for(awaitable, timeout=remaining)
        except asyncio.TimeoutError:
            raise self._job_timeout_error() from None

    async def _poll_job(
        self,
        job_id: str,
        timeout: float,
        *,
        _deadline: float | None = None,
    ) -> dict:
        if not isinstance(job_id, str) or not job_id.strip():
            raise ArcPyMcpError(
                "ARCPY_RESPONSE_INVALID", "ArcPy MCP response is invalid"
            )
        job_id = job_id.strip()
        own_deadline = self._clock() + max(0.0, float(timeout))
        deadline = (
            own_deadline
            if _deadline is None
            else min(_deadline, own_deadline)
        )
        delays = (2, 5, 10, 20)
        attempt = 0
        terminal_failures = {
            "failed",
            "timed_out",
            "cancelled",
            "interrupted",
        }
        active_statuses = {"queued", "running", "pending", "cancelling"}
        while True:
            remaining = deadline - self._clock()
            if remaining <= 0:
                raise self._job_timeout_error()
            delay = delays[min(attempt, len(delays) - 1)]
            attempt += 1
            await self._await_job_operation(
                self._sleep(min(delay, remaining)), deadline
            )
            if self._clock() > deadline:
                raise self._job_timeout_error()
            job = self._validate_job_response(
                await self._await_job_operation(
                    self.call_tool("get_job", {"job_id": job_id}),
                    deadline,
                ),
                job_id,
            )
            status = job.get("status")
            if status == "succeeded":
                return job
            if status in terminal_failures:
                try:
                    logs = await self._await_job_operation(
                        self.call_tool(
                            "get_job_log", {"job_id": job_id}
                        ),
                        deadline,
                    )
                except Exception:
                    logs = {}
                raise ArcPyMcpError(
                    self._job_error_code(status),
                    "ArcPy job failed",
                    {
                        "status": _SafeDetailString(status),
                        "arcpy_messages": self._final_job_messages(logs),
                    },
                )
            if status not in active_statuses:
                raise ArcPyMcpError(
                    "ARCPY_RESPONSE_INVALID", "ArcPy MCP response is invalid"
                )

    async def wait_for_job(self, job_id: str, timeout: float) -> dict:
        try:
            return await self._poll_job(job_id, timeout)
        except asyncio.CancelledError:
            deadline = self._clock() + self.job_timeout
            cancellation = asyncio.create_task(
                self._cancel_job_with_deadline(job_id, deadline)
            )
            await self._await_inspection_cleanup_task(
                cancellation, deadline
            )
            raise

    async def _cancel_job_with_deadline(
        self, job_id: str, deadline: float
    ) -> dict:
        if not isinstance(job_id, str) or not job_id.strip():
            raise ArcPyMcpError(
                "ARCPY_RESPONSE_INVALID", "ArcPy MCP response is invalid"
            )
        job_id = job_id.strip()
        try:
            response = await self._await_job_operation(
                self.call_tool("cancel_job", {"job_id": job_id}),
                deadline,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            response = None
        if isinstance(response, dict):
            response_id = response.get("job_id")
            if response_id is None:
                response_id = response.get("id")
            if response_id is not None and response_id != job_id:
                raise ArcPyMcpError(
                    "ARCPY_RESPONSE_INVALID", "ArcPy MCP response is invalid"
                )
        remaining = max(0.0, deadline - self._clock())
        return await self._poll_job(
            job_id, remaining, _deadline=deadline
        )

    async def cancel_job(self, job_id: str) -> dict:
        deadline = self._clock() + self.job_timeout
        return await self._cancel_job_with_deadline(job_id, deadline)

    @staticmethod
    def _download_payload(payload: Any, artifact_id: str) -> dict:
        if not isinstance(payload, dict):
            raise ArcPyMcpError(
                "ARCPY_RESPONSE_INVALID", "ArcPy MCP response is invalid"
            )
        nested = payload.get("artifact")
        metadata = dict(nested) if isinstance(nested, dict) else {}
        metadata.update(payload)
        response_id = metadata.get("artifact_id")
        if response_id is not None and response_id != artifact_id:
            raise ArcPyMcpError(
                "ARCPY_RESPONSE_INVALID", "ArcPy MCP response is invalid"
            )
        return metadata

    @classmethod
    def _download_url(cls, payload: dict) -> str:
        value = payload.get("download_url", payload.get("signed_url"))
        try:
            return cls._validate_signed_url(value)
        except ArcPyMcpError:
            raise ArcPyMcpError(
                "ARCPY_DOWNLOAD_FAILED", "ArcPy result download failed"
            ) from None

    @staticmethod
    def _download_sha256(payload: dict) -> str:
        value = payload.get("actual_sha256", payload.get("verified_sha256"))
        if (
            not isinstance(value, str)
            or re.fullmatch(r"[A-Fa-f0-9]{64}", value) is None
        ):
            raise ArcPyMcpError(
                "ARCPY_RESPONSE_INVALID", "ArcPy MCP response is invalid"
            )
        return value.lower()

    @staticmethod
    def _download_size(payload: dict) -> int:
        value = payload.get(
            "actual_size", payload.get("actual_size_bytes", payload.get("size"))
        )
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ArcPyMcpError(
                "ARCPY_RESPONSE_INVALID", "ArcPy MCP response is invalid"
            )
        return value

    @staticmethod
    def _download_name(payload: dict, artifact_id: str) -> str:
        value = payload.get(
            "logical_name", payload.get("file_name", payload.get("name"))
        )
        if value is None:
            suffix = hashlib.sha256(artifact_id.encode("utf-8")).hexdigest()[:16]
            return f"result-{suffix}.bin"
        try:
            parts = _safe_archive_parts(value)
        except ArcPyMcpError:
            raise ArcPyMcpError(
                "ARCPY_RESPONSE_INVALID", "ArcPy MCP response is invalid"
            ) from None
        if len(parts) != 1:
            raise ArcPyMcpError(
                "ARCPY_RESPONSE_INVALID", "ArcPy MCP response is invalid"
            )
        if len(parts[0].encode("utf-8")) > 240:
            raise ArcPyMcpError(
                "ARCPY_RESPONSE_INVALID", "ArcPy MCP response is invalid"
            )
        return parts[0]

    async def _stream_signed_download(
        self,
        http_client,
        signed_url: str,
        stream,
        offset: int,
        expected_size: int,
    ) -> None:
        current_url = signed_url
        registered_secrets = set()
        self._install_signed_transfer_log_filter()
        _begin_signed_transfer()
        try:
            for redirect_count in range(4):
                current_secrets = self._signed_transfer_secrets(current_url)
                new_secrets = current_secrets - registered_secrets
                if new_secrets:
                    register_runtime_secrets(new_secrets)
                    registered_secrets.update(new_secrets)
                headers = {"Accept-Encoding": "identity"}
                if offset:
                    headers["Range"] = f"bytes={offset}-"
                async with http_client.stream(
                    "GET",
                    current_url,
                    headers=headers,
                    timeout=self._download_timeout,
                ) as response:
                    status_code = getattr(response, "status_code", None)
                    if status_code in {301, 302, 303, 307, 308}:
                        if redirect_count >= 3:
                            raise ArcPyMcpError(
                                "ARCPY_DOWNLOAD_FAILED",
                                "ArcPy result download failed",
                            )
                        location = getattr(response, "headers", {}).get(
                            "Location"
                        )
                        if not isinstance(location, str) or not location.strip():
                            raise ArcPyMcpError(
                                "ARCPY_DOWNLOAD_FAILED",
                                "ArcPy result download failed",
                            )
                        try:
                            current_url = self._validate_signed_url(
                                urljoin(current_url, location.strip())
                            )
                        except ArcPyMcpError:
                            raise ArcPyMcpError(
                                "ARCPY_DOWNLOAD_FAILED",
                                "ArcPy result download failed",
                            ) from None
                        continue
                    if status_code == 416:
                        content_range = getattr(response, "headers", {}).get(
                            "Content-Range", ""
                        )
                        match = re.fullmatch(r"bytes \*/(\d+)", content_range)
                        if (
                            offset == expected_size
                            and match is not None
                            and int(match.group(1)) == expected_size
                        ):
                            return
                        raise ArcPyMcpError(
                            "ARCPY_DOWNLOAD_FAILED",
                            "ArcPy result download failed",
                        )
                    if status_code in {
                        401,
                        403,
                        408,
                        425,
                        429,
                        500,
                        502,
                        503,
                        504,
                    }:
                        raise _RetryableDownloadError()
                    if status_code not in {200, 206}:
                        raise ArcPyMcpError(
                            "ARCPY_DOWNLOAD_FAILED",
                            "ArcPy result download failed",
                        )
                    response_headers = getattr(response, "headers", {})
                    content_encoding = response_headers.get(
                        "Content-Encoding", "identity"
                    )
                    if (
                        not isinstance(content_encoding, str)
                        or content_encoding.casefold() not in {"", "identity"}
                    ):
                        raise ArcPyMcpError(
                            "ARCPY_DOWNLOAD_FAILED",
                            "ArcPy result download failed",
                        )
                    if status_code == 206:
                        content_range = response_headers.get(
                            "Content-Range", ""
                        )
                        match = re.fullmatch(
                            r"bytes (\d+)-(\d+)/(\d+|\*)", content_range
                        )
                        if match is None or int(match.group(1)) != offset:
                            raise ArcPyMcpError(
                                "ARCPY_DOWNLOAD_FAILED",
                                "ArcPy result download failed",
                            )
                        end = int(match.group(2))
                        total = match.group(3)
                        if (
                            end < offset
                            or end >= expected_size
                            or total == "*"
                            or int(total) != expected_size
                        ):
                            raise ArcPyMcpError(
                                "ARCPY_DOWNLOAD_FAILED",
                                "ArcPy result download failed",
                            )
                    if offset and status_code == 200:
                        stream.seek(0)
                        stream.truncate(0)
                        write_limit = expected_size
                    else:
                        stream.seek(offset)
                        write_limit = (
                            end + 1
                            if status_code == 206
                            else expected_size
                        )
                    async for chunk in response.aiter_raw():
                        if not isinstance(chunk, (bytes, bytearray)):
                            raise ArcPyMcpError(
                                "ARCPY_DOWNLOAD_FAILED",
                                "ArcPy result download failed",
                            )
                        if stream.tell() + len(chunk) > write_limit:
                            raise ArcPyMcpError(
                                "ARCPY_DOWNLOAD_FAILED",
                                "ArcPy result download failed",
                            )
                        stream.write(chunk)
                    stream.flush()
                    return
            raise ArcPyMcpError(
                "ARCPY_DOWNLOAD_FAILED", "ArcPy result download failed"
            )
        finally:
            if registered_secrets:
                unregister_runtime_secrets(registered_secrets)
            _end_signed_transfer()

    async def _download_artifact(
        self, artifact_id: str
    ) -> _VerifiedDownload:
        workspace = _new_download_workspace()
        stream = None
        part_name = None
        final_name = None
        expected_sha256 = None
        expected_size = None
        try:
            async with self._signed_http_client_factory(
                **self._signed_http_options()
            ) as http_client:
                completed = False
                for attempt in range(self._download_attempts):
                    metadata = self._download_payload(
                        await self.call_tool(
                            "create_download", {"artifact_id": artifact_id}
                        ),
                        artifact_id,
                    )
                    signed_url = self._download_url(metadata)
                    current_sha256 = self._download_sha256(metadata)
                    current_size = self._download_size(metadata)
                    current_name = self._download_name(metadata, artifact_id)
                    if expected_sha256 is None:
                        expected_sha256 = current_sha256
                        expected_size = current_size
                        final_name = current_name
                        part_name = f"{final_name}.part"
                        flags = os.O_RDWR | os.O_CREAT | os.O_EXCL
                        flags |= getattr(os, "O_CLOEXEC", 0)
                        flags |= getattr(os, "O_NOFOLLOW", 0)
                        descriptor = os.open(
                            part_name,
                            flags,
                            0o600,
                            dir_fd=workspace.directory_fd,
                        )
                        stream = os.fdopen(descriptor, "r+b")
                    elif (
                        current_sha256 != expected_sha256
                        or current_size != expected_size
                        or current_name != final_name
                    ):
                        raise ArcPyMcpError(
                            "ARCPY_RESPONSE_INVALID",
                            "ArcPy MCP response is invalid",
                        )
                    stream.seek(0, os.SEEK_END)
                    offset = stream.tell()
                    if expected_size is not None and offset > expected_size:
                        raise ArcPyMcpError(
                            "ARCPY_DOWNLOAD_FAILED",
                            "ArcPy result download failed",
                        )
                    try:
                        await self._stream_signed_download(
                            http_client,
                            signed_url,
                            stream,
                            offset,
                            expected_size,
                        )
                    except (httpx.RequestError, _RetryableDownloadError):
                        if attempt + 1 >= self._download_attempts:
                            raise ArcPyMcpError(
                                "ARCPY_DOWNLOAD_FAILED",
                                "ArcPy result download failed",
                            ) from None
                        continue
                    stream.seek(0, os.SEEK_END)
                    size = stream.tell()
                    if expected_size is not None and size < expected_size:
                        if attempt + 1 < self._download_attempts:
                            continue
                        raise ArcPyMcpError(
                            "ARCPY_DOWNLOAD_FAILED",
                            "ArcPy result download failed",
                        )
                    if expected_size is not None and size != expected_size:
                        raise ArcPyMcpError(
                            "ARCPY_DOWNLOAD_FAILED",
                            "ArcPy result download failed",
                        )
                    completed = True
                    break
                if not completed:
                    raise ArcPyMcpError(
                        "ARCPY_DOWNLOAD_FAILED", "ArcPy result download failed"
                    )

            stream.flush()
            os.fsync(stream.fileno())
            pre_hash_stat = os.fstat(stream.fileno())
            actual_sha256 = await asyncio.to_thread(
                _hash_file_descriptor, os.dup(stream.fileno())
            )
            post_hash_stat = os.fstat(stream.fileno())
            if (
                actual_sha256 != expected_sha256
                or not _same_regular_file_state(
                    pre_hash_stat, post_hash_stat
                )
            ):
                stream.close()
                stream = None
                os.unlink(part_name, dir_fd=workspace.directory_fd)
                raise ArcPyMcpError(
                    "ARCPY_DOWNLOAD_CHECKSUM_MISMATCH",
                    "ArcPy result checksum mismatch",
                )
            try:
                open_stat = post_hash_stat
                part_stat = os.stat(
                    part_name,
                    dir_fd=workspace.directory_fd,
                    follow_symlinks=False,
                )
                if not _same_regular_file_state(open_stat, part_stat):
                    raise ArcPyMcpError(
                        "ARCPY_DOWNLOAD_FAILED",
                        "ArcPy result download failed",
                    )
                os.rename(
                    part_name,
                    final_name,
                    src_dir_fd=workspace.directory_fd,
                    dst_dir_fd=workspace.directory_fd,
                )
                post_rename_stat = os.fstat(stream.fileno())
                if (
                    not _same_regular_file(open_stat, post_rename_stat)
                    or open_stat.st_mtime_ns
                    != post_rename_stat.st_mtime_ns
                    or open_stat.st_nlink != post_rename_stat.st_nlink
                ):
                    raise ArcPyMcpError(
                        "ARCPY_DOWNLOAD_FAILED",
                        "ArcPy result download failed",
                    )
                renamed_sha256 = await asyncio.to_thread(
                    _hash_file_descriptor, os.dup(stream.fileno())
                )
                verified_stat = os.fstat(stream.fileno())
                final_stat = os.stat(
                    final_name,
                    dir_fd=workspace.directory_fd,
                    follow_symlinks=False,
                )
                if (
                    renamed_sha256 != expected_sha256
                    or not _same_regular_file_state(
                        post_rename_stat, verified_stat
                    )
                    or not _same_regular_file_state(
                        verified_stat, final_stat
                    )
                ):
                    raise ArcPyMcpError(
                        "ARCPY_DOWNLOAD_FAILED",
                        "ArcPy result download failed",
                    )
            except ArcPyMcpError:
                raise
            except OSError:
                raise ArcPyMcpError(
                    "ARCPY_DOWNLOAD_FAILED",
                    "ArcPy result download failed",
                ) from None
            final_path = workspace.path / final_name
            verification_paths = [final_path]
            if final_path.suffix.lower() == ".zip":
                archive_stream = os.fdopen(
                    os.dup(stream.fileno()), "rb"
                )
                extraction_task = asyncio.create_task(
                    asyncio.to_thread(
                        _extract_verified_zip,
                        archive_stream,
                        workspace,
                    )
                )
                try:
                    extracted = await asyncio.shield(extraction_task)
                except asyncio.CancelledError:
                    try:
                        await _drain_shielded_task(extraction_task)
                    except Exception:
                        pass
                    raise
                finally:
                    archive_stream.close()
                if not _same_regular_file_state(
                    verified_stat, os.fstat(stream.fileno())
                ):
                    raise ArcPyMcpError(
                        "ARCPY_DOWNLOAD_FAILED",
                        "ArcPy result download failed",
                    )
                outputs = _extracted_dataset_paths(extracted)
                os.unlink(final_name, dir_fd=workspace.directory_fd)
                verification_paths = extracted
            else:
                outputs = [final_path]
            stream.close()
            stream = None
            return _VerifiedDownload(
                outputs, verification_paths, workspace
            )
        except BaseException:
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass
            workspace.cleanup()
            raise

    @staticmethod
    def _result_artifact_ids(job: dict) -> list[str]:
        if job.get("status") != "succeeded":
            raise ArcPyMcpError(
                "ARCPY_RESPONSE_INVALID", "ArcPy MCP response is invalid"
            )
        result = job.get("result")
        if not isinstance(result, dict):
            raise ArcPyMcpError(
                "ARCPY_RESPONSE_INVALID", "ArcPy MCP response is invalid"
            )
        values = result.get("output_artifact_ids")
        if not isinstance(values, list):
            raise ArcPyMcpError(
                "ARCPY_RESPONSE_INVALID", "ArcPy MCP response is invalid"
            )
        artifact_ids = []
        seen = set()
        for value in values:
            if (
                not isinstance(value, str)
                or not value.strip()
                or value in seen
            ):
                raise ArcPyMcpError(
                    "ARCPY_RESPONSE_INVALID", "ArcPy MCP response is invalid"
                )
            seen.add(value)
            artifact_ids.append(value)
        return artifact_ids

    @staticmethod
    def _dataset_summary(job: dict) -> dict:
        result = job.get("result")
        if not isinstance(result, dict):
            return {}
        summary = result.get("dataset_summary")
        if not isinstance(summary, dict):
            return {}
        allowed_scalar_keys = {
            "band_count",
            "cell_size",
            "count",
            "data_type",
            "geometry_type",
            "height",
            "name",
            "spatial_reference",
            "width",
        }
        sanitized = {}
        for key in allowed_scalar_keys:
            value = summary.get(key)
            if (
                value is None
                or isinstance(value, (bool, int))
                or isinstance(value, float) and math.isfinite(value)
            ):
                if key in summary:
                    sanitized[key] = value
            elif isinstance(value, str):
                safe = ArcPyMcpClient._safe_metadata_string(value)
                if safe is not None:
                    sanitized[key] = safe
        extent = summary.get("extent")
        if isinstance(extent, dict):
            safe_extent = {
                key: value
                for key, value in extent.items()
                if key in {"xmin", "ymin", "xmax", "ymax"}
                and isinstance(value, (int, float))
                and not isinstance(value, bool)
                and (not isinstance(value, float) or math.isfinite(value))
            }
            if safe_extent:
                sanitized["extent"] = safe_extent
        fields = summary.get("fields")
        if isinstance(fields, list):
            safe_fields = []
            for field in fields[:1000]:
                if not isinstance(field, dict):
                    continue
                safe_field = {}
                for key in {"name", "type", "alias"}:
                    value = ArcPyMcpClient._safe_metadata_string(
                        field.get(key)
                    )
                    if value is not None:
                        safe_field[key] = value
                for key in {"length", "precision", "scale"}:
                    value = field.get(key)
                    if isinstance(value, (int, float)) and not isinstance(
                        value, bool
                    ) and (
                        not isinstance(value, float) or math.isfinite(value)
                    ):
                        safe_field[key] = value
                if safe_field:
                    safe_fields.append(safe_field)
            sanitized["fields"] = safe_fields
        return sanitized

    @staticmethod
    def _safe_metadata_string(value: Any) -> str | None:
        if (
            not isinstance(value, str)
            or not value
            or len(value) > 512
            or any(
                ord(character) < 32 or ord(character) == 127
                for character in value
            )
        ):
            return None
        redacted = redact_mcp_text(value, current_runtime_secrets())
        if redacted != value or re.search(r"(?i)https?://", value):
            return None
        if (
            re.search(r"(?:^|[^A-Za-z0-9])/(?!/)", value)
            or re.search(r"(?i)(?:^|[^A-Za-z0-9])[A-Z]:[\\/]", value)
            or re.search(r"(?:^|[^A-Za-z0-9])\\\\[^\\]", value)
        ):
            return None
        windows_path = PureWindowsPath(value)
        posix_path = PurePosixPath(value)
        if (
            windows_path.is_absolute()
            or bool(windows_path.drive)
            or posix_path.is_absolute()
            or value.startswith("\\\\")
            or ".." in posix_path.parts
            or ".." in value.replace("\\", "/").split("/")
        ):
            return None
        return value

    @classmethod
    def _registration_parameters(cls, parameters: Any) -> dict:
        if not isinstance(parameters, dict):
            return {}

        def sanitize(value: Any):
            if isinstance(value, float) and not math.isfinite(value):
                return "[REDACTED]"
            if value is None or isinstance(value, (bool, int, float)):
                return value
            if isinstance(value, str):
                return cls._safe_metadata_string(value) or "[REDACTED]"
            if isinstance(value, list):
                return [sanitize(item) for item in value[:1000]]
            if isinstance(value, dict):
                return {
                    key: sanitize(item)
                    for key, item in value.items()
                    if isinstance(key, str)
                    and _SAFE_DETAIL_KEY_RE.fullmatch(key) is not None
                    and key != "artifact_id"
                    and not key.endswith("_artifact_id")
                    and key != "path"
                    and not key.endswith("_path")
                    and key != "inputs"
                }
            return "[REDACTED]"

        return sanitize(parameters)

    @staticmethod
    async def _create_consumer_snapshot(
        download: _VerifiedDownload, path: Path
    ) -> _ConsumerSnapshot:
        snapshot_task = asyncio.create_task(
            asyncio.to_thread(download.consumer_snapshot, path)
        )
        try:
            return await asyncio.shield(snapshot_task)
        except asyncio.CancelledError:
            try:
                snapshot = await _drain_shielded_task(snapshot_task)
            except Exception:
                pass
            else:
                snapshot.close()
            raise

    async def _register_and_map_outputs(
        self,
        download: _VerifiedDownload,
        operation: str,
        tool_params: dict,
        source_paths: list[str],
        owned_mvt_layers: list[dict],
    ) -> tuple[list[str], dict | None]:
        from data_agent import data_catalog

        local_outputs = []
        map_update = None
        vector_suffixes = {".geojson", ".json", ".gpkg", ".shp", ".gdb"}
        for path in download.paths:
            local_path = str(path)
            frame = None
            verified_metadata = None
            snapshot = await self._create_consumer_snapshot(
                download, path
            )
            try:
                if path.suffix.lower() in vector_suffixes:
                    try:
                        import geopandas as gpd

                        payload = await asyncio.to_thread(
                            snapshot.read_bytes,
                            _MAX_VECTOR_SNAPSHOT_BYTES,
                        )
                        if payload is not None:
                            frame = await asyncio.to_thread(
                                gpd.read_file, payload
                            )
                    except Exception:
                        frame = None
                    if frame is not None:
                        verified_metadata = _frame_metadata(
                            frame, snapshot.logical_size
                        )
                    else:
                        verified_metadata = {
                            "file_size_bytes": snapshot.logical_size,
                            "crs": "",
                            "srid": 0,
                            "feature_count": 0,
                            "spatial_extent": None,
                            "column_schema": [],
                        }
                data_catalog.register_tool_output(
                    snapshot.path,
                    operation,
                    tool_params,
                    source_paths=source_paths,
                    storage_path=local_path,
                    verified_metadata=verified_metadata,
                )
            finally:
                snapshot.close()
                download.validate()
            local_outputs.append(local_path)
            if (
                map_update is not None
                or frame is None
                or frame.empty
                or path.suffix.lower() not in vector_suffixes
            ):
                continue
            try:
                map_frame = await asyncio.to_thread(_map_frame, frame)
                from data_agent import tile_server
                from data_agent.user_context import current_user_id

                base_update = _map_update_from_frame(
                    map_frame, path.with_suffix(".geojson"), path.name
                )
                base_layer = base_update["layers"][0]
                feature_count = len(map_frame)
                if feature_count > tile_server.MVT_FEATURE_THRESHOLD:
                    tile_task = asyncio.create_task(
                        asyncio.to_thread(
                            tile_server.create_tile_layer_from_frame,
                            map_frame,
                            current_user_id.get("") or "anonymous",
                            base_layer["name"],
                            source_file=path.name,
                        )
                    )
                    try:
                        tile_metadata = await asyncio.shield(tile_task)
                    except asyncio.CancelledError:
                        try:
                            tile_metadata = await _drain_shielded_task(
                                tile_task
                            )
                        except Exception:
                            tile_metadata = None
                        if tile_metadata is not None:
                            await _cleanup_mvt_layer(
                                tile_server, tile_metadata
                            )
                        raise
                    except Exception:
                        tile_metadata = None
                    if tile_metadata is not None:
                        try:
                            layer_id = tile_metadata.get("layer_id")
                            if not isinstance(layer_id, str) or not layer_id:
                                raise ArcPyMcpError(
                                    "ARCPY_DOWNLOAD_FAILED",
                                    "ArcPy result download failed",
                                )
                            map_update = {
                                "layers": [
                                    {
                                        "name": base_layer["name"],
                                        "type": "mvt",
                                        "tile_url": (
                                            "/api/tiles/"
                                            f"{layer_id}"
                                            "/{z}/{x}/{y}.pbf"
                                        ),
                                        "metadata_url": (
                                            "/api/tiles/"
                                            f"{layer_id}"
                                            "/metadata.json"
                                        ),
                                        "layer_id": layer_id,
                                        "source_layer": (
                                            tile_metadata.get("layer_name")
                                            or "default"
                                        ),
                                        "style": {
                                            "fillColor": "#4682B4",
                                            "fillOpacity": 0.6,
                                            "color": "#333333",
                                            "weight": 1,
                                        },
                                        "visible": True,
                                    }
                                ],
                                "center": base_update["center"],
                                "zoom": base_update["zoom"],
                            }
                            download.validate()
                            if not any(
                                owned.get("layer_id") == layer_id
                                for owned in owned_mvt_layers
                            ):
                                owned_mvt_layers.append(
                                    {"layer_id": layer_id}
                                )
                        except (asyncio.CancelledError, ArcPyMcpError):
                            await _cleanup_mvt_layer(
                                tile_server, tile_metadata
                            )
                            raise
                        except Exception:
                            await _cleanup_mvt_layer(
                                tile_server, tile_metadata
                            )
                        else:
                            continue
                if feature_count > tile_server.FGB_FEATURE_THRESHOLD:
                    fgb_task = asyncio.create_task(
                        asyncio.to_thread(
                            download.write_flatgeobuf, map_frame, path
                        )
                    )
                    try:
                        fgb_path = await asyncio.shield(fgb_task)
                    except asyncio.CancelledError:
                        try:
                            await _drain_shielded_task(fgb_task)
                        except Exception:
                            pass
                        raise
                    except ArcPyMcpError:
                        raise
                    except Exception:
                        fgb_path = None
                    if fgb_path is not None:
                        fgb_snapshot = await self._create_consumer_snapshot(
                            download, fgb_path
                        )
                        try:
                            data_catalog.register_tool_output(
                                fgb_snapshot.path,
                                operation,
                                tool_params,
                                source_paths=source_paths,
                                storage_path=str(fgb_path),
                                verified_metadata=_frame_metadata(
                                    map_frame, fgb_snapshot.logical_size
                                ),
                            )
                        finally:
                            fgb_snapshot.close()
                            download.validate()
                        local_outputs.append(str(fgb_path))
                        map_update = {
                            "layers": [
                                {
                                    "name": base_layer["name"],
                                    "type": "fgb",
                                    "fgb": download.user_relative_path(
                                        fgb_path
                                    ),
                                    "geom_type": base_layer["type"],
                                    "style": {
                                        "fillColor": "#4682B4",
                                        "fillOpacity": 0.6,
                                        "color": "#333333",
                                        "weight": 1,
                                    },
                                    "visible": True,
                                }
                            ],
                            "center": base_update["center"],
                            "zoom": base_update["zoom"],
                        }
                        download.validate()
                        continue
                if path.suffix.lower() in {".geojson", ".json"}:
                    geojson_path = path
                else:
                    map_task = asyncio.create_task(
                        asyncio.to_thread(
                            download.write_geojson, map_frame, path
                        )
                    )
                    try:
                        geojson_path = await asyncio.shield(map_task)
                    except asyncio.CancelledError:
                        try:
                            await _drain_shielded_task(map_task)
                        except Exception:
                            pass
                        raise
                    generated_snapshot = await self._create_consumer_snapshot(
                        download, geojson_path
                    )
                    try:
                        data_catalog.register_tool_output(
                            generated_snapshot.path,
                            operation,
                            tool_params,
                            source_paths=source_paths,
                            storage_path=str(geojson_path),
                            verified_metadata=_frame_metadata(
                                map_frame, generated_snapshot.logical_size
                            ),
                        )
                    finally:
                        generated_snapshot.close()
                        download.validate()
                    local_outputs.append(str(geojson_path))
                map_update = _map_update_from_frame(
                    map_frame,
                    geojson_path,
                    download.user_relative_path(geojson_path),
                )
                download.validate()
            except ArcPyMcpError:
                raise
            except Exception:
                continue
        return local_outputs, map_update

    @staticmethod
    def _normalize_map_output_paths(
        download: _VerifiedDownload,
        map_update: Any,
        geojson_path: Path,
    ) -> tuple[dict | None, list[Path]]:
        if map_update is None:
            return None, []
        if not isinstance(map_update, dict):
            raise ArcPyMcpError(
                "ARCPY_DOWNLOAD_FAILED", "ArcPy result download failed"
            )
        normalized = copy.deepcopy(map_update)
        layers = normalized.get("layers")
        if not isinstance(layers, list):
            return normalized, []
        generated_paths = []
        for layer in layers:
            if not isinstance(layer, dict):
                raise ArcPyMcpError(
                    "ARCPY_DOWNLOAD_FAILED",
                    "ArcPy result download failed",
                )
            if "geojson" in layer:
                if layer.get("geojson") != geojson_path.name:
                    raise ArcPyMcpError(
                        "ARCPY_DOWNLOAD_FAILED",
                        "ArcPy result download failed",
                    )
                layer["geojson"] = download.user_relative_path(
                    geojson_path
                )
            if "fgb" in layer:
                fgb_path = geojson_path.with_suffix(".fgb")
                if layer.get("fgb") != fgb_path.name:
                    raise ArcPyMcpError(
                        "ARCPY_DOWNLOAD_FAILED",
                        "ArcPy result download failed",
                    )
                download.pin_path(fgb_path)
                layer["fgb"] = download.user_relative_path(fgb_path)
                generated_paths.append(fgb_path)
        return normalized, generated_paths

    @staticmethod
    def _mvt_layers_from_map_update(map_update: Any) -> list[dict]:
        if map_update is None:
            return []
        if not isinstance(map_update, dict):
            raise ArcPyMcpError(
                "ARCPY_DOWNLOAD_FAILED", "ArcPy result download failed"
            )
        layers = map_update.get("layers")
        if layers is None:
            return []
        if not isinstance(layers, list):
            raise ArcPyMcpError(
                "ARCPY_DOWNLOAD_FAILED", "ArcPy result download failed"
            )
        result = []
        for layer in layers:
            if not isinstance(layer, dict):
                raise ArcPyMcpError(
                    "ARCPY_DOWNLOAD_FAILED",
                    "ArcPy result download failed",
                )
            if layer.get("type") != "mvt":
                continue
            layer_id = layer.get("layer_id")
            if not isinstance(layer_id, str) or not layer_id:
                raise ArcPyMcpError(
                    "ARCPY_DOWNLOAD_FAILED",
                    "ArcPy result download failed",
                )
            result.append({"layer_id": layer_id})
        return result

    @staticmethod
    def _merge_map_updates(
        current: dict | None, incoming: dict | None
    ) -> dict | None:
        if incoming is None:
            return current
        if current is None:
            return incoming
        if not isinstance(current, dict) or not isinstance(incoming, dict):
            raise ArcPyMcpError(
                "ARCPY_DOWNLOAD_FAILED", "ArcPy result download failed"
            )
        current_layers = current.get("layers")
        incoming_layers = incoming.get("layers")
        if not isinstance(current_layers, list) or not isinstance(
            incoming_layers, list
        ):
            raise ArcPyMcpError(
                "ARCPY_DOWNLOAD_FAILED", "ArcPy result download failed"
            )
        merged = copy.deepcopy(current)
        merged["layers"].extend(copy.deepcopy(incoming_layers))
        return merged

    async def download_job_results(
        self,
        operation: str,
        job: dict,
        source_paths: list[str],
        *,
        _tool_params: dict | None = None,
    ) -> dict:
        started = self._clock()
        health = await self.health_check()
        artifact_ids = self._result_artifact_ids(job)
        tool_params = self._registration_parameters(_tool_params)
        local_outputs = []
        map_update = None
        owned_mvt_layers = []
        completed = False
        try:
            for artifact_id in artifact_ids:
                download = None
                try:
                    download = await self._download_artifact(artifact_id)
                    registered, artifact_map_update = (
                        await self._register_and_map_outputs(
                            download,
                            operation,
                            tool_params,
                            source_paths,
                            owned_mvt_layers,
                        )
                    )
                    local_outputs.extend(registered)
                    for metadata in self._mvt_layers_from_map_update(
                        artifact_map_update
                    ):
                        if not any(
                            owned.get("layer_id")
                            == metadata["layer_id"]
                            for owned in owned_mvt_layers
                        ):
                            owned_mvt_layers.append(metadata)
                    map_update = self._merge_map_updates(
                        map_update, artifact_map_update
                    )
                except BaseException:
                    valid_for_cleanup = False
                    if download is not None:
                        try:
                            download.validate()
                            valid_for_cleanup = True
                        except Exception:
                            pass
                        finally:
                            download.close()
                    if valid_for_cleanup:
                        try:
                            await self._run_remote_cleanup([artifact_id])
                        except BaseException:
                            pass
                    raise
                else:
                    try:
                        download.validate()
                    finally:
                        download.close()
                    if download is not None:
                        await self._run_remote_cleanup([artifact_id])
            worker = health.get("worker") if isinstance(health, dict) else None
            worker = worker if isinstance(worker, dict) else {}
            install = worker.get("install")
            install = install if isinstance(install, dict) else {}
            result = {
                "status": "success",
                "operation": operation,
                "message": f"ArcPy operation completed: {operation}",
                "local_outputs": local_outputs,
                "dataset_summary": self._dataset_summary(job),
                "arcgis_product": self._safe_metadata_string(
                    worker.get("product")
                ),
                "arcgis_version": self._safe_metadata_string(
                    install.get("Version")
                ),
                "duration_seconds": round(self._clock() - started, 3),
                "lineage": {
                    "source_paths": list(source_paths),
                    "tool": operation,
                },
                "map_update": map_update,
            }
            completed = True
            return result
        finally:
            if not completed and owned_mvt_layers:
                from data_agent import tile_server

                await _cleanup_mvt_layers(tile_server, owned_mvt_layers)

    @staticmethod
    def _select_exact_tool_id(matches: dict, query: str) -> str:
        if (
            not isinstance(matches, dict)
            or not isinstance(query, str)
            or not query.strip()
        ):
            raise ArcPyMcpError(
                "ARCPY_TOOL_NOT_ALLOWED",
                "Requested ArcPy MCP tool is not allowed",
            )
        rows = matches.get("result") or matches.get("tools") or []
        rows = rows if isinstance(rows, list) else []
        exact = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            actual_id = row.get("id")
            legacy_id = row.get("tool_id")
            if actual_id is None:
                actual_id = legacy_id
            elif legacy_id is not None and legacy_id != actual_id:
                raise ArcPyMcpError(
                    "ARCPY_RESPONSE_INVALID",
                    "ArcPy MCP response is invalid",
                )
            if actual_id == query:
                exact.append(row)
        if len(exact) == 1:
            selected = exact[0]
            tool_id = selected.get("id", selected.get("tool_id"))
            selected_category = re.sub(
                r"[^a-z0-9]+",
                "",
                str(selected.get("category") or "").casefold(),
            )
            tokens = {
                token
                for token in re.split(r"[._:\-]+", tool_id.casefold())
                if token
            }
            normalized = "".join(
                character
                for character in tool_id.casefold()
                if character.isalnum()
            )
            if (
                re.match(r"(?i)^dl(?:[._:\-]|$)", tool_id) is not None
                or selected_category in {"dl", "deeplearning"}
                or tokens & {"train", "training"}
                or "traindeeplearningmodel" in normalized
                or normalized
                in {
                    "dldetectobjects",
                    "dlclassifypixels",
                    "dlclassifyobjects",
                    "dldetectchange",
                    "detectobjectsusingdeeplearning",
                    "classifypixelsusingdeeplearning",
                    "classifyobjectsusingdeeplearning",
                    "detectchangeusingdeeplearning",
                }
            ):
                raise ArcPyMcpError(
                    "ARCPY_TOOL_NOT_ALLOWED",
                    "Requested ArcPy MCP tool is not allowed",
                )
            return tool_id
        raise ArcPyMcpError(
            "ARCPY_TOOL_NOT_ALLOWED",
            f"No exact allowlisted ArcPy tool for: {query}",
        )

    @staticmethod
    def _validate_catalog_parameters(parameters: dict, schema: dict) -> None:
        if not isinstance(parameters, dict) or not isinstance(schema, dict):
            raise ArcPyMcpError(
                "ARCPY_RESPONSE_INVALID", "ArcPy MCP response is invalid"
            )
        try:
            jsonschema.validate(parameters, schema)
        except jsonschema.ValidationError as exc:
            raise ArcPyMcpError(
                "ARCPY_TOOL_NOT_ALLOWED", exc.message
            ) from None
        except jsonschema.SchemaError:
            raise ArcPyMcpError(
                "ARCPY_RESPONSE_INVALID", "ArcPy MCP response is invalid"
            ) from None

    @staticmethod
    def _bind_prepared_inputs(
        parameters: dict,
        prepared: dict[str, UploadedArtifact],
    ) -> dict:
        arguments = dict(parameters)
        for prefix, artifact in prepared.items():
            arguments[f"{prefix}_artifact_id"] = artifact.artifact_id
            arguments[f"{prefix}_path"] = artifact.artifact_path
        return arguments

    @classmethod
    def _bind_dedicated_inputs(
        cls,
        remote_tool: str,
        parameters: dict,
        prepared: dict[str, UploadedArtifact],
    ) -> dict:
        arguments = cls._bind_prepared_inputs(parameters, prepared)
        if remote_tool == "export_map_layout":
            if set(prepared) != {"input"} or "input_path" not in arguments:
                raise ArcPyMcpError(
                    "ARCPY_INVALID_ARGUMENT",
                    "ArcPy export input is invalid",
                )
            arguments["aprx_path"] = arguments.pop("input_path")
        return arguments

    @staticmethod
    def _catalog_input_bindings(
        description: dict,
    ) -> dict[str, tuple[str, str]]:
        rows = description.get("inputs", [])
        if not isinstance(rows, list):
            raise ArcPyMcpError(
                "ARCPY_RESPONSE_INVALID", "ArcPy MCP response is invalid"
            )
        bindings: dict[str, tuple[str, str]] = {}
        seen_fields = set()
        for row in rows:
            if not isinstance(row, dict) or row.get("multiple") is True:
                raise ArcPyMcpError(
                    "ARCPY_TOOL_NOT_ALLOWED",
                    "Requested ArcPy MCP tool is not allowed",
                )
            artifact_field = row.get("artifact_id_field")
            path_field = row.get("path_field")
            container_field = row.get("container_field")
            if (
                not isinstance(artifact_field, str)
                or not artifact_field.endswith("_artifact_id")
                or not isinstance(path_field, str)
                or not path_field.endswith("_path")
                or container_field is not None
            ):
                raise ArcPyMcpError(
                    "ARCPY_RESPONSE_INVALID",
                    "ArcPy MCP response is invalid",
                )
            prefix = artifact_field[: -len("_artifact_id")]
            if (
                not prefix
                or path_field != f"{prefix}_path"
                or _SAFE_DETAIL_KEY_RE.fullmatch(prefix) is None
                or prefix in bindings
                or artifact_field in seen_fields
                or path_field in seen_fields
            ):
                raise ArcPyMcpError(
                    "ARCPY_RESPONSE_INVALID",
                    "ArcPy MCP response is invalid",
                )
            bindings[prefix] = (artifact_field, path_field)
            seen_fields.update({artifact_field, path_field})
        return bindings

    @staticmethod
    def _reject_catalog_remote_inputs(parameters: dict) -> None:
        if not isinstance(parameters, dict):
            raise ArcPyMcpError(
                "ARCPY_TOOL_NOT_ALLOWED",
                "Requested ArcPy MCP tool is not allowed",
            )
        for key in parameters:
            if not isinstance(key, str) or (
                key in {"artifact_id", "path", "inputs"}
                or key.endswith("_artifact_id")
                or key.endswith("_path")
            ):
                raise ArcPyMcpError(
                    "ARCPY_TOOL_NOT_ALLOWED",
                    "Requested ArcPy MCP tool is not allowed",
                )

    @staticmethod
    def _multi_input_artifact_ids(arguments: dict) -> list[str]:
        rows = arguments.get("inputs") if isinstance(arguments, dict) else None
        if not isinstance(rows, list):
            return []
        return list(
            dict.fromkeys(
                row["artifact_id"]
                for row in rows
                if isinstance(row, dict)
                and isinstance(row.get("artifact_id"), str)
                and row["artifact_id"]
            )
        )

    async def _delete_artifacts(
        self, artifact_ids: list[str], deadline: float | None = None
    ) -> None:
        if deadline is None:
            deadline = self._inspection_cleanup_deadline()
        for artifact_id in dict.fromkeys(artifact_ids):
            completed, _ = await self._inspection_cleanup_call(
                "delete_artifact",
                {"artifact_id": artifact_id},
                deadline,
            )
            if not completed and self._clock() >= deadline:
                return

    async def _run_remote_cleanup(self, artifact_ids: list[str]) -> None:
        if not artifact_ids:
            return
        deadline = self._inspection_cleanup_deadline()
        cleanup_task = asyncio.create_task(
            self._delete_artifacts(artifact_ids, deadline)
        )
        remaining = deadline - self._clock()
        if remaining <= 0:
            cleanup_task.cancel()
            cleanup_task.add_done_callback(self._consume_background_task)
            return
        try:
            await asyncio.wait_for(
                asyncio.shield(cleanup_task), timeout=remaining
            )
        except asyncio.TimeoutError:
            cleanup_task.cancel()
            cleanup_task.add_done_callback(self._consume_background_task)
        except asyncio.CancelledError:
            await self._await_inspection_cleanup_task(
                cleanup_task, deadline
            )
            raise
        except Exception:
            pass

    async def _cleanup_prepared_inputs(
        self,
        prepared: list[UploadedArtifact],
        *,
        delete_remote: bool,
    ) -> None:
        for item in prepared:
            try:
                if item.delete_local_package:
                    local_cleanup = asyncio.create_task(
                        asyncio.to_thread(item._cleanup_local_package)
                    )
                    await _drain_shielded_task(local_cleanup)
            finally:
                item._close_lease()
        if delete_remote:
            await self._run_remote_cleanup(
                [item.artifact_id for item in prepared]
            )

    @staticmethod
    def _apply_operation_timing(
        result: dict, health: dict, started: float, finished: float
    ) -> dict:
        worker = health.get("worker") if isinstance(health, dict) else None
        worker = worker if isinstance(worker, dict) else {}
        install = worker.get("install")
        install = install if isinstance(install, dict) else {}
        updated = dict(result)
        updated["arcgis_product"] = ArcPyMcpClient._safe_metadata_string(
            worker.get("product")
        )
        updated["arcgis_version"] = ArcPyMcpClient._safe_metadata_string(
            install.get("Version")
        )
        updated["duration_seconds"] = round(finished - started, 3)
        return updated

    async def _execute_operation(
        self,
        remote_tool: str,
        local_inputs: dict[str, str],
        parameters: dict,
        deep_learning: bool,
    ) -> dict:
        started = self._clock()
        health = await self.health_check()
        required_extension = {
            "calculate_slope": "Spatial",
            "zonal_statistics": "Spatial",
        }.get(remote_tool)
        if required_extension is not None:
            await self.get_capabilities(
                required_extension=required_extension
            )
        prepared_by_name: dict[str, UploadedArtifact] = {}
        try:
            for name, path in local_inputs.items():
                prepared_by_name[name] = await self.prepare_input(path)
            arguments = self._bind_dedicated_inputs(
                remote_tool, parameters, prepared_by_name
            )
            job_id = await self._submit_job_without_orphaning(
                remote_tool, arguments
            )
            timeout = self.dl_job_timeout if deep_learning else self.job_timeout
            job = await self.wait_for_job(job_id, timeout)
            result = await self.download_job_results(
                remote_tool,
                job,
                list(local_inputs.values()),
                _tool_params=parameters,
            )
            return self._apply_operation_timing(
                result, health, started, self._clock()
            )
        finally:
            await self._cleanup_prepared_inputs(
                list(prepared_by_name.values()), delete_remote=True
            )

    async def _submit_wait_download_as(
        self,
        operation: str,
        remote_tool: str,
        arguments: dict,
        source_paths: list[str],
    ) -> dict:
        artifact_ids = self._multi_input_artifact_ids(arguments)
        try:
            job_id = await self._submit_job_without_orphaning(
                remote_tool, arguments
            )
            job = await self.wait_for_job(job_id, self.job_timeout)
            return await self.download_job_results(
                operation,
                job,
                source_paths,
                _tool_params=arguments,
            )
        finally:
            await self._run_remote_cleanup(artifact_ids)

    async def _submit_wait_download(
        self,
        remote_tool: str,
        arguments: dict,
        source_paths: list[str],
    ) -> dict:
        return await self._submit_wait_download_as(
            remote_tool, remote_tool, arguments, source_paths
        )

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

    async def inspect_local_dataset(self, input_path: str) -> dict:
        started = self._clock()
        health = await self.health_check()
        prepared = None
        try:
            prepared = await self.prepare_input(input_path)
            result = {
                "status": "success",
                "operation": "inspect_dataset",
                "dataset": {"name": prepared.source_path.name},
            }
            return self._apply_operation_timing(
                result, health, started, self._clock()
            )
        finally:
            if prepared is not None:
                await self._cleanup_prepared_inputs(
                    [prepared], delete_remote=True
                )

    async def run_multi_input(
        self,
        remote_tool: str,
        local_inputs: list[str],
        parameters: dict,
    ) -> dict:
        started = self._clock()
        health = await self.health_check()
        prepared = []
        remote_cleanup_handed_off = False
        try:
            for path in local_inputs:
                prepared.append(await self.prepare_input(path))
            arguments = dict(parameters)
            arguments["inputs"] = [
                {
                    "artifact_id": item.artifact_id,
                    "path": item.artifact_path,
                }
                for item in prepared
            ]
            remote_cleanup_handed_off = True
            result = await self._submit_wait_download(
                remote_tool, arguments, list(local_inputs)
            )
            return self._apply_operation_timing(
                result, health, started, self._clock()
            )
        finally:
            await self._cleanup_prepared_inputs(
                prepared, delete_remote=not remote_cleanup_handed_off
            )

    async def run_deep_learning(
        self,
        remote_tool: str,
        imagery_inputs: dict[str, str],
        model_path: str,
        parameters: dict,
    ) -> dict:
        allowed = {
            "detect_objects",
            "classify_pixels",
            "classify_objects",
            "detect_change",
        }
        if remote_tool not in allowed:
            raise ArcPyMcpError(
                "ARCPY_TOOL_NOT_ALLOWED",
                "Requested ArcPy MCP tool is not allowed",
            )
        await self.health_check()
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
        normalized_category = re.sub(
            r"[^a-z0-9]+", "", (category or "").casefold()
        )
        if normalized_category in {"dl", "deeplearning"}:
            raise ArcPyMcpError(
                "ARCPY_TOOL_NOT_ALLOWED",
                "Requested ArcPy MCP tool is not allowed",
            )
        started = self._clock()
        health = await self.health_check()
        matches = await self.call_tool(
            "search_tools", {"query": query, "category": category or None}
        )
        tool_id = self._select_exact_tool_id(matches, query)
        description = await self.call_tool(
            "describe_tool", {"tool_id": tool_id}
        )
        if not isinstance(description, dict):
            raise ArcPyMcpError(
                "ARCPY_RESPONSE_INVALID", "ArcPy MCP response is invalid"
            )
        description_id = description.get("id")
        legacy_description_id = description.get("tool_id")
        if description_id is None:
            description_id = legacy_description_id or tool_id
        elif (
            legacy_description_id is not None
            and legacy_description_id != description_id
        ):
            raise ArcPyMcpError(
                "ARCPY_RESPONSE_INVALID", "ArcPy MCP response is invalid"
            )
        description_category = re.sub(
            r"[^a-z0-9]+",
            "",
            str(description.get("category") or "").casefold(),
        )
        if description_id != tool_id or description_category in {
            "dl",
            "deeplearning",
        }:
            raise ArcPyMcpError(
                "ARCPY_TOOL_NOT_ALLOWED",
                "Requested ArcPy MCP tool is not allowed",
            )
        required_extensions = self._catalog_required_extensions(description)
        schema = description.get("parameters")
        legacy_schema = description.get("input_schema")
        if schema is None:
            schema = legacy_schema
        elif legacy_schema is not None and legacy_schema != schema:
            raise ArcPyMcpError(
                "ARCPY_RESPONSE_INVALID", "ArcPy MCP response is invalid"
            )
        legacy_contract = (
            "inputs" not in description and "parameters" not in description
        )
        self._reject_catalog_remote_inputs(parameters)
        if not isinstance(local_inputs, dict):
            raise ArcPyMcpError(
                "ARCPY_TOOL_NOT_ALLOWED",
                "Requested ArcPy MCP tool is not allowed",
            )
        bindings: dict[str, tuple[str, str]] = {}
        if legacy_contract:
            if any(
                not isinstance(prefix, str)
                or _SAFE_DETAIL_KEY_RE.fullmatch(prefix) is None
                for prefix in local_inputs
            ):
                raise ArcPyMcpError(
                    "ARCPY_TOOL_NOT_ALLOWED",
                    "Requested ArcPy MCP tool is not allowed",
                )
            self._validate_catalog_parameters(parameters, schema)
        else:
            bindings = self._catalog_input_bindings(description)
            if any(prefix not in bindings for prefix in local_inputs):
                raise ArcPyMcpError(
                    "ARCPY_TOOL_NOT_ALLOWED",
                    "Requested ArcPy MCP tool is not allowed",
                )
        for extension in required_extensions:
            await self.get_capabilities(required_extension=extension)
        prepared_by_name: dict[str, UploadedArtifact] = {}
        try:
            for name, path in local_inputs.items():
                prepared_by_name[name] = await self.prepare_input(path)
            if legacy_contract:
                arguments = self._bind_prepared_inputs(
                    parameters, prepared_by_name
                )
            else:
                arguments = dict(parameters)
                for prefix, artifact in prepared_by_name.items():
                    artifact_field, path_field = bindings[prefix]
                    arguments[artifact_field] = artifact.artifact_id
                    arguments[path_field] = artifact.artifact_path
                self._validate_catalog_parameters(arguments, schema)
            job_id = await self._submit_job_without_orphaning(
                "submit_job",
                {"tool_id": tool_id, "parameters": arguments},
            )
            job = await self.wait_for_job(job_id, self.job_timeout)
            result = await self.download_job_results(
                tool_id,
                job,
                list(local_inputs.values()),
                _tool_params=parameters,
            )
            return self._apply_operation_timing(
                result, health, started, self._clock()
            )
        finally:
            await self._cleanup_prepared_inputs(
                list(prepared_by_name.values()), delete_remote=True
            )

#!/usr/bin/env python3
"""Run one sanitized end-to-end smoke test against the ArcPy MCP service."""

from __future__ import annotations

import argparse
import asyncio
from contextlib import redirect_stdout
import errno
import json
import math
import os
from pathlib import Path
import shutil
import stat
import sys
import time
import uuid


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_agent.arcpy_mcp_client import ArcPyMcpClient, ArcPyMcpError
from data_agent.mcp_hub import get_mcp_hub
from data_agent.toolsets.arcpy_mcp_toolset import get_arcpy_mcp_client
from data_agent.user_context import get_user_upload_dir


def _directory_open_flags() -> int:
    flags = os.O_RDONLY
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    return flags


def _open_absolute_directory(path: Path) -> int:
    if not path.is_absolute():
        raise ArcPyMcpError(
            "ARCPY_INPUT_OUTSIDE_SANDBOX",
            "ArcPy smoke output is outside the user sandbox",
        )
    current_fd = os.open(os.path.sep, _directory_open_flags())
    try:
        for part in path.parts[1:]:
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
            "ARCPY_INPUT_OUTSIDE_SANDBOX",
            "ArcPy smoke output is outside the user sandbox",
        ) from None
    finally:
        if current_fd is not None:
            os.close(current_fd)


def _directory_identity(descriptor: int) -> tuple[int, int]:
    value = os.fstat(descriptor)
    if not stat.S_ISDIR(value.st_mode):
        raise ArcPyMcpError(
            "ARCPY_INPUT_OUTSIDE_SANDBOX",
            "ArcPy smoke output is outside the user sandbox",
        )
    return value.st_dev, value.st_ino


class _PinnedOutputDirectory:
    def __init__(
        self,
        user_root: Path,
        path: Path,
        relative_parts: tuple[str, ...],
        root_fd: int,
        directory_fd: int,
    ) -> None:
        self.user_root = user_root
        self.path = path
        self._relative_parts = relative_parts
        self._root_fd = root_fd
        self._directory_fd = directory_fd
        self._root_identity = _directory_identity(root_fd)
        self._pinned_directory_identity = _directory_identity(directory_fd)
        self._staged_inputs: dict[str, tuple[int, int]] = {}
        self._closed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def _validate_root_binding(self) -> None:
        current_fd = _open_absolute_directory(self.user_root)
        try:
            if _directory_identity(current_fd) != self._root_identity:
                raise ArcPyMcpError(
                    "ARCPY_INPUT_OUTSIDE_SANDBOX",
                    "ArcPy smoke output is outside the user sandbox",
                )
        finally:
            os.close(current_fd)

    def _open_relative(
        self, parts: tuple[str, ...], *, directory: bool
    ) -> int:
        current_fd = os.dup(self._root_fd)
        try:
            for index, part in enumerate(parts):
                is_last = index == len(parts) - 1
                if not is_last or directory:
                    flags = _directory_open_flags()
                else:
                    flags = os.O_RDONLY
                    flags |= getattr(os, "O_CLOEXEC", 0)
                    flags |= getattr(os, "O_NOFOLLOW", 0)
                    flags |= getattr(os, "O_NONBLOCK", 0)
                next_fd = os.open(part, flags, dir_fd=current_fd)
                os.close(current_fd)
                current_fd = next_fd
            result = current_fd
            current_fd = None
            return result
        except OSError:
            raise ArcPyMcpError(
                "ARCPY_INPUT_OUTSIDE_SANDBOX",
                "ArcPy smoke output is outside the user sandbox",
            ) from None
        finally:
            if current_fd is not None:
                os.close(current_fd)

    def _validate_directory_binding(self) -> None:
        self._validate_root_binding()
        current_fd = self._open_relative(
            self._relative_parts, directory=True
        )
        try:
            if (
                _directory_identity(current_fd)
                != self._pinned_directory_identity
            ):
                raise ArcPyMcpError(
                    "ARCPY_INPUT_OUTSIDE_SANDBOX",
                    "ArcPy smoke output is outside the user sandbox",
                )
        finally:
            os.close(current_fd)

    def copy_input(self, input_path: str | Path) -> Path:
        self._validate_directory_binding()
        source = Path(
            os.path.abspath(os.fspath(Path(input_path).expanduser()))
        )
        source_flags = os.O_RDONLY
        source_flags |= getattr(os, "O_CLOEXEC", 0)
        source_flags |= getattr(os, "O_NOFOLLOW", 0)
        source_flags |= getattr(os, "O_NONBLOCK", 0)
        source_fd = None
        target_fd = None
        target_name = None
        try:
            source_fd = os.open(source, source_flags)
            if not stat.S_ISREG(os.fstat(source_fd).st_mode):
                raise ArcPyMcpError(
                    "ARCPY_INPUT_INVALID", "ArcPy smoke input is invalid"
                )
            suffix = source.suffix.lower()
            if (
                len(suffix) > 12
                or not suffix.startswith(".")
                or not suffix[1:].isascii()
                or not suffix[1:].isalnum()
            ):
                suffix = ".bin"
            target_name = (
                f"arcpy-smoke-input-{uuid.uuid4().hex}{suffix}"
            )
            target_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            target_flags |= getattr(os, "O_CLOEXEC", 0)
            target_flags |= getattr(os, "O_NOFOLLOW", 0)
            target_fd = os.open(
                target_name,
                target_flags,
                0o600,
                dir_fd=self._directory_fd,
            )
            with os.fdopen(os.dup(source_fd), "rb") as source_stream, os.fdopen(
                os.dup(target_fd), "wb"
            ) as target_stream:
                shutil.copyfileobj(
                    source_stream, target_stream, 1024 * 1024
                )
                target_stream.flush()
            target_stat = os.fstat(target_fd)
            self._staged_inputs[target_name] = (
                target_stat.st_dev,
                target_stat.st_ino,
            )
            self._validate_directory_binding()
            return self.path / target_name
        except ArcPyMcpError:
            raise
        except OSError:
            raise ArcPyMcpError(
                "ARCPY_INPUT_INVALID", "ArcPy smoke input is invalid"
            ) from None
        finally:
            if target_fd is not None:
                os.close(target_fd)
            if source_fd is not None:
                os.close(source_fd)
            if target_name is not None and target_name not in self._staged_inputs:
                try:
                    os.unlink(target_name, dir_fd=self._directory_fd)
                except OSError:
                    pass

    def validate_output(self, value: object) -> str:
        if not isinstance(value, str) or not value or "\x00" in value:
            raise ArcPyMcpError(
                "ARCPY_RESPONSE_INVALID", "ArcPy smoke response is invalid"
            )
        candidate = Path(value)
        if not candidate.is_absolute():
            candidate = Path.cwd() / candidate
        candidate = Path(os.path.abspath(os.fspath(candidate)))
        try:
            relative = candidate.relative_to(self.user_root)
        except ValueError:
            raise ArcPyMcpError(
                "ARCPY_RESPONSE_INVALID", "ArcPy smoke response is invalid"
            ) from None
        if not relative.parts:
            raise ArcPyMcpError(
                "ARCPY_RESPONSE_INVALID", "ArcPy smoke response is invalid"
            )
        try:
            self._validate_root_binding()
            descriptor = self._open_relative(
                tuple(relative.parts), directory=False
            )
        except ArcPyMcpError:
            raise ArcPyMcpError(
                "ARCPY_RESPONSE_INVALID", "ArcPy smoke response is invalid"
            ) from None
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise ArcPyMcpError(
                    "ARCPY_RESPONSE_INVALID",
                    "ArcPy smoke response is invalid",
                )
        finally:
            os.close(descriptor)
        return candidate.name

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for name, expected_identity in self._staged_inputs.items():
            try:
                current = os.stat(
                    name,
                    dir_fd=self._directory_fd,
                    follow_symlinks=False,
                )
                if (
                    stat.S_ISREG(current.st_mode)
                    and (current.st_dev, current.st_ino) == expected_identity
                ):
                    os.unlink(name, dir_fd=self._directory_fd)
            except OSError:
                pass
        self._staged_inputs.clear()
        os.close(self._directory_fd)
        os.close(self._root_fd)


def _sandbox_output_directory(
    output_dir: str | Path,
) -> _PinnedOutputDirectory:
    user_root = Path(
        os.path.abspath(os.fspath(Path(get_user_upload_dir())))
    )
    candidate = Path(output_dir).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    candidate = Path(os.path.abspath(os.fspath(candidate)))
    try:
        relative = candidate.relative_to(user_root)
    except ValueError:
        raise ArcPyMcpError(
            "ARCPY_INPUT_OUTSIDE_SANDBOX",
            "ArcPy smoke output is outside the user sandbox",
        ) from None
    root_fd = _open_absolute_directory(user_root)
    current_fd = os.dup(root_fd)
    try:
        for part in relative.parts:
            try:
                os.mkdir(part, 0o700, dir_fd=current_fd)
            except FileExistsError:
                pass
            next_fd = os.open(
                part, _directory_open_flags(), dir_fd=current_fd
            )
            os.close(current_fd)
            current_fd = next_fd
        result = _PinnedOutputDirectory(
            user_root,
            candidate,
            tuple(relative.parts),
            root_fd,
            current_fd,
        )
        root_fd = None
        current_fd = None
        return result
    except ArcPyMcpError:
        raise
    except OSError as exc:
        if exc.errno not in {errno.ELOOP, errno.ENOTDIR}:
            code = "ARCPY_INPUT_INVALID"
            message = "ArcPy smoke output is invalid"
        else:
            code = "ARCPY_INPUT_OUTSIDE_SANDBOX"
            message = "ArcPy smoke output is outside the user sandbox"
        raise ArcPyMcpError(
            code,
            message,
        ) from None
    finally:
        if current_fd is not None:
            os.close(current_fd)
        if root_fd is not None:
            os.close(root_fd)


def _copy_smoke_input(
    input_path: str | Path, output_dir: _PinnedOutputDirectory
) -> Path:
    return output_dir.copy_input(input_path)


def _version_from_health(health: dict) -> str | None:
    worker = health.get("worker") if isinstance(health, dict) else None
    install = worker.get("install") if isinstance(worker, dict) else None
    value = install.get("Version") if isinstance(install, dict) else None
    return ArcPyMcpClient._safe_metadata_string(value)


async def run_smoke(
    input_path: str | Path,
    output_dir: str | Path,
    *,
    client=None,
) -> dict:
    """Run health, capability, upload, buffer, and verified download checks."""
    owns_client = client is None
    if owns_client:
        get_mcp_hub().load_config()
        client = get_arcpy_mcp_client()

    started = time.monotonic()
    try:
        health = await client.health_check()
        await client.get_capabilities()
        with _sandbox_output_directory(output_dir) as destination:
            copied_input = _copy_smoke_input(input_path, destination)
            result = await client.run_dedicated(
                remote_tool="buffer_features",
                local_inputs={"input": str(copied_input)},
                parameters={
                    "distance": "10 Meters",
                    "output_name": "arcpy_mcp_smoke_buffer.zip",
                    "dissolve_option": "NONE",
                },
            )
            if not isinstance(result, dict) or result.get("status") != "success":
                raise ArcPyMcpError(
                    "ARCPY_JOB_FAILED", "ArcPy smoke buffer operation failed"
                )
            raw_outputs = result.get("local_outputs")
            if not isinstance(raw_outputs, list) or not raw_outputs:
                raise ArcPyMcpError(
                    "ARCPY_RESPONSE_INVALID",
                    "ArcPy smoke response is invalid",
                )
            output_names = [
                destination.validate_output(value) for value in raw_outputs
            ]

        duration = result.get("duration_seconds")
        if (
            isinstance(duration, bool)
            or not isinstance(duration, (int, float))
            or not math.isfinite(duration)
            or duration < 0
        ):
            duration = round(time.monotonic() - started, 3)
        version = ArcPyMcpClient._safe_metadata_string(
            result.get("arcgis_version")
        ) or _version_from_health(health)
        return {
            "status": "success",
            "arcgis_version": version,
            "local_outputs": output_names,
            "duration_seconds": duration,
        }
    finally:
        if owns_client:
            await client.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the ArcPy MCP buffer smoke verification."
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        with redirect_stdout(sys.stderr):
            summary = asyncio.run(run_smoke(args.input, args.output_dir))
    except ArcPyMcpError as exc:
        print(
            json.dumps({"status": "error", "error_code": exc.code}),
            file=sys.stderr,
        )
        return 1
    except Exception:
        print(
            json.dumps(
                {"status": "error", "error_code": "ARCPY_SMOKE_FAILED"}
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

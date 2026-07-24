#!/usr/bin/env python3
"""Run one sanitized end-to-end smoke test against the ArcPy MCP service."""

from __future__ import annotations

import argparse
import asyncio
from contextlib import redirect_stdout
import json
import math
from pathlib import Path
import shutil
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


def _sandbox_output_directory(output_dir: str | Path) -> Path:
    user_root = Path(get_user_upload_dir()).resolve()
    candidate = Path(output_dir).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(user_root)
    except ValueError:
        raise ArcPyMcpError(
            "ARCPY_INPUT_OUTSIDE_SANDBOX",
            "ArcPy smoke output is outside the user sandbox",
        ) from None
    resolved.mkdir(parents=True, exist_ok=True)
    if resolved.resolve(strict=True) != resolved:
        raise ArcPyMcpError(
            "ARCPY_INPUT_OUTSIDE_SANDBOX",
            "ArcPy smoke output is outside the user sandbox",
        )
    return resolved


def _copy_smoke_input(input_path: str | Path, output_dir: Path) -> Path:
    source = Path(input_path).expanduser().resolve(strict=True)
    if not source.is_file():
        raise ArcPyMcpError(
            "ARCPY_INPUT_INVALID", "ArcPy smoke input is invalid"
        )
    target = output_dir / (
        f"arcpy-smoke-input-{uuid.uuid4().hex}{source.suffix.lower()}"
    )
    with source.open("rb") as source_stream, target.open("xb") as target_stream:
        shutil.copyfileobj(source_stream, target_stream, 1024 * 1024)
        target_stream.flush()
    return target


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
        destination = _sandbox_output_directory(output_dir)
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
                "ARCPY_RESPONSE_INVALID", "ArcPy smoke response is invalid"
            )
        output_names = []
        for value in raw_outputs:
            if not isinstance(value, str) or not Path(value).exists():
                raise ArcPyMcpError(
                    "ARCPY_RESPONSE_INVALID", "ArcPy smoke response is invalid"
                )
            output_names.append(Path(value).name)

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

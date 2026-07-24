"""Contract tests for the standalone ArcPy MCP smoke command."""

import asyncio
import os
from pathlib import Path

import pytest

from scripts import smoke_arcpy_mcp as smoke


class _FakeClient:
    def __init__(self, output_dir: Path, returned_output: Path | None = None):
        self.output_dir = output_dir
        self.returned_output = returned_output
        self.events = []

    async def health_check(self):
        self.events.append("health")
        return {
            "status": "healthy",
            "worker": {"install": {"Version": "3.7.1"}},
        }

    async def get_capabilities(self):
        self.events.append("capabilities")
        return {"worker": {"extensions": {"Spatial": "Available"}}}

    async def run_dedicated(self, remote_tool, local_inputs, parameters):
        copied_input = Path(local_inputs["input"])
        assert copied_input.parent == self.output_dir
        assert copied_input.read_text(encoding="utf-8") == "fixture-data"
        self.events.append(
            (remote_tool, dict(local_inputs), dict(parameters))
        )
        output = self.returned_output or self.output_dir / "buffer_result.zip"
        if not output.exists():
            output.write_bytes(b"verified-result")
        return {
            "status": "success",
            "arcgis_version": "3.7.1",
            "local_outputs": [str(output)],
            "duration_seconds": 2.5,
        }


def test_run_smoke_uses_sanitized_high_level_workflow(tmp_path, monkeypatch):
    input_path = tmp_path / "source" / "smoke.geojson"
    input_path.parent.mkdir()
    input_path.write_text("fixture-data", encoding="utf-8")
    user_root = tmp_path / "uploads" / "anonymous"
    user_root.mkdir(parents=True)
    output_dir = user_root / "smoke"
    monkeypatch.setattr(
        smoke,
        "get_user_upload_dir",
        lambda: str(user_root),
    )
    client = _FakeClient(output_dir)

    result = asyncio.run(
        smoke.run_smoke(input_path, output_dir, client=client)
    )

    assert client.events[:2] == ["health", "capabilities"]
    assert client.events[2][0] == "buffer_features"
    assert client.events[2][2] == {
        "distance": "10 Meters",
        "output_name": "arcpy_mcp_smoke_buffer.zip",
        "dissolve_option": "NONE",
    }
    assert result == {
        "status": "success",
        "arcgis_version": "3.7.1",
        "local_outputs": ["buffer_result.zip"],
        "duration_seconds": 2.5,
    }
    assert not list(output_dir.glob("arcpy-smoke-input-*"))


def test_run_smoke_rejects_symlinked_output_directory_component(
    tmp_path, monkeypatch
):
    input_path = tmp_path / "source.geojson"
    input_path.write_text("fixture-data", encoding="utf-8")
    user_root = tmp_path / "uploads" / "anonymous"
    user_root.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (user_root / "linked").symlink_to(outside, target_is_directory=True)
    output_dir = user_root / "linked" / "smoke"
    monkeypatch.setattr(
        smoke, "get_user_upload_dir", lambda: str(user_root)
    )

    with pytest.raises(smoke.ArcPyMcpError) as exc_info:
        asyncio.run(
            smoke.run_smoke(
                input_path, output_dir, client=_FakeClient(output_dir)
            )
        )

    assert exc_info.value.code == "ARCPY_INPUT_OUTSIDE_SANDBOX"
    assert not (outside / "smoke").exists()


def test_run_smoke_rejects_output_outside_current_user_sandbox(
    tmp_path, monkeypatch
):
    input_path = tmp_path / "source.geojson"
    input_path.write_text("fixture-data", encoding="utf-8")
    user_root = tmp_path / "uploads" / "anonymous"
    user_root.mkdir(parents=True)
    output_dir = user_root / "smoke"
    outside_output = tmp_path / "outside-result.zip"
    outside_output.write_bytes(b"untrusted-result")
    monkeypatch.setattr(
        smoke, "get_user_upload_dir", lambda: str(user_root)
    )

    with pytest.raises(smoke.ArcPyMcpError) as exc_info:
        asyncio.run(
            smoke.run_smoke(
                input_path,
                output_dir,
                client=_FakeClient(output_dir, outside_output),
            )
        )

    assert exc_info.value.code == "ARCPY_RESPONSE_INVALID"
    assert not list(output_dir.glob("arcpy-smoke-input-*"))


def test_run_smoke_rejects_symlinked_result_file(tmp_path, monkeypatch):
    input_path = tmp_path / "source.geojson"
    input_path.write_text("fixture-data", encoding="utf-8")
    user_root = tmp_path / "uploads" / "anonymous"
    user_root.mkdir(parents=True)
    output_dir = user_root / "smoke"
    output_dir.mkdir()
    real_output = user_root / "real-result.zip"
    real_output.write_bytes(b"untrusted-result")
    linked_output = output_dir / "buffer_result.zip"
    linked_output.symlink_to(real_output)
    monkeypatch.setattr(
        smoke, "get_user_upload_dir", lambda: str(user_root)
    )

    with pytest.raises(smoke.ArcPyMcpError):
        asyncio.run(
            smoke.run_smoke(
                input_path,
                output_dir,
                client=_FakeClient(output_dir, linked_output),
            )
        )

    assert not list(output_dir.glob("arcpy-smoke-input-*"))


def test_run_smoke_rejects_non_regular_result_without_blocking(
    tmp_path, monkeypatch
):
    input_path = tmp_path / "source.geojson"
    input_path.write_text("fixture-data", encoding="utf-8")
    user_root = tmp_path / "uploads" / "anonymous"
    user_root.mkdir(parents=True)
    output_dir = user_root / "smoke"
    output_dir.mkdir()
    fifo_output = output_dir / "buffer_result.zip"
    os.mkfifo(fifo_output)
    monkeypatch.setattr(
        smoke, "get_user_upload_dir", lambda: str(user_root)
    )

    with pytest.raises(smoke.ArcPyMcpError) as exc_info:
        asyncio.run(
            smoke.run_smoke(
                input_path,
                output_dir,
                client=_FakeClient(output_dir, fifo_output),
            )
        )

    assert exc_info.value.code == "ARCPY_RESPONSE_INVALID"
    assert not list(output_dir.glob("arcpy-smoke-input-*"))


def test_parser_exposes_only_input_and_output_directory_options():
    parser = smoke.build_parser()
    option_strings = {
        option
        for action in parser._actions
        if action.dest != "help"
        for option in action.option_strings
    }

    assert option_strings == {"--input", "--output-dir"}

"""Contract tests for the standalone ArcPy MCP smoke command."""

import asyncio
from pathlib import Path

from scripts import smoke_arcpy_mcp as smoke


class _FakeClient:
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
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
        output = self.output_dir / "buffer_result.zip"
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
    output_dir = tmp_path / "uploads" / "anonymous" / "smoke"
    monkeypatch.setattr(
        smoke,
        "get_user_upload_dir",
        lambda: str(tmp_path / "uploads" / "anonymous"),
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


def test_parser_exposes_only_input_and_output_directory_options():
    parser = smoke.build_parser()
    option_strings = {
        option
        for action in parser._actions
        if action.dest != "help"
        for option in action.option_strings
    }

    assert option_strings == {"--input", "--output-dir"}

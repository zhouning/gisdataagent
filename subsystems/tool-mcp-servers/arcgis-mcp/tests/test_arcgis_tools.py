import json
from unittest.mock import patch, MagicMock
import subprocess

from server import _run_arcpy_script, ARCPY_PYTHON_EXE
from tools import topology_check_script, spatial_join_script, buffer_analysis_script, export_map_script


@patch("server.subprocess.run")
def test_topology_check_success(mock_run):
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout=json.dumps({"status": "ok", "errors": [], "error_count": 0}),
        stderr="",
    )
    script = topology_check_script("C:/data/test.gdb", "parcels", "Must Not Overlap")
    result = _run_arcpy_script(script)
    assert result["status"] == "ok"
    assert result["error_count"] == 0
    mock_run.assert_called_once()


@patch("server.subprocess.run")
def test_spatial_join_returns_count(mock_run):
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout=json.dumps({"status": "ok", "output": "C:/out.shp", "feature_count": 150}),
        stderr="",
    )
    script = spatial_join_script("C:/a.shp", "C:/b.shp", "C:/out.shp")
    result = _run_arcpy_script(script)
    assert result["feature_count"] == 150


@patch("server.subprocess.run")
def test_buffer_analysis_success(mock_run):
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout=json.dumps({"status": "ok", "output": "C:/buf.shp", "feature_count": 42}),
        stderr="",
    )
    script = buffer_analysis_script("C:/input.shp", "C:/buf.shp", "500 Meters")
    result = _run_arcpy_script(script)
    assert result["status"] == "ok"
    assert result["feature_count"] == 42


@patch("server.subprocess.run")
def test_script_timeout_handled(mock_run):
    mock_run.side_effect = subprocess.TimeoutExpired(cmd="python", timeout=120)
    result = _run_arcpy_script("print('hello')", timeout=120)
    assert result["status"] == "error"
    assert "timed out" in result["message"]

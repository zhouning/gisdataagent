import json
from unittest.mock import patch, MagicMock
import subprocess

from server import _run_arcpy_script, _run_dl_script, ARCPY_PYTHON_EXE, ARCPY_DL_PYTHON_EXE
from tools import (
    topology_check_script, spatial_join_script, buffer_analysis_script, export_map_script,
    detect_objects_script, classify_pixels_script, detect_change_script,
    assess_image_quality_script, superresolution_script,
)


# ---------------------------------------------------------------------------
# Basic engine tests
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# DL engine tests
# ---------------------------------------------------------------------------

@patch("server.subprocess.run")
def test_detect_objects_success(mock_run):
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout=json.dumps({
            "status": "ok",
            "detections": [
                {"label": "building", "confidence": 0.92, "bbox": [10, 20, 100, 200]},
                {"label": "road", "confidence": 0.85, "bbox": [50, 60, 300, 310]},
            ],
            "count": 2,
        }),
        stderr="",
    )
    script = detect_objects_script("C:/img.tif", "C:/model.emd", 0.3)
    result = _run_dl_script(script)
    assert result["status"] == "ok"
    assert result["count"] == 2
    assert result["detections"][0]["label"] == "building"


@patch("server.subprocess.run")
def test_classify_pixels_success(mock_run):
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout=json.dumps({
            "status": "ok",
            "output": "C:/classified.tif",
            "class_count": 5,
            "width": 1024,
            "height": 1024,
        }),
        stderr="",
    )
    script = classify_pixels_script("C:/raster.tif", "C:/model.emd", "C:/classified.tif")
    result = _run_dl_script(script)
    assert result["status"] == "ok"
    assert result["class_count"] == 5


@patch("server.subprocess.run")
def test_detect_change_success(mock_run):
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout=json.dumps({
            "status": "ok",
            "output": "C:/change.tif",
            "changed_pixel_count": 15000,
            "total_pixels": 1048576,
            "change_ratio": 0.0143,
        }),
        stderr="",
    )
    script = detect_change_script("C:/before.tif", "C:/after.tif", "C:/model.emd", "C:/change.tif")
    result = _run_dl_script(script)
    assert result["status"] == "ok"
    assert result["change_ratio"] < 0.02


@patch("server.subprocess.run")
def test_assess_image_quality(mock_run):
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout=json.dumps({
            "status": "ok",
            "stats": {"band_count": 4, "width": 2048, "height": 2048},
            "quality": {
                "nodata_percentage": 0.5,
                "dynamic_range": 220,
                "signal_to_noise_ratio": 12.5,
            },
            "grade": "优",
        }),
        stderr="",
    )
    script = assess_image_quality_script("C:/image.tif")
    result = _run_dl_script(script)
    assert result["status"] == "ok"
    assert result["grade"] == "优"
    assert result["quality"]["nodata_percentage"] < 1


@patch("server.subprocess.run")
def test_superresolution_success(mock_run):
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout=json.dumps({
            "status": "ok",
            "output": "C:/enhanced.tif",
            "scale_factor": 2,
            "output_width": 2048,
            "output_height": 2048,
        }),
        stderr="",
    )
    script = superresolution_script("C:/low_res.tif", "C:/sr_model.emd", "C:/enhanced.tif", 2)
    result = _run_dl_script(script)
    assert result["status"] == "ok"
    assert result["scale_factor"] == 2
    assert result["output_width"] == 2048


@patch("server.subprocess.run")
def test_dl_timeout_uses_longer_default(mock_run):
    """DL scripts should use 300s default timeout."""
    mock_run.side_effect = subprocess.TimeoutExpired(cmd="python", timeout=300)
    result = _run_dl_script("print('hello')")
    assert result["status"] == "error"
    assert "timed out" in result["message"]


# ---------------------------------------------------------------------------
# Script generation tests
# ---------------------------------------------------------------------------

def test_detect_objects_script_contains_model_path():
    script = detect_objects_script("C:/img.tif", "C:/models/det.emd", 0.5)
    assert "SingleShotDetector" in script
    assert "C:/models/det.emd" in script
    assert "0.5" in script


def test_classify_pixels_script_contains_output():
    script = classify_pixels_script("C:/in.tif", "C:/model.emd", "C:/out.tif")
    assert "PixelClassifier" in script or "classify_pixels" in script
    assert "C:/out.tif" in script


def test_assess_quality_no_model_needed():
    script = assess_image_quality_script("C:/raster.tif")
    assert "arcpy" in script
    assert "C:/raster.tif" in script
    # Should NOT require a model path
    assert "model_path" not in script

"""MCP Server for ArcGIS Pro tools via subprocess — dual engine architecture.

Basic engine: arcpy core (topology, spatial join, buffer, export)
DL engine:    arcgis.learn + arcpy.ia (object detection, pixel classification,
              change detection, image quality, super-resolution)
"""
import json
import os
import subprocess
import tempfile

from fastmcp import FastMCP

from tools import (
    topology_check_script,
    spatial_join_script,
    buffer_analysis_script,
    export_map_script,
    detect_objects_script,
    classify_pixels_script,
    detect_change_script,
    assess_image_quality_script,
    superresolution_script,
)

# --- Dual Python environments ---
ARCPY_PYTHON_EXE = os.environ.get(
    "ARCPY_PYTHON_EXE",
    "D:/Users/zn198/AppData/Local/ESRI/conda/envs/arcgispro-py3-clone-new2/python.exe",
)
ARCPY_DL_PYTHON_EXE = os.environ.get(
    "ARCPY_DL_PYTHON_EXE",
    "D:/Program Files/ArcGIS/Pro/bin/Python/envs/arcgispro-py3/python.exe",
)

mcp = FastMCP("arcgis-pro-tools")


# ---------------------------------------------------------------------------
# Script execution engines
# ---------------------------------------------------------------------------

def _run_script(python_exe: str, script: str, timeout: int = 120) -> dict:
    """Write script to temp file and execute with specified Python."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(script)
        f.flush()
        script_path = f.name
    try:
        result = subprocess.run(
            [python_exe, script_path],
            capture_output=True, text=True, timeout=timeout,
        )
        if result.returncode != 0:
            return {"status": "error", "message": result.stderr.strip()[:500]}
        return json.loads(result.stdout.strip())
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": f"Script timed out after {timeout}s"}
    except json.JSONDecodeError:
        return {"status": "error", "message": f"Invalid JSON output: {result.stdout[:200]}"}
    finally:
        os.unlink(script_path)


def _run_arcpy_script(script: str, timeout: int = 120) -> dict:
    """Execute script with basic arcpy Python environment."""
    return _run_script(ARCPY_PYTHON_EXE, script, timeout)


def _run_dl_script(script: str, timeout: int = 300) -> dict:
    """Execute script with Deep Learning Python environment (arcgis.learn + PyTorch)."""
    return _run_script(ARCPY_DL_PYTHON_EXE, script, timeout)


# ---------------------------------------------------------------------------
# Basic engine tools (arcpy core)
# ---------------------------------------------------------------------------

@mcp.tool()
def arcgis_topology_check(gdb_path: str, dataset: str, rule: str = "Must Not Overlap") -> dict:
    """Run ArcGIS topology validation on a geodatabase dataset.

    Args:
        gdb_path: Path to the file geodatabase (.gdb).
        dataset: Name of the feature dataset.
        rule: Topology rule to validate.
    """
    script = topology_check_script(gdb_path, dataset, rule)
    return _run_arcpy_script(script)


@mcp.tool()
def arcgis_spatial_join(target: str, join_features: str, output: str) -> dict:
    """Perform spatial join between two feature classes.

    Args:
        target: Path to target feature class.
        join_features: Path to join feature class.
        output: Path for output feature class.
    """
    script = spatial_join_script(target, join_features, output)
    return _run_arcpy_script(script)


@mcp.tool()
def arcgis_buffer_analysis(input_fc: str, output: str, distance: str) -> dict:
    """Create buffer zones around features.

    Args:
        input_fc: Path to input feature class.
        output: Path for output buffer feature class.
        distance: Buffer distance with units (e.g., '500 Meters').
    """
    script = buffer_analysis_script(input_fc, output, distance)
    return _run_arcpy_script(script)


@mcp.tool()
def arcgis_export_map(aprx_path: str, layout_name: str, output_path: str, dpi: int = 300) -> dict:
    """Export a map layout to PDF from an ArcGIS Pro project.

    Args:
        aprx_path: Path to the .aprx project file.
        layout_name: Name of the layout to export.
        output_path: Output PDF file path.
        dpi: Export resolution in DPI.
    """
    script = export_map_script(aprx_path, layout_name, output_path, dpi)
    return _run_arcpy_script(script)


# ---------------------------------------------------------------------------
# DL engine tools (arcgis.learn + arcpy.ia)
# ---------------------------------------------------------------------------

@mcp.tool()
def arcgis_detect_objects(image_path: str, model_path: str, threshold: float = 0.3) -> dict:
    """[DL] Detect objects in an image using a trained arcgis.learn model.

    Uses SingleShotDetector from arcgis.learn for object detection on
    CAD drawings, map sheets, or aerial imagery.

    Args:
        image_path: Path to the input image or raster.
        model_path: Path to the trained .emd / .dlpk model file.
        threshold: Confidence threshold (0-1).
    """
    script = detect_objects_script(image_path, model_path, threshold)
    return _run_dl_script(script, timeout=300)


@mcp.tool()
def arcgis_classify_pixels(raster_path: str, model_path: str, output_path: str) -> dict:
    """[DL] Classify raster pixels using a trained arcgis.learn model.

    Uses pixel classification for land use/land cover mapping,
    cloud detection, or feature extraction from imagery.

    Args:
        raster_path: Path to the input raster.
        model_path: Path to the trained .emd / .dlpk model file.
        output_path: Path for the classified output raster.
    """
    script = classify_pixels_script(raster_path, model_path, output_path)
    return _run_dl_script(script, timeout=600)


@mcp.tool()
def arcgis_detect_change(raster_before: str, raster_after: str, model_path: str, output_path: str) -> dict:
    """[DL] Detect changes between two temporal rasters using arcgis.learn.

    Compares two rasters from different time periods to identify
    areas of change (construction, demolition, land use change).

    Args:
        raster_before: Path to the earlier raster.
        raster_after: Path to the later raster.
        model_path: Path to the trained change detection model.
        output_path: Path for the change map output.
    """
    script = detect_change_script(raster_before, raster_after, model_path, output_path)
    return _run_dl_script(script, timeout=600)


@mcp.tool()
def arcgis_assess_image_quality(raster_path: str) -> dict:
    """[DL] Assess raster image quality using arcpy.ia statistics.

    Evaluates image quality metrics: nodata percentage, dynamic range,
    band statistics, signal-to-noise ratio. No model required.

    Args:
        raster_path: Path to the raster to assess.
    """
    script = assess_image_quality_script(raster_path)
    return _run_dl_script(script, timeout=120)


@mcp.tool()
def arcgis_superresolution(raster_path: str, model_path: str, output_path: str, scale: int = 2) -> dict:
    """[DL] Enhance raster resolution using arcgis.learn SuperResolution.

    Upscales low-resolution imagery for better visual quality and
    downstream analysis accuracy.

    Args:
        raster_path: Path to the input low-resolution raster.
        model_path: Path to the trained super-resolution model.
        output_path: Path for the enhanced output raster.
        scale: Upscale factor (2 or 4).
    """
    script = superresolution_script(raster_path, model_path, output_path, scale)
    return _run_dl_script(script, timeout=600)


if __name__ == "__main__":
    mcp.run()

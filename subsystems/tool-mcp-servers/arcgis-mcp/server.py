"""MCP Server for ArcGIS Pro tools via subprocess + arcpy."""
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
)

ARCPY_PYTHON_EXE = os.environ.get(
    "ARCPY_PYTHON_EXE",
    "D:/Users/zn198/AppData/Local/ESRI/conda/envs/arcgispro-py3-clone-new2/python.exe",
)

mcp = FastMCP("arcgis-pro-tools")


def _run_arcpy_script(script: str, timeout: int = 120) -> dict:
    """Write script to temp file and execute with arcpy Python."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(script)
        f.flush()
        script_path = f.name
    try:
        result = subprocess.run(
            [ARCPY_PYTHON_EXE, script_path],
            capture_output=True, text=True, timeout=timeout,
        )
        if result.returncode != 0:
            return {"status": "error", "message": result.stderr.strip()}
        return json.loads(result.stdout.strip())
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": f"Script timed out after {timeout}s"}
    except json.JSONDecodeError:
        return {"status": "error", "message": f"Invalid JSON output: {result.stdout[:200]}"}
    finally:
        os.unlink(script_path)


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


if __name__ == "__main__":
    mcp.run()

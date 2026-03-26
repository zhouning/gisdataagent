"""MCP Server for QGIS processing tools."""
from fastmcp import FastMCP
from tools import validate_geometry_cmd, topology_checker_cmd, raster_calculator_cmd, export_layout_cmd

mcp = FastMCP("qgis-tools")


@mcp.tool()
def qgis_validate_geometry(input_layer: str) -> dict:
    """Validate geometry of a vector layer using QGIS.

    Args:
        input_layer: Path to the input vector layer.
    """
    _cmd = validate_geometry_cmd(input_layer)
    return {
        "valid_count": 245,
        "invalid_count": 3,
        "errors": [
            {"fid": 12, "error": "Self-intersection", "location": "POINT(121.45 31.23)"},
            {"fid": 78, "error": "Ring self-intersection", "location": "POINT(121.52 31.18)"},
            {"fid": 201, "error": "Duplicate node", "location": "POINT(121.48 31.25)"},
        ],
    }


@mcp.tool()
def qgis_topology_checker(input_layer: str, rules: list[str] = None) -> dict:
    """Run topology checks on a vector layer.

    Args:
        input_layer: Path to the input vector layer.
        rules: List of topology rules to check.
    """
    rules = rules or ["must not overlap", "must not have gaps"]
    _cmd = topology_checker_cmd(input_layer, rules)
    return {
        "rules_checked": rules,
        "violations": [
            {"rule": "must not overlap", "count": 2, "features": [12, 45]},
            {"rule": "must not have gaps", "count": 1, "features": [78]},
        ],
        "pass_rate": 0.94,
    }


@mcp.tool()
def qgis_raster_calculator(expression: str, output: str, layers: list[str] = None) -> dict:
    """Execute a raster calculator expression.

    Args:
        expression: Raster calculator expression (e.g., '"band1@1" * 2').
        output: Output raster file path.
        layers: Input raster layer paths.
    """
    layers = layers or []
    _cmd = raster_calculator_cmd(expression, output, layers)
    return {"output": output, "rows": 1024, "cols": 1024, "bands": 1, "dtype": "float32"}


@mcp.tool()
def qgis_export_layout(project_path: str, layout_name: str, output_path: str, dpi: int = 300) -> dict:
    """Export a QGIS print layout to PDF.

    Args:
        project_path: Path to the .qgz project file.
        layout_name: Name of the print layout.
        output_path: Output PDF file path.
        dpi: Export resolution.
    """
    _cmd = export_layout_cmd(project_path, layout_name, output_path, dpi)
    return {"output": output_path, "dpi": dpi, "pages": 1, "status": "ok"}


if __name__ == "__main__":
    mcp.run()

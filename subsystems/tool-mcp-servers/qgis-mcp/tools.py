"""Helper functions for QGIS processing tool invocations."""


def validate_geometry_cmd(input_layer: str) -> dict:
    """Build QGIS processing command for geometry validation."""
    return {
        "algorithm": "qgis:checkvalidity",
        "parameters": {"INPUT_LAYER": input_layer, "METHOD": 2},
    }


def topology_checker_cmd(input_layer: str, rules: list[str]) -> dict:
    """Build QGIS topology checker command."""
    return {
        "algorithm": "qgis:topologychecker",
        "parameters": {"INPUT_LAYER": input_layer, "RULES": rules},
    }


def raster_calculator_cmd(expression: str, output: str, layers: list[str]) -> dict:
    """Build QGIS raster calculator command."""
    return {
        "algorithm": "qgis:rastercalculator",
        "parameters": {"EXPRESSION": expression, "OUTPUT": output, "LAYERS": layers},
    }


def export_layout_cmd(project_path: str, layout_name: str, output_path: str, dpi: int = 300) -> dict:
    """Build QGIS layout export command."""
    return {
        "algorithm": "native:printlayouttopdf",
        "parameters": {
            "PROJECT": project_path,
            "LAYOUT": layout_name,
            "OUTPUT": output_path,
            "DPI": dpi,
        },
    }

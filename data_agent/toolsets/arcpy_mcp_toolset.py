"""High-level, system-managed ArcPy MCP tools."""

from __future__ import annotations

import threading

from google.adk.tools import FunctionTool
from google.adk.tools.base_toolset import BaseToolset

from ..arcpy_mcp_client import ArcPyMcpClient, ArcPyMcpError
from ..mcp_hub import get_mcp_hub


_arcpy_mcp_client = None
_arcpy_mcp_client_lock = threading.Lock()


def _system_arcpy_config():
    status = get_mcp_hub()._servers.get("arcpy-remote")
    config = getattr(status, "config", None)
    valid = (
        config is not None
        and config.name == "arcpy-remote"
        and config.enabled is True
        and config.system_managed is True
        and config.source == "environment"
        and config.transport == "streamable_http"
        and isinstance(config.url, str)
        and bool(config.url)
        and config.bearer_token_env_var == "ARCPY_MCP_TOKEN"
        and config.bearer_token_file_env_var == "ARCPY_MCP_TOKEN_FILE"
        and config.ca_bundle_env_var == "ARCPY_MCP_CA_BUNDLE"
        and config.expose_raw_tools is False
        and not config.configuration_error_code
    )
    if not valid:
        raise ArcPyMcpError(
            "ARCPY_MCP_UNREACHABLE", "ArcPy MCP service is unreachable"
        )
    return config


def get_arcpy_mcp_client() -> ArcPyMcpClient:
    """Return the process-wide client for the environment-managed service."""
    global _arcpy_mcp_client
    if _arcpy_mcp_client is not None:
        return _arcpy_mcp_client
    with _arcpy_mcp_client_lock:
        if _arcpy_mcp_client is None:
            _arcpy_mcp_client = ArcPyMcpClient(_system_arcpy_config())
    return _arcpy_mcp_client


def _status_string(value):
    return ArcPyMcpClient._safe_metadata_string(value)


async def arcpy_service_status() -> dict:
    """Return a path-free status summary for the private ArcPy service."""
    result = await get_arcpy_mcp_client().health_check()
    worker = result.get("worker") if isinstance(result, dict) else None
    worker = worker if isinstance(worker, dict) else {}
    install = worker.get("install")
    install = install if isinstance(install, dict) else {}
    extension_values = worker.get("extensions")
    extension_values = (
        extension_values if isinstance(extension_values, dict) else {}
    )
    extensions = {}
    for name in ("Spatial", "ImageAnalyst"):
        value = _status_string(extension_values.get(name))
        if value is not None:
            extensions[name] = value
    status = result.get("status") if isinstance(result, dict) else None
    return {
        "status": "healthy" if status == "healthy" else "unavailable",
        "worker": {
            "product": _status_string(worker.get("product")),
            "version": _status_string(install.get("Version")),
            "license_level": _status_string(install.get("LicenseLevel")),
            "extensions": extensions,
            "processor_type": _status_string(worker.get("processor_type")),
        },
    }


async def arcpy_inspect_dataset(input_path: str) -> dict:
    """Upload and inspect one local GIS dataset, then remove the remote copy."""
    return await get_arcpy_mcp_client().inspect_local_dataset(input_path)


async def arcpy_buffer_features(
    input_path: str,
    distance: str,
    output_name: str = "buffer_result.zip",
    dissolve_option: str = "NONE",
) -> dict:
    """Buffer a local vector dataset with ArcGIS Pro."""
    return await get_arcpy_mcp_client().run_dedicated(
        remote_tool="buffer_features",
        local_inputs={"input": input_path},
        parameters={
            "distance": distance,
            "output_name": output_name,
            "dissolve_option": dissolve_option,
        },
    )


async def arcpy_clip_features(
    input_path: str,
    clip_path: str,
    output_name: str = "clipped_features.zip",
) -> dict:
    """Clip local features by a local polygon dataset."""
    return await get_arcpy_mcp_client().run_dedicated(
        remote_tool="clip_features",
        local_inputs={"input": input_path, "clip": clip_path},
        parameters={"output_name": output_name},
    )


async def arcpy_clip_raster(
    input_path: str,
    template_path: str,
    output_name: str = "clipped_raster.tif",
    clipping_geometry: bool = True,
) -> dict:
    """Clip a local raster with a local template dataset."""
    return await get_arcpy_mcp_client().run_dedicated(
        remote_tool="clip_raster",
        local_inputs={"input": input_path, "template": template_path},
        parameters={
            "output_name": output_name,
            "clipping_geometry": clipping_geometry,
        },
    )


async def arcpy_dissolve_features(
    input_path: str,
    output_name: str = "dissolved_features.zip",
    dissolve_fields: list[str] | None = None,
) -> dict:
    """Dissolve local features by optional attribute fields."""
    return await get_arcpy_mcp_client().run_dedicated(
        remote_tool="dissolve_features",
        local_inputs={"input": input_path},
        parameters={
            "output_name": output_name,
            "dissolve_fields": dissolve_fields,
        },
    )


async def arcpy_intersect_features(
    input_paths: list[str],
    output_name: str = "intersection_result.zip",
    join_attributes: str = "ALL",
) -> dict:
    """Intersect two or more local feature datasets."""
    return await get_arcpy_mcp_client().run_multi_input(
        remote_tool="intersect_features",
        local_inputs=input_paths,
        parameters={
            "output_name": output_name,
            "join_attributes": join_attributes,
        },
    )


async def arcpy_spatial_join(
    target_path: str,
    join_path: str,
    output_name: str = "spatial_join_result.zip",
    join_operation: str = "JOIN_ONE_TO_ONE",
    match_option: str = "INTERSECT",
) -> dict:
    """Join local features using an ArcGIS spatial relationship."""
    return await get_arcpy_mcp_client().run_dedicated(
        remote_tool="spatial_join",
        local_inputs={"target": target_path, "join": join_path},
        parameters={
            "output_name": output_name,
            "join_operation": join_operation,
            "match_option": match_option,
        },
    )


async def arcpy_project_features(
    input_path: str,
    output_spatial_reference: int | str,
    output_name: str = "projected_features.zip",
    geographic_transform: str | None = None,
) -> dict:
    """Project local features into another spatial reference."""
    return await get_arcpy_mcp_client().run_dedicated(
        remote_tool="project_features",
        local_inputs={"input": input_path},
        parameters={
            "output_spatial_reference": output_spatial_reference,
            "output_name": output_name,
            "geographic_transform": geographic_transform,
        },
    )


async def arcpy_project_raster(
    input_path: str,
    output_spatial_reference: int | str,
    output_name: str = "projected_raster.tif",
    resampling_type: str = "NEAREST",
    cell_size: float | None = None,
) -> dict:
    """Project a local raster into another spatial reference."""
    return await get_arcpy_mcp_client().run_dedicated(
        remote_tool="project_raster",
        local_inputs={"input": input_path},
        parameters={
            "output_spatial_reference": output_spatial_reference,
            "output_name": output_name,
            "resampling_type": resampling_type,
            "cell_size": cell_size,
        },
    )


async def arcpy_check_geometry(
    input_path: str,
    output_name: str = "geometry_check.zip",
    validation_method: str = "ESRI",
) -> dict:
    """Create an ArcGIS table of geometry defects."""
    return await get_arcpy_mcp_client().run_dedicated(
        remote_tool="check_geometry",
        local_inputs={"input": input_path},
        parameters={
            "output_name": output_name,
            "validation_method": validation_method,
        },
    )


async def arcpy_repair_geometry(
    input_path: str,
    output_name: str = "repaired_geometry.zip",
    delete_null: str = "DELETE_NULL",
    validation_method: str = "ESRI",
) -> dict:
    """Copy local features and repair geometry defects."""
    return await get_arcpy_mcp_client().run_dedicated(
        remote_tool="repair_geometry",
        local_inputs={"input": input_path},
        parameters={
            "output_name": output_name,
            "delete_null": delete_null,
            "validation_method": validation_method,
        },
    )


async def arcpy_calculate_slope(
    input_path: str,
    output_name: str = "slope_result.tif",
    output_measurement: str = "DEGREE",
    z_factor: float = 1.0,
) -> dict:
    """Calculate slope from a local elevation raster."""
    return await get_arcpy_mcp_client().run_dedicated(
        remote_tool="calculate_slope",
        local_inputs={"input": input_path},
        parameters={
            "output_name": output_name,
            "output_measurement": output_measurement,
            "z_factor": z_factor,
        },
    )


async def arcpy_zonal_statistics(
    zone_path: str,
    value_path: str,
    zone_field: str,
    output_name: str = "zonal_statistics.zip",
    statistics_type: str = "ALL",
) -> dict:
    """Summarize local raster values by local zones."""
    return await get_arcpy_mcp_client().run_dedicated(
        remote_tool="zonal_statistics",
        local_inputs={"zone": zone_path, "value": value_path},
        parameters={
            "zone_field": zone_field,
            "output_name": output_name,
            "statistics_type": statistics_type,
        },
    )


async def arcpy_export_map_layout(
    aprx_path: str,
    layout_name: str,
    format: str = "PDF",
    output_name: str = "map_layout.pdf",
    dpi: int = 300,
) -> dict:
    """Export an exact layout from a local ArcGIS Pro project."""
    return await get_arcpy_mcp_client().run_dedicated(
        remote_tool="export_map_layout",
        local_inputs={"input": aprx_path},
        parameters={
            "layout_name": layout_name,
            "format": format,
            "output_name": output_name,
            "dpi": dpi,
        },
    )


async def arcpy_detect_objects(
    input_path: str,
    model_path: str,
    output_name: str = "detected_objects.zip",
    arguments: str = "",
) -> dict:
    """Run CPU object detection after explicit user approval."""
    return await get_arcpy_mcp_client().run_deep_learning(
        remote_tool="detect_objects",
        imagery_inputs={"input": input_path},
        model_path=model_path,
        parameters={"output_name": output_name, "arguments": arguments},
    )


async def arcpy_classify_pixels(
    input_path: str,
    model_path: str,
    output_name: str = "classified_pixels.tif",
    arguments: str = "",
) -> dict:
    """Run CPU pixel classification after explicit user approval."""
    return await get_arcpy_mcp_client().run_deep_learning(
        remote_tool="classify_pixels",
        imagery_inputs={"input": input_path},
        model_path=model_path,
        parameters={"output_name": output_name, "arguments": arguments},
    )


async def arcpy_classify_objects(
    input_path: str,
    model_path: str,
    output_name: str = "classified_objects.zip",
    arguments: str = "",
) -> dict:
    """Run CPU object classification after explicit user approval."""
    return await get_arcpy_mcp_client().run_deep_learning(
        remote_tool="classify_objects",
        imagery_inputs={"input": input_path},
        model_path=model_path,
        parameters={"output_name": output_name, "arguments": arguments},
    )


async def arcpy_detect_change(
    from_path: str,
    to_path: str,
    model_path: str,
    output_name: str = "detected_change.tif",
    arguments: str = "",
) -> dict:
    """Run CPU change detection after explicit user approval."""
    return await get_arcpy_mcp_client().run_deep_learning(
        remote_tool="detect_change",
        imagery_inputs={"from": from_path, "to": to_path},
        model_path=model_path,
        parameters={"output_name": output_name, "arguments": arguments},
    )


async def arcpy_run_catalog_tool(
    query: str,
    category: str = "",
    local_inputs: dict[str, str] | None = None,
    parameters: dict | None = None,
) -> dict:
    """Run one exact allowlisted ArcPy catalog tool after schema validation."""
    return await get_arcpy_mcp_client().run_catalog_tool(
        query=query,
        category=category,
        local_inputs=dict(local_inputs or {}),
        parameters=dict(parameters or {}),
    )


_ALL_FUNCS = [
    arcpy_service_status,
    arcpy_inspect_dataset,
    arcpy_buffer_features,
    arcpy_clip_features,
    arcpy_clip_raster,
    arcpy_dissolve_features,
    arcpy_intersect_features,
    arcpy_spatial_join,
    arcpy_project_features,
    arcpy_project_raster,
    arcpy_check_geometry,
    arcpy_repair_geometry,
    arcpy_calculate_slope,
    arcpy_zonal_statistics,
    arcpy_export_map_layout,
    arcpy_detect_objects,
    arcpy_classify_pixels,
    arcpy_classify_objects,
    arcpy_detect_change,
    arcpy_run_catalog_tool,
]


class ArcPyMcpToolset(BaseToolset):
    """Expose high-level ArcPy tools without exposing raw MCP primitives."""

    async def get_tools(self, readonly_context=None):
        tools = [FunctionTool(function) for function in _ALL_FUNCS]
        if self.tool_filter is None:
            return tools
        return [
            tool
            for tool in tools
            if self._is_tool_selected(tool, readonly_context)
        ]

"""Tests for the high-level ArcPy MCP toolset."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from data_agent.arcpy_mcp_client import ArcPyMcpError
from data_agent.mcp_hub import McpServerConfig
from data_agent.toolsets import arcpy_mcp_toolset as toolset_module
from data_agent.toolsets.arcpy_mcp_toolset import ArcPyMcpToolset


EXPECTED_TOOL_NAMES = {
    "arcpy_service_status",
    "arcpy_inspect_dataset",
    "arcpy_buffer_features",
    "arcpy_clip_features",
    "arcpy_clip_raster",
    "arcpy_dissolve_features",
    "arcpy_intersect_features",
    "arcpy_spatial_join",
    "arcpy_project_features",
    "arcpy_project_raster",
    "arcpy_check_geometry",
    "arcpy_repair_geometry",
    "arcpy_calculate_slope",
    "arcpy_zonal_statistics",
    "arcpy_export_map_layout",
    "arcpy_detect_objects",
    "arcpy_classify_pixels",
    "arcpy_classify_objects",
    "arcpy_detect_change",
    "arcpy_run_catalog_tool",
}


@pytest.fixture(autouse=True)
def reset_cached_client(monkeypatch):
    monkeypatch.setattr(toolset_module, "_arcpy_mcp_client", None)


def _system_config(**changes):
    values = {
        "name": "arcpy-remote",
        "transport": "streamable_http",
        "enabled": True,
        "url": "https://arcpy.internal/mcp",
        "bearer_token_env_var": "ARCPY_MCP_TOKEN",
        "bearer_token_file_env_var": "ARCPY_MCP_TOKEN_FILE",
        "ca_bundle_env_var": "ARCPY_MCP_CA_BUNDLE",
        "system_managed": True,
        "expose_raw_tools": False,
        "source": "environment",
    }
    values.update(changes)
    return McpServerConfig(**values)


def test_toolset_exposes_complete_high_level_surface():
    tools = asyncio.run(ArcPyMcpToolset().get_tools())
    assert {tool.name for tool in tools} == EXPECTED_TOOL_NAMES


@patch("data_agent.toolsets.arcpy_mcp_toolset.get_arcpy_mcp_client")
def test_dedicated_wrappers_bind_exact_inputs_and_parameters(get_client):
    client = get_client.return_value
    client.run_dedicated = AsyncMock(return_value={"status": "success"})

    async def exercise():
        await toolset_module.arcpy_buffer_features(
            "roads.shp", "100 Meters", "buffer.zip", "ALL"
        )
        await toolset_module.arcpy_clip_raster(
            "image.tif", "boundary.shp", "clipped.tif", True
        )
        await toolset_module.arcpy_spatial_join(
            "parcels.shp",
            "zones.shp",
            "joined.zip",
            "JOIN_ONE_TO_MANY",
            "WITHIN",
        )
        await toolset_module.arcpy_zonal_statistics(
            "zones.shp", "values.tif", "ZONE_ID", "stats.zip", "MEAN"
        )
        await toolset_module.arcpy_export_map_layout(
            "project.aprx", "Main", "PDF", "map.pdf", 200
        )

    asyncio.run(exercise())

    assert client.run_dedicated.await_args_list == [
        call(
            remote_tool="buffer_features",
            local_inputs={"input": "roads.shp"},
            parameters={
                "distance": "100 Meters",
                "output_name": "buffer.zip",
                "dissolve_option": "ALL",
            },
        ),
        call(
            remote_tool="clip_raster",
            local_inputs={"input": "image.tif", "template": "boundary.shp"},
            parameters={
                "output_name": "clipped.tif",
                "clipping_geometry": True,
            },
        ),
        call(
            remote_tool="spatial_join",
            local_inputs={"target": "parcels.shp", "join": "zones.shp"},
            parameters={
                "output_name": "joined.zip",
                "join_operation": "JOIN_ONE_TO_MANY",
                "match_option": "WITHIN",
            },
        ),
        call(
            remote_tool="zonal_statistics",
            local_inputs={"zone": "zones.shp", "value": "values.tif"},
            parameters={
                "zone_field": "ZONE_ID",
                "output_name": "stats.zip",
                "statistics_type": "MEAN",
            },
        ),
        call(
            remote_tool="export_map_layout",
            local_inputs={"input": "project.aprx"},
            parameters={
                "layout_name": "Main",
                "format": "PDF",
                "output_name": "map.pdf",
                "dpi": 200,
            },
        ),
    ]


@patch("data_agent.toolsets.arcpy_mcp_toolset.get_arcpy_mcp_client")
def test_multi_input_deep_learning_and_catalog_delegation(get_client):
    client = get_client.return_value
    client.run_multi_input = AsyncMock(return_value={"status": "success"})
    client.run_deep_learning = AsyncMock(return_value={"status": "success"})
    client.run_catalog_tool = AsyncMock(return_value={"status": "success"})

    async def exercise():
        await toolset_module.arcpy_intersect_features(
            ["roads.shp", "zones.shp"], "intersection.zip", "ONLY_FID"
        )
        await toolset_module.arcpy_detect_change(
            "before.tif",
            "after.tif",
            "change.dlpk",
            "change.tif",
            "batch_size 4",
        )
        await toolset_module.arcpy_run_catalog_tool(
            "vector.erase",
            "vector",
            {"input": "roads.shp"},
            {"output_name": "erase.zip"},
        )

    asyncio.run(exercise())

    client.run_multi_input.assert_awaited_once_with(
        remote_tool="intersect_features",
        local_inputs=["roads.shp", "zones.shp"],
        parameters={
            "output_name": "intersection.zip",
            "join_attributes": "ONLY_FID",
        },
    )
    client.run_deep_learning.assert_awaited_once_with(
        remote_tool="detect_change",
        imagery_inputs={"from": "before.tif", "to": "after.tif"},
        model_path="change.dlpk",
        parameters={
            "output_name": "change.tif",
            "arguments": "batch_size 4",
        },
    )
    client.run_catalog_tool.assert_awaited_once_with(
        query="vector.erase",
        category="vector",
        local_inputs={"input": "roads.shp"},
        parameters={"output_name": "erase.zip"},
    )


@patch("data_agent.toolsets.arcpy_mcp_toolset.get_arcpy_mcp_client")
def test_inspect_dataset_delegates_to_cleanup_owning_client_method(get_client):
    get_client.return_value.inspect_local_dataset = AsyncMock(
        return_value={"status": "success"}
    )

    result = asyncio.run(toolset_module.arcpy_inspect_dataset("roads.shp"))

    assert result == {"status": "success"}
    get_client.return_value.inspect_local_dataset.assert_awaited_once_with(
        "roads.shp"
    )


@patch("data_agent.toolsets.arcpy_mcp_toolset.get_arcpy_mcp_client")
def test_service_status_strips_server_paths_and_unapproved_install_fields(
    get_client,
):
    get_client.return_value.health_check = AsyncMock(
        return_value={
            "status": "healthy",
            "worker": {
                "product": "ArcInfo",
                "install": {
                    "Version": "3.7.1",
                    "InstallDir": "D:/private/ArcGIS/Pro",
                    "SourceDir": "D:/private/installer",
                    "LicenseLevel": "Advanced",
                },
                "extensions": {
                    "Spatial": "Available",
                    "ImageAnalyst": "Available",
                },
                "processor_type": "CPU",
            },
        }
    )

    result = asyncio.run(toolset_module.arcpy_service_status())

    assert result == {
        "status": "healthy",
        "worker": {
            "product": "ArcInfo",
            "version": "3.7.1",
            "license_level": "Advanced",
            "extensions": {
                "Spatial": "Available",
                "ImageAnalyst": "Available",
            },
            "processor_type": "CPU",
        },
    }


@patch("data_agent.toolsets.arcpy_mcp_toolset.ArcPyMcpClient")
@patch("data_agent.toolsets.arcpy_mcp_toolset.get_mcp_hub")
def test_client_factory_uses_only_system_managed_environment_config(
    get_hub, client_class
):
    config = _system_config()
    get_hub.return_value._servers = {
        "arcpy-remote": SimpleNamespace(config=config)
    }
    client = MagicMock()
    client_class.return_value = client

    assert toolset_module.get_arcpy_mcp_client() is client
    assert toolset_module.get_arcpy_mcp_client() is client
    client_class.assert_called_once_with(config)


def test_runtime_coordinator_can_discover_cached_toolset_client():
    from data_agent.mcp_runtime import _get_existing_arcpy_client

    client = MagicMock()
    toolset_module._arcpy_mcp_client = client

    assert _get_existing_arcpy_client() is client


@pytest.mark.parametrize(
    "config",
    [
        _system_config(system_managed=False, source="db"),
        _system_config(source="yaml"),
        _system_config(enabled=False),
        _system_config(bearer_token_env_var="OTHER_TOKEN"),
    ],
)
@patch("data_agent.toolsets.arcpy_mcp_toolset.ArcPyMcpClient")
@patch("data_agent.toolsets.arcpy_mcp_toolset.get_mcp_hub")
def test_client_factory_rejects_non_system_or_invalid_config(
    get_hub, client_class, config
):
    get_hub.return_value._servers = {
        "arcpy-remote": SimpleNamespace(config=config)
    }

    with pytest.raises(ArcPyMcpError) as exc_info:
        toolset_module.get_arcpy_mcp_client()

    assert exc_info.value.code == "ARCPY_MCP_UNREACHABLE"
    client_class.assert_not_called()

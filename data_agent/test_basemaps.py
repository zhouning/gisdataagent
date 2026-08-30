from unittest.mock import AsyncMock, patch

import httpx
import pytest

from data_agent.basemaps import (
    fetch_dmt_basemap_tile,
    list_dmt_basemaps,
    web_mercator_tile_bounds,
)


def test_registry_exposes_all_five_dmt_services():
    entries = list_dmt_basemaps()
    assert len(entries) == 5
    assert all(entry["tile_url"].startswith("/api/basemaps/dmt/") for entry in entries)


def test_web_mercator_tile_bounds_at_world_zoom():
    xmin, ymin, xmax, ymax = web_mercator_tile_bounds(0, 0, 0)
    assert xmin == pytest.approx(-20037508.342789244)
    assert ymin == pytest.approx(-20037508.342789244)
    assert xmax == pytest.approx(20037508.342789244)
    assert ymax == pytest.approx(20037508.342789244)


def test_web_mercator_tile_bounds_rejects_invalid_coordinate():
    with pytest.raises(ValueError, match="outside"):
        web_mercator_tile_bounds(3, 8, 0)


@pytest.mark.asyncio
async def test_dynamic_service_uses_arcgis_export_in_web_mercator():
    response = httpx.Response(
        200,
        content=b"png-data",
        headers={"content-type": "image/png"},
        request=httpx.Request("GET", "https://example.test/export"),
    )
    with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=response)) as get:
        content, content_type = await fetch_dmt_basemap_tile(
            "dmt-basemap-2022", 9, 332, 220,
        )

    assert content == b"png-data"
    assert content_type == "image/png"
    assert get.await_args.args[0].endswith("DMT_Basemap_2022/MapServer/export")
    assert get.await_args.kwargs["params"]["bboxSR"] == "3857"
    assert get.await_args.kwargs["params"]["imageSR"] == "3857"


@pytest.mark.asyncio
async def test_cached_service_uses_arcgis_tile_row_column_order():
    response = httpx.Response(
        200,
        content=b"jpeg-data",
        headers={"content-type": "image/jpeg"},
        request=httpx.Request("GET", "https://example.test/tile"),
    )
    with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=response)) as get:
        await fetch_dmt_basemap_tile("dmt-basemap-wm", 9, 332, 220)

    assert get.await_args.args[0].endswith("DMT_Basemap_WM/MapServer/tile/9/220/332")
    assert get.await_args.kwargs["params"] is None


@pytest.mark.asyncio
async def test_cached_service_falls_back_to_export_for_sparse_cache_miss():
    missing = httpx.Response(
        404,
        content=b"missing",
        headers={"content-type": "text/html"},
        request=httpx.Request("GET", "https://example.test/tile"),
    )
    exported = httpx.Response(
        200,
        content=b"png-data",
        headers={"content-type": "image/png"},
        request=httpx.Request("GET", "https://example.test/export"),
    )
    with patch(
        "httpx.AsyncClient.get",
        new=AsyncMock(side_effect=[missing, exported]),
    ) as get:
        content, content_type = await fetch_dmt_basemap_tile(
            "dmt-basemap-wm", 11, 1334, 881,
        )

    assert content == b"png-data"
    assert content_type == "image/png"
    assert get.await_count == 2
    assert get.await_args_list[1].args[0].endswith("DMT_Basemap_WM/MapServer/export")
    assert get.await_args_list[1].kwargs["params"]["bboxSR"] == "3857"

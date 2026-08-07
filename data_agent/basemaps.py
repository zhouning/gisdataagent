"""Governed basemap registry and tile access for the map panel."""

from __future__ import annotations

from dataclasses import asdict, dataclass

import httpx

DMT_ARCGIS_BASE = "https://geosmart.dmt.gov.ae/arcgis/rest/services/BaseMaps"
WEB_MERCATOR_HALF_WORLD = 20037508.342789244


@dataclass(frozen=True)
class DMTBasemap:
    id: str
    name: str
    service: str
    cached: bool
    min_zoom: int = 0
    max_zoom: int = 20
    attribution: str = "Abu Dhabi Department of Municipalities and Transport"


DMT_BASEMAPS: tuple[DMTBasemap, ...] = (
    DMTBasemap(
        id="dmt-basemap-2022",
        name="DMT Basemap 2022",
        service="DMT_Basemap_2022",
        cached=False,
    ),
    DMTBasemap(
        id="dmt-basemap-2025-district",
        name="DMT Basemap 2025 District",
        service="DMT_Basemap_2025_District",
        cached=False,
    ),
    DMTBasemap(
        id="dmt-basemap-gcs-live",
        name="DMT Basemap GCS (Live)",
        service="DMT_Basemap_GCS_NoCache",
        cached=False,
    ),
    DMTBasemap(
        id="dmt-basemap-wm",
        name="DMT Basemap WM",
        service="DMT_Basemap_WM",
        cached=True,
        min_zoom=7,
        max_zoom=19,
    ),
    DMTBasemap(
        id="dmt-green-features",
        name="DMT Green Features",
        service="DMT_GreenFeatures",
        cached=False,
    ),
)

_DMT_BASEMAP_BY_ID = {item.id: item for item in DMT_BASEMAPS}


def list_dmt_basemaps() -> list[dict]:
    """Return browser-safe configuration for every governed DMT basemap."""
    result = []
    for item in DMT_BASEMAPS:
        entry = asdict(item)
        entry["tile_url"] = f"/api/basemaps/dmt/{item.id}/tiles/{{z}}/{{x}}/{{y}}"
        entry["source_url"] = f"{DMT_ARCGIS_BASE}/{item.service}/MapServer"
        result.append(entry)
    return result


def web_mercator_tile_bounds(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    """Return an XYZ tile bbox in EPSG:3857 coordinates."""
    if z < 0 or z > 22:
        raise ValueError("zoom must be between 0 and 22")
    tile_count = 1 << z
    if x < 0 or y < 0 or x >= tile_count or y >= tile_count:
        raise ValueError("tile coordinate is outside the zoom level")

    span = (WEB_MERCATOR_HALF_WORLD * 2) / tile_count
    xmin = -WEB_MERCATOR_HALF_WORLD + x * span
    xmax = xmin + span
    ymax = WEB_MERCATOR_HALF_WORLD - y * span
    ymin = ymax - span
    return xmin, ymin, xmax, ymax


async def fetch_dmt_basemap_tile(
    basemap_id: str,
    z: int,
    x: int,
    y: int,
) -> tuple[bytes, str]:
    """Fetch a cached tile or export a dynamic MapServer tile."""
    basemap = _DMT_BASEMAP_BY_ID.get(basemap_id)
    if basemap is None:
        raise KeyError(basemap_id)
    bounds = web_mercator_tile_bounds(z, x, y)
    service_url = f"{DMT_ARCGIS_BASE}/{basemap.service}/MapServer"
    export_params = {
        "bbox": ",".join(f"{coordinate:.8f}" for coordinate in bounds),
        "bboxSR": "3857",
        "imageSR": "3857",
        "size": "256,256",
        "format": "png32",
        "transparent": "true",
        "f": "image",
    }

    if basemap.cached:
        url = f"{service_url}/tile/{z}/{y}/{x}"
        params = None
    else:
        url = f"{service_url}/export"
        params = export_params

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        response = await client.get(
            url,
            params=params,
            headers={"User-Agent": "GISDataAgent/1.0 DMT basemap proxy"},
        )
        if basemap.cached and response.status_code == 404:
            response = await client.get(
                f"{service_url}/export",
                params=export_params,
                headers={"User-Agent": "GISDataAgent/1.0 DMT basemap proxy"},
            )
        response.raise_for_status()

    content_type = response.headers.get("content-type", "").split(";", 1)[0]
    if not content_type.startswith("image/"):
        raise RuntimeError(f"DMT basemap returned non-image content: {content_type or 'unknown'}")
    return response.content, content_type

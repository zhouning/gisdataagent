"""WMS / WMTS tile-service connector (v14.5).

Unlike vector connectors, ``WmsConnector.query()`` does **not** download
raster data.  Instead it returns a *layer config dict* that the frontend
renders via Leaflet's ``L.TileLayer.WMS``.
"""

import logging
from typing import Optional

from . import BaseConnector, ConnectorRegistry, build_auth_headers, HTTP_TIMEOUT

logger = logging.getLogger(__name__)


class WmsConnector(BaseConnector):
    SOURCE_TYPE = "wms"

    async def query(
        self,
        endpoint_url: str,
        auth_config: dict,
        query_config: dict,
        *,
        bbox: Optional[list[float]] = None,
        filter_expr: Optional[str] = None,
        limit: int = 1000,
        extra_params: Optional[dict] = None,
        target_crs: Optional[str] = None,
    ) -> dict:
        """Return a map-layer config dict for the frontend to render as WMS tiles."""
        layers = query_config.get("layers", "")
        styles = query_config.get("styles", "")
        fmt = query_config.get("format", "image/png")
        transparent = query_config.get("transparent", True)
        version = query_config.get("version", "1.1.1")
        srs = query_config.get("srs", target_crs or "EPSG:4326")

        return {
            "type": "wms_tile",
            "url": endpoint_url,
            "wms_params": {
                "layers": layers,
                "styles": styles,
                "format": fmt,
                "transparent": transparent,
                "version": version,
                "srs": srs,
            },
            "name": query_config.get("layer_name", layers or "WMS Layer"),
        }

    async def health_check(self, endpoint_url: str, auth_config: dict) -> dict:
        import httpx
        headers = build_auth_headers(auth_config)
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    endpoint_url,
                    params={"service": "WMS", "request": "GetCapabilities"},
                    headers=headers,
                )
                resp.raise_for_status()
            return {"health": "healthy", "message": "OK"}
        except httpx.TimeoutException:
            return {"health": "timeout", "message": "Connection timed out"}
        except Exception as e:
            return {"health": "error", "message": str(e)[:200]}

    async def get_capabilities(self, endpoint_url: str, auth_config: dict) -> dict:
        """Parse WMS GetCapabilities XML to discover available layers."""
        import httpx
        import xml.etree.ElementTree as ET

        headers = build_auth_headers(auth_config)
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.get(
                endpoint_url,
                params={"service": "WMS", "request": "GetCapabilities"},
                headers=headers,
            )
            resp.raise_for_status()

        root = ET.fromstring(resp.text)
        layers = []
        # Walk all <Layer> elements — handle both namespaced and bare tags
        for elem in root.iter():
            if not elem.tag.endswith("Layer"):
                continue
            name_el = None
            title_el = None
            for child in elem:
                tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                if tag == "Name":
                    name_el = child
                elif tag == "Title":
                    title_el = child
            # Only include layers that have a <Name> (queryable)
            if name_el is not None and name_el.text:
                entry: dict = {"name": name_el.text}
                if title_el is not None and title_el.text:
                    entry["title"] = title_el.text
                # Avoid duplicate entries
                if entry not in layers:
                    layers.append(entry)

        version = root.attrib.get("version", "1.1.1")
        return {"layers": layers, "service": "WMS", "version": version}


ConnectorRegistry.register(WmsConnector())

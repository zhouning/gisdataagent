"""WFS (Web Feature Service) connector."""

import logging
from typing import Optional

from . import BaseConnector, ConnectorRegistry, build_auth_headers, HTTP_TIMEOUT

logger = logging.getLogger(__name__)


class WfsConnector(BaseConnector):
    SOURCE_TYPE = "wfs"

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
    ):
        import httpx
        import geopandas as gpd

        feature_type = query_config.get("feature_type", "")
        version = query_config.get("version", "2.0.0")
        max_feat = query_config.get("max_features", limit)

        params = {
            "service": "WFS",
            "request": "GetFeature",
            "typeName": feature_type,
            "version": version,
            "outputFormat": "application/json",
            "count": str(min(max_feat, limit)),
        }
        if bbox:
            params["bbox"] = ",".join(str(v) for v in bbox)
        if filter_expr:
            params["CQL_FILTER"] = filter_expr

        headers = build_auth_headers(auth_config)

        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.get(endpoint_url, params=params, headers=headers)
            resp.raise_for_status()

        data = resp.json()
        if not data.get("features"):
            return gpd.GeoDataFrame()

        gdf = gpd.GeoDataFrame.from_features(data["features"], crs="EPSG:4326")

        crs_info = data.get("crs", {}).get("properties", {}).get("name")
        if crs_info:
            try:
                gdf = gdf.set_crs(crs_info, allow_override=True)
            except Exception:
                pass

        if target_crs and gdf.crs and str(gdf.crs) != target_crs:
            gdf = gdf.to_crs(target_crs)

        return gdf

    async def health_check(self, endpoint_url: str, auth_config: dict) -> dict:
        import httpx
        headers = build_auth_headers(auth_config)
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    endpoint_url,
                    params={"service": "WFS", "request": "GetCapabilities"},
                    headers=headers,
                )
                resp.raise_for_status()
            return {"health": "healthy", "message": "OK"}
        except httpx.TimeoutException:
            return {"health": "timeout", "message": "Connection timed out"}
        except Exception as e:
            return {"health": "error", "message": str(e)[:200]}

    async def get_capabilities(self, endpoint_url: str, auth_config: dict) -> dict:
        import httpx
        import xml.etree.ElementTree as ET

        headers = build_auth_headers(auth_config)
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.get(
                endpoint_url,
                params={"service": "WFS", "request": "GetCapabilities"},
                headers=headers,
            )
            resp.raise_for_status()

        root = ET.fromstring(resp.text)
        # Handle WFS 1.x and 2.x namespaces
        ns = {"wfs": root.tag.split("}")[0].strip("{") if "}" in root.tag else ""}
        layers = []
        # Try WFS 2.0 FeatureType elements
        for ft in root.iter():
            if ft.tag.endswith("FeatureType"):
                name_el = ft.find("{%s}Name" % ns.get("wfs", "")) if ns.get("wfs") else ft.find("Name")
                title_el = ft.find("{%s}Title" % ns.get("wfs", "")) if ns.get("wfs") else ft.find("Title")
                layers.append({
                    "name": name_el.text if name_el is not None else "",
                    "title": title_el.text if title_el is not None else "",
                })
        return {"layers": layers, "service": "WFS"}


ConnectorRegistry.register(WfsConnector())

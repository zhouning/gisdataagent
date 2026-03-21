"""OGC API Features connector."""

import logging
from typing import Optional

from . import BaseConnector, ConnectorRegistry, build_auth_headers, HTTP_TIMEOUT

logger = logging.getLogger(__name__)


class OgcApiConnector(BaseConnector):
    SOURCE_TYPE = "ogc_api"

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

        collection = query_config.get("collection", "")
        items_url = f"{endpoint_url.rstrip('/')}/collections/{collection}/items"

        params = {
            "f": "json",
            "limit": str(min(limit, query_config.get("limit", 1000))),
        }
        if bbox:
            params["bbox"] = ",".join(str(v) for v in bbox)

        headers = build_auth_headers(auth_config)

        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.get(items_url, params=params, headers=headers)
            resp.raise_for_status()

        data = resp.json()
        features = data.get("features", [])
        if not features:
            return gpd.GeoDataFrame()

        gdf = gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")
        if target_crs and gdf.crs and str(gdf.crs) != target_crs:
            gdf = gdf.to_crs(target_crs)
        return gdf

    async def health_check(self, endpoint_url: str, auth_config: dict) -> dict:
        import httpx
        headers = build_auth_headers(auth_config)
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(endpoint_url, headers=headers)
                resp.raise_for_status()
            return {"health": "healthy", "message": "OK"}
        except httpx.TimeoutException:
            return {"health": "timeout", "message": "Connection timed out"}
        except Exception as e:
            return {"health": "error", "message": str(e)[:200]}

    async def get_capabilities(self, endpoint_url: str, auth_config: dict) -> dict:
        import httpx
        headers = build_auth_headers(auth_config)
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.get(
                endpoint_url.rstrip("/") + "/collections",
                headers=headers,
            )
            resp.raise_for_status()

        data = resp.json()
        collections = data.get("collections", [])
        layers = [
            {"name": c.get("id", ""), "title": c.get("title", "")}
            for c in collections
        ]
        return {"layers": layers, "service": "OGC API Features"}


ConnectorRegistry.register(OgcApiConnector())

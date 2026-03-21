"""STAC (Spatio-Temporal Asset Catalog) connector."""

import logging
from typing import Optional

from . import BaseConnector, ConnectorRegistry, build_auth_headers, HTTP_TIMEOUT

logger = logging.getLogger(__name__)


class StacConnector(BaseConnector):
    SOURCE_TYPE = "stac"

    async def query(
        self,
        endpoint_url: str,
        auth_config: dict,
        query_config: dict,
        *,
        bbox: Optional[list[float]] = None,
        filter_expr: Optional[str] = None,
        limit: int = 20,
        extra_params: Optional[dict] = None,
        target_crs: Optional[str] = None,
    ) -> list[dict]:
        import httpx

        search_url = endpoint_url.rstrip("/") + "/search"
        headers = build_auth_headers(auth_config)
        headers["Content-Type"] = "application/json"

        body: dict = {"limit": min(limit, 100)}
        collection_id = query_config.get("collection_id")
        if collection_id:
            body["collections"] = [collection_id]
        if bbox:
            body["bbox"] = bbox
        dt = filter_expr or query_config.get("datetime_range")
        if dt:
            body["datetime"] = dt

        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.post(search_url, json=body, headers=headers)
            resp.raise_for_status()

        data = resp.json()
        items = data.get("features", [])
        results = []
        for item in items:
            props = item.get("properties", {})
            assets = item.get("assets", {})
            results.append({
                "id": item.get("id"),
                "datetime": props.get("datetime"),
                "bbox": item.get("bbox"),
                "collection": item.get("collection"),
                "cloud_cover": props.get("eo:cloud_cover"),
                "thumbnail": assets.get("thumbnail", {}).get("href"),
                "data_href": (assets.get("data", {}).get("href")
                              or assets.get("visual", {}).get("href")),
                "properties": props,
            })
        return results

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
            {"name": c.get("id", ""), "title": c.get("title", ""), "description": c.get("description", "")}
            for c in collections
        ]
        return {"layers": layers, "service": "STAC"}


ConnectorRegistry.register(StacConnector())

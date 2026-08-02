"""STAC (Spatio-Temporal Asset Catalog) connector."""

import logging

from . import HTTP_TIMEOUT, BaseConnector, ConnectorRegistry, build_auth_headers
from .schema_discovery import json_document_columns

logger = logging.getLogger(__name__)


def _client_kwargs(auth_config: dict, default_timeout: float = HTTP_TIMEOUT) -> dict:
    config = auth_config or {}
    timeout = config.get("timeout_seconds", default_timeout)
    try:
        timeout = float(timeout)
    except (TypeError, ValueError):
        timeout = default_timeout
    if timeout <= 0:
        timeout = default_timeout

    kwargs: dict = {"timeout": int(timeout) if timeout.is_integer() else timeout}
    proxy_url = (config.get("proxy_url") or "").strip()
    if proxy_url:
        kwargs["proxy"] = proxy_url
    return kwargs


class StacConnector(BaseConnector):
    SOURCE_TYPE = "stac"

    async def query(
        self,
        endpoint_url: str,
        auth_config: dict,
        query_config: dict,
        *,
        bbox: list[float] | None = None,
        filter_expr: str | None = None,
        limit: int = 20,
        extra_params: dict | None = None,
        target_crs: str | None = None,
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
        if extra_params:
            for key in ("query", "sortby", "fields"):
                if key in extra_params:
                    body[key] = extra_params[key]

        async with httpx.AsyncClient(**_client_kwargs(auth_config)) as client:
            resp = await client.post(search_url, json=body, headers=headers)
            resp.raise_for_status()

        data = resp.json()
        items = data.get("features", [])
        results = []
        for item in items:
            props = item.get("properties", {})
            assets = item.get("assets", {})
            results.append(
                {
                    "id": item.get("id"),
                    "datetime": props.get("datetime"),
                    "bbox": item.get("bbox"),
                    "collection": item.get("collection"),
                    "cloud_cover": props.get("eo:cloud_cover"),
                    "thumbnail": assets.get("thumbnail", {}).get("href"),
                    "data_href": (
                        assets.get("data", {}).get("href") or assets.get("visual", {}).get("href")
                    ),
                    "properties": props,
                }
            )
        return results

    async def health_check(self, endpoint_url: str, auth_config: dict) -> dict:
        import httpx

        headers = build_auth_headers(auth_config)
        try:
            async with httpx.AsyncClient(
                **_client_kwargs(auth_config, default_timeout=10)
            ) as client:
                resp = await client.get(endpoint_url, headers=headers)
                resp.raise_for_status()
            return {"health": "healthy", "message": "OK"}
        except httpx.TimeoutException:
            return {"health": "timeout", "message": "Connection timed out"}
        except Exception as e:
            return {"health": "error", "message": str(e)[:200]}

    async def get_capabilities(self, endpoint_url: str, auth_config: dict) -> dict:
        return await self.discover(endpoint_url, auth_config)

    async def discover(
        self,
        endpoint_url: str,
        auth_config: dict,
        query_config: dict | None = None,
    ) -> dict:
        import httpx

        headers = build_auth_headers(auth_config)
        async with httpx.AsyncClient(**_client_kwargs(auth_config)) as client:
            root_resp = await client.get(endpoint_url, headers=headers)
            root_resp.raise_for_status()
            collections_resp = await client.get(
                endpoint_url.rstrip("/") + "/collections",
                headers=headers,
            )
            collections_resp.raise_for_status()

            config = query_config or {}
            collection_id = str(config.get("collection_id") or "")
            search_data = None
            if collection_id:
                search_resp = await client.post(
                    endpoint_url.rstrip("/") + "/search",
                    json={"collections": [collection_id], "limit": 100},
                    headers={**headers, "Content-Type": "application/json"},
                )
                search_resp.raise_for_status()
                search_data = search_resp.json()

        root = root_resp.json()
        data = collections_resp.json()
        collections = data.get("collections", [])
        if collection_id:
            collections = [
                collection
                for collection in collections
                if collection.get("id") == collection_id
            ]
            if not collections:
                return {"error": f"STAC collection not found: {collection_id}", "layers": []}

        layers = []
        for collection in collections:
            layer = {
                "name": collection.get("id", ""),
                "type": "collection",
                "title": collection.get("title", ""),
                "description": collection.get("description", ""),
            }
            if search_data is not None:
                features = search_data.get("features") or []
                columns, record_count, schema_truncated = json_document_columns(
                    {"type": "FeatureCollection", "features": features},
                    record_limit=100,
                )
                layer["columns"] = columns
                layer["schema_record_count"] = record_count
                layer["schema_truncated"] = schema_truncated
            layers.append(layer)

        search_truncated = bool(
            search_data
            and (
                any(link.get("rel") == "next" for link in search_data.get("links") or [])
                or any(layer.get("schema_truncated") for layer in layers)
            )
        )
        return {
            "layers": layers,
            "service": "STAC",
            "provider": root.get("id") or root.get("title") or "STAC API",
            "provider_version": root.get("stac_version", "unknown"),
            "conforms_to": root.get("conformsTo", []),
            "collection_count": len(layers),
            "truncated": search_truncated,
        }


ConnectorRegistry.register(StacConnector())

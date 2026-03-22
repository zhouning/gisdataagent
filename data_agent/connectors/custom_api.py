"""Custom REST API connector."""

import logging
from typing import Optional

from . import BaseConnector, ConnectorRegistry, build_auth_headers, HTTP_TIMEOUT

logger = logging.getLogger(__name__)


class CustomApiConnector(BaseConnector):
    SOURCE_TYPE = "custom_api"

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
        import httpx

        method = query_config.get("method", "GET").upper()
        response_path = query_config.get("response_path", "")
        default_params = query_config.get("params", {})
        body = query_config.get("body")

        merged_params = {**default_params, **(extra_params or {})}

        url = endpoint_url
        try:
            url = url.format_map(merged_params)
        except (KeyError, ValueError):
            pass

        headers = build_auth_headers(auth_config)

        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            if method in ("POST", "PUT", "PATCH") and body:
                headers["Content-Type"] = "application/json"
                resp = await client.request(method, url, json=body, headers=headers)
            else:
                resp = await client.request(method, url, params=merged_params, headers=headers)
            resp.raise_for_status()

        data = resp.json()

        if response_path:
            for key in response_path.split("."):
                if isinstance(data, dict):
                    data = data.get(key, data)
                else:
                    break

        return data if isinstance(data, dict) else {"results": data}

    async def health_check(self, endpoint_url: str, auth_config: dict) -> dict:
        import httpx
        headers = build_auth_headers(auth_config)
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.request("HEAD", endpoint_url, headers=headers)
                resp.raise_for_status()
            return {"health": "healthy", "message": "OK"}
        except httpx.TimeoutException:
            return {"health": "timeout", "message": "Connection timed out"}
        except Exception as e:
            return {"health": "error", "message": str(e)[:200]}

    async def get_capabilities(self, endpoint_url: str, auth_config: dict) -> dict:
        return {"discovery": False, "service": "Custom API",
                "message": "Custom APIs do not support standard capability discovery."}


ConnectorRegistry.register(CustomApiConnector())

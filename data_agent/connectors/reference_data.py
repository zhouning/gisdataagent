"""Reference Data Service connector — queries control points and precision comparison."""

import logging
from typing import Any, Optional

from . import BaseConnector, ConnectorRegistry, build_auth_headers, HTTP_TIMEOUT

logger = logging.getLogger(__name__)


class ReferenceDataConnector(BaseConnector):
    """Connector for the Reference Data microservice (control points, datum, precision)."""

    SOURCE_TYPE = "reference_data"

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
    ) -> Any:
        import httpx

        endpoint = query_config.get("endpoint", "nearby")
        params = query_config.get("params", {})
        merged = {**params, **(extra_params or {})}
        headers = build_auth_headers(auth_config)

        if bbox:
            merged["bbox"] = ",".join(str(v) for v in bbox)
        if limit:
            merged["limit"] = limit

        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            if endpoint == "nearby":
                resp = await client.get(
                    f"{endpoint_url}/api/v1/points/nearby",
                    params=merged, headers=headers,
                )
            elif endpoint == "point":
                point_id = merged.pop("point_id", "")
                resp = await client.get(
                    f"{endpoint_url}/api/v1/points/{point_id}",
                    headers=headers,
                )
            elif endpoint == "compare":
                resp = await client.post(
                    f"{endpoint_url}/api/v1/compare/coordinates",
                    json=merged, headers=headers,
                )
            elif endpoint == "datum":
                datum_id = merged.pop("datum_id", "")
                resp = await client.get(
                    f"{endpoint_url}/api/v1/datum/{datum_id}",
                    headers=headers,
                )
            else:
                return {"status": "error", "message": f"Unknown endpoint: {endpoint}"}

            resp.raise_for_status()

        return resp.json()

    async def health_check(self, endpoint_url: str, auth_config: dict) -> dict:
        import httpx
        headers = build_auth_headers(auth_config)
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{endpoint_url}/health", headers=headers)
                resp.raise_for_status()
            return {"health": "healthy", "message": "OK"}
        except httpx.TimeoutException:
            return {"health": "timeout", "message": "Connection timed out"}
        except Exception as e:
            return {"health": "error", "message": str(e)[:200]}

    async def get_capabilities(self, endpoint_url: str, auth_config: dict) -> dict:
        return {
            "discovery": True,
            "service": "Reference Data Service",
            "endpoints": ["nearby", "point", "compare", "datum"],
            "description": "Control points, datum parameters, and precision comparison",
        }


ConnectorRegistry.register(ReferenceDataConnector())

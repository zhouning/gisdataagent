"""ArcGIS REST FeatureServer / MapServer connector (v14.5).

Supports paginated feature queries returning GeoDataFrames, service-info
discovery, and health checking.
"""

import logging
from typing import Optional

from . import BaseConnector, ConnectorRegistry, build_auth_headers, HTTP_TIMEOUT

logger = logging.getLogger(__name__)

_MAX_RECORDS_CAP = 5000
_PAGE_SIZE = 2000


class ArcGISRestConnector(BaseConnector):
    SOURCE_TYPE = "arcgis_rest"

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

        layer_id = query_config.get("layer_id", 0)
        where = filter_expr or query_config.get("where", "1=1")
        out_fields = query_config.get("out_fields", "*")
        return_geometry = query_config.get("return_geometry", True)
        max_records = min(limit, _MAX_RECORDS_CAP)
        page_size = min(_PAGE_SIZE, max_records)

        query_url = f"{endpoint_url.rstrip('/')}/{layer_id}/query"
        params: dict = {
            "where": where,
            "outFields": out_fields,
            "returnGeometry": str(return_geometry).lower(),
            "f": "geojson",
            "resultRecordCount": str(page_size),
        }
        if bbox:
            params["geometry"] = f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}"
            params["geometryType"] = "esriGeometryEnvelope"
            params["inSR"] = "4326"

        headers = build_auth_headers(auth_config)

        all_features: list = []
        offset = 0

        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            while True:
                params["resultOffset"] = str(offset)
                resp = await client.get(query_url, params=params, headers=headers)
                resp.raise_for_status()
                data = resp.json()

                # ArcGIS may return an error object
                if "error" in data:
                    msg = data["error"].get("message", str(data["error"]))
                    return {"status": "error", "message": msg}

                features = data.get("features", [])
                all_features.extend(features)

                if len(features) < page_size or len(all_features) >= max_records:
                    break
                offset += len(features)

        if not all_features:
            return gpd.GeoDataFrame()

        # Trim to limit
        all_features = all_features[:max_records]
        gdf = gpd.GeoDataFrame.from_features(all_features, crs="EPSG:4326")

        if target_crs and gdf.crs and str(gdf.crs) != target_crs:
            gdf = gdf.to_crs(target_crs)

        return gdf

    async def health_check(self, endpoint_url: str, auth_config: dict) -> dict:
        import httpx
        headers = build_auth_headers(auth_config)
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    endpoint_url, params={"f": "json"}, headers=headers,
                )
                resp.raise_for_status()
                data = resp.json()
                if "error" in data:
                    return {"health": "error", "message": data["error"].get("message", "Service error")}
            return {"health": "healthy", "message": "OK"}
        except httpx.TimeoutException:
            return {"health": "timeout", "message": "Connection timed out"}
        except Exception as e:
            return {"health": "error", "message": str(e)[:200]}

    async def get_capabilities(self, endpoint_url: str, auth_config: dict) -> dict:
        """Discover available layers from the FeatureServer/MapServer."""
        import httpx
        headers = build_auth_headers(auth_config)

        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            # Try /layers endpoint first (richer info)
            resp = await client.get(
                f"{endpoint_url.rstrip('/')}/layers",
                params={"f": "json"},
                headers=headers,
            )
            if resp.status_code == 200:
                data = resp.json()
                if "layers" in data:
                    layers = [
                        {
                            "id": lyr.get("id"),
                            "name": lyr.get("name", ""),
                            "geometryType": lyr.get("geometryType", ""),
                        }
                        for lyr in data["layers"]
                    ]
                    return {"layers": layers, "service": "ArcGIS REST"}

            # Fallback: service-level info
            resp = await client.get(
                endpoint_url, params={"f": "json"}, headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
            layers = [
                {"id": lyr.get("id"), "name": lyr.get("name", "")}
                for lyr in data.get("layers", [])
            ]
            return {
                "layers": layers,
                "service": "ArcGIS REST",
                "description": data.get("serviceDescription", ""),
            }


ConnectorRegistry.register(ArcGISRestConnector())

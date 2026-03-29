"""Object Storage connector — S3/OBS/OSS direct file access (v15.0).

Users register cloud object storage buckets as virtual data sources.
Supports reading GeoJSON, GeoParquet, CSV, and Shapefile from S3-compatible endpoints.
"""

import logging
import os
import tempfile
from typing import Optional

from . import BaseConnector, ConnectorRegistry, HTTP_TIMEOUT

logger = logging.getLogger(__name__)


class ObjectStorageConnector(BaseConnector):
    SOURCE_TYPE = "object_storage"

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
        """Download and read a file from S3-compatible object storage.

        endpoint_url: s3://bucket/key or https://obs.region.com/bucket/key
        auth_config: {"type": "apikey", "key": "access_key", "header": "secret_key"}
                     or use environment AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY
        query_config: {"format": "geojson|csv|parquet|shapefile", "layer": "..."}
        """
        import httpx
        import geopandas as gpd

        obj_key = query_config.get("key", "")
        fmt = query_config.get("format", "").lower()
        bucket = query_config.get("bucket", "")

        # Build download URL
        if endpoint_url.startswith("s3://"):
            # Parse s3://bucket/key format
            parts = endpoint_url[5:].split("/", 1)
            bucket = parts[0]
            obj_key = parts[1] if len(parts) > 1 else obj_key
            # Use AWS default endpoint or env override
            base = os.environ.get("AWS_ENDPOINT_URL", "https://s3.amazonaws.com")
            download_url = f"{base}/{bucket}/{obj_key}"
        else:
            download_url = endpoint_url
            if obj_key:
                download_url = f"{endpoint_url.rstrip('/')}/{obj_key}"

        # Download to temp file
        headers = {}
        if auth_config.get("type") == "apikey":
            # Simple token-based auth for OBS/OSS
            headers["Authorization"] = f"Bearer {auth_config.get('key', '')}"

        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT * 2) as client:
                resp = await client.get(download_url, headers=headers)
                resp.raise_for_status()

            # Detect format from key extension if not specified
            if not fmt:
                ext = os.path.splitext(obj_key or download_url)[1].lower()
                format_map = {".geojson": "geojson", ".json": "geojson",
                              ".csv": "csv", ".parquet": "parquet",
                              ".shp": "shapefile", ".gpkg": "gpkg"}
                fmt = format_map.get(ext, "geojson")

            # Save to temp and read
            suffix = {"geojson": ".geojson", "csv": ".csv", "parquet": ".parquet",
                       "gpkg": ".gpkg", "shapefile": ".shp"}.get(fmt, ".geojson")
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(resp.content)
                tmp_path = tmp.name

            try:
                if fmt == "csv":
                    import pandas as pd
                    df = pd.read_csv(tmp_path)
                    # Try to create GeoDataFrame if coordinate columns exist
                    cols_lower = [c.lower() for c in df.columns]
                    if "lng" in cols_lower and "lat" in cols_lower:
                        x_col = df.columns[cols_lower.index("lng")]
                        y_col = df.columns[cols_lower.index("lat")]
                        gdf = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df[x_col], df[y_col]),
                                                crs="EPSG:4326")
                        return gdf
                    return df
                elif fmt == "parquet":
                    gdf = gpd.read_parquet(tmp_path)
                else:
                    gdf = gpd.read_file(tmp_path)

                if target_crs and hasattr(gdf, 'crs') and gdf.crs and str(gdf.crs) != target_crs:
                    gdf = gdf.to_crs(target_crs)
                return gdf
            finally:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

        except Exception as e:
            return {"status": "error", "message": str(e)[:300]}

    async def health_check(self, endpoint_url: str, auth_config: dict) -> dict:
        import httpx
        headers = {}
        if auth_config.get("type") == "apikey":
            headers["Authorization"] = f"Bearer {auth_config.get('key', '')}"
        try:
            url = endpoint_url
            if url.startswith("s3://"):
                parts = url[5:].split("/", 1)
                base = os.environ.get("AWS_ENDPOINT_URL", "https://s3.amazonaws.com")
                url = f"{base}/{parts[0]}/"
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.head(url, headers=headers)
                if resp.status_code < 500:
                    return {"health": "healthy", "message": "OK"}
                return {"health": "error", "message": f"HTTP {resp.status_code}"}
        except httpx.TimeoutException:
            return {"health": "timeout", "message": "Connection timed out"}
        except Exception as e:
            return {"health": "error", "message": str(e)[:200]}

    async def get_capabilities(self, endpoint_url: str, auth_config: dict) -> dict:
        """List objects in the bucket (if accessible)."""
        return {
            "discovery": False,
            "service": "Object Storage",
            "message": "Object storage does not support standard capability discovery. Specify key in query_config.",
        }


ConnectorRegistry.register(ObjectStorageConnector())

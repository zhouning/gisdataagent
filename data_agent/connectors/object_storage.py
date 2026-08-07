"""Object Storage connector — S3/OBS/OSS direct file access (v15.0).

Users register cloud object storage buckets as virtual data sources.
Supports reading GeoJSON, GeoParquet, CSV, and Shapefile from S3-compatible endpoints.
"""

import json
import logging
import os
import tempfile

from . import HTTP_TIMEOUT, BaseConnector, ConnectorRegistry
from .schema_discovery import json_document_columns

logger = logging.getLogger(__name__)


def _s3_target(endpoint_url: str, query_config: dict) -> tuple[str, str, str] | None:
    bucket = str(query_config.get("bucket") or "")
    key = str(query_config.get("key") or "")
    endpoint = endpoint_url
    if endpoint_url.startswith("s3://"):
        parts = endpoint_url[5:].split("/", 1)
        bucket = parts[0]
        key = parts[1] if len(parts) > 1 else key
        endpoint = str(query_config.get("endpoint_url") or os.environ.get("AWS_ENDPOINT_URL") or "")
    if not bucket:
        return None
    return endpoint, bucket, key


def _s3_client(endpoint_url: str, auth_config: dict):
    import boto3
    from botocore.config import Config as BotoConfig

    config = auth_config or {}
    auth_type = config.get("type", "none")
    access_key = config.get("access_key_id")
    secret_key = config.get("secret_access_key")
    if auth_type == "basic":
        access_key = config.get("username")
        secret_key = config.get("password")
    elif auth_type == "apikey":
        access_key = config.get("key")
        secret_key = config.get("secret") or config.get("header")
    kwargs = {
        "region_name": config.get("region_name") or os.environ.get("AWS_REGION", "us-east-1"),
    }
    if access_key:
        kwargs["aws_access_key_id"] = access_key
    if secret_key:
        kwargs["aws_secret_access_key"] = secret_key
    if config.get("session_token"):
        kwargs["aws_session_token"] = config["session_token"]
    if endpoint_url:
        kwargs["endpoint_url"] = endpoint_url
        kwargs["config"] = BotoConfig(s3={"addressing_style": "path"})
    return boto3.client("s3", **kwargs)


class ObjectStorageConnector(BaseConnector):
    SOURCE_TYPE = "object_storage"

    async def query(
        self,
        endpoint_url: str,
        auth_config: dict,
        query_config: dict,
        *,
        bbox: list[float] | None = None,
        filter_expr: str | None = None,
        limit: int = 1000,
        extra_params: dict | None = None,
        target_crs: str | None = None,
    ):
        """Download and read a file from S3-compatible object storage.

        endpoint_url: s3://bucket/key or https://obs.region.com/bucket/key
        auth_config: runtime-only ``aws_sigv4`` or legacy basic/apikey credentials
        query_config: {"format": "geojson|csv|parquet|shapefile", "layer": "..."}
        """
        import geopandas as gpd
        import httpx

        obj_key = query_config.get("key", "")
        fmt = query_config.get("format", "").lower()
        bucket = query_config.get("bucket", "")

        target = _s3_target(endpoint_url, query_config)
        if target is not None:
            endpoint, bucket, obj_key = target
            if not obj_key:
                return {"status": "error", "message": "object key is required"}
            try:
                response = _s3_client(endpoint, auth_config).get_object(
                    Bucket=bucket,
                    Key=obj_key,
                )
                content = response["Body"].read()
            except Exception as e:
                return {"status": "error", "message": str(e)[:300]}
        else:
            content = None

        # Retain the existing unsigned HTTP path for non-S3 object endpoints.
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
            if content is None:
                async with httpx.AsyncClient(timeout=HTTP_TIMEOUT * 2) as client:
                    resp = await client.get(download_url, headers=headers)
                    resp.raise_for_status()
                content = resp.content

            # Detect format from key extension if not specified
            if not fmt:
                ext = os.path.splitext(obj_key or download_url)[1].lower()
                format_map = {
                    ".geojson": "geojson",
                    ".json": "geojson",
                    ".csv": "csv",
                    ".parquet": "parquet",
                    ".shp": "shapefile",
                    ".gpkg": "gpkg",
                }
                fmt = format_map.get(ext, "geojson")

            # Save to temp and read
            suffix = {
                "geojson": ".geojson",
                "csv": ".csv",
                "parquet": ".parquet",
                "gpkg": ".gpkg",
                "shapefile": ".shp",
            }.get(fmt, ".geojson")
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(content)
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
                        gdf = gpd.GeoDataFrame(
                            df,
                            geometry=gpd.points_from_xy(df[x_col], df[y_col]),
                            crs="EPSG:4326",
                        )
                        return gdf
                    return df
                elif fmt == "parquet":
                    gdf = gpd.read_parquet(tmp_path)
                else:
                    gdf = gpd.read_file(tmp_path)

                if target_crs and hasattr(gdf, "crs") and gdf.crs and str(gdf.crs) != target_crs:
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

        if (auth_config or {}).get("type") in {"aws_sigv4", "basic"}:
            try:
                response = _s3_client(endpoint_url, auth_config).list_buckets()
                metadata = response.get("ResponseMetadata", {})
                return {
                    "health": "healthy",
                    "message": "OK",
                    "provider": metadata.get("HTTPHeaders", {}).get("server", "S3"),
                }
            except Exception as e:
                return {"health": "error", "message": str(e)[:200]}
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
                if 200 <= resp.status_code < 400:
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
            "message": (
                "Object storage does not support standard capability discovery. "
                "Specify key in query_config."
            ),
        }

    async def discover(
        self,
        endpoint_url: str,
        auth_config: dict,
        query_config: dict | None = None,
    ) -> dict:
        config = query_config or {}
        target = _s3_target(endpoint_url, config)
        if target is None:
            return await self.get_capabilities(endpoint_url, auth_config)
        endpoint, bucket, prefix = target
        try:
            client = _s3_client(endpoint, auth_config)
            response = client.list_objects_v2(
                Bucket=bucket,
                Prefix=prefix,
                MaxKeys=min(int(config.get("discovery_limit", 50)), 1000),
            )
            layers = [
                {
                    "name": item["Key"],
                    "type": "object",
                    "size": int(item["Size"]),
                    "etag": str(item.get("ETag") or "").strip('"'),
                }
                for item in response.get("Contents", [])
            ]
            schema_truncated = False
            if str(config.get("format") or "").lower() == "geojson":
                exact_layer = next((layer for layer in layers if layer["name"] == prefix), None)
                if exact_layer is not None:
                    object_response = client.get_object(Bucket=bucket, Key=prefix)
                    try:
                        document = json.loads(object_response["Body"].read())
                    finally:
                        object_response["Body"].close()
                    columns, record_count, schema_truncated = json_document_columns(
                        document,
                        record_limit=min(int(config.get("discovery_limit", 50)), 1000),
                    )
                    exact_layer["columns"] = columns
                    exact_layer["schema_record_count"] = record_count
            headers = response.get("ResponseMetadata", {}).get("HTTPHeaders", {})
            return {
                "layers": layers,
                "service": "Object Storage",
                "provider": headers.get("server", "S3"),
                "provider_version": headers.get("x-minio-version", "S3-compatible"),
                "bucket": bucket,
                "prefix": prefix,
                "object_count": len(layers),
                "truncated": bool(response.get("IsTruncated", False)) or schema_truncated,
            }
        except Exception as e:
            return {"error": str(e)[:200], "layers": []}


ConnectorRegistry.register(ObjectStorageConnector())

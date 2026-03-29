"""
StorageManager — unified data lake storage abstraction layer.

Provides URI-based routing so that tools can transparently read/write data
across local filesystem, S3/OBS cloud storage, and PostGIS without knowing
the backend. All existing tools continue to use local file paths; the
StorageManager handles download-on-read and upload-on-write behind the scenes.

URI schemes:
  file://  or bare path  → local filesystem (default)
  s3://{bucket}/{key}    → S3/OBS object storage
  obs://{bucket}/{key}   → alias for s3:// (Huawei OBS)
  postgis://{table}      → PostGIS table

Environment variables:
  DEFAULT_STORAGE_BACKEND  — 'local' (default) | 'cloud' | 'postgis'
                             Controls where tool outputs are persisted.
  LAKE_CACHE_DIR           — Local cache directory for cloud files
                             (default: data_agent/.lake_cache)

Architecture:
  ┌──────────────────────────────────────────────┐
  │  Agent Tools (gis_processors, toolsets/*)     │
  │   read: _resolve_path() → local path          │
  │   write: _generate_output_path() → local path │
  └──────────┬──────────────────┬─────────────────┘
             │ resolve()        │ store()
  ┌──────────▼──────────────────▼─────────────────┐
  │           StorageManager (this module)          │
  │  ┌─────────┐  ┌──────────┐  ┌──────────────┐  │
  │  │  Local   │  │ S3 / OBS │  │   PostGIS    │  │
  │  └─────────┘  └──────────┘  └──────────────┘  │
  └────────────────────────────────────────────────┘
"""
import hashlib
import os
import shutil
import threading
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from .observability import get_logger

logger = get_logger("storage_manager")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_BASE_DIR = os.path.dirname(__file__)
_DEFAULT_CACHE_DIR = os.path.join(_BASE_DIR, ".lake_cache")


def _get_cache_dir() -> str:
    d = os.environ.get("LAKE_CACHE_DIR", _DEFAULT_CACHE_DIR)
    os.makedirs(d, exist_ok=True)
    return d


def get_default_backend() -> str:
    """Return the configured default storage backend."""
    return os.environ.get("DEFAULT_STORAGE_BACKEND", "local")


# ---------------------------------------------------------------------------
# URI Parsing
# ---------------------------------------------------------------------------

class StorageURI:
    """Parsed storage URI with scheme, bucket, key, and path."""

    __slots__ = ("scheme", "bucket", "key", "path", "raw")

    def __init__(self, uri: str):
        self.raw = uri
        if "://" in uri:
            parsed = urlparse(uri)
            self.scheme = parsed.scheme.lower()  # s3, obs, file, postgis
            if self.scheme in ("s3", "obs"):
                self.bucket = parsed.netloc
                self.key = parsed.path.lstrip("/")
                self.path = None
            elif self.scheme == "postgis":
                self.bucket = None
                self.key = None
                self.path = parsed.netloc + parsed.path  # table name
            elif self.scheme == "file":
                self.bucket = None
                self.key = None
                self.path = parsed.path
                # Windows: file:///D:/path → D:/path
                if self.path and len(self.path) > 2 and self.path[0] == "/" and self.path[2] == ":":
                    self.path = self.path[1:]
            else:
                self.scheme = "file"
                self.bucket = None
                self.key = None
                self.path = uri
        else:
            # Bare path — treat as local file
            self.scheme = "file"
            self.bucket = None
            self.key = None
            self.path = uri

    @property
    def is_local(self) -> bool:
        return self.scheme == "file"

    @property
    def is_cloud(self) -> bool:
        return self.scheme in ("s3", "obs")

    @property
    def is_postgis(self) -> bool:
        return self.scheme == "postgis"

    @property
    def filename(self) -> str:
        if self.key:
            return os.path.basename(self.key)
        if self.path:
            return os.path.basename(self.path)
        return ""

    def __repr__(self):
        return f"StorageURI({self.raw!r})"


# ---------------------------------------------------------------------------
# StorageManager Singleton
# ---------------------------------------------------------------------------

class StorageManager:
    """Unified storage layer for data lake architecture.

    Core operations:
      resolve(uri)  → local_path    Download cloud file to cache if needed.
      store(local, uri) → uri       Upload local file to cloud / copy to target.
      delete(uri) → bool            Remove file from any backend.
      exists(uri) → bool            Check existence on any backend.
      list_objects(prefix) → list    List cloud objects under prefix.

    High-level convenience:
      open_dataframe(uri) → GeoDataFrame   Read spatial data from any backend.
      save_dataframe(gdf, name, ...) → uri  Write GeoDataFrame to configured backend.
    """

    def __init__(self):
        self._cloud = None  # lazy
        self._cloud_checked = False
        self._lock = threading.Lock()

    # ----- Cloud adapter (lazy) -----

    def _get_cloud(self):
        if not self._cloud_checked:
            with self._lock:
                if not self._cloud_checked:
                    try:
                        from .cloud_storage import get_cloud_adapter
                        self._cloud = get_cloud_adapter()
                    except Exception as e:
                        logger.warning("Cloud storage not available: %s", e)
                        self._cloud = None
                    self._cloud_checked = True
        return self._cloud

    @property
    def cloud_available(self) -> bool:
        return self._get_cloud() is not None

    # ----- resolve: URI → local path -----

    def resolve(self, uri: str) -> str:
        """Resolve a URI to a local file path.

        For local URIs: returns the path directly (if exists).
        For cloud URIs: downloads to local cache, returns cached path.
        For postgis URIs: returns the table name as-is (tools handle DB access).
        """
        parsed = StorageURI(uri)

        if parsed.is_local:
            return parsed.path

        if parsed.is_postgis:
            return parsed.path  # Table name for DB access

        if parsed.is_cloud:
            return self._resolve_cloud(parsed)

        return uri  # fallback

    def _resolve_cloud(self, parsed: StorageURI) -> str:
        """Download cloud file to local cache. Returns cached local path."""
        cloud = self._get_cloud()
        if not cloud:
            logger.warning("Cloud storage not configured, cannot resolve: %s", parsed.raw)
            return parsed.raw  # Return raw URI; tool will likely fail

        cache_dir = _get_cache_dir()
        # Use hash of key for cache path to avoid collisions
        key_hash = hashlib.md5(parsed.key.encode()).hexdigest()[:12]
        cache_subdir = os.path.join(cache_dir, key_hash)
        os.makedirs(cache_subdir, exist_ok=True)
        local_path = os.path.join(cache_subdir, parsed.filename)

        # Check cache freshness (skip re-download if file exists and < 5 min old)
        if os.path.isfile(local_path):
            import time
            age = time.time() - os.path.getmtime(local_path)
            if age < 300:  # 5 min cache
                return local_path

        # Download
        key = parsed.key
        if parsed.filename.lower().endswith(".shp"):
            result = cloud.download_file_smart(key, cache_subdir)
        else:
            result = cloud.download(key, local_path)
            result = local_path if result else None

        if result and os.path.isfile(result):
            logger.info("[Lake] Cached: %s → %s", parsed.raw, result)
            return result

        logger.warning("[Lake] Download failed: %s", parsed.raw)
        return parsed.raw

    # ----- store: local path → URI -----

    def store(self, local_path: str, target_uri: str = None,
              user_id: str = None) -> str:
        """Store a local file to the target backend.

        Args:
            local_path: Path to the local file.
            target_uri: Target URI. If None, uses DEFAULT_STORAGE_BACKEND.
            user_id: User ID for key construction (cloud backend).

        Returns:
            URI string for the stored file.
        """
        if not os.path.isfile(local_path):
            return f"file://{local_path}"

        if target_uri:
            parsed = StorageURI(target_uri)
        else:
            backend = get_default_backend()
            if backend == "cloud":
                # Build cloud URI from filename
                uid = user_id or "default"
                filename = os.path.basename(local_path)
                cloud = self._get_cloud()
                if cloud:
                    bucket = cloud.get_bucket_name()
                    parsed = StorageURI(f"s3://{bucket}/{uid}/{filename}")
                else:
                    return f"file://{os.path.abspath(local_path)}"
            else:
                return f"file://{os.path.abspath(local_path)}"

        if parsed.is_local:
            # Copy to target path if different
            target = parsed.path
            if os.path.abspath(local_path) != os.path.abspath(target):
                os.makedirs(os.path.dirname(target), exist_ok=True)
                shutil.copy2(local_path, target)
            return f"file://{os.path.abspath(target)}"

        if parsed.is_cloud:
            return self._store_cloud(local_path, parsed, user_id)

        return f"file://{os.path.abspath(local_path)}"

    def _store_cloud(self, local_path: str, parsed: StorageURI,
                     user_id: str = None) -> str:
        """Upload local file to cloud storage."""
        cloud = self._get_cloud()
        if not cloud:
            logger.warning("[Lake] Cloud not available, keeping local: %s", local_path)
            return f"file://{os.path.abspath(local_path)}"

        uid = user_id or "default"
        keys = cloud.upload_file_smart(local_path, uid)
        if keys:
            bucket = cloud.get_bucket_name()
            scheme = "s3"
            uri = f"{scheme}://{bucket}/{keys[0]}"
            logger.info("[Lake] Stored: %s → %s", local_path, uri)
            return uri

        logger.warning("[Lake] Upload failed, keeping local: %s", local_path)
        return f"file://{os.path.abspath(local_path)}"

    # ----- exists -----

    def exists(self, uri: str) -> bool:
        """Check if a resource exists at the given URI."""
        parsed = StorageURI(uri)

        if parsed.is_local:
            return os.path.exists(parsed.path)

        if parsed.is_cloud:
            cloud = self._get_cloud()
            if cloud:
                return cloud.exists(parsed.key)
            return False

        if parsed.is_postgis:
            try:
                from .db_engine import get_engine
                from sqlalchemy import text
                engine = get_engine()
                if engine:
                    with engine.connect() as conn:
                        r = conn.execute(text(
                            "SELECT 1 FROM information_schema.tables WHERE table_name = :t"
                        ), {"t": parsed.path}).fetchone()
                        return r is not None
            except Exception:
                return False

        return False

    # ----- delete -----

    def delete(self, uri: str) -> bool:
        """Delete a resource at the given URI."""
        parsed = StorageURI(uri)

        if parsed.is_local:
            if os.path.isfile(parsed.path):
                os.remove(parsed.path)
                return True
            return False

        if parsed.is_cloud:
            cloud = self._get_cloud()
            if cloud:
                return cloud.delete(parsed.key)
            return False

        return False

    # ----- list_objects (cloud) -----

    def list_objects(self, prefix: str = "", user_id: str = None) -> list:
        """List objects in cloud storage under prefix.

        Returns list of dicts: {"uri": str, "key": str, "size": int, "filename": str}
        """
        cloud = self._get_cloud()
        if not cloud:
            return []

        search_prefix = f"{user_id}/{prefix}" if user_id else prefix
        try:
            objects = cloud.list_objects(search_prefix)
            bucket = cloud.get_bucket_name()
            return [
                {
                    "uri": f"s3://{bucket}/{obj['key']}",
                    "key": obj["key"],
                    "filename": obj.get("filename", os.path.basename(obj["key"])),
                    "size": obj.get("size", 0),
                    "last_modified": obj.get("last_modified", ""),
                }
                for obj in objects
            ]
        except Exception as e:
            logger.warning("[Lake] List failed: %s", e)
            return []

    # ----- High-level: DataFrame I/O -----

    def open_dataframe(self, uri: str):
        """Read a spatial dataset from any backend into a GeoDataFrame.

        Supports: local files, cloud files (auto-download), PostGIS tables.
        """
        import geopandas as gpd
        parsed = StorageURI(uri)

        if parsed.is_postgis:
            from .db_engine import get_engine
            engine = get_engine()
            if engine:
                return gpd.read_postgis(
                    f"SELECT * FROM {parsed.path}", engine, geom_col="geometry"
                )
            raise RuntimeError("Database not available")

        # For file and cloud: resolve to local path first
        local_path = self.resolve(uri)
        if not os.path.isfile(local_path):
            raise FileNotFoundError(f"Cannot resolve: {uri}")

        ext = local_path.rsplit(".", 1)[-1].lower() if "." in local_path else ""
        if ext in ("csv", "xlsx", "xls"):
            import pandas as pd
            df = pd.read_csv(local_path) if ext == "csv" else pd.read_excel(local_path)
            # Auto-detect geometry columns
            lon_col = next((c for c in df.columns if c.lower() in
                           ("lon", "lng", "longitude", "x")), None)
            lat_col = next((c for c in df.columns if c.lower() in
                           ("lat", "latitude", "y")), None)
            if lon_col and lat_col:
                from shapely.geometry import Point
                geometry = [Point(xy) for xy in zip(df[lon_col], df[lat_col])]
                return gpd.GeoDataFrame(df, geometry=geometry, crs="EPSG:4326")
            return df  # Return plain DataFrame if no geometry
        return gpd.read_file(local_path)

    def save_dataframe(self, gdf, name: str, user_id: str = None,
                       file_format: str = "gpkg") -> str:
        """Save a GeoDataFrame to the configured default backend.

        Args:
            gdf: GeoDataFrame or DataFrame to save.
            name: Base filename (without extension).
            user_id: User ID for path construction.
            file_format: Output format — gpkg, geojson, shp, csv, parquet.

        Returns:
            URI string for the saved file.
        """
        import uuid
        uid8 = uuid.uuid4().hex[:8]
        filename = f"{name}_{uid8}.{file_format}"

        backend = get_default_backend()

        if backend == "postgis":
            try:
                from .db_engine import get_engine
                engine = get_engine()
                if engine:
                    table_name = f"{name}_{uid8}"
                    import geopandas as gpd
                    if isinstance(gdf, gpd.GeoDataFrame):
                        gdf.to_postgis(table_name, engine, if_exists="replace", index=False)
                    else:
                        gdf.to_sql(table_name, engine, if_exists="replace", index=False)
                    return f"postgis://{table_name}"
            except Exception as e:
                logger.warning("[Lake] PostGIS save failed, falling back to local: %s", e)

        # Write to local first (always needed, even for cloud)
        from .user_context import get_user_upload_dir
        local_dir = get_user_upload_dir() if not user_id else os.path.join(
            os.path.dirname(__file__), "uploads", user_id)
        os.makedirs(local_dir, exist_ok=True)
        local_path = os.path.join(local_dir, filename)

        import geopandas as gpd
        if file_format == "csv":
            gdf.to_csv(local_path, index=False)
        elif file_format == "parquet":
            gdf.to_parquet(local_path, index=False)
        elif isinstance(gdf, gpd.GeoDataFrame):
            driver = {"gpkg": "GPKG", "geojson": "GeoJSON", "shp": "ESRI Shapefile"}.get(
                file_format, "GPKG")
            gdf.to_file(local_path, driver=driver)
        else:
            gdf.to_csv(local_path, index=False)

        # If cloud backend, upload
        if backend == "cloud":
            return self.store(local_path, user_id=user_id or "default")

        return f"file://{os.path.abspath(local_path)}"

    # ----- Info -----

    def get_info(self) -> dict:
        """Return storage system info for diagnostics."""
        cloud = self._get_cloud()
        return {
            "default_backend": get_default_backend(),
            "cloud_available": cloud is not None,
            "cloud_bucket": cloud.get_bucket_name() if cloud else None,
            "cache_dir": _get_cache_dir(),
            "cache_size_mb": self._cache_size_mb(),
        }

    def _cache_size_mb(self) -> float:
        cache_dir = _get_cache_dir()
        if not os.path.isdir(cache_dir):
            return 0.0
        total = sum(
            os.path.getsize(os.path.join(r, f))
            for r, _, files in os.walk(cache_dir) for f in files
        )
        return round(total / (1024 * 1024), 2)

    def clear_cache(self) -> int:
        """Clear the local cache directory. Returns number of files removed."""
        cache_dir = _get_cache_dir()
        if not os.path.isdir(cache_dir):
            return 0
        count = sum(len(files) for _, _, files in os.walk(cache_dir))
        shutil.rmtree(cache_dir, ignore_errors=True)
        os.makedirs(cache_dir, exist_ok=True)
        return count


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: Optional[StorageManager] = None
_instance_lock = threading.Lock()


def get_storage_manager() -> StorageManager:
    """Return the singleton StorageManager instance."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = StorageManager()
    return _instance


def reset_storage_manager():
    """Reset singleton (for testing)."""
    global _instance
    _instance = None

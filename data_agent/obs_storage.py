"""
Cloud storage integration (backward-compatible shim).

All public functions delegate to cloud_storage.get_cloud_adapter().
Signatures are identical to the original boto3-only implementation,
so no caller changes are needed.

S3 key structure: {user_id}/{filename}
"""
import os
import logging
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)

SHAPEFILE_SIDECAR_EXTS = ['.cpg', '.dbf', '.prj', '.shx', '.sbn', '.sbx', '.shp.xml']


def is_obs_configured() -> bool:
    """Check if cloud storage is configured (any provider)."""
    from .cloud_storage import is_cloud_configured
    return is_cloud_configured()


def get_s3_client():
    """Return the cloud adapter (backward compat name).

    .. deprecated:: Use cloud_storage.get_cloud_adapter() directly.
    """
    from .cloud_storage import get_cloud_adapter
    return get_cloud_adapter()


# --------------- Upload ---------------

def upload_to_obs(local_path: str, user_id: str,
                  s3_key: Optional[str] = None) -> Optional[str]:
    """Upload a single local file to cloud. Returns key or None."""
    from .cloud_storage import get_cloud_adapter
    adapter = get_cloud_adapter()
    if not adapter:
        return None
    return adapter.upload_file(local_path, user_id, key=s3_key)


def upload_shapefile_bundle(shp_path: str, user_id: str) -> List[str]:
    """Upload a .shp and all its sidecar files. Returns list of uploaded keys."""
    from .cloud_storage import get_cloud_adapter
    adapter = get_cloud_adapter()
    if not adapter:
        return []
    return adapter.upload_shapefile_bundle(shp_path, user_id)


def upload_file_smart(local_path: str, user_id: str) -> List[str]:
    """Smart upload: .shp -> bundle, otherwise single file. Returns uploaded keys."""
    from .cloud_storage import get_cloud_adapter
    adapter = get_cloud_adapter()
    if not adapter:
        return []
    return adapter.upload_file_smart(local_path, user_id)


# --------------- Download ---------------

def download_from_obs(s3_key: str, local_path: str) -> bool:
    """Download a single object to local_path. Returns True on success."""
    from .cloud_storage import get_cloud_adapter
    adapter = get_cloud_adapter()
    if not adapter:
        return False
    try:
        return adapter.download(s3_key, local_path)
    except Exception as e:
        logger.error("[OBS] Download failed for %s: %s", s3_key, e)
        return False


def download_shapefile_bundle(shp_s3_key: str, local_dir: str) -> Optional[str]:
    """Download a .shp and all its sidecar files. Returns local .shp path."""
    from .cloud_storage import get_cloud_adapter
    adapter = get_cloud_adapter()
    if not adapter:
        return None
    return adapter._download_bundle(shp_s3_key, local_dir)


def download_file_smart(s3_key: str, local_dir: str) -> Optional[str]:
    """Smart download: .shp -> bundle, otherwise single file. Returns local path."""
    from .cloud_storage import get_cloud_adapter
    adapter = get_cloud_adapter()
    if not adapter:
        return None
    return adapter.download_file_smart(s3_key, local_dir)


# --------------- Delete ---------------

def delete_from_obs(s3_key: str) -> bool:
    """Delete a single object from cloud."""
    from .cloud_storage import get_cloud_adapter
    adapter = get_cloud_adapter()
    if not adapter:
        return False
    try:
        return adapter.delete(s3_key)
    except Exception as e:
        logger.error("[OBS] Delete failed for %s: %s", s3_key, e)
        return False


def delete_shapefile_bundle_from_obs(shp_s3_key: str) -> int:
    """Delete a .shp and all its sidecar files. Returns count deleted."""
    from .cloud_storage import get_cloud_adapter
    adapter = get_cloud_adapter()
    if not adapter:
        return 0
    return adapter.delete_shapefile_bundle(shp_s3_key)


# --------------- List ---------------

def list_user_objects(user_id: str) -> List[Dict]:
    """List all objects under user's prefix. Returns [{filename, size, ...}]."""
    from .cloud_storage import get_cloud_adapter
    adapter = get_cloud_adapter()
    if not adapter:
        return []
    try:
        return adapter.list_user_objects(user_id)
    except Exception as e:
        logger.error("[OBS] List objects failed for user %s: %s", user_id, e)
        return []


# --------------- Presigned URL ---------------

def generate_presigned_url(s3_key: str, expiration: int = 3600) -> Optional[str]:
    """Generate a presigned URL for external sharing (default 1 hour)."""
    from .cloud_storage import get_cloud_adapter
    adapter = get_cloud_adapter()
    if not adapter:
        return None
    return adapter.get_presigned_url(s3_key, expiration)


# --------------- Startup ---------------

def ensure_obs_connection():
    """Test cloud connectivity at startup."""
    from .cloud_storage import get_cloud_adapter
    adapter = get_cloud_adapter()
    if adapter is None:
        print("[Cloud] Not configured. Cloud storage disabled, using local-only mode.")
        return
    try:
        if adapter.health_check():
            print(f"[Cloud] Connected to bucket '{adapter.get_bucket_name()}' successfully.")
        else:
            print("[Cloud] WARNING: Health check failed. Falling back to local-only mode.")
    except Exception as e:
        print(f"[Cloud] WARNING: Connection test failed: {e}. Falling back to local-only mode.")

"""
Huawei Cloud OBS (S3-compatible) storage integration.

Provides upload, download, list, delete, and presigned URL generation
via standard S3 protocol (boto3). Falls back gracefully to local-only
mode when OBS is not configured.

S3 key structure: {user_id}/{filename}
"""
import os
import logging
import threading
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)

SHAPEFILE_SIDECAR_EXTS = ['.cpg', '.dbf', '.prj', '.shx', '.sbn', '.sbx', '.shp.xml']

_s3_client = None
_s3_lock = threading.Lock()


def is_obs_configured() -> bool:
    """Check if all required OBS environment variables are set."""
    return all([
        os.environ.get("HUAWEI_OBS_AK"),
        os.environ.get("HUAWEI_OBS_SK"),
        os.environ.get("HUAWEI_OBS_SERVER"),
        os.environ.get("HUAWEI_OBS_BUCKET"),
    ])


def get_s3_client():
    """Return singleton boto3 S3 client configured for Huawei OBS."""
    global _s3_client
    if _s3_client is not None:
        return _s3_client
    with _s3_lock:
        if _s3_client is not None:
            return _s3_client
        if not is_obs_configured():
            return None
        import boto3
        _s3_client = boto3.client(
            's3',
            aws_access_key_id=os.environ["HUAWEI_OBS_AK"],
            aws_secret_access_key=os.environ["HUAWEI_OBS_SK"],
            endpoint_url=os.environ["HUAWEI_OBS_SERVER"],
            region_name='cn-north-4',
        )
        return _s3_client


def _get_bucket() -> str:
    return os.environ.get("HUAWEI_OBS_BUCKET", "")


def _user_s3_key(user_id: str, filename: str) -> str:
    """Build the S3 key: {user_id}/{filename}."""
    return f"{user_id}/{filename}"


# --------------- Upload ---------------

def upload_to_obs(local_path: str, user_id: str,
                  s3_key: Optional[str] = None) -> Optional[str]:
    """Upload a single local file to OBS. Returns s3_key or None."""
    client = get_s3_client()
    if not client:
        return None
    if not os.path.exists(local_path):
        logger.warning("[OBS] File not found for upload: %s", local_path)
        return None
    if s3_key is None:
        s3_key = _user_s3_key(user_id, os.path.basename(local_path))
    try:
        client.upload_file(local_path, _get_bucket(), s3_key)
        logger.info("[OBS] Uploaded: %s", s3_key)
        return s3_key
    except Exception as e:
        logger.error("[OBS] Upload failed for %s: %s", local_path, e)
        return None


def upload_shapefile_bundle(shp_path: str, user_id: str) -> List[str]:
    """Upload a .shp and all its sidecar files. Returns list of uploaded keys."""
    uploaded = []
    base, _ = os.path.splitext(shp_path)
    all_files = [shp_path]
    for sidecar_ext in SHAPEFILE_SIDECAR_EXTS:
        sidecar_path = base + sidecar_ext
        if os.path.exists(sidecar_path):
            all_files.append(sidecar_path)
    for fpath in all_files:
        key = upload_to_obs(fpath, user_id)
        if key:
            uploaded.append(key)
    return uploaded


def upload_file_smart(local_path: str, user_id: str) -> List[str]:
    """Smart upload: .shp -> bundle, otherwise single file. Returns uploaded keys."""
    if local_path.lower().endswith('.shp'):
        return upload_shapefile_bundle(local_path, user_id)
    key = upload_to_obs(local_path, user_id)
    return [key] if key else []


# --------------- Download ---------------

def download_from_obs(s3_key: str, local_path: str) -> bool:
    """Download a single S3 object to local_path. Returns True on success."""
    client = get_s3_client()
    if not client:
        return False
    try:
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        client.download_file(_get_bucket(), s3_key, local_path)
        logger.info("[OBS] Downloaded: %s -> %s", s3_key, local_path)
        return True
    except Exception as e:
        logger.error("[OBS] Download failed for %s: %s", s3_key, e)
        return False


def download_shapefile_bundle(shp_s3_key: str, local_dir: str) -> Optional[str]:
    """Download a .shp and all its sidecar files. Returns local .shp path."""
    client = get_s3_client()
    if not client:
        return None
    base_key, _ = os.path.splitext(shp_s3_key)
    filename = os.path.basename(shp_s3_key)
    try:
        resp = client.list_objects_v2(Bucket=_get_bucket(), Prefix=base_key)
        for obj in resp.get('Contents', []):
            obj_key = obj['Key']
            obj_filename = os.path.basename(obj_key)
            local_path = os.path.join(local_dir, obj_filename)
            download_from_obs(obj_key, local_path)
        return os.path.join(local_dir, filename)
    except Exception as e:
        logger.error("[OBS] Shapefile bundle download failed: %s", e)
        return None


def download_file_smart(s3_key: str, local_dir: str) -> Optional[str]:
    """Smart download: .shp -> bundle, otherwise single file. Returns local path."""
    filename = os.path.basename(s3_key)
    if filename.lower().endswith('.shp'):
        return download_shapefile_bundle(s3_key, local_dir)
    local_path = os.path.join(local_dir, filename)
    if download_from_obs(s3_key, local_path):
        return local_path
    return None


# --------------- Delete ---------------

def delete_from_obs(s3_key: str) -> bool:
    """Delete a single object from OBS."""
    client = get_s3_client()
    if not client:
        return False
    try:
        client.delete_object(Bucket=_get_bucket(), Key=s3_key)
        logger.info("[OBS] Deleted: %s", s3_key)
        return True
    except Exception as e:
        logger.error("[OBS] Delete failed for %s: %s", s3_key, e)
        return False


def delete_shapefile_bundle_from_obs(shp_s3_key: str) -> int:
    """Delete a .shp and all its sidecar files. Returns count deleted."""
    client = get_s3_client()
    if not client:
        return 0
    base_key, _ = os.path.splitext(shp_s3_key)
    count = 0
    try:
        resp = client.list_objects_v2(Bucket=_get_bucket(), Prefix=base_key)
        for obj in resp.get('Contents', []):
            if delete_from_obs(obj['Key']):
                count += 1
    except Exception:
        pass
    return count


# --------------- List ---------------

def list_user_objects(user_id: str) -> List[Dict]:
    """List all objects under user's S3 prefix. Returns [{filename, size, ...}]."""
    client = get_s3_client()
    if not client:
        return []
    prefix = f"{user_id}/"
    results = []
    try:
        paginator = client.get_paginator('list_objects_v2')
        for page in paginator.paginate(Bucket=_get_bucket(), Prefix=prefix):
            for obj in page.get('Contents', []):
                results.append({
                    "key": obj['Key'],
                    "filename": os.path.basename(obj['Key']),
                    "size": obj['Size'],
                    "last_modified": obj['LastModified'].isoformat(),
                })
    except Exception as e:
        logger.error("[OBS] List objects failed for user %s: %s", user_id, e)
    return results


# --------------- Presigned URL ---------------

def generate_presigned_url(s3_key: str, expiration: int = 3600) -> Optional[str]:
    """Generate a presigned URL for external sharing (default 1 hour)."""
    client = get_s3_client()
    if not client:
        return None
    try:
        url = client.generate_presigned_url(
            'get_object',
            Params={'Bucket': _get_bucket(), 'Key': s3_key},
            ExpiresIn=expiration,
        )
        return url
    except Exception as e:
        logger.error("[OBS] Presigned URL failed for %s: %s", s3_key, e)
        return None


# --------------- Startup ---------------

def ensure_obs_connection():
    """Test OBS connectivity at startup."""
    if not is_obs_configured():
        print("[OBS] Not configured (HUAWEI_OBS_AK/SK/SERVER/BUCKET missing). "
              "Cloud storage disabled, using local-only mode.")
        return
    client = get_s3_client()
    if client:
        try:
            client.head_bucket(Bucket=_get_bucket())
            print(f"[OBS] Connected to bucket '{_get_bucket()}' successfully.")
        except Exception as e:
            print(f"[OBS] WARNING: Connection test failed: {e}. "
                  "Falling back to local-only mode.")
    else:
        print("[OBS] WARNING: Failed to create S3 client.")

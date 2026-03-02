"""
Multi-provider cloud storage abstraction layer.

Provides a unified interface for cloud object storage across:
- Huawei OBS (via esdk-obs-python native SDK)
- AWS S3 (via boto3)
- Google Cloud Storage (via google-cloud-storage)

Selection is automatic based on environment variables, or explicit
via CLOUD_STORAGE_PROVIDER. Singleton pattern, thread-safe.
"""
import os
import threading
from abc import ABC, abstractmethod
from typing import Optional, List, Dict

from .observability import get_logger

logger = get_logger("cloud_storage")

SHAPEFILE_SIDECAR_EXTS = ['.cpg', '.dbf', '.prj', '.shx', '.sbn', '.sbx', '.shp.xml']


# =====================================================================
# Abstract Base
# =====================================================================

class CloudStorageAdapter(ABC):
    """Abstract base class for cloud storage providers."""

    @abstractmethod
    def upload(self, local_path: str, key: str) -> bool:
        """Upload a local file to cloud. Returns True on success."""

    @abstractmethod
    def download(self, key: str, local_path: str) -> bool:
        """Download a cloud object to local path. Returns True on success."""

    @abstractmethod
    def delete(self, key: str) -> bool:
        """Delete a cloud object. Returns True on success."""

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Check if a cloud object exists."""

    @abstractmethod
    def list_objects(self, prefix: str) -> List[Dict]:
        """List objects under prefix.
        Returns [{"key": str, "filename": str, "size": int, "last_modified": str}].
        """

    @abstractmethod
    def get_presigned_url(self, key: str, expiration: int = 3600) -> Optional[str]:
        """Generate a presigned download URL."""

    @abstractmethod
    def get_bucket_name(self) -> str:
        """Return the bucket name."""

    @abstractmethod
    def health_check(self) -> bool:
        """Test connectivity to the bucket."""

    # ---- Convenience methods (non-abstract) ----

    def user_key(self, user_id: str, filename: str) -> str:
        """Build the standard key: {user_id}/{filename}."""
        return f"{user_id}/{filename}"

    def upload_file(self, local_path: str, user_id: str,
                    key: Optional[str] = None) -> Optional[str]:
        """Upload a single file. Returns s3_key or None."""
        if not os.path.exists(local_path):
            logger.warning("[Cloud] File not found for upload: %s", local_path)
            return None
        if key is None:
            key = self.user_key(user_id, os.path.basename(local_path))
        try:
            if self.upload(local_path, key):
                logger.info("[Cloud] Uploaded: %s", key)
                return key
        except Exception as e:
            logger.error("[Cloud] Upload failed for %s: %s", local_path, e)
        return None

    def upload_shapefile_bundle(self, shp_path: str, user_id: str) -> List[str]:
        """Upload a .shp and all its sidecar files. Returns list of uploaded keys."""
        uploaded = []
        base, _ = os.path.splitext(shp_path)
        all_files = [shp_path]
        for ext in SHAPEFILE_SIDECAR_EXTS:
            sidecar = base + ext
            if os.path.exists(sidecar):
                all_files.append(sidecar)
        for fpath in all_files:
            key = self.upload_file(fpath, user_id)
            if key:
                uploaded.append(key)
        return uploaded

    def upload_file_smart(self, local_path: str, user_id: str) -> List[str]:
        """Smart upload: .shp -> bundle, otherwise single file."""
        if local_path.lower().endswith('.shp'):
            return self.upload_shapefile_bundle(local_path, user_id)
        key = self.upload_file(local_path, user_id)
        return [key] if key else []

    def download_file_smart(self, key: str, local_dir: str) -> Optional[str]:
        """Smart download: .shp -> bundle, otherwise single file."""
        filename = os.path.basename(key)
        if filename.lower().endswith('.shp'):
            return self._download_bundle(key, local_dir)
        local_path = os.path.join(local_dir, filename)
        os.makedirs(local_dir, exist_ok=True)
        if self.download(key, local_path):
            return local_path
        return None

    def _download_bundle(self, shp_key: str, local_dir: str) -> Optional[str]:
        """Download a shapefile bundle (main + sidecars)."""
        base_key, _ = os.path.splitext(shp_key)
        os.makedirs(local_dir, exist_ok=True)
        try:
            for obj in self.list_objects(base_key):
                local_path = os.path.join(local_dir, os.path.basename(obj['key']))
                self.download(obj['key'], local_path)
            return os.path.join(local_dir, os.path.basename(shp_key))
        except Exception as e:
            logger.error("[Cloud] Shapefile bundle download failed: %s", e)
            return None

    def delete_shapefile_bundle(self, shp_key: str) -> int:
        """Delete a shapefile bundle. Returns count deleted."""
        base_key, _ = os.path.splitext(shp_key)
        count = 0
        try:
            for obj in self.list_objects(base_key):
                if self.delete(obj['key']):
                    count += 1
        except Exception:
            pass
        return count

    def list_user_objects(self, user_id: str) -> List[Dict]:
        """List all objects under user's prefix."""
        return self.list_objects(f"{user_id}/")


# =====================================================================
# Huawei OBS Adapter (esdk-obs-python native SDK)
# =====================================================================

class HuaweiOBSAdapter(CloudStorageAdapter):
    """Huawei OBS using native esdk-obs-python SDK (avoids boto3 S3 compat issues)."""

    def __init__(self):
        from obs import ObsClient
        self._client = ObsClient(
            access_key_id=os.environ["HUAWEI_OBS_AK"],
            secret_access_key=os.environ["HUAWEI_OBS_SK"],
            server=os.environ["HUAWEI_OBS_SERVER"],
        )
        self._bucket = os.environ.get("HUAWEI_OBS_BUCKET", "")

    def upload(self, local_path: str, key: str) -> bool:
        resp = self._client.putFile(self._bucket, key, local_path)
        ok = resp.status < 300
        if not ok:
            logger.error("[HuaweiOBS] Upload %s failed: %s %s", key, resp.status, resp.reason)
        return ok

    def download(self, key: str, local_path: str) -> bool:
        os.makedirs(os.path.dirname(local_path) or '.', exist_ok=True)
        resp = self._client.getObject(self._bucket, key, downloadPath=local_path)
        ok = resp.status < 300
        if not ok:
            logger.error("[HuaweiOBS] Download %s failed: %s %s", key, resp.status, resp.reason)
        return ok

    def delete(self, key: str) -> bool:
        resp = self._client.deleteObject(self._bucket, key)
        return resp.status < 300

    def exists(self, key: str) -> bool:
        resp = self._client.getObjectMetadata(self._bucket, key)
        return resp.status < 300

    def list_objects(self, prefix: str) -> List[Dict]:
        results = []
        marker = None
        while True:
            kwargs = {"prefix": prefix}
            if marker:
                kwargs["marker"] = marker
            resp = self._client.listObjects(self._bucket, **kwargs)
            if resp.status >= 300:
                break
            for obj in resp.body.contents:
                results.append({
                    "key": obj.key,
                    "filename": os.path.basename(obj.key),
                    "size": obj.size,
                    "last_modified": str(obj.lastModified),
                })
            if not resp.body.is_truncated:
                break
            marker = resp.body.next_marker
        return results

    def get_presigned_url(self, key: str, expiration: int = 3600) -> Optional[str]:
        try:
            resp = self._client.createSignedUrl('GET', self._bucket, key,
                                                expires=expiration)
            return resp.signedUrl if resp else None
        except Exception as e:
            logger.error("[HuaweiOBS] Presigned URL failed for %s: %s", key, e)
            return None

    def get_bucket_name(self) -> str:
        return self._bucket

    def health_check(self) -> bool:
        try:
            resp = self._client.headBucket(self._bucket)
            return resp.status < 300
        except Exception:
            return False


# =====================================================================
# AWS S3 Adapter (boto3)
# =====================================================================

class AWSS3Adapter(CloudStorageAdapter):
    """AWS S3 via standard boto3 client."""

    def __init__(self):
        import boto3
        self._client = boto3.client(
            's3',
            aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
            region_name=os.environ.get("AWS_REGION", "us-east-1"),
        )
        self._bucket = os.environ.get("AWS_S3_BUCKET", "")

    def upload(self, local_path: str, key: str) -> bool:
        try:
            self._client.upload_file(local_path, self._bucket, key)
            return True
        except Exception as e:
            logger.error("[AWSS3] Upload %s failed: %s", key, e)
            return False

    def download(self, key: str, local_path: str) -> bool:
        try:
            os.makedirs(os.path.dirname(local_path) or '.', exist_ok=True)
            self._client.download_file(self._bucket, key, local_path)
            return True
        except Exception as e:
            logger.error("[AWSS3] Download %s failed: %s", key, e)
            return False

    def delete(self, key: str) -> bool:
        try:
            self._client.delete_object(Bucket=self._bucket, Key=key)
            return True
        except Exception as e:
            logger.error("[AWSS3] Delete %s failed: %s", key, e)
            return False

    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
            return True
        except Exception:
            return False

    def list_objects(self, prefix: str) -> List[Dict]:
        results = []
        try:
            paginator = self._client.get_paginator('list_objects_v2')
            for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
                for obj in page.get('Contents', []):
                    results.append({
                        "key": obj['Key'],
                        "filename": os.path.basename(obj['Key']),
                        "size": obj['Size'],
                        "last_modified": obj['LastModified'].isoformat(),
                    })
        except Exception as e:
            logger.error("[AWSS3] List objects failed: %s", e)
        return results

    def get_presigned_url(self, key: str, expiration: int = 3600) -> Optional[str]:
        try:
            return self._client.generate_presigned_url(
                'get_object',
                Params={'Bucket': self._bucket, 'Key': key},
                ExpiresIn=expiration,
            )
        except Exception as e:
            logger.error("[AWSS3] Presigned URL failed for %s: %s", key, e)
            return None

    def get_bucket_name(self) -> str:
        return self._bucket

    def health_check(self) -> bool:
        try:
            self._client.head_bucket(Bucket=self._bucket)
            return True
        except Exception:
            return False


# =====================================================================
# Google Cloud Storage Adapter
# =====================================================================

class GCSAdapter(CloudStorageAdapter):
    """Google Cloud Storage via google-cloud-storage SDK."""

    def __init__(self):
        from google.cloud import storage as gcs_storage
        self._gcs_client = gcs_storage.Client()
        self._bucket_name = os.environ.get("GCS_BUCKET", "")
        self._bucket = self._gcs_client.bucket(self._bucket_name)

    def upload(self, local_path: str, key: str) -> bool:
        try:
            blob = self._bucket.blob(key)
            blob.upload_from_filename(local_path)
            return True
        except Exception as e:
            logger.error("[GCS] Upload %s failed: %s", key, e)
            return False

    def download(self, key: str, local_path: str) -> bool:
        try:
            os.makedirs(os.path.dirname(local_path) or '.', exist_ok=True)
            blob = self._bucket.blob(key)
            blob.download_to_filename(local_path)
            return True
        except Exception as e:
            logger.error("[GCS] Download %s failed: %s", key, e)
            return False

    def delete(self, key: str) -> bool:
        try:
            blob = self._bucket.blob(key)
            blob.delete()
            return True
        except Exception as e:
            logger.error("[GCS] Delete %s failed: %s", key, e)
            return False

    def exists(self, key: str) -> bool:
        blob = self._bucket.blob(key)
        return blob.exists()

    def list_objects(self, prefix: str) -> List[Dict]:
        results = []
        try:
            for blob in self._gcs_client.list_blobs(self._bucket_name, prefix=prefix):
                results.append({
                    "key": blob.name,
                    "filename": os.path.basename(blob.name),
                    "size": blob.size or 0,
                    "last_modified": blob.updated.isoformat() if blob.updated else "",
                })
        except Exception as e:
            logger.error("[GCS] List objects failed: %s", e)
        return results

    def get_presigned_url(self, key: str, expiration: int = 3600) -> Optional[str]:
        try:
            import datetime
            blob = self._bucket.blob(key)
            return blob.generate_signed_url(
                expiration=datetime.timedelta(seconds=expiration),
                method='GET',
            )
        except Exception as e:
            logger.error("[GCS] Presigned URL failed for %s: %s", key, e)
            return None

    def get_bucket_name(self) -> str:
        return self._bucket_name

    def health_check(self) -> bool:
        try:
            self._bucket.reload()
            return True
        except Exception:
            return False


# =====================================================================
# Singleton Factory
# =====================================================================

_adapter_instance: Optional[CloudStorageAdapter] = None
_adapter_lock = threading.Lock()


def _detect_provider() -> Optional[str]:
    """Detect cloud provider from environment variables."""
    if os.environ.get("HUAWEI_OBS_AK"):
        return "huawei"
    if os.environ.get("AWS_ACCESS_KEY_ID") or os.environ.get("AWS_S3_BUCKET"):
        return "aws"
    if os.environ.get("GCS_BUCKET"):
        return "gcs"
    return None


def get_cloud_adapter() -> Optional[CloudStorageAdapter]:
    """Return singleton cloud storage adapter. None if not configured."""
    global _adapter_instance
    if _adapter_instance is not None:
        return _adapter_instance
    with _adapter_lock:
        if _adapter_instance is not None:
            return _adapter_instance
        provider = os.environ.get("CLOUD_STORAGE_PROVIDER") or _detect_provider()
        if not provider:
            return None
        try:
            if provider == "huawei":
                _adapter_instance = HuaweiOBSAdapter()
            elif provider == "aws":
                _adapter_instance = AWSS3Adapter()
            elif provider == "gcs":
                _adapter_instance = GCSAdapter()
            else:
                logger.warning("[Cloud] Unknown provider: %s", provider)
        except Exception as e:
            logger.error("[Cloud] Failed to create %s adapter: %s", provider, e)
    return _adapter_instance


def is_cloud_configured() -> bool:
    """Check if any cloud storage provider is configured."""
    return get_cloud_adapter() is not None


def reset_cloud_adapter():
    """Reset singleton. For testing."""
    global _adapter_instance
    with _adapter_lock:
        _adapter_instance = None

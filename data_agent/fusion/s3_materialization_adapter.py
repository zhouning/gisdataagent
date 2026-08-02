"""Optional S3/MinIO object materialization adapter for MMFE lakehouse assets."""

from __future__ import annotations

import hashlib
import mimetypes
import os
from pathlib import Path
from typing import Any


def build_s3_materialization_executor(
    *,
    endpoint_url: str | None = None,
    access_key_id: str | None = None,
    secret_access_key: str | None = None,
    region_name: str | None = None,
):
    """Build an executor that uploads local files to an S3-compatible store."""

    def executor(payload: dict[str, Any]) -> dict[str, Any]:
        return materialize_file_to_s3(
            payload,
            endpoint_url=endpoint_url,
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
            region_name=region_name,
        )

    return executor


def materialize_file_to_s3(
    payload: dict[str, Any],
    *,
    endpoint_url: str | None = None,
    access_key_id: str | None = None,
    secret_access_key: str | None = None,
    region_name: str | None = None,
) -> dict[str, Any]:
    """Upload one local file to an S3-compatible object store."""

    try:
        import boto3
        from botocore.config import Config as BotoConfig
    except Exception as exc:  # pragma: no cover - exercised when optional deps absent.
        raise RuntimeError("S3 materialization requires optional dependency: boto3") from exc

    source_path = Path(str(payload.get("source_path") or ""))
    if not source_path.exists() or not source_path.is_file():
        raise ValueError(f"source_path must be an existing file: {source_path}")

    target_uri = str(payload.get("target_uri") or "")
    bucket, key = _target_object(target_uri, source_path=source_path)
    content_type = str(payload.get("content_type") or "") or _guess_content_type(source_path)
    body = source_path.read_bytes()
    sha256 = hashlib.sha256(body).hexdigest()
    immutable = bool(payload.get("immutable", False))
    verify_readback = bool(payload.get("verify_readback", immutable))

    endpoint = endpoint_url or os.environ.get("AWS_ENDPOINT_URL") or None
    client_kwargs = {
        "aws_access_key_id": access_key_id or os.environ.get("AWS_ACCESS_KEY_ID"),
        "aws_secret_access_key": secret_access_key or os.environ.get("AWS_SECRET_ACCESS_KEY"),
        "region_name": region_name or os.environ.get("AWS_REGION", "us-east-1"),
    }
    if endpoint:
        client_kwargs["endpoint_url"] = endpoint
        client_kwargs["config"] = BotoConfig(s3={"addressing_style": "path"})

    client = boto3.client("s3", **client_kwargs)
    created = True
    if immutable:
        existing = _read_existing_object(client, bucket=bucket, key=key)
        if existing is not None:
            if existing["sha256"] != sha256 or existing["size_bytes"] != len(body):
                raise RuntimeError(
                    "immutable S3 target is already bound to different bytes: "
                    f"s3://{bucket}/{key}"
                )
            created = False

    if created:
        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=body,
            ContentType=content_type,
            Metadata={"sha256": sha256},
        )

    verified = False
    if verify_readback:
        observed = _read_existing_object(client, bucket=bucket, key=key)
        if observed is None or observed["sha256"] != sha256:
            raise RuntimeError(f"S3 read-back checksum mismatch: s3://{bucket}/{key}")
        if observed["size_bytes"] != len(body):
            raise RuntimeError(f"S3 read-back size mismatch: s3://{bucket}/{key}")
        verified = True

    return {
        "materialized": True,
        "created": created,
        "verified": verified,
        "published_count": 1,
        "target": "s3",
        "source_path": str(source_path),
        "target_uri": f"s3://{bucket}/{key}",
        "bucket": bucket,
        "key": key,
        "endpoint_url": endpoint or "",
        "bytes_written": len(body),
        "sha256": sha256,
        "content_type": content_type,
    }


def _read_existing_object(client, *, bucket: str, key: str) -> dict[str, Any] | None:
    try:
        response = client.get_object(Bucket=bucket, Key=key)
    except Exception as exc:
        error = getattr(exc, "response", {}).get("Error", {})
        if str(error.get("Code") or "") in {"404", "NoSuchKey", "NotFound"}:
            return None
        raise
    body = response["Body"].read()
    return {
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _target_object(target_uri: str, *, source_path: Path) -> tuple[str, str]:
    if not target_uri.startswith("s3://"):
        raise ValueError("target_uri must start with s3://")
    rest = target_uri[5:]
    bucket, _, key = rest.partition("/")
    if not bucket:
        raise ValueError("target_uri bucket is required")
    if not key:
        raise ValueError("target_uri key is required")
    if key.endswith("/"):
        key = f"{key}{source_path.name}"
    return bucket, key


def _guess_content_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".parquet", ".geoparquet", ".parq"}:
        return "application/vnd.apache.parquet"
    if suffix == ".geojson":
        return "application/geo+json"
    content_type, _ = mimetypes.guess_type(str(path))
    if content_type:
        return content_type
    return "application/octet-stream"

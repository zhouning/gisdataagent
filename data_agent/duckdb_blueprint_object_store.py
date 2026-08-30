"""Immutable S3/MinIO I/O for governed DuckDB Blueprint executions."""

from __future__ import annotations

import hashlib
import hmac
import os
import re
from pathlib import Path
from typing import Any, Literal, Protocol
from urllib.parse import unquote, urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .platform_contracts import Sha256

DUCKDB_BLUEPRINT_PARQUET_MEDIA_TYPE = "application/vnd.apache.parquet"
S3_OBJECT_VERSION_EVIDENCE_SCHEMA = "gda.s3_object_version.v1"

_TENANT_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_BUCKET_RE = re.compile(r"^(?=.{3,63}$)[a-z0-9][a-z0-9.-]*[a-z0-9]$")
_PREFIX_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._=-]{0,127}$")
_PRECONDITION_CODES = frozenset(
    {"409", "412", "ConditionalRequestConflict", "PreconditionFailed"}
)


class DuckDBBlueprintObjectStoreError(RuntimeError):
    """The object store could not preserve the Blueprint I/O contract."""


class DuckDBBlueprintObjectStoreUnavailable(DuckDBBlueprintObjectStoreError):
    """The object store is temporarily unavailable."""


class DuckDBBlueprintObjectStoreConflict(DuckDBBlueprintObjectStoreError):
    """An immutable object identity is bound to unexpected bytes."""


class S3ObjectVersionEvidence(BaseModel):
    """Credential-free identity of one immutable S3 object version."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        serialize_by_alias=True,
    )

    evidence_schema: Literal["gda.s3_object_version.v1"] = Field(
        default=S3_OBJECT_VERSION_EVIDENCE_SCHEMA,
        alias="schema",
    )
    version_id: str = Field(min_length=1, max_length=1024)
    etag: str = Field(min_length=1, max_length=256)

    @field_validator("version_id", "etag")
    @classmethod
    def _opaque_identity(cls, value: str) -> str:
        if (
            value != value.strip()
            or not value.isascii()
            or any(ord(character) < 33 for character in value)
        ):
            raise ValueError("S3 object identity contains unsafe whitespace")
        return value

    @field_validator("version_id")
    @classmethod
    def _immutable_version(cls, value: str) -> str:
        if value == "null":
            raise ValueError("S3 object version must be immutable")
        return value


class DuckDBBlueprintObjectStore(Protocol):
    """Narrow provider boundary for immutable Blueprint object I/O."""

    def download_input(
        self,
        uri: str,
        *,
        version_id: str,
        destination: Path,
        expected_sha256: str,
        max_bytes: int,
    ) -> int: ...

    def publish_output(
        self,
        tenant_id: str,
        run_id: UUID,
        uri: str,
        *,
        source: Path,
        expected_sha256: str,
    ) -> S3ObjectVersionEvidence: ...

    def verify_output(
        self,
        tenant_id: str,
        run_id: UUID,
        uri: str,
        *,
        evidence: S3ObjectVersionEvidence,
        expected_sha256: str,
        expected_size_bytes: int,
    ) -> None: ...

    def probe(self) -> None: ...


def validate_blueprint_s3_location(bucket: str, prefix: str) -> tuple[str, str]:
    """Validate a deployment-owned output bucket and key prefix."""

    normalized_bucket = bucket.strip()
    normalized_prefix = prefix.strip().strip("/")
    if (
        _BUCKET_RE.fullmatch(normalized_bucket) is None
        or ".." in normalized_bucket
        or ".-" in normalized_bucket
        or "-." in normalized_bucket
    ):
        raise ValueError("DuckDB Blueprint S3 bucket is invalid")
    segments = normalized_prefix.split("/")
    if (
        not normalized_prefix
        or len(normalized_prefix) > 512
        or any(_PREFIX_SEGMENT_RE.fullmatch(segment) is None for segment in segments)
    ):
        raise ValueError("DuckDB Blueprint S3 prefix is invalid")
    return normalized_bucket, normalized_prefix


def parse_blueprint_s3_uri(uri: str) -> tuple[str, str]:
    """Parse a credential-free absolute S3 URI without accepting path tricks."""

    parts = urlsplit(uri)
    bucket = parts.netloc
    key = unquote(parts.path.removeprefix("/"))
    if (
        parts.scheme != "s3"
        or not bucket
        or not key
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
        or _BUCKET_RE.fullmatch(bucket) is None
        or ".." in bucket
        or ".-" in bucket
        or "-." in bucket
        or len(key.encode("utf-8")) > 1024
        or "\\" in key
        or any(ord(character) < 32 or ord(character) == 127 for character in key)
        or any(segment in {"", ".", ".."} for segment in key.split("/"))
    ):
        raise ValueError("DuckDB Blueprint object location must be a safe S3 URI")
    return bucket, key


def blueprint_s3_output_uri(
    bucket: str,
    prefix: str,
    tenant_id: str,
    run_id: UUID,
) -> str:
    """Build the one stable immutable result identity for a Blueprint Run."""

    bucket, prefix = validate_blueprint_s3_location(bucket, prefix)
    if _TENANT_RE.fullmatch(tenant_id) is None:
        raise ValueError("DuckDB Blueprint tenant identity is unsafe")
    return f"s3://{bucket}/{prefix}/{tenant_id}/{run_id}.parquet"


def validate_blueprint_s3_input_prefixes(values: tuple[str, ...]) -> tuple[str, ...]:
    """Normalize the deployment-owned allowlist of readable object prefixes."""

    normalized: list[str] = []
    for value in values:
        bucket, key = parse_blueprint_s3_uri(value.strip().rstrip("/"))
        candidate = f"s3://{bucket}/{key}"
        if candidate not in normalized:
            normalized.append(candidate)
    if not normalized:
        raise ValueError("DuckDB Blueprint S3 input prefix allowlist is required")
    return tuple(sorted(normalized))


def blueprint_s3_input_allowed(uri: str, prefixes: tuple[str, ...]) -> bool:
    """Return whether an input URI is inside one explicit bucket/key prefix."""

    bucket, key = parse_blueprint_s3_uri(uri)
    for prefix_uri in prefixes:
        prefix_bucket, prefix_key = parse_blueprint_s3_uri(prefix_uri)
        if bucket == prefix_bucket and (
            key == prefix_key or key.startswith(f"{prefix_key}/")
        ):
            return True
    return False


class S3DuckDBBlueprintObjectStore:
    """Version-bound S3/MinIO I/O with conditional create and exact read-back."""

    def __init__(
        self,
        client: Any,
        *,
        bucket: str,
        prefix: str,
        input_prefixes: tuple[str, ...],
    ):
        if client is None:
            raise ValueError("DuckDB Blueprint S3 client is required")
        self.client = client
        self.bucket, self.prefix = validate_blueprint_s3_location(bucket, prefix)
        self.input_prefixes = validate_blueprint_s3_input_prefixes(input_prefixes)

    @staticmethod
    def _error_code(exc: Exception) -> str:
        response = getattr(exc, "response", {})
        error = response.get("Error", {}) if isinstance(response, dict) else {}
        metadata = (
            response.get("ResponseMetadata", {}) if isinstance(response, dict) else {}
        )
        return str(error.get("Code") or metadata.get("HTTPStatusCode") or "")

    @staticmethod
    def _version_id(response: dict[str, Any]) -> str:
        try:
            return S3ObjectVersionEvidence(
                version_id=str(response.get("VersionId") or ""),
                etag=S3DuckDBBlueprintObjectStore._etag(response),
            ).version_id
        except ValueError as exc:
            raise DuckDBBlueprintObjectStoreUnavailable(
                "DuckDB Blueprint storage did not return an immutable version"
            ) from exc

    @staticmethod
    def _etag(response: dict[str, Any]) -> str:
        etag = str(response.get("ETag") or "").strip()
        if len(etag) >= 2 and etag[0] == etag[-1] == '"':
            etag = etag[1:-1]
        if (
            not etag
            or not etag.isascii()
            or any(ord(character) < 33 for character in etag)
        ):
            raise DuckDBBlueprintObjectStoreUnavailable(
                "DuckDB Blueprint storage did not return an object ETag"
            )
        return etag

    def _head(
        self,
        bucket: str,
        key: str,
        *,
        version_id: str | None = None,
    ) -> dict[str, Any]:
        parameters = {"Bucket": bucket, "Key": key}
        if version_id is not None:
            parameters["VersionId"] = version_id
        try:
            return self.client.head_object(**parameters)
        except Exception as exc:
            raise DuckDBBlueprintObjectStoreUnavailable(
                "DuckDB Blueprint object identity verification failed"
            ) from exc

    def _read_to_path(
        self,
        bucket: str,
        key: str,
        version_id: str,
        destination: Path | None,
        *,
        max_bytes: int,
    ) -> tuple[int, str]:
        try:
            response = self.client.get_object(
                Bucket=bucket,
                Key=key,
                VersionId=version_id,
            )
            if str(response.get("VersionId") or "") != version_id:
                raise DuckDBBlueprintObjectStoreUnavailable(
                    "DuckDB Blueprint object read-back version changed"
                )
            try:
                declared_size = int(response.get("ContentLength"))
            except (TypeError, ValueError):
                declared_size = -1
            if declared_size > max_bytes:
                raise DuckDBBlueprintObjectStoreConflict(
                    "DuckDB Blueprint object exceeds its admitted byte limit"
                )
            body = response["Body"]
            digest = hashlib.sha256()
            observed_size = 0
            handle = destination.open("xb") if destination is not None else None
            try:
                while True:
                    chunk = body.read(1024 * 1024)
                    if not chunk:
                        break
                    observed_size += len(chunk)
                    if observed_size > max_bytes:
                        raise DuckDBBlueprintObjectStoreConflict(
                            "DuckDB Blueprint object exceeds its admitted byte limit"
                        )
                    digest.update(chunk)
                    if handle is not None:
                        handle.write(chunk)
            finally:
                if handle is not None:
                    handle.close()
                close = getattr(body, "close", None)
                if close is not None:
                    close()
            if declared_size >= 0 and observed_size != declared_size:
                raise DuckDBBlueprintObjectStoreConflict(
                    "DuckDB Blueprint object size changed during read-back"
                )
            return observed_size, digest.hexdigest()
        except DuckDBBlueprintObjectStoreError:
            if destination is not None:
                destination.unlink(missing_ok=True)
            raise
        except Exception as exc:
            if destination is not None:
                destination.unlink(missing_ok=True)
            raise DuckDBBlueprintObjectStoreUnavailable(
                "DuckDB Blueprint object read-back failed"
            ) from exc

    def download_input(
        self,
        uri: str,
        *,
        version_id: str,
        destination: Path,
        expected_sha256: str,
        max_bytes: int,
    ) -> int:
        try:
            evidence = S3ObjectVersionEvidence(version_id=version_id, etag="bound")
            if not blueprint_s3_input_allowed(uri, self.input_prefixes):
                raise DuckDBBlueprintObjectStoreConflict(
                    "DuckDB Blueprint input is outside its allowed object prefixes"
                )
            bucket, key = parse_blueprint_s3_uri(uri)
            destination.parent.mkdir(parents=True, exist_ok=True)
            size, sha256 = self._read_to_path(
                bucket,
                key,
                evidence.version_id,
                destination,
                max_bytes=max_bytes,
            )
            if not hmac.compare_digest(sha256, expected_sha256):
                destination.unlink(missing_ok=True)
                raise DuckDBBlueprintObjectStoreConflict(
                    "DuckDB Blueprint input checksum changed"
                )
            return size
        except DuckDBBlueprintObjectStoreError:
            raise
        except (OSError, ValueError) as exc:
            destination.unlink(missing_ok=True)
            raise DuckDBBlueprintObjectStoreConflict(
                "DuckDB Blueprint input object binding is invalid"
            ) from exc

    def _expected_output(
        self,
        tenant_id: str,
        run_id: UUID,
        uri: str,
    ) -> tuple[str, str]:
        expected = blueprint_s3_output_uri(
            self.bucket,
            self.prefix,
            tenant_id,
            run_id,
        )
        if uri != expected:
            raise DuckDBBlueprintObjectStoreConflict(
                "DuckDB Blueprint output is outside its managed object location"
            )
        return parse_blueprint_s3_uri(uri)

    def publish_output(
        self,
        tenant_id: str,
        run_id: UUID,
        uri: str,
        *,
        source: Path,
        expected_sha256: str,
    ) -> S3ObjectVersionEvidence:
        bucket, key = self._expected_output(tenant_id, run_id, uri)
        try:
            size = source.stat().st_size
            if not hmac.compare_digest(_file_sha256(source), expected_sha256):
                raise DuckDBBlueprintObjectStoreConflict(
                    "DuckDB Blueprint output changed before publication"
                )
            created: dict[str, Any] | None = None
            try:
                with source.open("rb") as body:
                    created = self.client.put_object(
                        Bucket=bucket,
                        Key=key,
                        Body=body,
                        ContentType=DUCKDB_BLUEPRINT_PARQUET_MEDIA_TYPE,
                        Metadata={"sha256": expected_sha256},
                        IfNoneMatch="*",
                    )
            except Exception as exc:
                if self._error_code(exc) not in _PRECONDITION_CODES:
                    raise DuckDBBlueprintObjectStoreUnavailable(
                        "DuckDB Blueprint output publication failed"
                    ) from exc

            if created is not None:
                version_id = self._version_id(created)
                created_etag = self._etag(created)
                head = self._head(bucket, key, version_id=version_id)
            else:
                head = self._head(bucket, key)
                version_id = self._version_id(head)
                created_etag = None
            evidence = S3ObjectVersionEvidence(
                version_id=version_id,
                etag=self._etag(head),
            )
            if str(head.get("VersionId") or "") != evidence.version_id or (
                created_etag is not None
                and not hmac.compare_digest(created_etag, evidence.etag)
            ):
                raise DuckDBBlueprintObjectStoreUnavailable(
                    "DuckDB Blueprint storage returned inconsistent object identity"
                )
            metadata = head.get("Metadata") or {}
            try:
                observed_size = int(head.get("ContentLength"))
            except (TypeError, ValueError):
                observed_size = -1
            if (
                observed_size != size
                or head.get("ContentType") != DUCKDB_BLUEPRINT_PARQUET_MEDIA_TYPE
                or not hmac.compare_digest(
                    str(metadata.get("sha256") or ""), expected_sha256
                )
            ):
                raise DuckDBBlueprintObjectStoreConflict(
                    "immutable DuckDB Blueprint output has different content or metadata"
                )
            read_size, read_sha256 = self._read_to_path(
                bucket,
                key,
                evidence.version_id,
                None,
                max_bytes=size,
            )
            if read_size != size or not hmac.compare_digest(
                read_sha256, expected_sha256
            ):
                raise DuckDBBlueprintObjectStoreConflict(
                    "immutable DuckDB Blueprint output has different content"
                )
            return evidence
        except DuckDBBlueprintObjectStoreError:
            raise
        except OSError as exc:
            raise DuckDBBlueprintObjectStoreUnavailable(
                "DuckDB Blueprint local output is unavailable for publication"
            ) from exc

    def verify_output(
        self,
        tenant_id: str,
        run_id: UUID,
        uri: str,
        *,
        evidence: S3ObjectVersionEvidence,
        expected_sha256: Sha256,
        expected_size_bytes: int,
    ) -> None:
        bucket, key = self._expected_output(tenant_id, run_id, uri)
        head = self._head(bucket, key, version_id=evidence.version_id)
        observed = S3ObjectVersionEvidence(
            version_id=self._version_id(head),
            etag=self._etag(head),
        )
        metadata = head.get("Metadata") or {}
        try:
            observed_size = int(head.get("ContentLength"))
        except (TypeError, ValueError):
            observed_size = -1
        if (
            observed != evidence
            or observed_size != expected_size_bytes
            or head.get("ContentType") != DUCKDB_BLUEPRINT_PARQUET_MEDIA_TYPE
            or not hmac.compare_digest(
                str(metadata.get("sha256") or ""), expected_sha256
            )
        ):
            raise DuckDBBlueprintObjectStoreConflict(
                "DuckDB Blueprint output identity or metadata changed"
            )
        size, sha256 = self._read_to_path(
            bucket,
            key,
            evidence.version_id,
            None,
            max_bytes=expected_size_bytes,
        )
        if size != expected_size_bytes or not hmac.compare_digest(
            sha256, expected_sha256
        ):
            raise DuckDBBlueprintObjectStoreConflict(
                "DuckDB Blueprint output bytes changed"
            )

    def probe(self) -> None:
        try:
            versioning = self.client.get_bucket_versioning(Bucket=self.bucket)
            object_lock_response = self.client.get_object_lock_configuration(
                Bucket=self.bucket
            )
        except Exception as exc:
            raise DuckDBBlueprintObjectStoreUnavailable(
                "DuckDB Blueprint object storage probe failed"
            ) from exc
        object_lock = (
            object_lock_response.get("ObjectLockConfiguration")
            or object_lock_response
        )
        retention = (object_lock.get("Rule") or {}).get("DefaultRetention") or {}
        duration = retention.get("Days") or retention.get("Years")
        if (
            versioning.get("Status") != "Enabled"
            or object_lock.get("ObjectLockEnabled") != "Enabled"
            or retention.get("Mode") not in {"GOVERNANCE", "COMPLIANCE"}
            or not isinstance(duration, int)
            or isinstance(duration, bool)
            or duration <= 0
        ):
            raise DuckDBBlueprintObjectStoreUnavailable(
                "DuckDB Blueprint storage lacks versioning and object-lock retention"
            )


def build_s3_duckdb_blueprint_object_store(
    *,
    bucket: str,
    prefix: str,
    input_prefixes: tuple[str, ...],
    connect_timeout_seconds: float = 5.0,
    read_timeout_seconds: float = 60.0,
) -> S3DuckDBBlueprintObjectStore:
    """Build the S3/MinIO adapter from the standard AWS SDK credential chain."""

    try:
        import boto3
        from botocore.config import Config as BotoConfig
    except Exception as exc:  # pragma: no cover - optional dependency boundary.
        raise DuckDBBlueprintObjectStoreUnavailable(
            "DuckDB Blueprint S3 storage requires boto3"
        ) from exc

    if not 0.1 <= connect_timeout_seconds <= 30:
        raise ValueError("DuckDB Blueprint S3 connect timeout is invalid")
    if not 1 <= read_timeout_seconds <= 300:
        raise ValueError("DuckDB Blueprint S3 read timeout is invalid")
    endpoint = str(os.getenv("AWS_ENDPOINT_URL") or "").strip()
    region = str(os.getenv("AWS_REGION") or "us-east-1").strip()
    boto_config: dict[str, Any] = {
        "connect_timeout": connect_timeout_seconds,
        "read_timeout": read_timeout_seconds,
        "retries": {"max_attempts": 0, "mode": "standard"},
    }
    if endpoint:
        boto_config["s3"] = {"addressing_style": "path"}
    client_kwargs: dict[str, Any] = {
        "region_name": region,
        "config": BotoConfig(**boto_config),
    }
    if endpoint:
        client_kwargs["endpoint_url"] = endpoint
    try:
        client = boto3.client("s3", **client_kwargs)
    except Exception as exc:
        raise DuckDBBlueprintObjectStoreUnavailable(
            "DuckDB Blueprint S3 client configuration is invalid"
        ) from exc
    return S3DuckDBBlueprintObjectStore(
        client,
        bucket=bucket,
        prefix=prefix,
        input_prefixes=input_prefixes,
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

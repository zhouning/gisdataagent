"""Immutable result storage backends for governed metric-query Artifacts."""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

METRIC_QUERY_RESULT_MEDIA_TYPE = "application/vnd.gda.metric-query-result+json"
S3_OBJECT_VERSION_EVIDENCE_SCHEMA = "gda.s3_object_version.v1"
LOCAL_RESULT_PUBLICATION_EVIDENCE_SCHEMA = "gda.local_result_publication.v1"

_TENANT_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_BUCKET_RE = re.compile(r"^(?=.{3,63}$)[a-z0-9][a-z0-9.-]*[a-z0-9]$")
_PREFIX_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._=-]{0,127}$")
_PRECONDITION_CODES = frozenset(
    {"409", "412", "ConditionalRequestConflict", "PreconditionFailed"}
)


class MetricQueryResultStoreError(RuntimeError):
    """The result store could not preserve its immutable publication contract."""


class MetricQueryResultStoreUnavailable(MetricQueryResultStoreError):
    """The result store is temporarily unavailable."""


class MetricQueryResultStoreConflict(MetricQueryResultStoreError):
    """A stable result location already contains different bytes."""


@dataclass(frozen=True)
class MetricQueryResultPublication:
    """Credential-free receipt for the exact bytes accepted by a result store."""

    storage_uri: str
    backend: str
    version_id: str | None = None
    etag: str | None = None

    def __post_init__(self) -> None:
        if self.backend not in {"local", "s3"}:
            raise ValueError("metric result publication backend is unsupported")
        if not self.storage_uri:
            raise ValueError("metric result publication URI is required")
        if self.backend == "s3":
            if not self.version_id or self.version_id == "null":
                raise ValueError("S3 metric result publication requires a version ID")
            if not self.etag:
                raise ValueError("S3 metric result publication requires an ETag")
        elif self.version_id is not None or self.etag is not None:
            raise ValueError("local metric result publication cannot carry S3 evidence")

    def storage_evidence(self) -> dict[str, str]:
        if self.backend == "s3":
            assert self.version_id is not None
            assert self.etag is not None
            return {
                "schema": S3_OBJECT_VERSION_EVIDENCE_SCHEMA,
                "version_id": self.version_id,
                "etag": self.etag,
            }
        return {"schema": LOCAL_RESULT_PUBLICATION_EVIDENCE_SCHEMA}


class MetricQueryResultStore(Protocol):
    backend_name: str

    def put(
        self,
        tenant_id: str,
        run_id: UUID,
        payload: bytes,
        *,
        media_type: str = METRIC_QUERY_RESULT_MEDIA_TYPE,
    ) -> MetricQueryResultPublication: ...

    def probe(self) -> None: ...


def _result_key(prefix: str, tenant_id: str, run_id: UUID) -> str:
    _validate_tenant(tenant_id)
    return f"{prefix}/{tenant_id}/{run_id}.json"


def _validate_tenant(tenant_id: str) -> None:
    if _TENANT_RE.fullmatch(tenant_id) is None:
        raise MetricQueryResultStoreConflict("metric result tenant identity is unsafe")


def validate_s3_result_location(bucket: str, prefix: str) -> tuple[str, str]:
    normalized_bucket = bucket.strip()
    normalized_prefix = prefix.strip().strip("/")
    if (
        _BUCKET_RE.fullmatch(normalized_bucket) is None
        or ".." in normalized_bucket
        or ".-" in normalized_bucket
        or "-." in normalized_bucket
    ):
        raise ValueError("metric result S3 bucket is invalid")
    segments = normalized_prefix.split("/")
    if (
        not normalized_prefix
        or len(normalized_prefix) > 512
        or any(_PREFIX_SEGMENT_RE.fullmatch(segment) is None for segment in segments)
    ):
        raise ValueError("metric result S3 prefix is invalid")
    return normalized_bucket, normalized_prefix


class LocalMetricQueryResultStore:
    """Atomic local result store retained for lightweight and disposable profiles."""

    backend_name = "local"

    def __init__(self, root: Path):
        resolved = root.expanduser().resolve()
        if resolved == Path(resolved.anchor):
            raise ValueError("metric query result root must not be a filesystem root")
        self.root = resolved

    def put(
        self,
        tenant_id: str,
        run_id: UUID,
        payload: bytes,
        *,
        media_type: str = METRIC_QUERY_RESULT_MEDIA_TYPE,
    ) -> MetricQueryResultPublication:
        del media_type
        _validate_tenant(tenant_id)
        try:
            directory = self.root / tenant_id
            directory.mkdir(parents=True, exist_ok=True)
            destination = directory / f"{run_id}.json"
            if destination.exists():
                if destination.read_bytes() != payload:
                    raise MetricQueryResultStoreConflict(
                        "stable metric query result path contains different content"
                    )
                return MetricQueryResultPublication(
                    storage_uri=destination.as_uri(),
                    backend=self.backend_name,
                )
            temporary_name: str | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="wb",
                    dir=directory,
                    prefix=f".{run_id}.",
                    delete=False,
                ) as temporary:
                    temporary.write(payload)
                    temporary.flush()
                    os.fsync(temporary.fileno())
                    temporary_name = temporary.name
                try:
                    os.link(temporary_name, destination)
                except FileExistsError:
                    if destination.read_bytes() != payload:
                        raise MetricQueryResultStoreConflict(
                            "stable metric query result path contains different content"
                        ) from None
            finally:
                if temporary_name is not None:
                    Path(temporary_name).unlink(missing_ok=True)
            return MetricQueryResultPublication(
                storage_uri=destination.as_uri(),
                backend=self.backend_name,
            )
        except MetricQueryResultStoreError:
            raise
        except OSError as exc:
            raise MetricQueryResultStoreUnavailable(
                "metric query result storage is unavailable"
            ) from exc

    def probe(self) -> None:
        temporary_name: str | None = None
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=self.root,
                prefix=".gda-metric-result-probe.",
                delete=False,
            ) as temporary:
                temporary.write(b"probe")
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_name = temporary.name
        except OSError as exc:
            raise MetricQueryResultStoreUnavailable(
                "metric query result storage probe failed"
            ) from exc
        finally:
            if temporary_name is not None:
                Path(temporary_name).unlink(missing_ok=True)


class S3MetricQueryResultStore:
    """Version-bound S3/MinIO store with exact read-back verification."""

    backend_name = "s3"

    def __init__(self, client: Any, *, bucket: str, prefix: str):
        if client is None:
            raise ValueError("metric result S3 client is required")
        self.client = client
        self.bucket, self.prefix = validate_s3_result_location(bucket, prefix)

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
        version_id = str(response.get("VersionId") or "").strip()
        if (
            not version_id
            or version_id == "null"
            or not version_id.isascii()
            or any(ord(character) < 33 for character in version_id)
        ):
            raise MetricQueryResultStoreUnavailable(
                "metric query result storage did not return an immutable version"
            )
        return version_id

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
            raise MetricQueryResultStoreUnavailable(
                "metric query result storage did not return an object ETag"
            )
        return etag

    def _head(self, key: str, version_id: str | None = None) -> dict[str, Any]:
        parameters = {"Bucket": self.bucket, "Key": key}
        if version_id is not None:
            parameters["VersionId"] = version_id
        try:
            return self.client.head_object(**parameters)
        except Exception as exc:
            raise MetricQueryResultStoreUnavailable(
                "metric query result storage identity verification failed"
            ) from exc

    def _read(self, key: str, version_id: str) -> bytes:
        try:
            response = self.client.get_object(
                Bucket=self.bucket,
                Key=key,
                VersionId=version_id,
            )
            body = response["Body"]
            try:
                if str(response.get("VersionId") or "") != version_id:
                    raise MetricQueryResultStoreUnavailable(
                        "metric query result storage read-back version changed"
                    )
                return body.read()
            finally:
                close = getattr(body, "close", None)
                if close is not None:
                    close()
        except Exception as exc:
            raise MetricQueryResultStoreUnavailable(
                "metric query result storage read-back failed"
            ) from exc

    def put(
        self,
        tenant_id: str,
        run_id: UUID,
        payload: bytes,
        *,
        media_type: str = METRIC_QUERY_RESULT_MEDIA_TYPE,
    ) -> MetricQueryResultPublication:
        key = _result_key(self.prefix, tenant_id, run_id)
        sha256 = hashlib.sha256(payload).hexdigest()
        created: dict[str, Any] | None = None
        try:
            created = self.client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=payload,
                ContentType=media_type,
                Metadata={"sha256": sha256},
                IfNoneMatch="*",
            )
        except Exception as exc:
            if self._error_code(exc) not in _PRECONDITION_CODES:
                raise MetricQueryResultStoreUnavailable(
                    "metric query result storage publication failed"
                ) from exc

        if created is not None:
            version_id = self._version_id(created)
            created_etag = self._etag(created)
            head = self._head(key, version_id)
        else:
            head = self._head(key)
            version_id = self._version_id(head)
            created_etag = None
        observed_version_id = self._version_id(head)
        observed_etag = self._etag(head)
        if observed_version_id != version_id or (
            created_etag is not None and not hmac.compare_digest(
                created_etag, observed_etag
            )
        ):
            raise MetricQueryResultStoreUnavailable(
                "metric query result storage returned inconsistent object identity"
            )
        metadata = head.get("Metadata") or {}
        try:
            observed_size = int(head.get("ContentLength"))
        except (TypeError, ValueError):
            observed_size = -1
        if (
            observed_size != len(payload)
            or head.get("ContentType") != media_type
            or not hmac.compare_digest(str(metadata.get("sha256") or ""), sha256)
        ):
            raise MetricQueryResultStoreConflict(
                "stable metric query result object contains different content or metadata"
            )

        observed = self._read(key, version_id)
        if len(observed) != len(payload) or not hmac.compare_digest(
            hashlib.sha256(observed).hexdigest(), sha256
        ):
            raise MetricQueryResultStoreConflict(
                "stable metric query result object contains different content"
            )
        return MetricQueryResultPublication(
            storage_uri=f"s3://{self.bucket}/{key}",
            backend=self.backend_name,
            version_id=version_id,
            etag=observed_etag,
        )

    def probe(self) -> None:
        try:
            versioning = self.client.get_bucket_versioning(Bucket=self.bucket)
            object_lock_response = self.client.get_object_lock_configuration(
                Bucket=self.bucket
            )
        except Exception as exc:
            raise MetricQueryResultStoreUnavailable(
                "metric query result storage probe failed"
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
            raise MetricQueryResultStoreUnavailable(
                "metric query result storage lacks versioning and object-lock retention"
            )

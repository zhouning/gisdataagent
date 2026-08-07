"""Governed, audited access to immutable metric-query result Artifacts."""

from __future__ import annotations

import hashlib
import hmac
import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from .metric_query_execution import (
    MetricQueryExecutionAuthority,
    MetricQueryExecutionConfigurationError,
    MetricQueryExecutionError,
    MetricQueryExecutionForbiddenError,
    MetricQueryExecutionNotFoundError,
    MetricQueryOutcome,
)
from .metric_query_result_store import (
    S3_OBJECT_VERSION_EVIDENCE_SCHEMA,
    validate_s3_result_location,
)
from .platform_contracts import Artifact, ArtifactRole, RunStatus, Sha256, TenantId
from .platform_gateway import (
    GatewayConfigurationError,
    GatewayConflictError,
    GatewayForbiddenError,
    GatewayNotFoundError,
    GatewayUnavailableError,
    GatewayValidationError,
    PlatformGateway,
)
from .security_event_ledger import SecurityEventLedger, SecurityEventLedgerError

METRIC_QUERY_RESULT_ACCESS_ACTION = "metric.query.result.access"
MIN_RESULT_ACCESS_TTL_SECONDS = 60
MAX_RESULT_ACCESS_TTL_SECONDS = 900
DEFAULT_RESULT_ACCESS_TTL_SECONDS = 300
_MISSING_CODES = frozenset(
    {"404", "NoSuchBucket", "NoSuchKey", "NoSuchVersion", "NotFound"}
)


class _FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MetricQueryResultAccessGrant(_FrozenContract):
    tenant_id: TenantId
    access_id: UUID
    run_id: UUID
    artifact_id: UUID
    delivery: str = Field(pattern=r"^presigned_get$")
    download_url: str = Field(min_length=1, max_length=8192)
    media_type: str = Field(min_length=1, max_length=256)
    size_bytes: int = Field(ge=0, le=10**18)
    content_sha256: Sha256
    issued_at: datetime
    expires_at: datetime

    @field_validator("download_url")
    @classmethod
    def _temporary_http_url(cls, value: str) -> str:
        parts = urlsplit(value)
        if (
            parts.scheme not in {"http", "https"}
            or not parts.netloc
            or parts.username
            or parts.password
            or not parts.query
            or parts.fragment
        ):
            raise ValueError("metric query result access URL must be a signed HTTP URL")
        return value

    @field_validator("issued_at", "expires_at")
    @classmethod
    def _utc_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("metric query result access time must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _bounded_lifetime(self) -> MetricQueryResultAccessGrant:
        lifetime = (self.expires_at - self.issued_at).total_seconds()
        if not MIN_RESULT_ACCESS_TTL_SECONDS <= lifetime <= MAX_RESULT_ACCESS_TTL_SECONDS:
            raise ValueError("metric query result access lifetime is outside policy")
        return self


class S3ObjectVersionEvidence(_FrozenContract):
    evidence_schema: Literal["gda.s3_object_version.v1"] = Field(alias="schema")
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

    @field_validator("evidence_schema")
    @classmethod
    def _shared_schema_constant(cls, value: str) -> str:
        if value != S3_OBJECT_VERSION_EVIDENCE_SCHEMA:
            raise ValueError("S3 object version evidence schema is unsupported")
        return value


class MetricQueryResultAccessError(RuntimeError):
    code = "metric_query_result_access_error"


class MetricQueryResultAccessNotFound(MetricQueryResultAccessError):
    code = "metric_query_result_not_found"


class MetricQueryResultAccessForbidden(MetricQueryResultAccessError):
    code = "metric_query_result_access_forbidden"


class MetricQueryResultNotReady(MetricQueryResultAccessError):
    code = "metric_query_result_not_ready"


class MetricQueryResultIntegrityError(MetricQueryResultAccessError):
    code = "metric_query_result_integrity_error"


class MetricQueryResultAccessUnavailable(MetricQueryResultAccessError):
    code = "metric_query_result_access_unavailable"


class MetricQueryResultAccessBackend(Protocol):
    def verify_and_presign(
        self,
        artifact: Artifact,
        *,
        tenant_id: str,
        run_id: UUID,
        expires_in_seconds: int,
    ) -> str: ...


def _s3_error_code(exc: Exception) -> str:
    response = getattr(exc, "response", {})
    error = response.get("Error", {}) if isinstance(response, dict) else {}
    metadata = response.get("ResponseMetadata", {}) if isinstance(response, dict) else {}
    return str(error.get("Code") or metadata.get("HTTPStatusCode") or "")


def _expected_result_key(prefix: str, tenant_id: str, run_id: UUID) -> str:
    # validate_s3_result_location already constrains the configured prefix; the
    # tenant is validated by the Artifact/Run contracts before this boundary.
    return f"{prefix}/{tenant_id}/{run_id}.json"


def _etag(response: dict[str, Any]) -> str:
    etag = str(response.get("ETag") or "").strip()
    if len(etag) >= 2 and etag[0] == etag[-1] == '"':
        etag = etag[1:-1]
    return etag


class S3MetricQueryResultAccessBackend:
    """Verify exact result bytes before issuing a bounded S3 GET capability."""

    def __init__(
        self,
        client: Any,
        *,
        bucket: str,
        prefix: str,
        signing_client: Any | None = None,
    ):
        if client is None:
            raise ValueError("metric result access S3 client is required")
        self.client = client
        self.signing_client = signing_client or client
        self.bucket, self.prefix = validate_s3_result_location(bucket, prefix)

    def _object_identity(
        self, artifact: Artifact, tenant_id: str, run_id: UUID
    ) -> str:
        key = _expected_result_key(self.prefix, tenant_id, run_id)
        expected_uri = f"s3://{self.bucket}/{key}"
        if artifact.storage_uri != expected_uri:
            raise MetricQueryResultIntegrityError(
                "metric query result Artifact is outside the managed result location"
            )
        return key

    @staticmethod
    def _object_version(artifact: Artifact) -> S3ObjectVersionEvidence:
        try:
            return S3ObjectVersionEvidence.model_validate(
                artifact.manifest.get("storage_evidence")
            )
        except ValidationError as exc:
            raise MetricQueryResultIntegrityError(
                "metric query result Artifact lacks valid immutable storage evidence"
            ) from exc

    def _head(self, key: str, version_id: str) -> dict[str, Any]:
        try:
            return self.client.head_object(
                Bucket=self.bucket,
                Key=key,
                VersionId=version_id,
            )
        except Exception as exc:
            if _s3_error_code(exc) in _MISSING_CODES:
                raise MetricQueryResultAccessUnavailable(
                    "metric query result object is unavailable"
                ) from exc
            raise MetricQueryResultAccessUnavailable(
                "metric query result storage is unavailable"
            ) from exc

    def _verify_bytes(
        self,
        key: str,
        artifact: Artifact,
        evidence: S3ObjectVersionEvidence,
    ) -> None:
        try:
            response = self.client.get_object(
                Bucket=self.bucket,
                Key=key,
                VersionId=evidence.version_id,
            )
            body = response["Body"]
            digest = hashlib.sha256()
            observed_size = 0
            try:
                if str(response.get("VersionId") or "") != evidence.version_id:
                    raise MetricQueryResultIntegrityError(
                        "metric query result object version does not match its Artifact"
                    )
                while True:
                    chunk = body.read(1024 * 1024)
                    if not chunk:
                        break
                    observed_size += len(chunk)
                    if observed_size > artifact.size_bytes:
                        raise MetricQueryResultIntegrityError(
                            "metric query result object size does not match its Artifact"
                        )
                    digest.update(chunk)
            finally:
                close = getattr(body, "close", None)
                if close is not None:
                    close()
        except MetricQueryResultAccessError:
            raise
        except Exception as exc:
            if _s3_error_code(exc) in _MISSING_CODES:
                raise MetricQueryResultAccessUnavailable(
                    "metric query result object is unavailable"
                ) from exc
            raise MetricQueryResultAccessUnavailable(
                "metric query result storage is unavailable"
            ) from exc
        if observed_size != artifact.size_bytes or not hmac.compare_digest(
            digest.hexdigest(), artifact.content_sha256
        ):
            raise MetricQueryResultIntegrityError(
                "metric query result object content does not match its Artifact"
            )

    def verify_and_presign(
        self,
        artifact: Artifact,
        *,
        tenant_id: str,
        run_id: UUID,
        expires_in_seconds: int,
    ) -> str:
        if not MIN_RESULT_ACCESS_TTL_SECONDS <= expires_in_seconds <= (
            MAX_RESULT_ACCESS_TTL_SECONDS
        ):
            raise MetricQueryResultIntegrityError(
                "metric query result access lifetime is outside policy"
            )
        key = self._object_identity(artifact, tenant_id, run_id)
        evidence = self._object_version(artifact)
        head = self._head(key, evidence.version_id)
        metadata = head.get("Metadata") or {}
        observed_sha256 = str(metadata.get("sha256") or "")
        try:
            observed_size = int(head.get("ContentLength"))
        except (TypeError, ValueError):
            observed_size = -1
        if (
            str(head.get("VersionId") or "") != evidence.version_id
            or not hmac.compare_digest(_etag(head), evidence.etag)
            or observed_size != artifact.size_bytes
            or head.get("ContentType") != artifact.media_type
            or not hmac.compare_digest(observed_sha256, artifact.content_sha256)
        ):
            raise MetricQueryResultIntegrityError(
                "metric query result object metadata does not match its Artifact"
            )
        self._verify_bytes(key, artifact, evidence)
        try:
            url = self.signing_client.generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": self.bucket,
                    "Key": key,
                    "VersionId": evidence.version_id,
                    "ResponseContentType": artifact.media_type,
                },
                ExpiresIn=expires_in_seconds,
                HttpMethod="GET",
            )
        except Exception as exc:
            raise MetricQueryResultAccessUnavailable(
                "metric query result access signing is unavailable"
            ) from exc
        if not isinstance(url, str) or not url:
            raise MetricQueryResultAccessUnavailable(
                "metric query result access signing is unavailable"
            )
        return url


def _validated_endpoint(value: str | None, field: str) -> str | None:
    if not value:
        return None
    parts = urlsplit(value)
    if (
        parts.scheme not in {"http", "https"}
        or not parts.netloc
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
    ):
        raise MetricQueryResultAccessUnavailable(f"{field} is invalid")
    return value.rstrip("/")


def build_s3_metric_query_result_access_backend() -> S3MetricQueryResultAccessBackend:
    """Build the API-side verifier/signer from a scoped SDK credential chain."""

    try:
        import boto3
        from botocore.config import Config as BotoConfig

        bucket = str(os.getenv("GDA_METRIC_QUERY_RESULT_S3_BUCKET") or "").strip()
        prefix = str(
            os.getenv("GDA_METRIC_QUERY_RESULT_S3_PREFIX")
            or "metric-query-results/v1"
        ).strip()
        bucket, prefix = validate_s3_result_location(bucket, prefix)
        timeout = int(
            os.getenv("GDA_METRIC_QUERY_RESULT_ACCESS_TIMEOUT_SECONDS") or "10"
        )
        if not 1 <= timeout <= 60:
            raise ValueError("result access timeout is outside policy")
        endpoint = _validated_endpoint(os.getenv("AWS_ENDPOINT_URL"), "S3 endpoint")
        signing_endpoint = _validated_endpoint(
            os.getenv("GDA_METRIC_QUERY_RESULT_ACCESS_ENDPOINT_URL") or endpoint,
            "result access endpoint",
        )
        access_key = str(
            os.getenv("GDA_METRIC_QUERY_RESULT_ACCESS_KEY_ID") or ""
        ).strip()
        secret_key = str(
            os.getenv("GDA_METRIC_QUERY_RESULT_ACCESS_SECRET_ACCESS_KEY") or ""
        ).strip()
        session_token = str(
            os.getenv("GDA_METRIC_QUERY_RESULT_ACCESS_SESSION_TOKEN") or ""
        ).strip()
        if bool(access_key) != bool(secret_key) or (session_token and not access_key):
            raise ValueError("result access credential fields are incomplete")
        client_options: dict[str, Any] = {
            "region_name": os.getenv("AWS_REGION") or "us-east-1",
            "config": BotoConfig(
                connect_timeout=timeout,
                read_timeout=timeout,
                retries={"total_max_attempts": 1, "mode": "standard"},
                signature_version="s3v4",
                s3={"addressing_style": "path"}
                if endpoint or signing_endpoint
                else None,
            ),
        }
        if endpoint is not None:
            client_options["endpoint_url"] = endpoint
        if access_key:
            client_options.update(
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
            )
            if session_token:
                client_options["aws_session_token"] = session_token
        client = boto3.client("s3", **client_options)
        signing_client = client
        if signing_endpoint != endpoint:
            signing_options = {**client_options, "endpoint_url": signing_endpoint}
            signing_client = boto3.client("s3", **signing_options)
        return S3MetricQueryResultAccessBackend(
            client,
            bucket=bucket,
            prefix=prefix,
            signing_client=signing_client,
        )
    except MetricQueryResultAccessError:
        raise
    except Exception as exc:
        raise MetricQueryResultAccessUnavailable(
            "metric query result access is not configured"
        ) from exc


class MetricQueryResultAccessService:
    """Authorize, verify, audit and issue one bounded result-read capability."""

    def __init__(
        self,
        *,
        authority: MetricQueryExecutionAuthority | None = None,
        gateway: PlatformGateway | None = None,
        ledger: SecurityEventLedger | None = None,
        backend: MetricQueryResultAccessBackend | None = None,
        backend_factory: Callable[[], MetricQueryResultAccessBackend] = (
            build_s3_metric_query_result_access_backend
        ),
        now: Callable[[], datetime] | None = None,
        access_id_factory: Callable[[], UUID] = uuid4,
    ):
        self.authority = authority or MetricQueryExecutionAuthority()
        self.gateway = gateway or PlatformGateway()
        self.ledger = ledger or SecurityEventLedger()
        self.backend = backend
        self.backend_factory = backend_factory
        self.now = now or (lambda: datetime.now(UTC))
        self.access_id_factory = access_id_factory

    @staticmethod
    def _resource_ref(tenant_id: str, run_id: UUID) -> str:
        return f"gda://{tenant_id}/run/{run_id}"

    def _audit_denied(
        self,
        *,
        tenant_id: str,
        access_id: UUID,
        run_id: UUID,
        actor_subject: str,
        role: str,
        reason: str,
    ) -> None:
        try:
            self.ledger.append(
                tenant_id=tenant_id,
                attempt_id=access_id,
                phase="denied",
                action=METRIC_QUERY_RESULT_ACCESS_ACTION,
                outcome="denied",
                actor_subject=actor_subject,
                resource_ref=self._resource_ref(tenant_id, run_id),
                reason=reason,
                details={"run_id": str(run_id), "role": role},
            )
        except SecurityEventLedgerError:
            # The request remains denied; a ledger outage must never turn a
            # denial into result access or disclose storage details.
            return

    @staticmethod
    def _validate_result_artifact(record: Any, artifact: Artifact) -> None:
        observation = record.observation
        if observation is None or observation.result_artifact_id is None:
            raise MetricQueryResultNotReady("metric query result is not available")
        manifest = artifact.manifest
        if (
            artifact.tenant_id != record.admission.tenant_id
            or artifact.artifact_id != observation.result_artifact_id
            or artifact.artifact_key != "metric-query-result"
            or artifact.artifact_role is not ArtifactRole.OUTPUT
            or artifact.run_id != record.run.run_id
            or artifact.content_sha256 != observation.result_sha256
            or manifest.get("schema") != "gda.metric_query_result_artifact.v1"
            or str(manifest.get("plan_artifact_id"))
            != str(record.admission.plan_artifact_id)
            or manifest.get("cache_key") != record.admission.cache_key
            or manifest.get("rows_returned") != observation.rows_returned
            or manifest.get("rows_scanned") != observation.rows_scanned
            or manifest.get("bytes_scanned") != observation.bytes_scanned
            or manifest.get("duration_ms") != observation.duration_ms
        ):
            raise MetricQueryResultIntegrityError(
                "metric query result Artifact evidence is inconsistent"
            )

    def issue(
        self,
        *,
        tenant_id: str,
        run_id: UUID,
        actor_subject: str,
        role: str,
        expires_in_seconds: int = DEFAULT_RESULT_ACCESS_TTL_SECONDS,
    ) -> MetricQueryResultAccessGrant:
        access_id = self.access_id_factory()
        if not MIN_RESULT_ACCESS_TTL_SECONDS <= expires_in_seconds <= (
            MAX_RESULT_ACCESS_TTL_SECONDS
        ):
            raise MetricQueryResultIntegrityError(
                "metric query result access lifetime is outside policy"
            )
        try:
            record = self.authority.get(tenant_id, run_id)
        except MetricQueryExecutionNotFoundError as exc:
            self._audit_denied(
                tenant_id=tenant_id,
                access_id=access_id,
                run_id=run_id,
                actor_subject=actor_subject,
                role=role,
                reason="run_not_found",
            )
            raise MetricQueryResultAccessNotFound(
                "metric query result was not found"
            ) from exc
        except MetricQueryExecutionForbiddenError as exc:
            raise MetricQueryResultAccessForbidden(
                "metric query result access was denied"
            ) from exc
        except (MetricQueryExecutionConfigurationError, MetricQueryExecutionError) as exc:
            raise MetricQueryResultAccessUnavailable(
                "metric query result authority is unavailable"
            ) from exc

        owner = record.admission.admitted_by
        if actor_subject != owner and role not in {"admin", "platform_operator"}:
            self._audit_denied(
                tenant_id=tenant_id,
                access_id=access_id,
                run_id=run_id,
                actor_subject=actor_subject,
                role=role,
                reason="run_owner_required",
            )
            raise MetricQueryResultAccessForbidden(
                "metric query result access requires its submitter or a platform operator"
            )
        observation = record.observation
        if (
            record.run.status is not RunStatus.SUCCEEDED
            or observation is None
            or observation.outcome is not MetricQueryOutcome.SUCCEEDED
            or observation.result_artifact_id is None
            or observation.result_sha256 is None
        ):
            self._audit_denied(
                tenant_id=tenant_id,
                access_id=access_id,
                run_id=run_id,
                actor_subject=actor_subject,
                role=role,
                reason="result_not_ready",
            )
            raise MetricQueryResultNotReady(
                "metric query Run has no successful result available"
            )
        try:
            artifact = self.gateway.get_artifact(
                tenant_id, observation.result_artifact_id
            )
        except GatewayNotFoundError as exc:
            raise MetricQueryResultIntegrityError(
                "metric query result Artifact is missing"
            ) from exc
        except (GatewayConflictError, GatewayValidationError) as exc:
            raise MetricQueryResultIntegrityError(
                "metric query result Artifact evidence is invalid"
            ) from exc
        except GatewayForbiddenError as exc:
            raise MetricQueryResultAccessForbidden(
                "metric query result Artifact access was denied"
            ) from exc
        except (GatewayConfigurationError, GatewayUnavailableError) as exc:
            raise MetricQueryResultAccessUnavailable(
                "metric query result Artifact authority is unavailable"
            ) from exc

        self._validate_result_artifact(record, artifact)
        backend = self.backend or self.backend_factory()
        download_url = backend.verify_and_presign(
            artifact,
            tenant_id=tenant_id,
            run_id=run_id,
            expires_in_seconds=expires_in_seconds,
        )
        issued_at = self.now()
        if issued_at.tzinfo is None or issued_at.utcoffset() is None:
            raise MetricQueryResultAccessUnavailable(
                "metric query result access clock is invalid"
            )
        issued_at = issued_at.astimezone(UTC)
        try:
            grant = MetricQueryResultAccessGrant(
                tenant_id=tenant_id,
                access_id=access_id,
                run_id=run_id,
                artifact_id=artifact.artifact_id,
                delivery="presigned_get",
                download_url=download_url,
                media_type=artifact.media_type,
                size_bytes=artifact.size_bytes,
                content_sha256=artifact.content_sha256,
                issued_at=issued_at,
                expires_at=issued_at + timedelta(seconds=expires_in_seconds),
            )
        except ValidationError as exc:
            raise MetricQueryResultAccessUnavailable(
                "metric query result access signing returned an invalid grant"
            ) from exc
        try:
            self.ledger.append(
                tenant_id=tenant_id,
                attempt_id=access_id,
                phase="outcome",
                action=METRIC_QUERY_RESULT_ACCESS_ACTION,
                outcome="success",
                actor_subject=actor_subject,
                resource_ref=self._resource_ref(tenant_id, run_id),
                reason="result_access_granted",
                details={
                    "run_id": str(run_id),
                    "artifact_id": str(artifact.artifact_id),
                    "role": role,
                    "delivery": "presigned_get",
                    "expires_in_seconds": expires_in_seconds,
                    "media_type": artifact.media_type,
                    "size_bytes": artifact.size_bytes,
                    "content_sha256": artifact.content_sha256,
                },
            )
        except SecurityEventLedgerError as exc:
            raise MetricQueryResultAccessUnavailable(
                "metric query result access audit is unavailable"
            ) from exc
        return grant


__all__ = [
    "DEFAULT_RESULT_ACCESS_TTL_SECONDS",
    "MAX_RESULT_ACCESS_TTL_SECONDS",
    "METRIC_QUERY_RESULT_ACCESS_ACTION",
    "MIN_RESULT_ACCESS_TTL_SECONDS",
    "MetricQueryResultAccessBackend",
    "MetricQueryResultAccessError",
    "MetricQueryResultAccessForbidden",
    "MetricQueryResultAccessGrant",
    "MetricQueryResultAccessNotFound",
    "MetricQueryResultAccessService",
    "MetricQueryResultAccessUnavailable",
    "MetricQueryResultIntegrityError",
    "MetricQueryResultNotReady",
    "S3MetricQueryResultAccessBackend",
    "build_s3_metric_query_result_access_backend",
]

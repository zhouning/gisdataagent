"""Audited access to immutable GIS analysis result Artifacts."""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
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

from .gis_analysis_execution import (
    GISAnalysisExecutionAuthority,
    GISAnalysisExecutionConfigurationError,
    GISAnalysisExecutionError,
    GISAnalysisExecutionForbiddenError,
    GISAnalysisExecutionNotFoundError,
    GISAnalysisOutcome,
)
from .governed_query_result_access_security import (
    GOVERNED_QUERY_RESULT_ACCESS_SECURITY_PURPOSE,
    GovernedQueryResultAccessSecurityDecision,
    GovernedQueryResultAccessSecurityDeniedError,
    GovernedQueryResultAccessSecurityError,
    build_governed_query_result_access_security_request,
    evaluate_governed_query_result_access_security,
)
from .governed_query_security import GovernedQuerySecurityCurrentReader
from .metric_query_result_access import (
    DEFAULT_RESULT_ACCESS_TTL_SECONDS,
    MAX_RESULT_ACCESS_TTL_SECONDS,
    MIN_RESULT_ACCESS_TTL_SECONDS,
    MetricQueryResultAccessBackend,
    MetricQueryResultAccessError,
    MetricQueryResultIntegrityError,
    S3MetricQueryResultAccessBackend,
)
from .metric_query_result_store import validate_s3_result_location
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

GIS_ANALYSIS_RESULT_ACCESS_ACTION = "gis.analysis.result.access"


class _FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GISAnalysisResultAccessGrant(_FrozenContract):
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
            raise ValueError("GIS result access URL must be a signed HTTP URL")
        return value

    @model_validator(mode="after")
    def _bounded_lifetime(self) -> GISAnalysisResultAccessGrant:
        lifetime = (self.expires_at - self.issued_at).total_seconds()
        if not MIN_RESULT_ACCESS_TTL_SECONDS <= lifetime <= MAX_RESULT_ACCESS_TTL_SECONDS:
            raise ValueError("GIS result access lifetime is outside policy")
        return self

    @field_validator("issued_at", "expires_at")
    @classmethod
    def _utc_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("GIS result access time must be timezone-aware")
        return value.astimezone(UTC)


class GISAnalysisResultAccessError(RuntimeError):
    code = "gis_analysis_result_access_error"


class GISAnalysisResultAccessNotFound(GISAnalysisResultAccessError):
    code = "gis_analysis_result_not_found"


class GISAnalysisResultAccessForbidden(GISAnalysisResultAccessError):
    code = "gis_analysis_result_access_forbidden"


class GISAnalysisResultNotReady(GISAnalysisResultAccessError):
    code = "gis_analysis_result_not_ready"


class GISAnalysisResultIntegrityError(GISAnalysisResultAccessError):
    code = "gis_analysis_result_integrity_error"


class GISAnalysisResultAccessUnavailable(GISAnalysisResultAccessError):
    code = "gis_analysis_result_access_unavailable"


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
        raise GISAnalysisResultAccessUnavailable(f"{field} is invalid")
    return value.rstrip("/")


def build_s3_gis_analysis_result_access_backend() -> S3MetricQueryResultAccessBackend:
    try:
        import boto3
        from botocore.config import Config as BotoConfig

        bucket, prefix = validate_s3_result_location(
            str(os.getenv("GDA_GIS_ANALYSIS_RESULT_S3_BUCKET") or "").strip(),
            str(
                os.getenv("GDA_GIS_ANALYSIS_RESULT_S3_PREFIX")
                or "gis-analysis-results/v1"
            ).strip(),
        )
        timeout = int(os.getenv("GDA_GIS_ANALYSIS_RESULT_ACCESS_TIMEOUT_SECONDS") or "10")
        if not 1 <= timeout <= 60:
            raise ValueError("GIS result access timeout is outside policy")
        endpoint = _validated_endpoint(os.getenv("AWS_ENDPOINT_URL"), "S3 endpoint")
        signing_endpoint = _validated_endpoint(
            os.getenv("GDA_GIS_ANALYSIS_RESULT_ACCESS_ENDPOINT_URL") or endpoint,
            "GIS result access endpoint",
        )
        access_key = str(
            os.getenv("GDA_GIS_ANALYSIS_RESULT_ACCESS_KEY_ID") or ""
        ).strip()
        secret_key = str(
            os.getenv("GDA_GIS_ANALYSIS_RESULT_ACCESS_SECRET_ACCESS_KEY") or ""
        ).strip()
        session_token = str(
            os.getenv("GDA_GIS_ANALYSIS_RESULT_ACCESS_SESSION_TOKEN") or ""
        ).strip()
        if bool(access_key) != bool(secret_key) or (session_token and not access_key):
            raise ValueError("GIS result access credential fields are incomplete")
        options: dict[str, Any] = {
            "region_name": os.getenv("AWS_REGION") or "us-east-1",
            "config": BotoConfig(
                connect_timeout=timeout,
                read_timeout=timeout,
                retries={"total_max_attempts": 1, "mode": "standard"},
                signature_version="s3v4",
                s3={"addressing_style": "path"} if endpoint or signing_endpoint else None,
            ),
        }
        if endpoint:
            options["endpoint_url"] = endpoint
        if access_key:
            options.update(
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
            )
            if session_token:
                options["aws_session_token"] = session_token
        client = boto3.client("s3", **options)
        signing_client = client
        if signing_endpoint != endpoint:
            signing_client = boto3.client(
                "s3", **{**options, "endpoint_url": signing_endpoint}
            )
        return S3MetricQueryResultAccessBackend(
            client,
            bucket=bucket,
            prefix=prefix,
            signing_client=signing_client,
        )
    except Exception as exc:
        raise GISAnalysisResultAccessUnavailable(
            "GIS analysis result access is not configured"
        ) from exc


class GISAnalysisResultAccessService:
    """Authorize, verify, audit, and issue one bounded GIS result read."""

    def __init__(
        self,
        *,
        authority: GISAnalysisExecutionAuthority | None = None,
        gateway: PlatformGateway | None = None,
        ledger: SecurityEventLedger | None = None,
        backend: MetricQueryResultAccessBackend | None = None,
        backend_factory: Callable[[], MetricQueryResultAccessBackend] = (
            build_s3_gis_analysis_result_access_backend
        ),
        now: Callable[[], datetime] | None = None,
        access_id_factory: Callable[[], UUID] = uuid4,
    ):
        self.authority = authority or GISAnalysisExecutionAuthority()
        self.gateway = gateway or PlatformGateway()
        self.ledger = ledger or SecurityEventLedger()
        self.backend = backend
        self.backend_factory = backend_factory
        self.now = now or (lambda: datetime.now(UTC))
        self.access_id_factory = access_id_factory

    @staticmethod
    def _resource_ref(tenant_id: str, run_id: UUID) -> str:
        return f"gda://{tenant_id}/run/{run_id}"

    def _audit(
        self,
        *,
        tenant_id: str,
        access_id: UUID,
        run_id: UUID,
        actor_subject: str,
        role: str,
        outcome: str,
        reason: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.ledger.append(
            tenant_id=tenant_id,
            attempt_id=access_id,
            phase="outcome" if outcome == "success" else "denied",
            action=GIS_ANALYSIS_RESULT_ACCESS_ACTION,
            outcome=outcome,
            actor_subject=actor_subject,
            resource_ref=self._resource_ref(tenant_id, run_id),
            reason=reason,
            details={"run_id": str(run_id), "role": role, **(details or {})},
        )

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
            self._audit(
                tenant_id=tenant_id,
                access_id=access_id,
                run_id=run_id,
                actor_subject=actor_subject,
                role=role,
                outcome="denied",
                reason=reason,
            )
        except SecurityEventLedgerError:
            return

    def _authorize_result_access(
        self,
        *,
        tenant_id: str,
        access_id: UUID,
        run_id: UUID,
        artifact_id: UUID,
        actor_subject: str,
        role: str,
        purpose_code: str,
        expires_in_seconds: int,
        security_reader: GovernedQuerySecurityCurrentReader,
    ) -> GovernedQueryResultAccessSecurityDecision:
        evaluated_at = self.now()
        try:
            request = build_governed_query_result_access_security_request(
                tenant_id=tenant_id,
                request_id=f"gis-result-access:{access_id}",
                actor_subject=actor_subject,
                roles=(role,),
                purpose_code=purpose_code,
                channel="gis_result",
                adapter_id="gda.gis-analysis.result-access.v1",
                consumption_mode="download",
                resource_refs=(
                    self._resource_ref(tenant_id, run_id),
                    f"gda://{tenant_id}/artifact/{artifact_id}",
                ),
                request_payload={
                    "tenant_id": tenant_id,
                    "run_id": str(run_id),
                    "artifact_id": str(artifact_id),
                    "actor_subject": actor_subject,
                    "role": role,
                    "purpose_code": purpose_code,
                    "delivery": "presigned_get",
                    "expires_in_seconds": expires_in_seconds,
                },
                evaluated_at=evaluated_at,
            )
            decision = evaluate_governed_query_result_access_security(
                request,
                security_reader,
                evaluated_at=evaluated_at,
            )
        except GovernedQueryResultAccessSecurityDeniedError as exc:
            self._audit_denied(
                tenant_id=tenant_id,
                access_id=access_id,
                run_id=run_id,
                actor_subject=actor_subject,
                role=role,
                reason="spr_policy_denied",
            )
            raise GISAnalysisResultAccessForbidden(
                "GIS result access was denied by current policy"
            ) from exc
        except (GovernedQueryResultAccessSecurityError, ValueError) as exc:
            raise GISAnalysisResultAccessUnavailable(
                "GIS result security is unavailable"
            ) from exc
        try:
            self.ledger.append(
                tenant_id=tenant_id,
                attempt_id=access_id,
                phase="admitted",
                action=GIS_ANALYSIS_RESULT_ACCESS_ACTION,
                outcome="admitted",
                actor_subject=actor_subject,
                resource_ref=self._resource_ref(tenant_id, run_id),
                reason="exact-scope SPR allow recorded before result storage access",
                details={
                    "run_id": str(run_id),
                    "artifact_id": str(artifact_id),
                    "purpose_code": purpose_code,
                    "request_sha256": request.request_sha256,
                    "decision_sha256": decision.decision_sha256,
                    "policy_ref": decision.policy_ref,
                    "policy_version": decision.policy_version,
                    "role": role,
                },
            )
        except SecurityEventLedgerError as exc:
            raise GISAnalysisResultAccessUnavailable(
                "GIS result security admission audit is unavailable"
            ) from exc
        return decision

    @staticmethod
    def _validate_artifact(record: Any, artifact: Artifact) -> None:
        observation = record.observation
        manifest = artifact.manifest
        if (
            observation is None
            or observation.result_artifact_id is None
            or artifact.tenant_id != record.admission.tenant_id
            or artifact.artifact_id != observation.result_artifact_id
            or artifact.artifact_key != "gis-analysis-result"
            or artifact.artifact_role is not ArtifactRole.OUTPUT
            or artifact.run_id != record.run.run_id
            or artifact.content_sha256 != observation.result_sha256
            or manifest.get("schema") != "gda.gis_analysis_result_artifact.v1"
            or str(manifest.get("plan_artifact_id"))
            != str(record.admission.plan_artifact_id)
            or manifest.get("cache_key") != record.admission.cache_key
            or manifest.get("features_returned") != observation.features_returned
            or manifest.get("bytes_scanned") != observation.bytes_scanned
            or manifest.get("duration_ms") != observation.duration_ms
        ):
            raise GISAnalysisResultIntegrityError(
                "GIS result Artifact evidence is inconsistent"
            )

    def issue(
        self,
        *,
        tenant_id: str,
        run_id: UUID,
        actor_subject: str,
        role: str,
        expires_in_seconds: int = DEFAULT_RESULT_ACCESS_TTL_SECONDS,
        purpose_code: str = GOVERNED_QUERY_RESULT_ACCESS_SECURITY_PURPOSE,
        security_reader: GovernedQuerySecurityCurrentReader | None = None,
    ) -> GISAnalysisResultAccessGrant:
        access_id = self.access_id_factory()
        if not MIN_RESULT_ACCESS_TTL_SECONDS <= expires_in_seconds <= (
            MAX_RESULT_ACCESS_TTL_SECONDS
        ):
            raise GISAnalysisResultIntegrityError(
                "GIS result access lifetime is outside policy"
            )
        try:
            record = self.authority.get(tenant_id, run_id)
        except GISAnalysisExecutionNotFoundError as exc:
            self._audit_denied(
                tenant_id=tenant_id,
                access_id=access_id,
                run_id=run_id,
                actor_subject=actor_subject,
                role=role,
                reason="run_not_found",
            )
            raise GISAnalysisResultAccessNotFound("GIS result was not found") from exc
        except GISAnalysisExecutionForbiddenError as exc:
            self._audit_denied(
                tenant_id=tenant_id,
                access_id=access_id,
                run_id=run_id,
                actor_subject=actor_subject,
                role=role,
                reason="run_access_forbidden",
            )
            raise GISAnalysisResultAccessForbidden("GIS result access was denied") from exc
        except (GISAnalysisExecutionConfigurationError, GISAnalysisExecutionError) as exc:
            raise GISAnalysisResultAccessUnavailable(
                "GIS result authority is unavailable"
            ) from exc
        if (
            actor_subject != record.admission.admitted_by
            and role not in {"admin", "platform_operator"}
        ):
            self._audit_denied(
                tenant_id=tenant_id,
                access_id=access_id,
                run_id=run_id,
                actor_subject=actor_subject,
                role=role,
                reason="run_owner_required",
            )
            raise GISAnalysisResultAccessForbidden(
                "GIS result access requires its submitter or a platform operator"
            )
        observation = record.observation
        if (
            record.run.status is not RunStatus.SUCCEEDED
            or observation is None
            or observation.outcome is not GISAnalysisOutcome.SUCCEEDED
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
            raise GISAnalysisResultNotReady(
                "GIS analysis Run has no successful result available"
            )
        security_decision = None
        if security_reader is not None:
            security_decision = self._authorize_result_access(
                tenant_id=tenant_id,
                access_id=access_id,
                run_id=run_id,
                artifact_id=observation.result_artifact_id,
                actor_subject=actor_subject,
                role=role,
                purpose_code=purpose_code,
                expires_in_seconds=expires_in_seconds,
                security_reader=security_reader,
            )
        try:
            artifact = self.gateway.get_artifact(
                tenant_id, observation.result_artifact_id
            )
        except GatewayNotFoundError as exc:
            raise GISAnalysisResultIntegrityError(
                "GIS result Artifact is missing"
            ) from exc
        except (GatewayConflictError, GatewayValidationError) as exc:
            raise GISAnalysisResultIntegrityError(
                "GIS result Artifact evidence is invalid"
            ) from exc
        except GatewayForbiddenError as exc:
            raise GISAnalysisResultAccessForbidden(
                "GIS result Artifact access was denied"
            ) from exc
        except (GatewayConfigurationError, GatewayUnavailableError) as exc:
            raise GISAnalysisResultAccessUnavailable(
                "GIS result Artifact authority is unavailable"
            ) from exc
        self._validate_artifact(record, artifact)
        try:
            url = (self.backend or self.backend_factory()).verify_and_presign(
                artifact,
                tenant_id=tenant_id,
                run_id=run_id,
                expires_in_seconds=expires_in_seconds,
            )
            issued_at = self.now()
            if issued_at.tzinfo is None or issued_at.utcoffset() is None:
                raise GISAnalysisResultAccessUnavailable(
                    "GIS result access clock is invalid"
                )
            issued_at = issued_at.astimezone(UTC)
            grant = GISAnalysisResultAccessGrant(
                tenant_id=tenant_id,
                access_id=access_id,
                run_id=run_id,
                artifact_id=artifact.artifact_id,
                delivery="presigned_get",
                download_url=url,
                media_type=artifact.media_type,
                size_bytes=artifact.size_bytes,
                content_sha256=artifact.content_sha256,
                issued_at=issued_at,
                expires_at=issued_at + timedelta(seconds=expires_in_seconds),
            )
            self._audit(
                tenant_id=tenant_id,
                access_id=access_id,
                run_id=run_id,
                actor_subject=actor_subject,
                role=role,
                outcome="success",
                reason="result_access_granted",
                details={
                    "artifact_id": str(artifact.artifact_id),
                    "delivery": "presigned_get",
                    "expires_in_seconds": expires_in_seconds,
                    "media_type": artifact.media_type,
                    "size_bytes": artifact.size_bytes,
                    "content_sha256": artifact.content_sha256,
                    **(
                        {}
                        if security_decision is None
                        else {
                            "purpose_code": purpose_code,
                            "security_request_sha256": (
                                security_decision.request.request_sha256
                            ),
                            "security_decision_sha256": (
                                security_decision.decision_sha256
                            ),
                            "policy_ref": security_decision.policy_ref,
                            "policy_version": security_decision.policy_version,
                        }
                    ),
                },
            )
            return grant
        except MetricQueryResultIntegrityError as exc:
            raise GISAnalysisResultIntegrityError(
                "GIS result object does not match its Artifact"
            ) from exc
        except MetricQueryResultAccessError as exc:
            raise GISAnalysisResultAccessUnavailable(
                "GIS result object access is unavailable"
            ) from exc
        except GISAnalysisResultAccessError:
            raise
        except (SecurityEventLedgerError, ValidationError, ValueError) as exc:
            raise GISAnalysisResultAccessUnavailable(
                "GIS result access verification is unavailable"
            ) from exc


__all__ = [
    "GIS_ANALYSIS_RESULT_ACCESS_ACTION",
    "GISAnalysisResultAccessError",
    "GISAnalysisResultAccessForbidden",
    "GISAnalysisResultAccessGrant",
    "GISAnalysisResultAccessNotFound",
    "GISAnalysisResultAccessService",
    "GISAnalysisResultAccessUnavailable",
    "GISAnalysisResultIntegrityError",
    "GISAnalysisResultNotReady",
    "build_s3_gis_analysis_result_access_backend",
]

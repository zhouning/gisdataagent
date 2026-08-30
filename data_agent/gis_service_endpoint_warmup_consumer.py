"""Managed delivery of exact-release Martin endpoint warmup commands."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import re
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID, uuid4, uuid5

from pydantic import ValidationError

from .gis_provider_runtime import (
    GISProviderContractError,
    GISProviderUnavailable,
    MartinMVTEndpointWarmupReceipt,
    MartinVectorTileProvider,
    MVTProviderReleaseContext,
)
from .gis_service_endpoint_warmup import (
    GIS_SERVICE_ENDPOINT_WARMUP_PURPOSE,
    GIS_SERVICE_ENDPOINT_WARMUP_QUALITY_SCHEMA,
    GIS_SERVICE_ENDPOINT_WARMUP_WORKLOAD,
    GISServiceEndpointWarmupExecutionPlan,
    GISServiceEndpointWarmupSettlement,
    GISServiceEndpointWarmupStorageEvidence,
    gis_service_endpoint_warmup_artifact_manifest,
)
from .platform_contracts import (
    Artifact,
    ArtifactRole,
    FrameworkAttemptObservation,
    FrameworkKind,
    LineageEvent,
    LineageEventType,
    PlatformCommand,
    PlatformCommandStatus,
    PlatformCommandType,
    QualityResult,
    QualityVerdict,
    RunStatus,
    RunSuccessEvidence,
    canonical_json_bytes,
    canonical_json_fingerprint,
    quality_result_fingerprint,
    run_success_evidence_fingerprint,
)
from .platform_gateway import (
    GatewayConflictError,
    GatewayForbiddenError,
    GatewayNotFoundError,
    GatewayValidationError,
    PlatformGateway,
    PlatformGatewayError,
)

_TENANT_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_BUCKET_RE = re.compile(r"^(?=.{3,63}$)[a-z0-9][a-z0-9.-]*[a-z0-9]$")
_PREFIX_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._=-]{0,127}$")
_PRECONDITION_CODES = frozenset(
    {"409", "412", "ConditionalRequestConflict", "PreconditionFailed"}
)


class WarmupReceiptStoreError(RuntimeError):
    """Base class for provider receipt persistence failures."""


class WarmupReceiptStoreUnavailable(WarmupReceiptStoreError):
    """The configured receipt filesystem could not publish the evidence."""


class WarmupReceiptStoreConflict(WarmupReceiptStoreError):
    """A deterministic receipt location already contains different bytes."""


class WarmupReceiptStore(Protocol):
    backend_name: str

    def publish(
        self,
        receipt: MartinMVTEndpointWarmupReceipt,
        *,
        run_id: UUID,
    ) -> WarmupReceiptPublication: ...

    def probe(self) -> None: ...


@dataclass(frozen=True)
class WarmupReceiptPublication:
    storage_uri: str
    content_sha256: str
    size_bytes: int
    storage_evidence: GISServiceEndpointWarmupStorageEvidence | None = None


class LocalWarmupReceiptStore:
    """Content-verified local storage for the fingerprinted receipt payload."""

    backend_name = "local"

    def __init__(self, root: Path) -> None:
        if not root.is_absolute():
            raise ValueError("warmup receipt root must be absolute")
        resolved = root.expanduser().resolve()
        if resolved == Path(resolved.anchor):
            raise ValueError("warmup receipt root must not be a filesystem root")
        self.root = resolved

    def publish(
        self,
        receipt: MartinMVTEndpointWarmupReceipt,
        *,
        run_id: UUID,
    ) -> WarmupReceiptPublication:
        payload = receipt.model_dump(
            mode="json", by_alias=True, exclude={"receipt_sha256"}
        )
        content = canonical_json_bytes(payload)
        content_sha256 = hashlib.sha256(content).hexdigest()
        if content_sha256 != receipt.receipt_sha256:
            raise WarmupReceiptStoreConflict(
                "provider receipt bytes do not match receipt_sha256"
            )
        target = (
            self.root
            / receipt.tenant_id
            / str(run_id)
            / "martin-origin-warmup-receipt.json"
        )
        try:
            target.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
            try:
                target.parent.resolve().relative_to(self.root)
            except ValueError as exc:
                raise WarmupReceiptStoreConflict(
                    "warmup receipt path escapes the configured root"
                ) from exc
            if target.exists():
                if (
                    target.is_symlink()
                    or not target.is_file()
                    or target.read_bytes() != content
                ):
                    raise WarmupReceiptStoreConflict(
                        "warmup receipt location already has different content"
                    )
            else:
                temporary = target.with_name(
                    f".{target.name}.{uuid4().hex}.tmp"
                )
                try:
                    descriptor = os.open(
                        temporary,
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                        0o640,
                    )
                    with os.fdopen(descriptor, "wb") as stream:
                        stream.write(content)
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.replace(temporary, target)
                finally:
                    if temporary.exists():
                        temporary.unlink()
        except WarmupReceiptStoreConflict:
            raise
        except OSError as exc:
            raise WarmupReceiptStoreUnavailable(
                "warmup receipt publication failed"
            ) from exc
        return WarmupReceiptPublication(
            storage_uri=target.as_uri(),
            content_sha256=content_sha256,
            size_bytes=len(content),
        )

    def probe(self) -> None:
        """Local directories are created and verified during publication."""


def validate_warmup_s3_location(bucket: str, prefix: str) -> tuple[str, str]:
    """Validate and normalize the deployment-owned warmup evidence location."""

    normalized_bucket = bucket.strip()
    normalized_prefix = prefix.strip().strip("/")
    if (
        _BUCKET_RE.fullmatch(normalized_bucket) is None
        or ".." in normalized_bucket
        or ".-" in normalized_bucket
        or "-." in normalized_bucket
    ):
        raise ValueError("warmup S3 bucket is invalid")
    segments = normalized_prefix.split("/")
    if (
        not normalized_prefix
        or len(normalized_prefix) > 512
        or any(
            _PREFIX_SEGMENT_RE.fullmatch(segment) is None
            for segment in segments
        )
    ):
        raise ValueError("warmup S3 prefix is invalid")
    return normalized_bucket, normalized_prefix


class S3WarmupReceiptStore:
    """Version-bound S3/MinIO receipt publication with exact read-back."""

    backend_name = "s3"

    def __init__(self, client: Any, *, bucket: str, prefix: str) -> None:
        if client is None:
            raise ValueError("warmup S3 client is required")
        self.client = client
        self.bucket, self.prefix = validate_warmup_s3_location(bucket, prefix)

    @staticmethod
    def _error_code(exc: Exception) -> str:
        response = getattr(exc, "response", {})
        error = response.get("Error", {}) if isinstance(response, dict) else {}
        metadata = (
            response.get("ResponseMetadata", {}) if isinstance(response, dict) else {}
        )
        return str(error.get("Code") or metadata.get("HTTPStatusCode") or "")

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
            raise WarmupReceiptStoreUnavailable("warmup S3 object has no valid ETag")
        return etag

    @staticmethod
    def _version_id(response: dict[str, Any]) -> str:
        version_id = str(response.get("VersionId") or "").strip()
        if (
            not version_id
            or version_id == "null"
            or not version_id.isascii()
            or any(ord(character) < 33 for character in version_id)
        ):
            raise WarmupReceiptStoreUnavailable(
                "warmup S3 object has no immutable VersionId"
            )
        return version_id

    def _key(self, tenant_id: str, run_id: UUID) -> str:
        if _TENANT_RE.fullmatch(tenant_id) is None:
            raise WarmupReceiptStoreConflict("warmup S3 tenant path is invalid")
        return f"{self.prefix}/{tenant_id}/{run_id}/martin-origin-warmup-receipt.json"

    def _head(self, key: str, *, version_id: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {"Bucket": self.bucket, "Key": key}
        if version_id is not None:
            params["VersionId"] = version_id
        try:
            return self.client.head_object(**params)
        except Exception as exc:
            raise WarmupReceiptStoreUnavailable("warmup S3 HEAD failed") from exc

    def _read(self, key: str, version_id: str, expected: bytes) -> None:
        try:
            response = self.client.get_object(
                Bucket=self.bucket, Key=key, VersionId=version_id
            )
            if self._version_id(response) != version_id:
                raise WarmupReceiptStoreConflict("warmup S3 read-back version drifted")
            body = response["Body"]
            try:
                data = body.read()
            finally:
                close = getattr(body, "close", None)
                if close is not None:
                    close()
        except WarmupReceiptStoreError:
            raise
        except Exception as exc:
            raise WarmupReceiptStoreUnavailable("warmup S3 GET failed") from exc
        if data != expected:
            raise WarmupReceiptStoreConflict("warmup S3 receipt bytes differ")

    def publish(
        self,
        receipt: MartinMVTEndpointWarmupReceipt,
        *,
        run_id: UUID,
    ) -> WarmupReceiptPublication:
        payload = receipt.model_dump(
            mode="json", by_alias=True, exclude={"receipt_sha256"}
        )
        content = canonical_json_bytes(payload)
        content_sha256 = hashlib.sha256(content).hexdigest()
        if not hmac.compare_digest(content_sha256, receipt.receipt_sha256):
            raise WarmupReceiptStoreConflict("warmup receipt bytes do not match SHA")
        key = self._key(receipt.tenant_id, run_id)
        created: dict[str, Any] | None = None
        try:
            created = self.client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=content,
                ContentType="application/json",
                Metadata={"sha256": receipt.receipt_sha256},
                IfNoneMatch="*",
            )
        except Exception as exc:
            if self._error_code(exc) not in _PRECONDITION_CODES:
                raise WarmupReceiptStoreUnavailable(
                    "warmup S3 receipt publication failed"
                ) from exc
        if created is not None:
            version_id = self._version_id(created)
            created_etag = self._etag(created)
            head = self._head(key, version_id=version_id)
        else:
            head = self._head(key)
            version_id = self._version_id(head)
            created_etag = None
        observed_version_id = self._version_id(head)
        observed_etag = self._etag(head)
        if observed_version_id != version_id or (
            created_etag is not None
            and not hmac.compare_digest(created_etag, observed_etag)
        ):
            raise WarmupReceiptStoreUnavailable(
                "warmup S3 object identity changed during publication"
            )
        metadata = {
            str(name).lower(): str(value)
            for name, value in (head.get("Metadata") or {}).items()
        }
        try:
            size = int(head.get("ContentLength"))
        except (TypeError, ValueError):
            size = -1
        if (
            size != len(content)
            or str(head.get("ContentType") or "") != "application/json"
            or not hmac.compare_digest(
                metadata.get("sha256", ""), receipt.receipt_sha256
            )
        ):
            raise WarmupReceiptStoreConflict("warmup S3 receipt metadata differs")
        self._read(key, version_id, content)
        return WarmupReceiptPublication(
            storage_uri=f"s3://{self.bucket}/{key}",
            content_sha256=content_sha256,
            size_bytes=len(content),
            storage_evidence=GISServiceEndpointWarmupStorageEvidence(
                backend="s3", version_id=version_id, etag=observed_etag
            ),
        )

    def probe(self) -> None:
        try:
            versioning = self.client.get_bucket_versioning(Bucket=self.bucket)
            object_lock_response = self.client.get_object_lock_configuration(
                Bucket=self.bucket
            )
        except Exception as exc:
            raise WarmupReceiptStoreUnavailable("warmup S3 probe failed") from exc
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
            raise WarmupReceiptStoreUnavailable(
                "warmup S3 bucket lacks versioning and object-lock retention"
            )


def build_s3_warmup_receipt_store(
    *,
    bucket: str,
    prefix: str,
    connect_timeout_seconds: float = 5.0,
    read_timeout_seconds: float = 60.0,
) -> S3WarmupReceiptStore:
    try:
        import boto3
        from botocore.config import Config as BotoConfig
    except Exception as exc:  # pragma: no cover - optional dependency boundary.
        raise WarmupReceiptStoreUnavailable(
            "warmup S3 storage requires boto3"
        ) from exc
    if not 0.1 <= connect_timeout_seconds <= 30:
        raise ValueError("warmup S3 connect timeout is invalid")
    if not 1 <= read_timeout_seconds <= 300:
        raise ValueError("warmup S3 read timeout is invalid")
    endpoint = str(os.getenv("AWS_ENDPOINT_URL") or "").strip()
    config: dict[str, Any] = {
        "connect_timeout": connect_timeout_seconds,
        "read_timeout": read_timeout_seconds,
        "retries": {"max_attempts": 0, "mode": "standard"},
    }
    if endpoint:
        config["s3"] = {"addressing_style": "path"}
    kwargs: dict[str, Any] = {
        "region_name": str(os.getenv("AWS_REGION") or "us-east-1"),
        "config": BotoConfig(**config),
    }
    if endpoint:
        kwargs["endpoint_url"] = endpoint
    try:
        client = boto3.client("s3", **kwargs)
    except Exception as exc:
        raise WarmupReceiptStoreUnavailable(
            "warmup S3 client configuration failed"
        ) from exc
    return S3WarmupReceiptStore(client, bucket=bucket, prefix=prefix)


@dataclass(frozen=True)
class GISServiceEndpointWarmupBatchResult:
    claimed: int
    completed: int
    succeeded: int
    retry_pending: int
    failed: int
    command_ids: tuple[UUID, ...]


class GISServiceEndpointWarmupConsumer:
    """Claim, execute, settle and acknowledge Martin warmup commands."""

    def __init__(
        self,
        gateway: PlatformGateway,
        provider: MartinVectorTileProvider,
        receipt_store: WarmupReceiptStore,
        *,
        retry_delay_seconds: int = 30,
    ) -> None:
        if not 0 <= retry_delay_seconds <= 86_400:
            raise ValueError("warmup retry delay must be between 0 and 86400")
        self.gateway = gateway
        self.provider = provider
        self.receipt_store = receipt_store
        self.retry_delay_seconds = retry_delay_seconds

    @staticmethod
    def _validate_command(
        command: PlatformCommand,
        plan: GISServiceEndpointWarmupExecutionPlan,
    ) -> None:
        payload = command.payload
        if (
            command.command_type
            is not PlatformCommandType.GIS_SERVICE_ENDPOINT_WARMUP
            or command.actor_subject != GIS_SERVICE_ENDPOINT_WARMUP_WORKLOAD
            or command.run_id != plan.run_id
            or payload.get("execution_plan_sha256") != plan.plan_sha256
            or payload.get("sample_set_sha256") != plan.sample_set_sha256
            or payload.get("endpoint_revision_id")
            != str(plan.endpoint_revision_id)
            or payload.get("service_release_binding_id")
            != str(plan.service_release_binding_id)
            or payload.get("provider_system") != "martin"
        ):
            raise GISProviderContractError(
                "warmup command does not match its admitted execution plan"
            )

    def _advance_run(self, command: PlatformCommand):
        run = self.gateway.get_run(command.tenant_id, command.run_id)
        if (
            run.subject_context.purpose != GIS_SERVICE_ENDPOINT_WARMUP_PURPOSE
            or (
                f"{run.subject_context.subject_type.value}:"
                f"{run.subject_context.subject_id}"
            )
            != GIS_SERVICE_ENDPOINT_WARMUP_WORKLOAD
        ):
            raise GISProviderContractError(
                "warmup Run does not have its dedicated workload and purpose"
            )
        if run.status is RunStatus.ACCEPTED:
            run = self.gateway.transition_run(
                command.tenant_id,
                command.run_id,
                run.state_version,
                RunStatus.DISPATCHING,
                GIS_SERVICE_ENDPOINT_WARMUP_WORKLOAD,
                "GIS endpoint warmup command claimed",
                {"command_id": str(command.command_id)},
            )
        if run.status is RunStatus.DISPATCHING:
            run = self.gateway.transition_run(
                command.tenant_id,
                command.run_id,
                run.state_version,
                RunStatus.RUNNING,
                GIS_SERVICE_ENDPOINT_WARMUP_WORKLOAD,
                "Martin origin warmup started",
                {"command_id": str(command.command_id)},
            )
        if run.status not in {RunStatus.RUNNING, RunStatus.RECONCILING}:
            raise GISProviderContractError(
                f"warmup command found non-executable Run state {run.status.value}"
            )
        return run

    def _execute_provider(
        self,
        plan: GISServiceEndpointWarmupExecutionPlan,
    ) -> MartinMVTEndpointWarmupReceipt:
        service_definition = self.gateway.get_gis_service_definition_version(
            plan.tenant_id, plan.service_definition_version_id
        )
        release = self.gateway.get_service_release_binding(
            plan.tenant_id, plan.service_release_binding_id
        )
        tile_matrix_set = self.gateway.get_tile_matrix_set_definition_version(
            plan.tenant_id, plan.tile_matrix_set_definition_version_id
        )
        serving_projection = self.gateway.get_mvt_serving_projection_version(
            plan.tenant_id, plan.mvt_serving_projection_version_id
        )
        cache_policy = self.gateway.get_cache_policy_version(
            plan.tenant_id, plan.cache_policy_version_id
        )
        deployment = self.gateway.get_service_deployment_revision(
            plan.tenant_id, plan.deployment_revision_id
        )
        endpoint = self.gateway.get_endpoint_revision(
            plan.tenant_id, plan.endpoint_revision_id
        )
        context = MVTProviderReleaseContext.from_release(
            release,
            tile_matrix_set,
            serving_projection,
            service_type=service_definition.service_type,
            provider_layer_ref=plan.provider_layer_ref,
            provider_query={
                "serving_projection_version_id": str(
                    plan.mvt_serving_projection_version_id
                )
            },
        )
        receipt = asyncio.run(
            self.provider.warmup_mvt_tiles(
                context,
                release,
                deployment,
                endpoint,
                cache_policy,
                plan.samples,
            )
        )
        if (
            receipt.provider_origin_uri != self.provider.endpoint_uri
            or receipt.sample_set_sha256 != plan.sample_set_sha256
        ):
            raise GISProviderContractError(
                "Martin receipt does not match configured origin or sample set"
            )
        return receipt

    def _build_settlement(
        self,
        command: PlatformCommand,
        plan: GISServiceEndpointWarmupExecutionPlan,
        receipt: MartinMVTEndpointWarmupReceipt,
        publication: WarmupReceiptPublication,
        *,
        expected_state_version: int,
    ) -> GISServiceEndpointWarmupSettlement:
        warmup_id = uuid5(
            command.run_id,
            f"gda.gis-service-warmup.receipt:{plan.plan_sha256}",
        )
        artifact_id = uuid5(
            command.run_id,
            f"gda.gis-service-warmup.evidence:{receipt.receipt_sha256}",
        )
        observation_id = uuid5(
            command.run_id,
            f"gda.gis-service-warmup.observation:{receipt.receipt_sha256}",
        )
        quality_result_id = uuid5(
            command.run_id,
            f"gda.gis-service-warmup.quality:{receipt.receipt_sha256}",
        )
        lineage_event_id = uuid5(
            command.run_id,
            f"gda.gis-service-warmup.lineage:{plan.plan_sha256}",
        )
        valid_until = receipt.completed_at + timedelta(
            seconds=plan.cache_max_age_seconds
        )
        receipt_manifest = gis_service_endpoint_warmup_artifact_manifest(
            {
                "warmup_id": warmup_id,
                "service_urn": plan.service_urn,
                "endpoint_revision_id": plan.endpoint_revision_id,
                "deployment_revision_id": plan.deployment_revision_id,
                "service_definition_version_id": (
                    plan.service_definition_version_id
                ),
                "service_release_binding_id": plan.service_release_binding_id,
                "cache_policy_version_id": plan.cache_policy_version_id,
                "cache_namespace": plan.cache_namespace,
                "requested_sample_count": receipt.requested_sample_count,
                "successful_sample_count": receipt.successful_sample_count,
                "sample_set_sha256": receipt.sample_set_sha256,
                "provider_receipt_sha256": receipt.receipt_sha256,
                "started_at": receipt.started_at,
                "completed_at": receipt.completed_at,
                "valid_until": valid_until,
                "storage_evidence": publication.storage_evidence,
            }
        )
        evidence_artifact = Artifact(
            tenant_id=plan.tenant_id,
            artifact_id=artifact_id,
            artifact_key=f"gis-warmup-evidence-{command.run_id.hex}",
            artifact_role=ArtifactRole.EVIDENCE,
            storage_uri=publication.storage_uri,
            media_type="application/json",
            content_sha256=publication.content_sha256,
            size_bytes=publication.size_bytes,
            run_id=command.run_id,
            resource_version_id=plan.source_output_resource_version_id,
            manifest=receipt_manifest,
            created_by=GIS_SERVICE_ENDPOINT_WARMUP_WORKLOAD,
            created_at=receipt.completed_at,
        )
        observation_evidence = {
            **receipt.model_dump(mode="json", by_alias=True),
            "run_id": str(command.run_id),
            "execution_plan_artifact_id": str(
                command.execution_plan_artifact_id
            ),
            "execution_plan_sha256": plan.plan_sha256,
            "source_output_resource_version_id": str(
                plan.source_output_resource_version_id
            ),
        }
        observation = FrameworkAttemptObservation(
            tenant_id=plan.tenant_id,
            observation_id=observation_id,
            run_id=command.run_id,
            attempt_no=command.attempt_count,
            framework_kind=FrameworkKind.CLOUD,
            external_namespace="martin",
            external_run_id=str(plan.deployment_revision_id),
            external_attempt_id=f"warmup-attempt-{command.attempt_count}",
            observed_state="success",
            observation_sha256=canonical_json_fingerprint(
                observation_evidence
            ),
            evidence=observation_evidence,
            observed_at=receipt.completed_at,
        )
        quality_metrics = {
            "schema": GIS_SERVICE_ENDPOINT_WARMUP_QUALITY_SCHEMA,
            "requested_sample_count": receipt.requested_sample_count,
            "successful_sample_count": receipt.successful_sample_count,
            "sample_set_sha256": receipt.sample_set_sha256,
            "provider_receipt_sha256": receipt.receipt_sha256,
        }
        quality_result = QualityResult(
            tenant_id=plan.tenant_id,
            quality_result_id=quality_result_id,
            run_id=command.run_id,
            resource_version_id=plan.source_output_resource_version_id,
            rule_version_ref="gda:gis-service-endpoint-warmup/v1",
            verdict=QualityVerdict.PASSED,
            metrics=quality_metrics,
            evidence_artifact_id=artifact_id,
            result_sha256=quality_result_fingerprint(
                tenant_id=plan.tenant_id,
                run_id=command.run_id,
                resource_version_id=plan.source_output_resource_version_id,
                rule_version_ref="gda:gis-service-endpoint-warmup/v1",
                verdict=QualityVerdict.PASSED,
                metrics=quality_metrics,
                evidence_artifact_id=artifact_id,
                evaluated_by=GIS_SERVICE_ENDPOINT_WARMUP_WORKLOAD,
                evaluated_at=receipt.completed_at,
            ),
            evaluated_by=GIS_SERVICE_ENDPOINT_WARMUP_WORKLOAD,
            evaluated_at=receipt.completed_at,
        )
        lineage_facets = {
            "schema": "gda.gis_service_endpoint_warmup_lineage.v1",
            "execution_plan_sha256": plan.plan_sha256,
            "provider_receipt_sha256": receipt.receipt_sha256,
            "endpoint_revision_id": str(plan.endpoint_revision_id),
            "sample_set_sha256": plan.sample_set_sha256,
        }
        lineage_values = {
            "schema": "gda.gis_service_endpoint_warmup_lineage.v1",
            "lineage_event_id": str(lineage_event_id),
            "source_resource_version_id": str(
                plan.source_output_resource_version_id
            ),
            "target_resource_version_id": str(plan.definition_version_id),
            "run_id": str(command.run_id),
            "definition_version_id": str(plan.definition_version_id),
            "artifact_id": str(artifact_id),
            "facets": lineage_facets,
        }
        lineage_event = LineageEvent(
            tenant_id=plan.tenant_id,
            lineage_event_id=lineage_event_id,
            event_type=LineageEventType.READ,
            source_resource_version_id=plan.source_output_resource_version_id,
            target_resource_version_id=plan.definition_version_id,
            producer=GIS_SERVICE_ENDPOINT_WARMUP_WORKLOAD,
            event_sha256=canonical_json_fingerprint(lineage_values),
            run_id=command.run_id,
            definition_version_id=plan.definition_version_id,
            artifact_id=artifact_id,
            facets=lineage_facets,
            occurred_at=receipt.completed_at,
        )
        success_evidence = RunSuccessEvidence(
            tenant_id=plan.tenant_id,
            run_id=command.run_id,
            attempt_observation_id=observation_id,
            output_artifact_id=artifact_id,
            quality_result_id=quality_result_id,
            lineage_event_id=lineage_event_id,
            evidence_sha256=run_success_evidence_fingerprint(
                tenant_id=plan.tenant_id,
                run_id=command.run_id,
                attempt_observation_id=observation_id,
                output_artifact_id=artifact_id,
                quality_result_id=quality_result_id,
                lineage_event_id=lineage_event_id,
            ),
        )
        return GISServiceEndpointWarmupSettlement(
            execution_plan=plan,
            provider_receipt=receipt,
            observation=observation,
            evidence_artifact=evidence_artifact,
            quality_result=quality_result,
            lineage_event=lineage_event,
            success_evidence=success_evidence,
            warmup_id=warmup_id,
            valid_until=valid_until,
            expected_state_version=expected_state_version,
            storage_evidence=publication.storage_evidence,
        )

    def _ack_settled_run(
        self,
        command: PlatformCommand,
        plan: GISServiceEndpointWarmupExecutionPlan,
        *,
        worker_id: str,
    ) -> bool:
        run = self.gateway.get_run(command.tenant_id, command.run_id)
        if run.status is not RunStatus.SUCCEEDED:
            return False
        receipts = self.gateway.list_gis_service_endpoint_warmups(
            command.tenant_id,
            plan.service_urn,
            plan.endpoint_revision_id,
        )
        if not any(
            receipt.run_id == command.run_id
            and receipt.sample_set_sha256 == plan.sample_set_sha256
            and receipt.service_release_binding_id
            == plan.service_release_binding_id
            for receipt in receipts
        ):
            raise GatewayValidationError(
                "successful warmup Run lacks its atomic migration 220 receipt"
            )
        self.gateway.complete_command(
            command.tenant_id, command.command_id, worker_id=worker_id
        )
        return True

    @staticmethod
    def _error(exc: BaseException) -> str:
        return f"{type(exc).__name__}: {exc}"[:2000]

    def _retry_or_exhaust(
        self,
        command: PlatformCommand,
        *,
        worker_id: str,
        error: str,
    ) -> PlatformCommand:
        if command.attempt_count >= command.max_attempts:
            return self.gateway.fail_gis_service_endpoint_warmup_command_terminal(
                command.tenant_id,
                command.command_id,
                worker_id=worker_id,
                error=f"retry exhausted: {error}",
            )
        return self.gateway.fail_command(
            command.tenant_id,
            command.command_id,
            worker_id=worker_id,
            error=error,
            retry_delay_seconds=self.retry_delay_seconds,
        )

    def run_once(
        self,
        tenant_id: str,
        *,
        worker_id: str,
        limit: int = 10,
        lease_seconds: int = 90,
    ) -> GISServiceEndpointWarmupBatchResult:
        commands = self.gateway.claim_commands(
            tenant_id,
            worker_id,
            actor_subject=GIS_SERVICE_ENDPOINT_WARMUP_WORKLOAD,
            limit=limit,
            lease_seconds=lease_seconds,
        )
        completed = 0
        succeeded = 0
        retry_pending = 0
        failed = 0
        for command in commands:
            try:
                plan = self.gateway.get_gis_service_endpoint_warmup_execution_plan(
                    command.tenant_id,
                    command.execution_plan_artifact_id,
                )
                self._validate_command(command, plan)
                if self._ack_settled_run(
                    command, plan, worker_id=worker_id
                ):
                    completed += 1
                    continue
                run = self.gateway.get_run(command.tenant_id, command.run_id)
                if run.status in {
                    RunStatus.FAILED,
                    RunStatus.CANCELLED,
                    RunStatus.TIMED_OUT,
                }:
                    self.gateway.complete_command(
                        command.tenant_id,
                        command.command_id,
                        worker_id=worker_id,
                    )
                    completed += 1
                    continue
                running = self._advance_run(command)
                receipt = self._execute_provider(plan)
                publication = self.receipt_store.publish(
                    receipt, run_id=command.run_id
                )
                settlement = self._build_settlement(
                    command,
                    plan,
                    receipt,
                    publication,
                    expected_state_version=running.state_version,
                )
                self.gateway.settle_gis_service_endpoint_warmup_success(
                    settlement
                )
                self.gateway.complete_command(
                    command.tenant_id,
                    command.command_id,
                    worker_id=worker_id,
                )
                completed += 1
                succeeded += 1
            except (GISProviderUnavailable, WarmupReceiptStoreUnavailable) as exc:
                delivery = self._retry_or_exhaust(
                    command,
                    worker_id=worker_id,
                    error=self._error(exc),
                )
                if delivery.status is PlatformCommandStatus.FAILED:
                    failed += 1
                else:
                    retry_pending += 1
            except (
                GISProviderContractError,
                WarmupReceiptStoreConflict,
                ValidationError,
                GatewayForbiddenError,
                GatewayNotFoundError,
                GatewayValidationError,
            ) as exc:
                self.gateway.fail_gis_service_endpoint_warmup_command_terminal(
                    command.tenant_id,
                    command.command_id,
                    worker_id=worker_id,
                    error=self._error(exc),
                )
                failed += 1
            except GatewayConflictError as exc:
                delivery = self._retry_or_exhaust(
                    command,
                    worker_id=worker_id,
                    error=self._error(exc),
                )
                if delivery.status is PlatformCommandStatus.FAILED:
                    failed += 1
                else:
                    retry_pending += 1
            except PlatformGatewayError as exc:
                try:
                    delivery = self._retry_or_exhaust(
                        command,
                        worker_id=worker_id,
                        error=self._error(exc),
                    )
                except PlatformGatewayError:
                    retry_pending += 1
                else:
                    if delivery.status is PlatformCommandStatus.FAILED:
                        failed += 1
                    else:
                        retry_pending += 1
        return GISServiceEndpointWarmupBatchResult(
            claimed=len(commands),
            completed=completed,
            succeeded=succeeded,
            retry_pending=retry_pending,
            failed=failed,
            command_ids=tuple(command.command_id for command in commands),
        )


__all__ = [
    "GISServiceEndpointWarmupBatchResult",
    "GISServiceEndpointWarmupConsumer",
    "LocalWarmupReceiptStore",
    "S3WarmupReceiptStore",
    "WarmupReceiptStore",
    "WarmupReceiptPublication",
    "WarmupReceiptStoreConflict",
    "WarmupReceiptStoreError",
    "WarmupReceiptStoreUnavailable",
    "build_s3_warmup_receipt_store",
    "validate_warmup_s3_location",
]

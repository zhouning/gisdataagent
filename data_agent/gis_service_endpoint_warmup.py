"""Run-bound cache warmup evidence for one immutable GIS endpoint release."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .gis_provider_runtime import (
    MartinMVTEndpointWarmupReceipt,
    MartinMVTWarmupSample,
    martin_mvt_warmup_sample_set_fingerprint,
)
from .platform_contracts import (
    Artifact,
    ArtifactRole,
    FrameworkAttemptObservation,
    FrameworkKind,
    LineageEvent,
    PlatformCommand,
    PlatformCommandType,
    PlatformRun,
    QualityResult,
    QualityVerdict,
    ResourceBinding,
    RunSuccessEvidence,
    SubjectType,
    TenantId,
    canonical_json_fingerprint,
)

_WORKLOAD_REF_RE = re.compile(r"^workload:[^\s]{1,503}$")
_SERVICE_URN_RE = re.compile(
    r"^gda://[a-z0-9][a-z0-9._-]{0,63}/gis_service/[a-z0-9][a-z0-9._-]{0,127}$"
)

GIS_SERVICE_ENDPOINT_WARMUP_SCHEMA = "gda.gis_service_endpoint_warmup.v1"
GIS_SERVICE_ENDPOINT_WARMUP_ARTIFACT_SCHEMA = (
    "gda.gis_service_endpoint_warmup_receipt.v1"
)
GIS_SERVICE_ENDPOINT_WARMUP_COMMAND_SCHEMA = (
    "gda.gis_service_endpoint_warmup_command.v1"
)
GIS_SERVICE_ENDPOINT_WARMUP_PLAN_SCHEMA = (
    "gda.gis_service_endpoint_warmup_execution_plan.v1"
)
GIS_SERVICE_ENDPOINT_WARMUP_QUALITY_SCHEMA = (
    "gda.gis_service_endpoint_warmup_quality.v1"
)
GIS_SERVICE_ENDPOINT_WARMUP_WORKLOAD = "workload:gis-warmup-controller"
GIS_SERVICE_ENDPOINT_WARMUP_PURPOSE = "gis_service.endpoint_warmup"
GIS_SERVICE_ENDPOINT_WARMUP_STORAGE_EVIDENCE_SCHEMA = (
    "gda.gis_service_endpoint_warmup_storage.v1"
)


class GISServiceEndpointWarmupStorageEvidence(BaseModel):
    """Credential-free immutable identity of the receipt evidence object."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    evidence_schema: Literal[
        "gda.gis_service_endpoint_warmup_storage.v1"
    ] = Field(
        default=GIS_SERVICE_ENDPOINT_WARMUP_STORAGE_EVIDENCE_SCHEMA,
        alias="schema",
    )
    backend: Literal["s3"]
    version_id: str = Field(min_length=1, max_length=1024)
    etag: str = Field(min_length=1, max_length=256)

    @field_validator("version_id", "etag")
    @classmethod
    def _safe_identity(cls, value: str) -> str:
        if (
            value != value.strip()
            or not value.isascii()
            or any(ord(character) < 33 for character in value)
        ):
            raise ValueError("storage evidence identity contains unsafe whitespace")
        return value

    @field_validator("version_id")
    @classmethod
    def _immutable_version(cls, value: str) -> str:
        if value == "null":
            raise ValueError("storage evidence must identify an immutable version")
        return value


class GISServiceEndpointWarmupRunRequest(BaseModel):
    """Client intent for one exact endpoint and ordered MVT sample set."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: TenantId
    run_id: UUID
    definition_version_id: UUID
    service_urn: str
    endpoint_revision_id: UUID
    samples: tuple[MartinMVTWarmupSample, ...] = Field(
        min_length=1, max_length=100
    )
    idempotency_key: str = Field(min_length=1, max_length=512)
    submitted_at: datetime

    @field_validator("service_urn")
    @classmethod
    def _request_service_urn(cls, value: str) -> str:
        if _SERVICE_URN_RE.fullmatch(value) is None:
            raise ValueError("service_urn must identify a GIS service")
        return value

    @field_validator("submitted_at")
    @classmethod
    def _request_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("warmup submission timestamp must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _request_binding(self) -> GISServiceEndpointWarmupRunRequest:
        if self.service_urn.split("/")[2] != self.tenant_id:
            raise ValueError("service_urn tenant must match tenant_id")
        if len(set(self.samples)) != len(self.samples):
            raise ValueError("warmup samples must be unique")
        return self


class GISServiceEndpointWarmupExecutionPlan(BaseModel):
    """Server-compiled immutable provider plan; it never contains origin secrets."""

    model_config = ConfigDict(
        extra="forbid", frozen=True, populate_by_name=True
    )

    plan_schema: Literal[
        "gda.gis_service_endpoint_warmup_execution_plan.v1"
    ] = Field(default=GIS_SERVICE_ENDPOINT_WARMUP_PLAN_SCHEMA, alias="schema")
    tenant_id: TenantId
    run_id: UUID
    definition_version_id: UUID
    definition_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    service_urn: str
    service_definition_version_id: UUID
    endpoint_revision_id: UUID
    endpoint_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    consumer_endpoint_uri: str
    deployment_revision_id: UUID
    deployment_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    service_release_binding_id: UUID
    release_binding_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    cache_policy_version_id: UUID
    cache_policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    cache_namespace: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$")
    cache_max_age_seconds: int = Field(ge=1, le=31_536_000)
    tile_matrix_set_definition_version_id: UUID
    tile_matrix_set_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    mvt_serving_projection_version_id: UUID
    serving_projection_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_output_resource_version_id: UUID
    provider_system: Literal["martin"] = "martin"
    provider_layer_ref: Literal["gda_mvt_serving_projection"] = (
        "gda_mvt_serving_projection"
    )
    samples: tuple[MartinMVTWarmupSample, ...] = Field(
        min_length=1, max_length=100
    )
    sample_set_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("service_urn")
    @classmethod
    def _plan_service_urn(cls, value: str) -> str:
        if _SERVICE_URN_RE.fullmatch(value) is None:
            raise ValueError("service_urn must identify a GIS service")
        return value

    @field_validator("consumer_endpoint_uri")
    @classmethod
    def _consumer_endpoint(cls, value: str) -> str:
        parts = urlsplit(value)
        if (
            parts.scheme != "https"
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
            or parts.query
            or parts.fragment
        ):
            raise ValueError("consumer endpoint must be stable credential-free HTTPS")
        return value

    @model_validator(mode="after")
    def _plan_binding(self) -> GISServiceEndpointWarmupExecutionPlan:
        if self.service_urn.split("/")[2] != self.tenant_id:
            raise ValueError("service_urn tenant must match tenant_id")
        if len(set(self.samples)) != len(self.samples):
            raise ValueError("warmup samples must be unique")
        if self.sample_set_sha256 != martin_mvt_warmup_sample_set_fingerprint(
            self.samples
        ):
            raise ValueError("sample_set_sha256 does not match ordered samples")
        if self.plan_sha256 != gis_service_endpoint_warmup_plan_fingerprint(self):
            raise ValueError("plan_sha256 does not match the warmup execution plan")
        return self


def gis_service_endpoint_warmup_plan_fingerprint(
    value: GISServiceEndpointWarmupExecutionPlan | dict[str, Any],
) -> str:
    if isinstance(value, BaseModel):
        payload = value.model_dump(
            mode="json", by_alias=True, exclude={"plan_sha256"}
        )
    else:
        payload = {key: item for key, item in value.items() if key != "plan_sha256"}
    return canonical_json_fingerprint(_canonical(payload))


class GISServiceEndpointWarmupRunAdmission(BaseModel):
    """Atomic admission result for the Run, plan Artifact and shared command."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run: PlatformRun
    execution_plan: GISServiceEndpointWarmupExecutionPlan
    execution_plan_artifact: Artifact
    command: PlatformCommand
    run_created: bool
    artifact_created: bool
    command_created: bool

    @model_validator(mode="after")
    def _admission_binding(self) -> GISServiceEndpointWarmupRunAdmission:
        plan = self.execution_plan
        artifact = self.execution_plan_artifact
        command = self.command
        if (
            self.run.tenant_id != plan.tenant_id
            or self.run.run_id != plan.run_id
            or self.run.definition_version_id != plan.definition_version_id
            or self.run.config_fingerprint != plan.plan_sha256
            or self.run.subject_context.purpose
            != GIS_SERVICE_ENDPOINT_WARMUP_PURPOSE
            or self.run.subject_context.subject_type is not SubjectType.WORKLOAD
            or f"workload:{self.run.subject_context.subject_id}"
            != GIS_SERVICE_ENDPOINT_WARMUP_WORKLOAD
        ):
            raise ValueError("warmup Run does not match its execution plan")
        expected_input = ResourceBinding(
            binding_name="source_product_output",
            resource_version_id=plan.source_output_resource_version_id,
            semantic_type="gda.gis_service.warmup_source",
        )
        if self.run.input_bindings != (expected_input,):
            raise ValueError("warmup Run must bind its source product output")
        if (
            artifact.tenant_id != plan.tenant_id
            or artifact.run_id != plan.run_id
            or artifact.artifact_role is not ArtifactRole.EXECUTION_PLAN
            or artifact.content_sha256
            != canonical_json_fingerprint(artifact.manifest)
            or artifact.manifest != plan.model_dump(mode="json", by_alias=True)
            or command.run_id != plan.run_id
            or command.execution_plan_artifact_id != artifact.artifact_id
            or command.command_type
            is not PlatformCommandType.GIS_SERVICE_ENDPOINT_WARMUP
        ):
            raise ValueError("warmup command does not match its plan Artifact")
        return self


class GISServiceEndpointWarmupSettlement(BaseModel):
    """Complete evidence set committed with Run success and migration 220 receipt."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    execution_plan: GISServiceEndpointWarmupExecutionPlan
    provider_receipt: MartinMVTEndpointWarmupReceipt
    observation: FrameworkAttemptObservation
    evidence_artifact: Artifact
    quality_result: QualityResult
    lineage_event: LineageEvent
    success_evidence: RunSuccessEvidence
    warmup_id: UUID
    valid_until: datetime
    expected_state_version: int = Field(ge=0)
    storage_evidence: GISServiceEndpointWarmupStorageEvidence | None = None

    @field_validator("valid_until")
    @classmethod
    def _settlement_valid_until(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("warmup validity timestamp must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _settlement_binding(self) -> GISServiceEndpointWarmupSettlement:
        plan = self.execution_plan
        provider = self.provider_receipt
        artifact = self.evidence_artifact
        if (
            provider.tenant_id != plan.tenant_id
            or provider.service_urn != plan.service_urn
            or provider.endpoint_revision_id != plan.endpoint_revision_id
            or provider.deployment_revision_id != plan.deployment_revision_id
            or provider.service_definition_version_id
            != plan.service_definition_version_id
            or provider.service_release_binding_id
            != plan.service_release_binding_id
            or provider.cache_policy_version_id != plan.cache_policy_version_id
            or provider.cache_namespace != plan.cache_namespace
            or provider.mvt_serving_projection_version_id
            != plan.mvt_serving_projection_version_id
            or provider.consumer_endpoint_uri != plan.consumer_endpoint_uri
            or provider.sample_set_sha256 != plan.sample_set_sha256
        ):
            raise ValueError("Martin receipt does not match the admitted warmup plan")
        if (
            self.observation.tenant_id != plan.tenant_id
            or self.observation.run_id != plan.run_id
            or self.observation.framework_kind is not FrameworkKind.CLOUD
            or self.observation.external_namespace != "martin"
            or self.observation.observed_state.lower() != "success"
            or self.observation.evidence.get("schema")
            != "gda.gis_service_martin_endpoint_warmup.v1"
            or self.observation.evidence.get("receipt_sha256")
            != provider.receipt_sha256
            or self.observation.evidence.get("execution_plan_sha256")
            != plan.plan_sha256
        ):
            raise ValueError("warmup observation does not bind provider and plan evidence")
        expected_manifest = {
            "schema": GIS_SERVICE_ENDPOINT_WARMUP_ARTIFACT_SCHEMA,
            "warmup_id": self.warmup_id,
            "service_urn": plan.service_urn,
            "endpoint_revision_id": plan.endpoint_revision_id,
            "deployment_revision_id": plan.deployment_revision_id,
            "service_definition_version_id": plan.service_definition_version_id,
            "service_release_binding_id": plan.service_release_binding_id,
            "cache_policy_version_id": plan.cache_policy_version_id,
            "cache_namespace": plan.cache_namespace,
            "requested_sample_count": provider.requested_sample_count,
            "successful_sample_count": provider.successful_sample_count,
            "sample_set_sha256": provider.sample_set_sha256,
            "provider_receipt_sha256": provider.receipt_sha256,
            "started_at": provider.started_at,
            "completed_at": provider.completed_at,
            "valid_until": self.valid_until,
        }
        if self.storage_evidence is not None:
            expected_manifest["storage_evidence"] = self.storage_evidence
        if (
            artifact.tenant_id != plan.tenant_id
            or artifact.run_id != plan.run_id
            or artifact.resource_version_id
            != plan.source_output_resource_version_id
            or artifact.artifact_role is not ArtifactRole.EVIDENCE
            or artifact.content_sha256 != provider.receipt_sha256
            or artifact.created_by != GIS_SERVICE_ENDPOINT_WARMUP_WORKLOAD
            or artifact.manifest != _canonical(expected_manifest)
        ):
            raise ValueError("warmup evidence Artifact does not match its receipt")
        if not (
            provider.completed_at < self.valid_until
            <= provider.completed_at + timedelta(seconds=plan.cache_max_age_seconds)
        ):
            raise ValueError("warmup evidence exceeds its admitted cache policy")
        metrics = self.quality_result.metrics
        if (
            self.quality_result.tenant_id != plan.tenant_id
            or self.quality_result.run_id != plan.run_id
            or self.quality_result.resource_version_id
            != plan.source_output_resource_version_id
            or self.quality_result.verdict is not QualityVerdict.PASSED
            or self.quality_result.evaluated_by
            != GIS_SERVICE_ENDPOINT_WARMUP_WORKLOAD
            or self.quality_result.evidence_artifact_id != artifact.artifact_id
            or metrics.get("schema") != GIS_SERVICE_ENDPOINT_WARMUP_QUALITY_SCHEMA
            or metrics.get("requested_sample_count")
            != provider.requested_sample_count
            or metrics.get("successful_sample_count")
            != provider.successful_sample_count
            or metrics.get("sample_set_sha256") != provider.sample_set_sha256
            or metrics.get("provider_receipt_sha256") != provider.receipt_sha256
        ):
            raise ValueError("warmup quality result does not bind all provider samples")
        if (
            self.lineage_event.tenant_id != plan.tenant_id
            or self.lineage_event.run_id != plan.run_id
            or self.lineage_event.definition_version_id != plan.definition_version_id
            or self.lineage_event.artifact_id != artifact.artifact_id
            or self.lineage_event.source_resource_version_id
            != plan.source_output_resource_version_id
            or self.lineage_event.target_resource_version_id
            != plan.definition_version_id
        ):
            raise ValueError("warmup lineage does not bind source, plan and evidence")
        if (
            self.success_evidence.tenant_id != plan.tenant_id
            or self.success_evidence.run_id != plan.run_id
            or self.success_evidence.attempt_observation_id
            != self.observation.observation_id
            or self.success_evidence.output_artifact_id != artifact.artifact_id
            or self.success_evidence.quality_result_id
            != self.quality_result.quality_result_id
            or self.success_evidence.lineage_event_id
            != self.lineage_event.lineage_event_id
        ):
            raise ValueError("warmup success evidence is incomplete")
        return self


class GISServiceEndpointWarmupReceipt(BaseModel):
    """Immutable successful sample set for an exact endpoint/cache namespace."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: TenantId
    warmup_id: UUID
    service_urn: str
    endpoint_revision_id: UUID
    deployment_revision_id: UUID
    service_definition_version_id: UUID
    service_release_binding_id: UUID
    cache_policy_version_id: UUID
    cache_namespace: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$")
    run_id: UUID
    evidence_artifact_id: UUID
    requested_sample_count: int = Field(gt=0)
    successful_sample_count: int = Field(gt=0)
    sample_set_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    started_at: datetime
    completed_at: datetime
    valid_until: datetime
    recorded_by: str = Field(min_length=1, max_length=512)
    recorded_at: datetime
    warmup_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("service_urn")
    @classmethod
    def _valid_service_urn(cls, value: str) -> str:
        if _SERVICE_URN_RE.fullmatch(value) is None:
            raise ValueError("service_urn must identify a GIS service")
        return value

    @field_validator("recorded_by")
    @classmethod
    def _valid_actor(cls, value: str) -> str:
        value = value.strip()
        if _WORKLOAD_REF_RE.fullmatch(value) is None:
            raise ValueError("recorded_by must identify the warmup workload")
        return value

    @field_validator("started_at", "completed_at", "valid_until", "recorded_at")
    @classmethod
    def _aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("warmup timestamps must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _consistent_receipt(self) -> GISServiceEndpointWarmupReceipt:
        if self.service_urn.split("/")[2] != self.tenant_id:
            raise ValueError("service_urn tenant must match tenant_id")
        if self.successful_sample_count != self.requested_sample_count:
            raise ValueError("every requested warmup sample must succeed")
        if not (
            self.started_at
            <= self.completed_at
            < self.valid_until
            and self.completed_at <= self.recorded_at < self.valid_until
        ):
            raise ValueError("warmup timestamps must form one live evidence window")
        if self.warmup_sha256 != gis_service_endpoint_warmup_fingerprint(self):
            raise ValueError("warmup_sha256 does not match the warmup evidence")
        return self


def gis_service_endpoint_warmup_artifact_manifest(
    value: GISServiceEndpointWarmupReceipt | dict[str, Any],
) -> dict[str, Any]:
    """Build the immutable evidence Artifact manifest checked by PostgreSQL."""
    payload = value.model_dump(mode="python") if isinstance(value, BaseModel) else value
    manifest = {
            "schema": GIS_SERVICE_ENDPOINT_WARMUP_ARTIFACT_SCHEMA,
            "warmup_id": payload["warmup_id"],
            "service_urn": payload["service_urn"],
            "endpoint_revision_id": payload["endpoint_revision_id"],
            "deployment_revision_id": payload["deployment_revision_id"],
            "service_definition_version_id": payload[
                "service_definition_version_id"
            ],
            "service_release_binding_id": payload["service_release_binding_id"],
            "cache_policy_version_id": payload["cache_policy_version_id"],
            "cache_namespace": payload["cache_namespace"],
            "requested_sample_count": payload["requested_sample_count"],
            "successful_sample_count": payload["successful_sample_count"],
            "sample_set_sha256": payload["sample_set_sha256"],
            "provider_receipt_sha256": payload["provider_receipt_sha256"],
            "started_at": payload["started_at"],
            "completed_at": payload["completed_at"],
            "valid_until": payload["valid_until"],
    }
    if payload.get("storage_evidence") is not None:
        manifest["storage_evidence"] = payload["storage_evidence"]
    return _canonical(manifest)


def gis_service_endpoint_warmup_fingerprint(
    value: GISServiceEndpointWarmupReceipt | dict[str, Any],
) -> str:
    """Fingerprint every immutable warmup field except its own checksum."""
    if isinstance(value, BaseModel):
        payload = value.model_dump(mode="python", exclude={"warmup_sha256"})
    else:
        payload = {
            key: item for key, item in value.items() if key != "warmup_sha256"
        }
    payload = _canonical(payload)
    payload["schema"] = GIS_SERVICE_ENDPOINT_WARMUP_SCHEMA
    return canonical_json_fingerprint(payload)


def _canonical(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _canonical(value.model_dump(mode="json", by_alias=True))
    if isinstance(value, dict):
        return {str(key): _canonical(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f+00:00")
    return value


GISServiceEndpointWarmupSettlement.model_rebuild()


__all__ = [
    "GIS_SERVICE_ENDPOINT_WARMUP_ARTIFACT_SCHEMA",
    "GIS_SERVICE_ENDPOINT_WARMUP_COMMAND_SCHEMA",
    "GIS_SERVICE_ENDPOINT_WARMUP_PLAN_SCHEMA",
    "GIS_SERVICE_ENDPOINT_WARMUP_PURPOSE",
    "GIS_SERVICE_ENDPOINT_WARMUP_QUALITY_SCHEMA",
    "GIS_SERVICE_ENDPOINT_WARMUP_SCHEMA",
    "GIS_SERVICE_ENDPOINT_WARMUP_STORAGE_EVIDENCE_SCHEMA",
    "GIS_SERVICE_ENDPOINT_WARMUP_WORKLOAD",
    "GISServiceEndpointWarmupStorageEvidence",
    "GISServiceEndpointWarmupExecutionPlan",
    "GISServiceEndpointWarmupReceipt",
    "GISServiceEndpointWarmupRunAdmission",
    "GISServiceEndpointWarmupRunRequest",
    "GISServiceEndpointWarmupSettlement",
    "gis_service_endpoint_warmup_artifact_manifest",
    "gis_service_endpoint_warmup_fingerprint",
    "gis_service_endpoint_warmup_plan_fingerprint",
]

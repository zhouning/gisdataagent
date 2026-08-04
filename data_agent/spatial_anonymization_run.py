"""Immutable admission contracts for governed spatial anonymization runs."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .dataops_manual import (
    DataOpsManualTriggerSpec,
    ManualDataOpsSubmission,
    ManualTriggerWriteResult,
    build_manual_dataops_submission,
)
from .platform_contracts import (
    PlatformCommand,
    PlatformRun,
    Resource,
    ResourceBinding,
    ResourceVersion,
    Sha256,
    ShortName,
    TenantId,
    build_resource_urn,
    canonical_json_fingerprint,
)

SPATIAL_ANONYMIZATION_REQUEST_SCHEMA = (
    "gda.security.spatial_anonymization_request.v1"
)
SPATIAL_ANONYMIZATION_VERSION_SCHEMA = (
    "gda.security.spatial_anonymization_request_version.v1"
)
SPATIAL_ANONYMIZATION_SEMANTIC_TYPE = "security.spatial_anonymization.request"

_IDENTIFIER_RE = re.compile(r"^[^\W\d]\w*$", re.UNICODE)
_REQUEST_NAMESPACE = uuid5(
    NAMESPACE_URL,
    "https://gis-data-agent.local/contracts/spatial-anonymization-request/v1",
)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone")
    return value.astimezone(UTC)


def _identifier(value: str, field_name: str) -> str:
    normalized = value.strip()
    if (
        not normalized
        or len(normalized.encode("utf-8")) > 63
        or not _IDENTIFIER_RE.fullmatch(normalized)
    ):
        raise ValueError(f"invalid {field_name}")
    return normalized


class SpatialAnonymizationRequest(_FrozenModel):
    """Complete immutable business request bound to one client retry identity."""

    tenant_id: TenantId
    client_request_id: str = Field(
        min_length=3,
        max_length=128,
        pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._:-]{2,127}$",
    )
    requester_subject: str = Field(
        min_length=7,
        max_length=512,
        pattern=r"^human:[^\s]+$",
    )
    source_asset_ref: str = Field(min_length=3, max_length=512)
    source_schema: str
    source_table: str
    output_schema: str = "public"
    output_table: str
    data_type: Literal["point", "polygon"] = "polygon"
    level: Literal["L1", "L2", "L3", "L4"] = "L3"
    k_anonymity: int = Field(default=5, ge=2, le=1000)
    keep_attrs: tuple[str, ...] = ()
    agg_strategy: Literal["mode", "area_weighted", "topk"] = "area_weighted"
    dp_epsilon: float | None = Field(default=None, ge=0.01, le=10.0)
    dp_numeric_fields: tuple[str, ...] = ()
    category_column: str | None = None
    top_k_categories: int | None = Field(default=None, ge=1, le=100)
    random_offset: bool = True
    random_seed: int = Field(default=42, ge=0, le=2147483647)
    register_lineage: bool = True

    @field_validator("client_request_id", "requester_subject", "source_asset_ref")
    @classmethod
    def _trim_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("spatial anonymization text fields must not be blank")
        return normalized

    @field_validator(
        "source_schema",
        "source_table",
        "output_schema",
        "output_table",
        "category_column",
    )
    @classmethod
    def _postgres_identifier(cls, value: str | None, info) -> str | None:
        return _identifier(value, info.field_name) if value is not None else None

    @field_validator("keep_attrs", "dp_numeric_fields")
    @classmethod
    def _canonical_columns(cls, value: tuple[str, ...], info) -> tuple[str, ...]:
        normalized = tuple(sorted(_identifier(item, info.field_name) for item in value))
        if len(normalized) != len(set(normalized)):
            raise ValueError(f"{info.field_name} must not contain duplicates")
        if len(normalized) > 100:
            raise ValueError(f"{info.field_name} must contain at most 100 columns")
        return normalized

    @model_validator(mode="after")
    def _consistent_operation(self) -> SpatialAnonymizationRequest:
        if self.output_schema != "public":
            raise ValueError("output_schema must be public")
        if (self.source_schema, self.source_table) == (
            self.output_schema,
            self.output_table,
        ):
            raise ValueError("source and output tables must be different")
        if self.data_type == "point":
            if self.category_column is None or self.top_k_categories is None:
                raise ValueError(
                    "point anonymization requires category_column and top_k_categories"
                )
            if self.keep_attrs or self.dp_numeric_fields or self.dp_epsilon is not None:
                raise ValueError(
                    "point anonymization cannot declare polygon aggregation fields"
                )
        elif self.category_column is not None or self.top_k_categories is not None:
            raise ValueError(
                "polygon anonymization cannot declare point category parameters"
            )
        if self.dp_epsilon is None and self.dp_numeric_fields:
            raise ValueError("dp_numeric_fields require dp_epsilon")
        if self.dp_epsilon is not None and not self.dp_numeric_fields:
            raise ValueError("dp_epsilon requires dp_numeric_fields")
        return self


def spatial_anonymization_request_identity(
    request: SpatialAnonymizationRequest,
) -> str:
    return canonical_json_fingerprint(
        {
            "schema": SPATIAL_ANONYMIZATION_REQUEST_SCHEMA,
            "tenant_id": request.tenant_id,
            "client_request_id": request.client_request_id,
        }
    )


def spatial_anonymization_request_fingerprint(
    request: SpatialAnonymizationRequest,
) -> str:
    return canonical_json_fingerprint(
        {
            "schema": SPATIAL_ANONYMIZATION_REQUEST_SCHEMA,
            **request.model_dump(mode="json"),
        }
    )


def spatial_anonymization_lock_keys(
    request: SpatialAnonymizationRequest,
) -> tuple[int, int]:
    raw = bytes.fromhex(spatial_anonymization_request_identity(request))
    return (
        int.from_bytes(raw[:4], byteorder="big", signed=True),
        int.from_bytes(raw[4:8], byteorder="big", signed=True),
    )


def spatial_anonymization_resource_urn(
    request: SpatialAnonymizationRequest,
) -> str:
    return build_resource_urn(
        request.tenant_id,
        "anonymization",
        spatial_anonymization_request_identity(request),
    )


def spatial_anonymization_version_id(
    request: SpatialAnonymizationRequest,
) -> UUID:
    return uuid5(
        _REQUEST_NAMESPACE,
        (
            f"{request.tenant_id}:"
            f"{spatial_anonymization_request_fingerprint(request)}"
        ),
    )


def spatial_anonymization_dataops_client_request_id(
    request: SpatialAnonymizationRequest,
) -> str:
    identity = spatial_anonymization_request_identity(request)
    return f"spatial-anonymization:{identity[:40]}"


def build_spatial_anonymization_resources(
    request: SpatialAnonymizationRequest,
    *,
    created_at: datetime,
    owner_ref: str = "team:data-governance",
) -> tuple[Resource, ResourceVersion]:
    created = _aware_utc(created_at, "created_at")
    request_sha256 = spatial_anonymization_request_fingerprint(request)
    resource_urn = spatial_anonymization_resource_urn(request)
    resource = Resource(
        tenant_id=request.tenant_id,
        resource_urn=resource_urn,
        resource_kind="anonymization",
        authority_system="gda-control",
        authority_locator=(
            "spatial-anonymization-requests/"
            f"{spatial_anonymization_request_identity(request)}"
        ),
        owner_ref=owner_ref,
        governance_ref={
            "document_schema": SPATIAL_ANONYMIZATION_REQUEST_SCHEMA,
            "immutable": True,
            "security_operation": "data_anonymize",
        },
        technical_refs=(
            {
                "kind": "postgis_source",
                "asset_ref": request.source_asset_ref,
                "table": f"{request.source_schema}.{request.source_table}",
            },
            {
                "kind": "postgis_output",
                "table": f"{request.output_schema}.{request.output_table}",
            },
        ),
    )
    version = ResourceVersion(
        tenant_id=request.tenant_id,
        resource_urn=resource_urn,
        resource_version_id=spatial_anonymization_version_id(request),
        version_key=f"req-{request_sha256[:20]}",
        content_sha256=request_sha256,
        authority_version_ref={
            "schema": SPATIAL_ANONYMIZATION_VERSION_SCHEMA,
            "request": request.model_dump(mode="json"),
        },
        created_by=request.requester_subject,
        created_at=created,
    )
    return resource, version


def parse_spatial_anonymization_version(
    version: ResourceVersion,
) -> SpatialAnonymizationRequest:
    try:
        envelope = version.authority_version_ref
        if set(envelope) != {"schema", "request"}:
            raise ValueError("request version envelope has unexpected fields")
        if envelope["schema"] != SPATIAL_ANONYMIZATION_VERSION_SCHEMA:
            raise ValueError("request version schema is unsupported")
        request = SpatialAnonymizationRequest.model_validate(envelope["request"])
    except Exception as exc:
        raise ValueError("spatial anonymization ResourceVersion is invalid") from exc

    _resource, expected = build_spatial_anonymization_resources(
        request,
        created_at=version.created_at,
        owner_ref="team:data-governance",
    )
    comparable = {
        "tenant_id",
        "resource_urn",
        "resource_version_id",
        "version_key",
        "predecessor_version_id",
        "content_sha256",
        "authority_version_ref",
        "created_by",
        "created_at",
    }
    if version.model_dump(mode="python", include=comparable) != expected.model_dump(
        mode="python", include=comparable
    ):
        raise ValueError(
            "spatial anonymization ResourceVersion metadata does not match its document"
        )
    return request


class SpatialAnonymizationRunSpec(_FrozenModel):
    request: SpatialAnonymizationRequest
    definition_version_id: UUID
    execution_plan_artifact_id: UUID
    workload_subject_id: str = Field(min_length=3, max_length=512, pattern=r"^[^\s]+$")
    workload_roles: tuple[ShortName, ...] = Field(
        default=("platform_operator",), min_length=1
    )
    purpose: str = Field(min_length=3, max_length=1024)
    policy_version_ref: str = Field(min_length=3, max_length=1024)
    policy_evaluator_subject: str = Field(
        min_length=12,
        max_length=512,
        pattern=r"^workload:[^\s]+$",
    )
    policy_ttl_seconds: int = Field(default=86400, ge=60, le=604800)
    config_fingerprint: Sha256 | None = None
    invocation_owner_ref: str = Field(default="team:data-platform", min_length=3)
    request_owner_ref: str = Field(default="team:data-governance", min_length=3)

    @field_validator(
        "workload_subject_id",
        "purpose",
        "policy_version_ref",
        "policy_evaluator_subject",
        "invocation_owner_ref",
        "request_owner_ref",
    )
    @classmethod
    def _trim_profile_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("spatial anonymization profile fields must not be blank")
        return normalized

    @field_validator("workload_roles")
    @classmethod
    def _canonical_roles(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(sorted(item.strip() for item in value))
        if any(not item for item in normalized):
            raise ValueError("workload roles must not be blank")
        if len(normalized) != len(set(normalized)):
            raise ValueError("workload roles must not contain duplicates")
        return normalized

    @model_validator(mode="after")
    def _independent_evaluator(self) -> SpatialAnonymizationRunSpec:
        if self.policy_evaluator_subject == f"workload:{self.workload_subject_id}":
            raise ValueError("policy evaluator must be independent from the workload")
        return self


class SpatialAnonymizationSubmission(_FrozenModel):
    request_sha256: Sha256
    admitted_at: datetime
    request_resource: Resource
    request_version: ResourceVersion
    manual_spec: DataOpsManualTriggerSpec
    manual_submission: ManualDataOpsSubmission

    @field_validator("admitted_at")
    @classmethod
    def _utc_admitted_at(cls, value: datetime) -> datetime:
        return _aware_utc(value, "admitted_at")

    @model_validator(mode="after")
    def _consistent_submission(self) -> SpatialAnonymizationSubmission:
        binding = next(
            (
                item
                for item in self.manual_submission.run.input_bindings
                if item.binding_name == "anonymization_request"
            ),
            None,
        )
        if binding is None or (
            binding.resource_version_id != self.request_version.resource_version_id
            or binding.semantic_type != SPATIAL_ANONYMIZATION_SEMANTIC_TYPE
        ):
            raise ValueError("Run does not bind the spatial anonymization request")
        if self.request_sha256 != self.request_version.content_sha256:
            raise ValueError("request fingerprint does not match its ResourceVersion")
        return self

    @property
    def run(self) -> PlatformRun:
        return self.manual_submission.run


def build_spatial_anonymization_submission(
    spec: SpatialAnonymizationRunSpec,
    *,
    admitted_at: datetime,
) -> SpatialAnonymizationSubmission:
    admitted = _aware_utc(admitted_at, "admitted_at")
    request_resource, request_version = build_spatial_anonymization_resources(
        spec.request,
        created_at=admitted,
        owner_ref=spec.request_owner_ref,
    )
    manual_spec = DataOpsManualTriggerSpec(
        tenant_id=spec.request.tenant_id,
        client_request_id=spatial_anonymization_dataops_client_request_id(spec.request),
        definition_version_id=spec.definition_version_id,
        logical_start=admitted,
        logical_end=admitted + timedelta(microseconds=1),
        input_bindings=(
            ResourceBinding(
                binding_name="anonymization_request",
                resource_version_id=request_version.resource_version_id,
                semantic_type=SPATIAL_ANONYMIZATION_SEMANTIC_TYPE,
            ),
        ),
        execution_plan_artifact_id=spec.execution_plan_artifact_id,
        requester_subject=spec.request.requester_subject,
        workload_subject_id=spec.workload_subject_id,
        workload_roles=spec.workload_roles,
        purpose=spec.purpose,
        policy_version_ref=spec.policy_version_ref,
        policy_evaluator_subject=spec.policy_evaluator_subject,
        policy_ttl_seconds=spec.policy_ttl_seconds,
        config_fingerprint=spec.config_fingerprint,
        invocation_owner_ref=spec.invocation_owner_ref,
    )
    manual_submission = build_manual_dataops_submission(
        manual_spec,
        admitted_at=admitted,
    )
    return SpatialAnonymizationSubmission(
        request_sha256=spatial_anonymization_request_fingerprint(spec.request),
        admitted_at=admitted,
        request_resource=request_resource,
        request_version=request_version,
        manual_spec=manual_spec,
        manual_submission=manual_submission,
    )


@dataclass(frozen=True)
class SpatialAnonymizationRunWriteResult:
    request: SpatialAnonymizationRequest
    request_sha256: str
    admitted_at: datetime
    request_resource: Resource
    request_version: ResourceVersion
    run: PlatformRun
    command: PlatformCommand
    request_resource_created: bool
    request_version_created: bool
    invocation_resource_created: bool
    invocation_version_created: bool
    policy_artifact_created: bool
    run_created: bool
    command_created: bool

    @classmethod
    def from_manual_result(
        cls,
        *,
        submission: SpatialAnonymizationSubmission,
        manual_result: ManualTriggerWriteResult,
        request_resource_created: bool,
        request_version_created: bool,
    ) -> SpatialAnonymizationRunWriteResult:
        return cls(
            request=parse_spatial_anonymization_version(submission.request_version),
            request_sha256=submission.request_sha256,
            admitted_at=manual_result.admitted_at,
            request_resource=submission.request_resource,
            request_version=submission.request_version,
            run=manual_result.run,
            command=manual_result.command,
            request_resource_created=request_resource_created,
            request_version_created=request_version_created,
            invocation_resource_created=manual_result.invocation_resource_created,
            invocation_version_created=manual_result.invocation_version_created,
            policy_artifact_created=manual_result.policy_artifact_created,
            run_created=manual_result.run_created,
            command_created=manual_result.command_created,
        )

    @property
    def created(self) -> bool:
        return any(
            (
                self.request_resource_created,
                self.request_version_created,
                self.invocation_resource_created,
                self.invocation_version_created,
                self.policy_artifact_created,
                self.run_created,
                self.command_created,
            )
        )

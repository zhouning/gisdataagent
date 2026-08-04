"""Immutable invocation resources for governed DataOps runs."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .platform_contracts import (
    Resource,
    ResourceVersion,
    TenantId,
    build_resource_urn,
    canonical_json_fingerprint,
)

DATAOPS_INVOCATION_SCHEMA = "gda.dataops_invocation.v1"
DATAOPS_INVOCATION_VERSION_SCHEMA = "gda.dataops_invocation_resource_version.v1"
DATAOPS_INVOCATION_SEMANTIC_TYPE = "platform.dataops.invocation"


class DataOpsInvocationError(ValueError):
    """An invocation resource is missing, inconsistent, or tampered."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone")
    return value.astimezone(UTC)


def dataops_invocation_fingerprint(
    *,
    tenant_id: str,
    definition_version_id: UUID,
    trigger_kind: str,
    logical_start: datetime,
    logical_end: datetime,
    window_semantics: str,
    schedule_times: tuple[datetime, ...],
    schedule_ref: str | None,
    requested_by: str,
    requested_at: datetime,
    client_request_id: str | None = None,
) -> str:
    document = {
        "schema": DATAOPS_INVOCATION_SCHEMA,
        "tenant_id": tenant_id,
        "definition_version_id": str(definition_version_id),
        "trigger_kind": trigger_kind,
        "logical_start": _aware_utc(logical_start, "logical_start").isoformat(),
        "logical_end": _aware_utc(logical_end, "logical_end").isoformat(),
        "window_semantics": window_semantics,
        "schedule_ref": schedule_ref,
        "requested_by": requested_by,
        "requested_at": _aware_utc(requested_at, "requested_at").isoformat(),
    }
    if client_request_id is not None:
        document["client_request_id"] = client_request_id
    if schedule_times:
        document["schedule_times"] = [
            _aware_utc(value, "schedule_times").isoformat()
            for value in schedule_times
        ]
    return canonical_json_fingerprint(document)


class DataOpsInvocation(_FrozenModel):
    """Content-addressed request to execute one governed logical window."""

    schema_name: Literal["gda.dataops_invocation.v1"] = Field(
        default=DATAOPS_INVOCATION_SCHEMA,
        alias="schema",
    )
    tenant_id: TenantId
    definition_version_id: UUID
    trigger_kind: Literal["manual", "schedule", "backfill", "replay"]
    logical_start: datetime
    logical_end: datetime
    window_semantics: Literal["closed", "half_open"] = "half_open"
    schedule_times: tuple[datetime, ...] = ()
    schedule_ref: str | None = Field(default=None, min_length=1, max_length=512)
    requested_by: str = Field(min_length=3, max_length=512)
    requested_at: datetime
    client_request_id: str | None = Field(
        default=None,
        min_length=3,
        max_length=128,
        pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._:-]{2,127}$",
    )
    invocation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("logical_start", "logical_end", "requested_at")
    @classmethod
    def _utc_timestamp(cls, value: datetime, info) -> datetime:
        return _aware_utc(value, info.field_name)

    @field_validator("schedule_times")
    @classmethod
    def _utc_schedule_times(cls, values: tuple[datetime, ...]) -> tuple[datetime, ...]:
        return tuple(_aware_utc(value, "schedule_times") for value in values)

    @field_validator("schedule_ref", "requested_by", "client_request_id")
    @classmethod
    def _trim_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("invocation text fields must not be blank")
        return normalized

    @model_validator(mode="after")
    def _consistent_invocation(self) -> DataOpsInvocation:
        if self.logical_start >= self.logical_end:
            raise ValueError("logical_start must be earlier than logical_end")
        if self.trigger_kind == "schedule" and self.schedule_ref is None:
            raise ValueError("scheduled invocation requires schedule_ref")
        if self.trigger_kind in {"manual", "replay"} and self.schedule_ref is not None:
            raise ValueError(
                "manual and replay invocations must not claim a schedule reference"
            )
        if self.trigger_kind == "manual" and self.client_request_id is None:
            raise ValueError("manual invocation requires client_request_id")
        if self.client_request_id is not None and self.trigger_kind != "manual":
            raise ValueError("client_request_id is only valid for manual invocations")
        if self.schedule_times != tuple(sorted(set(self.schedule_times))):
            raise ValueError("schedule_times must be sorted and unique")
        if self.trigger_kind in {"schedule", "backfill"} and self.window_semantics == "half_open":
            if len(self.schedule_times) != 1:
                raise ValueError(
                    "each governed schedule or backfill Run requires exactly one schedule time"
                )
            if self.trigger_kind == "backfill" and not all(
                self.logical_start <= value < self.logical_end
                for value in self.schedule_times
            ):
                raise ValueError(
                    "backfill schedule time must be inside the half-open logical window"
                )
        elif self.schedule_times:
            raise ValueError(
                "explicit schedule_times are only supported for half-open schedules and backfills"
            )
        expected = dataops_invocation_fingerprint(
            tenant_id=self.tenant_id,
            definition_version_id=self.definition_version_id,
            trigger_kind=self.trigger_kind,
            logical_start=self.logical_start,
            logical_end=self.logical_end,
            window_semantics=self.window_semantics,
            schedule_times=self.schedule_times,
            schedule_ref=self.schedule_ref,
            requested_by=self.requested_by,
            requested_at=self.requested_at,
            client_request_id=self.client_request_id,
        )
        if self.invocation_sha256 != expected:
            raise ValueError("invocation_sha256 does not match invocation content")
        return self

    @classmethod
    def create(
        cls,
        *,
        tenant_id: str,
        definition_version_id: UUID,
        trigger_kind: Literal["manual", "schedule", "backfill", "replay"],
        logical_start: datetime,
        logical_end: datetime,
        requested_by: str,
        requested_at: datetime,
        schedule_ref: str | None = None,
        window_semantics: Literal["closed", "half_open"] = "half_open",
        schedule_times: tuple[datetime, ...] = (),
        client_request_id: str | None = None,
    ) -> DataOpsInvocation:
        fingerprint = dataops_invocation_fingerprint(
            tenant_id=tenant_id,
            definition_version_id=definition_version_id,
            trigger_kind=trigger_kind,
            logical_start=logical_start,
            logical_end=logical_end,
            window_semantics=window_semantics,
            schedule_times=schedule_times,
            schedule_ref=schedule_ref.strip() if schedule_ref is not None else None,
            requested_by=requested_by.strip(),
            requested_at=requested_at,
            client_request_id=(
                client_request_id.strip() if client_request_id is not None else None
            ),
        )
        return cls(
            tenant_id=tenant_id,
            definition_version_id=definition_version_id,
            trigger_kind=trigger_kind,
            logical_start=logical_start,
            logical_end=logical_end,
            window_semantics=window_semantics,
            schedule_times=schedule_times,
            schedule_ref=schedule_ref,
            requested_by=requested_by,
            requested_at=requested_at,
            client_request_id=client_request_id,
            invocation_sha256=fingerprint,
        )


def dataops_invocation_resource_urn(invocation: DataOpsInvocation) -> str:
    return build_resource_urn(
        invocation.tenant_id,
        "trigger",
        str(invocation.definition_version_id),
    )


def dataops_invocation_version_id(invocation: DataOpsInvocation) -> UUID:
    return uuid5(
        invocation.definition_version_id,
        f"dataops-invocation:{invocation.invocation_sha256}",
    )


def _authority_version_ref(invocation: DataOpsInvocation) -> dict[str, object]:
    document = invocation.model_dump(mode="json", by_alias=True)
    if not invocation.schedule_times:
        document.pop("schedule_times")
    if invocation.client_request_id is None:
        document.pop("client_request_id")
    return {
        "schema": DATAOPS_INVOCATION_VERSION_SCHEMA,
        "invocation": document,
    }


def build_dataops_invocation_resources(
    invocation: DataOpsInvocation,
    *,
    owner_ref: str = "team:data-platform",
) -> tuple[Resource, ResourceVersion]:
    """Build the stable trigger resource and immutable invocation version."""
    resource_urn = dataops_invocation_resource_urn(invocation)
    version_id = dataops_invocation_version_id(invocation)
    resource = Resource(
        tenant_id=invocation.tenant_id,
        resource_urn=resource_urn,
        resource_kind="trigger",
        authority_system="gda-control",
        authority_locator=f"dataops-invocations/{invocation.definition_version_id}",
        owner_ref=owner_ref,
        governance_ref={
            "document_schema": DATAOPS_INVOCATION_SCHEMA,
            "immutable": True,
        },
        technical_refs=(
            {
                "kind": "platform_definition_version",
                "definition_version_id": str(invocation.definition_version_id),
            },
        ),
    )
    version = ResourceVersion(
        tenant_id=invocation.tenant_id,
        resource_urn=resource_urn,
        resource_version_id=version_id,
        version_key=f"inv-{invocation.invocation_sha256[:20]}",
        content_sha256=invocation.invocation_sha256,
        authority_version_ref=_authority_version_ref(invocation),
        created_by=invocation.requested_by,
        created_at=invocation.requested_at,
    )
    return resource, version


def parse_dataops_invocation_version(version: ResourceVersion) -> DataOpsInvocation:
    """Validate the complete ResourceVersion envelope before using its window."""
    try:
        if set(version.authority_version_ref) != {"schema", "invocation"}:
            raise ValueError("invocation version envelope has unexpected fields")
        if (
            version.authority_version_ref["schema"]
            != DATAOPS_INVOCATION_VERSION_SCHEMA
        ):
            raise ValueError("invocation version schema is unsupported")
        invocation = DataOpsInvocation.model_validate(
            version.authority_version_ref["invocation"]
        )
    except Exception as exc:
        raise DataOpsInvocationError(
            "invocation ResourceVersion document is invalid"
        ) from exc

    _resource, expected = build_dataops_invocation_resources(invocation)
    fields = {
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
    if version.model_dump(mode="python", include=fields) != expected.model_dump(
        mode="python", include=fields
    ):
        raise DataOpsInvocationError(
            "invocation ResourceVersion metadata does not match its document"
        )
    return invocation

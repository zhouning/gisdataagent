"""Content-bound contracts for the Active Metadata change outbox."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import Enum
from typing import Annotated, Any, Literal, Self
from uuid import UUID, uuid5

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from .platform_contracts import (
    ResourceVersion,
    Sha256,
    TenantId,
    canonical_json_fingerprint,
)


EVENT_SCHEMA = "gda.metadata_change_event.v1"
DELIVERY_SCHEMA = "gda.metadata_change_delivery.v1"
REGISTRATION_SCHEMA = "gda.active_metadata_registration.v1"
ACTIVATION_INTENT_SCHEMA = "gda.metadata_activation_intent.v1"
RESOURCE_VERSION_REGISTERED = "resource_version.registered"
METADATA_PROJECTION_ROUTE = "metadata_fabric.projection_plan"

ActorSubject = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=3,
        max_length=256,
        pattern=r"^(human|workload|agent):[a-zA-Z0-9][a-zA-Z0-9._:@/-]{0,247}$",
    ),
]
WorkloadSubject = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=10,
        max_length=256,
        pattern=r"^workload:[a-zA-Z0-9][a-zA-Z0-9._:@/-]{0,247}$",
    ),
]
ErrorCode = Annotated[
    str,
    StringConstraints(pattern=r"^[a-z0-9_]{1,64}$"),
]


class ActiveMetadataContractError(ValueError):
    """An Active Metadata change or activation intent is not content-bound."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MetadataChangeDeliveryStatus(str, Enum):
    PENDING = "pending"
    IN_FLIGHT = "in_flight"
    PROCESSED = "processed"
    FAILED = "failed"


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return value.astimezone(UTC)


def _event_stable(values: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": EVENT_SCHEMA,
        "event_id": str(values["event_id"]),
        "event_type": RESOURCE_VERSION_REGISTERED,
        "tenant_id": values["tenant_id"],
        "resource_urn": values["resource_urn"],
        "resource_version_id": str(values["resource_version_id"]),
        "version_key": values["version_key"],
        "predecessor_version_id": (
            str(values["predecessor_version_id"])
            if values["predecessor_version_id"] is not None
            else None
        ),
        "content_sha256": values["content_sha256"],
        "producer_subject": values["producer_subject"],
        "consumer_subject": values["consumer_subject"],
        "occurred_at": _utc(values["occurred_at"])
        .isoformat()
        .replace("+00:00", "Z"),
    }


class MetadataChangeEvent(_FrozenModel):
    event_schema: Literal["gda.metadata_change_event.v1"] = Field(
        default=EVENT_SCHEMA,
        alias="schema",
    )
    event_id: UUID
    event_type: Literal["resource_version.registered"] = (
        RESOURCE_VERSION_REGISTERED
    )
    tenant_id: TenantId
    resource_urn: str
    resource_version_id: UUID
    version_key: str
    predecessor_version_id: UUID | None = None
    content_sha256: Sha256
    producer_subject: ActorSubject
    consumer_subject: WorkloadSubject
    occurred_at: datetime
    event_sha256: Sha256

    @field_validator("occurred_at")
    @classmethod
    def _aware_time(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def _content_bound(self) -> Self:
        expected_id = uuid5(
            self.resource_version_id,
            f"active-metadata:{self.event_type}",
        )
        if self.event_id != expected_id:
            raise ValueError("MetadataChangeEvent ID does not match the version")
        expected_sha = canonical_json_fingerprint(
            _event_stable(
                self.model_dump(
                    mode="python",
                    by_alias=True,
                    exclude={"event_sha256"},
                )
            )
        )
        if self.event_sha256 != expected_sha:
            raise ValueError("MetadataChangeEvent SHA-256 does not match")
        return self


def build_metadata_change_event(
    version: ResourceVersion,
    *,
    consumer_subject: str,
) -> MetadataChangeEvent:
    if not re.fullmatch(
        r"^(human|workload|agent):[a-zA-Z0-9][a-zA-Z0-9._:@/-]{0,247}$",
        version.created_by,
    ):
        raise ActiveMetadataContractError(
            "ResourceVersion creator must use an authenticated subject"
        )
    event_id = uuid5(
        version.resource_version_id,
        f"active-metadata:{RESOURCE_VERSION_REGISTERED}",
    )
    values: dict[str, Any] = {
        "event_id": event_id,
        "tenant_id": version.tenant_id,
        "resource_urn": version.resource_urn,
        "resource_version_id": version.resource_version_id,
        "version_key": version.version_key,
        "predecessor_version_id": version.predecessor_version_id,
        "content_sha256": version.content_sha256,
        "producer_subject": version.created_by,
        "consumer_subject": consumer_subject,
        "occurred_at": version.created_at,
    }
    return MetadataChangeEvent(
        **values,
        event_sha256=canonical_json_fingerprint(_event_stable(values)),
    )


class ActiveMetadataRegistration(_FrozenModel):
    registration_schema: Literal["gda.active_metadata_registration.v1"] = Field(
        default=REGISTRATION_SCHEMA,
        alias="schema",
    )
    resource_version: ResourceVersion
    event: MetadataChangeEvent

    @model_validator(mode="after")
    def _same_change(self) -> Self:
        expected = build_metadata_change_event(
            self.resource_version,
            consumer_subject=self.event.consumer_subject,
        )
        if self.event != expected:
            raise ValueError(
                "MetadataChangeEvent does not match its ResourceVersion"
            )
        return self


def build_active_metadata_registration(
    version: ResourceVersion,
    *,
    consumer_subject: str,
) -> ActiveMetadataRegistration:
    return ActiveMetadataRegistration(
        resource_version=version,
        event=build_metadata_change_event(
            version,
            consumer_subject=consumer_subject,
        ),
    )


class MetadataActivationIntent(_FrozenModel):
    intent_schema: Literal["gda.metadata_activation_intent.v1"] = Field(
        default=ACTIVATION_INTENT_SCHEMA,
        alias="schema",
    )
    event_id: UUID
    event_sha256: Sha256
    tenant_id: TenantId
    resource_urn: str
    resource_version_id: UUID
    content_sha256: Sha256
    route: Literal["metadata_fabric.projection_plan"] = METADATA_PROJECTION_ROUTE
    routed_by: WorkloadSubject
    provider_apply_authorized: Literal[False] = False
    provider_mutations_executed: Literal[False] = False
    production_ingestion_verified: Literal[False] = False
    intent_sha256: Sha256

    @model_validator(mode="after")
    def _content_bound(self) -> Self:
        stable = self.model_dump(
            mode="json",
            by_alias=True,
            exclude={"intent_sha256"},
        )
        if self.intent_sha256 != canonical_json_fingerprint(stable):
            raise ValueError("Metadata activation intent SHA-256 does not match")
        return self


def build_metadata_activation_intent(
    event: MetadataChangeEvent,
    *,
    routed_by: str,
) -> MetadataActivationIntent:
    if routed_by != event.consumer_subject:
        raise ActiveMetadataContractError(
            "activation router must match the event consumer"
        )
    values: dict[str, Any] = {
        "event_id": event.event_id,
        "event_sha256": event.event_sha256,
        "tenant_id": event.tenant_id,
        "resource_urn": event.resource_urn,
        "resource_version_id": event.resource_version_id,
        "content_sha256": event.content_sha256,
        "routed_by": routed_by,
    }
    stable = {
        "schema": ACTIVATION_INTENT_SCHEMA,
        "event_id": str(event.event_id),
        "event_sha256": event.event_sha256,
        "tenant_id": event.tenant_id,
        "resource_urn": event.resource_urn,
        "resource_version_id": str(event.resource_version_id),
        "content_sha256": event.content_sha256,
        "route": METADATA_PROJECTION_ROUTE,
        "routed_by": routed_by,
        "provider_apply_authorized": False,
        "provider_mutations_executed": False,
        "production_ingestion_verified": False,
    }
    return MetadataActivationIntent(
        **values,
        intent_sha256=canonical_json_fingerprint(stable),
    )


class MetadataChangeDelivery(_FrozenModel):
    delivery_schema: Literal["gda.metadata_change_delivery.v1"] = Field(
        default=DELIVERY_SCHEMA,
        alias="schema",
    )
    event: MetadataChangeEvent
    status: MetadataChangeDeliveryStatus = MetadataChangeDeliveryStatus.PENDING
    attempt_count: Annotated[int, Field(ge=0)] = 0
    max_attempts: Annotated[int, Field(ge=1, le=20)] = 5
    available_at: datetime
    claimed_by: str | None = None
    claimed_until: datetime | None = None
    last_error_code: ErrorCode | None = None
    activation_intent_sha256: Sha256 | None = None
    completed_at: datetime | None = None

    @field_validator("available_at", "claimed_until", "completed_at")
    @classmethod
    def _aware_delivery_time(cls, value: datetime | None) -> datetime | None:
        return _utc(value) if value is not None else None

    @model_validator(mode="after")
    def _consistent_state(self) -> Self:
        claimed = self.claimed_by is not None and self.claimed_until is not None
        if (self.claimed_by is None) != (self.claimed_until is None):
            raise ValueError("metadata change claim fields must be set together")
        if self.status == MetadataChangeDeliveryStatus.PENDING:
            if claimed or self.completed_at or self.activation_intent_sha256:
                raise ValueError("pending metadata change has invalid state")
        elif self.status == MetadataChangeDeliveryStatus.IN_FLIGHT:
            if not claimed or self.completed_at or self.activation_intent_sha256:
                raise ValueError("in-flight metadata change has invalid state")
        elif self.status == MetadataChangeDeliveryStatus.PROCESSED:
            if (
                claimed
                or self.completed_at is None
                or self.activation_intent_sha256 is None
                or self.last_error_code is not None
            ):
                raise ValueError("processed metadata change has invalid state")
        elif (
            claimed
            or self.completed_at is None
            or self.last_error_code is None
            or self.activation_intent_sha256 is not None
        ):
            raise ValueError("failed metadata change has invalid state")
        return self


def build_metadata_change_delivery(
    event: MetadataChangeEvent,
    *,
    max_attempts: int = 5,
) -> MetadataChangeDelivery:
    return MetadataChangeDelivery(
        event=event,
        max_attempts=max_attempts,
        available_at=event.occurred_at,
    )


def metadata_change_binding_payload(
    delivery: MetadataChangeDelivery,
) -> dict[str, Any]:
    return {
        "event": delivery.event.model_dump(mode="json", by_alias=True),
        "max_attempts": delivery.max_attempts,
    }

"""CloudEvents delivery contracts for immutable PlatformRun status events."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from .platform_contracts import (
    FrozenContract,
    NonEmptyText,
    PlatformRunEvent,
    RunStatus,
    TenantId,
)

PLATFORM_RUN_EVENT_CHANNEL = "gda.platform-runs.status"
PLATFORM_RUN_EVENT_TYPE = "gda.platform-run.status-changed.v1"
DEFAULT_PLATFORM_RUN_EVENT_DESTINATION = "cloudevents:platform-run-default"


class PlatformRunEventDeliveryStatus(StrEnum):
    PENDING = "pending"
    IN_FLIGHT = "in_flight"
    DONE = "done"
    FAILED = "failed"


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return value.astimezone(UTC)


class PlatformRunEventDelivery(FrozenContract):
    schema_id = "platform_run_event_delivery"

    tenant_id: TenantId
    delivery_id: UUID
    run_id: UUID
    run_event_id: UUID
    run_sequence_no: Annotated[int, Field(ge=0)]
    channel: Literal["gda.platform-runs.status"] = PLATFORM_RUN_EVENT_CHANNEL
    destination_ref: Literal["cloudevents:platform-run-default"] = (
        DEFAULT_PLATFORM_RUN_EVENT_DESTINATION
    )
    status: PlatformRunEventDeliveryStatus = PlatformRunEventDeliveryStatus.PENDING
    attempt_count: Annotated[int, Field(ge=0)] = 0
    max_attempts: Annotated[int, Field(ge=1, le=100)] = 10
    available_at: datetime
    claimed_by: NonEmptyText | None = None
    claimed_until: datetime | None = None
    last_error: NonEmptyText | None = None
    created_at: datetime
    completed_at: datetime | None = None

    @field_validator("available_at", "claimed_until", "created_at", "completed_at")
    @classmethod
    def _utc_delivery_time(cls, value: datetime | None) -> datetime | None:
        return _aware_utc(value) if value is not None else None

    @model_validator(mode="after")
    def _consistent_delivery(self) -> PlatformRunEventDelivery:
        claimed = self.claimed_by is not None and self.claimed_until is not None
        if (self.claimed_by is None) != (self.claimed_until is None):
            raise ValueError("delivery claim owner and expiry must be set together")
        if self.status == PlatformRunEventDeliveryStatus.PENDING:
            if claimed or self.completed_at is not None:
                raise ValueError("pending delivery cannot be claimed or completed")
        elif self.status == PlatformRunEventDeliveryStatus.IN_FLIGHT:
            if not claimed or self.completed_at is not None:
                raise ValueError("in-flight delivery requires an active claim")
        elif claimed or self.completed_at is None:
            raise ValueError("completed delivery must release its claim")
        return self


class PlatformRunStatusEventData(FrozenContract):
    schema_id = "platform_run_status_event_data"

    tenant_id: TenantId
    run_id: UUID
    status: RunStatus
    state_version: Annotated[int, Field(ge=0)]
    artifact_ids: tuple[UUID, ...] | None = None

    @field_validator("artifact_ids")
    @classmethod
    def _unique_artifacts(
        cls, value: tuple[UUID, ...] | None
    ) -> tuple[UUID, ...] | None:
        if value is not None and len(value) != len(set(value)):
            raise ValueError("artifact_ids must be unique")
        return value


class PlatformRunStatusCloudEvent(FrozenContract):
    schema_id = "platform_run_status_cloudevent"

    specversion: Literal["1.0"] = "1.0"
    id: UUID
    source: NonEmptyText
    type: Literal["gda.platform-run.status-changed.v1"] = PLATFORM_RUN_EVENT_TYPE
    subject: NonEmptyText
    time: datetime
    datacontenttype: Literal["application/json"] = "application/json"
    data: PlatformRunStatusEventData

    @field_validator("time")
    @classmethod
    def _utc_event_time(cls, value: datetime) -> datetime:
        return _aware_utc(value)


class PlatformRunEventEnvelope(FrozenContract):
    schema_id = "platform_run_event_envelope"

    delivery: PlatformRunEventDelivery
    event: PlatformRunEvent

    @model_validator(mode="after")
    def _consistent_binding(self) -> PlatformRunEventEnvelope:
        if self.delivery.tenant_id != self.event.tenant_id:
            raise ValueError("delivery and event tenants must match")
        if self.delivery.run_event_id != self.event.event_id:
            raise ValueError("delivery must bind the immutable run event")
        if self.delivery.run_id != self.event.run_id:
            raise ValueError("delivery and event runs must match")
        if self.delivery.run_sequence_no != self.event.sequence_no:
            raise ValueError("delivery sequence must match the run event")
        return self

    def to_cloudevent(self) -> PlatformRunStatusCloudEvent:
        tenant_id = self.event.tenant_id
        run_id = self.event.run_id
        return PlatformRunStatusCloudEvent(
            id=self.event.event_id,
            source=f"gda://{tenant_id}/service/platform-gateway",
            subject=f"gda://{tenant_id}/run/{run_id}",
            time=self.event.occurred_at,
            data=PlatformRunStatusEventData(
                tenant_id=tenant_id,
                run_id=run_id,
                status=self.event.to_status,
                state_version=self.event.sequence_no,
            ),
        )

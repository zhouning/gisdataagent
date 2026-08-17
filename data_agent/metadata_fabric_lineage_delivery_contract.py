"""Content-bound outbox contract for Metadata Fabric OpenLineage delivery."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
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

from .metadata_fabric_binding_contract import (
    MetadataFabricApplyPlan,
    MetadataFabricBindingRecord,
)
from .metadata_fabric_ingestion import (
    MetadataFabricIngestionPlan,
    OpenLineageRunEvent,
)
from .platform_contracts import (
    Sha256,
    TenantId,
    canonical_json_fingerprint,
)

DELIVERY_SCHEMA = "gda.metadata_fabric_openlineage_delivery.v1"
DEFAULT_TARGET_NAME = "local-openlineage-http-sink"

NonEmptyText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=512),
]
FailureCode = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        pattern=r"^[a-z0-9_]{1,64}$",
    ),
]


class LineageDeliveryStatus(StrEnum):
    PENDING = "pending"
    IN_FLIGHT = "in_flight"
    DELIVERED = "delivered"
    FAILED = "failed"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("delivery timestamps must include a timezone")
    return value.astimezone(UTC)


def openlineage_event_sha256(event: OpenLineageRunEvent) -> str:
    return canonical_json_fingerprint(event.model_dump(mode="json", by_alias=True))


def openlineage_delivery_id(
    binding_id: UUID,
    *,
    target_name: str,
    event_sha256: str,
) -> UUID:
    return uuid5(
        binding_id,
        f"openlineage:{target_name}:{event_sha256}",
    )


def openlineage_idempotency_key(
    *,
    tenant_id: str,
    binding_id: UUID,
    target_name: str,
    event_sha256: str,
) -> str:
    return canonical_json_fingerprint(
        {
            "tenant_id": tenant_id,
            "binding_id": str(binding_id),
            "target_name": target_name,
            "event_sha256": event_sha256,
        }
    )


def openlineage_receipt_sha256(
    delivery: MetadataFabricLineageDelivery,
    *,
    response_status: int,
    response_body_sha256: str,
) -> str:
    return canonical_json_fingerprint(
        {
            "tenant_id": delivery.tenant_id,
            "delivery_id": str(delivery.delivery_id),
            "binding_id": str(delivery.binding_id),
            "target_name": delivery.target_name,
            "event_sha256": delivery.event_sha256,
            "idempotency_key": delivery.idempotency_key,
            "response_status": response_status,
            "response_body_sha256": response_body_sha256,
        }
    )


class MetadataFabricLineageDelivery(_FrozenModel):
    delivery_schema: Literal["gda.metadata_fabric_openlineage_delivery.v1"] = Field(
        default=DELIVERY_SCHEMA, alias="schema"
    )
    tenant_id: TenantId
    delivery_id: UUID
    binding_id: UUID
    resource_version_id: UUID
    run_id: UUID
    source_plan_sha256: Sha256
    target_name: NonEmptyText
    event: OpenLineageRunEvent
    event_sha256: Sha256
    idempotency_key: Sha256
    actor_subject: NonEmptyText
    status: LineageDeliveryStatus = LineageDeliveryStatus.PENDING
    attempt_count: Annotated[int, Field(ge=0)] = 0
    max_attempts: Annotated[int, Field(ge=1, le=20)] = 3
    available_at: datetime
    claimed_by: NonEmptyText | None = None
    claimed_until: datetime | None = None
    last_error_code: FailureCode | None = None
    response_status: Annotated[int, Field(ge=100, le=599)] | None = None
    response_body_sha256: Sha256 | None = None
    receipt_sha256: Sha256 | None = None
    created_at: datetime
    completed_at: datetime | None = None

    @field_validator("available_at", "claimed_until", "created_at", "completed_at")
    @classmethod
    def _utc_timestamps(cls, value: datetime | None) -> datetime | None:
        return _aware_utc(value) if value is not None else None

    @model_validator(mode="after")
    def _content_bound_delivery(self) -> Self:
        if not self.actor_subject.startswith("workload:"):
            raise ValueError("lineage delivery actor must use workload identity")
        if self.event.run.run_id != self.run_id:
            raise ValueError("lineage delivery run does not match event")
        expected_event_sha = openlineage_event_sha256(self.event)
        if self.event_sha256 != expected_event_sha:
            raise ValueError("lineage delivery event SHA-256 does not match")
        expected_id = openlineage_delivery_id(
            self.binding_id,
            target_name=self.target_name,
            event_sha256=self.event_sha256,
        )
        if self.delivery_id != expected_id:
            raise ValueError("lineage delivery UUID does not match content")
        expected_key = openlineage_idempotency_key(
            tenant_id=self.tenant_id,
            binding_id=self.binding_id,
            target_name=self.target_name,
            event_sha256=self.event_sha256,
        )
        if self.idempotency_key != expected_key:
            raise ValueError("lineage delivery idempotency key does not match")

        claimed = self.claimed_by is not None and self.claimed_until is not None
        if (self.claimed_by is None) != (self.claimed_until is None):
            raise ValueError("delivery claim owner and expiry must be set together")
        if self.status == LineageDeliveryStatus.PENDING:
            if claimed or self.completed_at is not None:
                raise ValueError("pending delivery cannot be claimed or completed")
        elif self.status == LineageDeliveryStatus.IN_FLIGHT:
            if not claimed or self.completed_at is not None:
                raise ValueError("in-flight delivery requires an active claim")
        elif claimed or self.completed_at is None:
            raise ValueError("terminal delivery must release its claim")

        if self.status == LineageDeliveryStatus.DELIVERED:
            if (
                self.response_status is None
                or not 200 <= self.response_status < 300
                or self.response_body_sha256 is None
                or self.receipt_sha256 is None
                or self.last_error_code is not None
            ):
                raise ValueError("delivered lineage state is incomplete")
            expected_receipt = openlineage_receipt_sha256(
                self,
                response_status=self.response_status,
                response_body_sha256=self.response_body_sha256,
            )
            if self.receipt_sha256 != expected_receipt:
                raise ValueError("lineage delivery receipt SHA-256 does not match")
        elif self.receipt_sha256 is not None:
            raise ValueError("only delivered lineage may have a receipt")

        if self.response_body_sha256 is not None and self.response_status is None:
            raise ValueError("response body fingerprint requires HTTP status")
        if self.status == LineageDeliveryStatus.FAILED:
            if self.last_error_code is None:
                raise ValueError("failed lineage delivery requires an error code")
        return self


def validate_delivery_source(
    *,
    binding: MetadataFabricBindingRecord,
    source_plan: MetadataFabricIngestionPlan,
    apply_plan: MetadataFabricApplyPlan,
) -> None:
    expected_identity = (
        binding.tenant_id,
        binding.binding.resource_urn,
        binding.binding.resource_version_id,
        binding.binding.content_sha256,
    )
    observed_identity = (
        source_plan.tenant_id,
        source_plan.resource_urn,
        source_plan.resource_version_id,
        source_plan.content_sha256,
    )
    if observed_identity != expected_identity:
        raise ValueError("OpenLineage source plan does not match binding identity")
    if apply_plan.source_plan_sha256 != source_plan.plan_sha256:
        raise ValueError("authorized apply plan does not bind OpenLineage source plan")
    if (
        apply_plan.tenant_id != binding.tenant_id
        or apply_plan.resource_version_id != binding.binding.resource_version_id
        or apply_plan.run_id != source_plan.run_id
    ):
        raise ValueError("authorized apply plan does not match binding lineage")


def build_metadata_fabric_lineage_delivery(
    *,
    binding: MetadataFabricBindingRecord,
    source_plan: MetadataFabricIngestionPlan,
    apply_plan: MetadataFabricApplyPlan,
    actor_subject: str,
    created_at: datetime,
    target_name: str = DEFAULT_TARGET_NAME,
    max_attempts: int = 3,
) -> MetadataFabricLineageDelivery:
    validate_delivery_source(
        binding=binding,
        source_plan=source_plan,
        apply_plan=apply_plan,
    )
    created_at = _aware_utc(created_at)
    if created_at < binding.recorded_at:
        raise ValueError("lineage delivery cannot predate the binding")
    event = source_plan.openlineage_event
    event_sha = openlineage_event_sha256(event)
    delivery_id = openlineage_delivery_id(
        binding.binding_id,
        target_name=target_name,
        event_sha256=event_sha,
    )
    return MetadataFabricLineageDelivery(
        tenant_id=binding.tenant_id,
        delivery_id=delivery_id,
        binding_id=binding.binding_id,
        resource_version_id=binding.binding.resource_version_id,
        run_id=source_plan.run_id,
        source_plan_sha256=source_plan.plan_sha256,
        target_name=target_name,
        event=event,
        event_sha256=event_sha,
        idempotency_key=openlineage_idempotency_key(
            tenant_id=binding.tenant_id,
            binding_id=binding.binding_id,
            target_name=target_name,
            event_sha256=event_sha,
        ),
        actor_subject=actor_subject,
        max_attempts=max_attempts,
        available_at=created_at,
        created_at=created_at,
    )


def delivery_binding_payload(
    delivery: MetadataFabricLineageDelivery,
) -> dict[str, Any]:
    """Return immutable identity fields, excluding mutable delivery state."""
    return delivery.model_dump(
        mode="json",
        by_alias=True,
        exclude={
            "status",
            "attempt_count",
            "available_at",
            "claimed_by",
            "claimed_until",
            "last_error_code",
            "response_status",
            "response_body_sha256",
            "receipt_sha256",
            "created_at",
            "completed_at",
        },
    )

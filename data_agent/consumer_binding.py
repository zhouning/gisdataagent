"""Immutable, tenant-scoped consumer contracts for DataProduct versions."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .gis_service_consumer_binding_migration import (
    GISServiceConsumerBindingMigrationImpact,
)
from .platform_contracts import TenantId, canonical_json_fingerprint

_PRODUCT_URN_RE = re.compile(
    r"^gda://[a-z0-9][a-z0-9._-]{0,63}/data_product/[a-z0-9][a-z0-9._-]{0,127}$"
)
_VERSION_KEY_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
_SUBJECT_REF_RE = re.compile(r"^(human|workload|agent|service):[^\s]{1,511}$")
_NOTIFICATION_STATE_NAMESPACE = UUID("64c8e4a5-4885-4f61-b2ca-d19956c5c307")


class ConsumerCompatibilityConclusion(StrEnum):
    """Consumer-specific conclusion for one product version transition."""

    BACKWARD_COMPATIBLE = "backward_compatible"
    BREAKING = "breaking"
    INDETERMINATE = "indeterminate"


class ConsumerNotificationStatus(StrEnum):
    """Delivery conclusion recorded by the governed notification path."""

    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    DELIVERED = "delivered"
    FAILED = "failed"


class ConsumerMigrationNotificationChannel(StrEnum):
    """Server-owned provider channel for one migration notice."""

    ALERTMANAGER = "alertmanager"


class ConsumerMigrationNotificationDeliveryStatus(StrEnum):
    """Durable delivery state owned by the notification outbox."""

    PENDING = "pending"
    IN_FLIGHT = "in_flight"
    DONE = "done"
    FAILED = "failed"
    SUPERSEDED = "superseded"


class ConsumerNotificationReceiptEvidence(BaseModel):
    """Exact terminal outbox receipt referenced by migration state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    notification_id: UUID
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ConsumerAcknowledgement(BaseModel):
    """Content-bound acknowledgement made by the bound consumer."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    consumer_ref: str = Field(min_length=1, max_length=512)
    acknowledgement_ref: str = Field(min_length=1, max_length=512)
    evidence: dict[str, Any]
    acknowledged_at: datetime

    @field_validator("consumer_ref")
    @classmethod
    def _valid_consumer_ref(cls, value: str) -> str:
        value = value.strip()
        if not _SUBJECT_REF_RE.fullmatch(value):
            raise ValueError("consumer_ref must use a typed subject reference")
        return value

    @field_validator("acknowledged_at")
    @classmethod
    def _aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("acknowledged_at must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _complete_evidence(self) -> ConsumerAcknowledgement:
        if not self.evidence:
            raise ValueError("consumer acknowledgement evidence is required")
        return self


class ConsumerBinding(BaseModel):
    """A durable permission and compatibility contract for one product consumer."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: TenantId
    binding_id: UUID
    product_urn: str
    consumer_ref: str = Field(min_length=1, max_length=512)
    purpose: str = Field(min_length=1, max_length=256)
    scope: dict[str, Any]
    min_product_version: str | None = None
    max_product_version: str | None = None
    credential_ref: str = Field(min_length=1, max_length=512)
    quota: dict[str, Any]
    expires_at: datetime
    compatibility_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    compatibility_evidence: dict[str, Any]
    created_by: str = Field(min_length=1, max_length=512)
    created_at: datetime
    binding_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("product_urn")
    @classmethod
    def _valid_product_urn(cls, value: str) -> str:
        if not _PRODUCT_URN_RE.fullmatch(value):
            raise ValueError("product_urn must reference a DataProduct")
        return value

    @field_validator("consumer_ref")
    @classmethod
    def _valid_consumer_ref(cls, value: str) -> str:
        value = value.strip()
        if not _SUBJECT_REF_RE.fullmatch(value):
            raise ValueError("consumer_ref must use a typed subject reference")
        return value

    @field_validator("created_at", "expires_at")
    @classmethod
    def _aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamps must include a timezone")
        return value.astimezone(UTC)

    @field_validator("min_product_version", "max_product_version")
    @classmethod
    def _valid_version_key(cls, value: str | None) -> str | None:
        if value is not None and _VERSION_KEY_RE.fullmatch(value) is None:
            raise ValueError("product version bounds must use vMAJOR.MINOR.PATCH")
        return value

    @model_validator(mode="after")
    def _consistent_binding(self) -> ConsumerBinding:
        if self.product_urn.split("/")[2] != self.tenant_id:
            raise ValueError("product_urn tenant must match tenant_id")
        if self.expires_at <= self.created_at:
            raise ValueError("expires_at must be after created_at")
        if not self.scope:
            raise ValueError("scope must contain at least one governed value")
        if not self.compatibility_evidence:
            raise ValueError("compatibility_evidence is required")
        max_packages = self.quota.get("max_packages")
        if not isinstance(max_packages, int) or isinstance(max_packages, bool):
            raise ValueError("quota.max_packages must be an integer")
        if not 1 <= max_packages <= 100:
            raise ValueError("quota.max_packages must be between 1 and 100")
        max_bytes = self.quota.get("max_bytes")
        if max_bytes is not None and (
            not isinstance(max_bytes, int)
            or isinstance(max_bytes, bool)
            or max_bytes < 0
        ):
            raise ValueError("quota.max_bytes must be a non-negative integer")
        if self.min_product_version and self.max_product_version:
            if _version_tuple(self.min_product_version) > _version_tuple(
                self.max_product_version
            ):
                raise ValueError("min_product_version must not exceed max_product_version")
        expected = consumer_binding_fingerprint(self)
        if self.binding_sha256 != expected:
            raise ValueError("binding_sha256 does not match the contract")
        return self


class ConsumerBindingMigrationState(BaseModel):
    """Append-only state for one consumer and one product version transition."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: TenantId
    migration_state_id: UUID
    binding_id: UUID
    product_urn: str
    from_product_version_id: UUID
    to_product_version_id: UUID
    state_version: int = Field(ge=1)
    compatibility_conclusion: ConsumerCompatibilityConclusion
    compatibility_evidence: dict[str, Any]
    notification_status: ConsumerNotificationStatus
    notification_evidence: dict[str, Any]
    migration_deadline: datetime | None = None
    consumer_acknowledgement: ConsumerAcknowledgement | None = None
    previous_state_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    recorded_by: str = Field(min_length=1, max_length=512)
    recorded_at: datetime
    state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("product_urn")
    @classmethod
    def _valid_product_urn(cls, value: str) -> str:
        if not _PRODUCT_URN_RE.fullmatch(value):
            raise ValueError("product_urn must reference a DataProduct")
        return value

    @field_validator("recorded_by")
    @classmethod
    def _valid_actor_ref(cls, value: str) -> str:
        value = value.strip()
        if not _SUBJECT_REF_RE.fullmatch(value):
            raise ValueError("recorded_by must use a typed subject reference")
        return value

    @field_validator("recorded_at", "migration_deadline")
    @classmethod
    def _aware_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamps must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _consistent_state(self) -> ConsumerBindingMigrationState:
        if self.product_urn.split("/")[2] != self.tenant_id:
            raise ValueError("product_urn tenant must match tenant_id")
        if self.from_product_version_id == self.to_product_version_id:
            raise ValueError("migration state must bind different product versions")
        if not self.compatibility_evidence:
            raise ValueError("compatibility_evidence is required")
        if self.state_version == 1 and self.previous_state_sha256 is not None:
            raise ValueError("initial state must not name a previous state")
        if self.state_version > 1 and self.previous_state_sha256 is None:
            raise ValueError("successor state must name the previous state")
        if self.notification_status in {
            ConsumerNotificationStatus.DELIVERED,
            ConsumerNotificationStatus.FAILED,
        } and not self.notification_evidence:
            raise ValueError("terminal notification status requires evidence")
        if self.notification_status in {
            ConsumerNotificationStatus.DELIVERED,
            ConsumerNotificationStatus.FAILED,
        }:
            receipt = ConsumerNotificationReceiptEvidence.model_validate(
                self.notification_evidence
            )
            if receipt.model_dump(mode="json") != self.notification_evidence:
                raise ValueError(
                    "terminal notification evidence must contain only the outbox receipt"
                )
        if self.notification_status in {
            ConsumerNotificationStatus.NOT_REQUIRED,
            ConsumerNotificationStatus.PENDING,
        } and self.notification_evidence:
            raise ValueError("non-terminal notification must not carry evidence")
        if (
            self.compatibility_conclusion
            is ConsumerCompatibilityConclusion.BACKWARD_COMPATIBLE
        ):
            if (
                self.notification_status
                is not ConsumerNotificationStatus.NOT_REQUIRED
            ):
                raise ValueError(
                    "backward-compatible transition does not require notification"
                )
            if (
                self.migration_deadline is not None
                or self.consumer_acknowledgement is not None
            ):
                raise ValueError("backward-compatible transition does not require migration")
        elif self.compatibility_conclusion is ConsumerCompatibilityConclusion.BREAKING:
            if self.migration_deadline is None:
                raise ValueError("breaking transition requires a migration_deadline")
            if self.notification_status is ConsumerNotificationStatus.NOT_REQUIRED:
                raise ValueError("breaking transition requires consumer notification")
        elif self.consumer_acknowledgement is not None:
            raise ValueError("indeterminate transition cannot be acknowledged")
        if self.consumer_acknowledgement is not None:
            if self.notification_status is not ConsumerNotificationStatus.DELIVERED:
                raise ValueError("consumer acknowledgement requires delivered notification")
            if self.consumer_acknowledgement.acknowledged_at > self.recorded_at:
                raise ValueError("consumer acknowledgement cannot postdate the state")
        expected = consumer_binding_migration_state_fingerprint(self)
        if self.state_sha256 != expected:
            raise ValueError("state_sha256 does not match the migration state")
        return self


class ConsumerBindingMigrationNotification(BaseModel):
    """Durable provider delivery for one ConsumerBinding migration state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: TenantId
    notification_id: UUID
    migration_state_id: UUID
    binding_id: UUID
    product_urn: str
    from_product_version_id: UUID
    to_product_version_id: UUID
    source_state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    channel: ConsumerMigrationNotificationChannel
    destination_ref: str = Field(min_length=1, max_length=128)
    status: ConsumerMigrationNotificationDeliveryStatus
    attempt_count: int = Field(ge=0)
    max_attempts: int = Field(ge=1, le=100)
    available_at: datetime
    claimed_by: str | None = Field(default=None, min_length=1, max_length=512)
    claimed_until: datetime | None = None
    last_error: str | None = Field(default=None, min_length=1, max_length=512)
    provider_receipt: dict[str, Any]
    receipt_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    terminal_worker_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=512,
    )
    created_at: datetime
    completed_at: datetime | None = None

    @field_validator("product_urn")
    @classmethod
    def _valid_notification_product_urn(cls, value: str) -> str:
        if not _PRODUCT_URN_RE.fullmatch(value):
            raise ValueError("product_urn must reference a DataProduct")
        return value

    @field_validator(
        "available_at", "claimed_until", "created_at", "completed_at"
    )
    @classmethod
    def _aware_delivery_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("notification timestamps must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _consistent_notification(self) -> ConsumerBindingMigrationNotification:
        if self.product_urn.split("/")[2] != self.tenant_id:
            raise ValueError("notification product tenant must match tenant_id")
        if self.from_product_version_id == self.to_product_version_id:
            raise ValueError("notification must bind different product versions")
        if not self.destination_ref.startswith(f"{self.channel.value}:"):
            raise ValueError("notification destination must match its channel")
        if (self.claimed_by is None) != (self.claimed_until is None):
            raise ValueError("notification claim owner and expiry must be set together")
        claimed = self.claimed_by is not None
        terminal = self.status in {
            ConsumerMigrationNotificationDeliveryStatus.DONE,
            ConsumerMigrationNotificationDeliveryStatus.FAILED,
            ConsumerMigrationNotificationDeliveryStatus.SUPERSEDED,
        }
        if self.status is ConsumerMigrationNotificationDeliveryStatus.PENDING:
            if claimed or self.completed_at is not None:
                raise ValueError("pending notification cannot be claimed or completed")
        elif self.status is ConsumerMigrationNotificationDeliveryStatus.IN_FLIGHT:
            if not claimed or self.completed_at is not None:
                raise ValueError("in-flight notification requires an active claim")
        elif claimed or not terminal or self.completed_at is None:
            raise ValueError("terminal notification must release its claim")
        if self.status is ConsumerMigrationNotificationDeliveryStatus.DONE:
            if (
                not self.provider_receipt
                or self.receipt_sha256 is None
                or self.terminal_worker_id is None
                or self.last_error is not None
            ):
                raise ValueError("delivered notification requires a provider receipt")
        elif self.status is ConsumerMigrationNotificationDeliveryStatus.FAILED:
            if (
                self.provider_receipt
                or self.receipt_sha256 is None
                or self.terminal_worker_id is None
                or self.last_error is None
            ):
                raise ValueError("failed notification requires terminal failure evidence")
        elif self.status is ConsumerMigrationNotificationDeliveryStatus.SUPERSEDED:
            if (
                self.provider_receipt
                or self.receipt_sha256 is not None
                or self.terminal_worker_id is not None
                or self.last_error is None
            ):
                raise ValueError("superseded notification must not manufacture a receipt")
        elif (
            self.provider_receipt
            or self.receipt_sha256 is not None
            or self.terminal_worker_id is not None
        ):
            raise ValueError("non-terminal notification must not carry receipt evidence")
        return self


class ConsumerBindingMigrationNotificationEnvelope(BaseModel):
    """Provider payload with its immutable binding and source migration state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    notification: ConsumerBindingMigrationNotification
    binding: ConsumerBinding
    migration_state: ConsumerBindingMigrationState
    gis_service_impacts: tuple[GISServiceConsumerBindingMigrationImpact, ...] = ()

    @model_validator(mode="after")
    def _consistent_envelope(self) -> ConsumerBindingMigrationNotificationEnvelope:
        notification = self.notification
        if len(
            {
                notification.tenant_id,
                self.binding.tenant_id,
                self.migration_state.tenant_id,
            }
        ) != 1:
            raise ValueError("notification envelope tenants must match")
        if notification.binding_id != self.binding.binding_id:
            raise ValueError("notification must bind its ConsumerBinding")
        if notification.migration_state_id != self.migration_state.migration_state_id:
            raise ValueError("notification must bind its source migration state")
        if notification.product_urn != self.migration_state.product_urn:
            raise ValueError("notification product must match its migration state")
        if (
            notification.from_product_version_id
            != self.migration_state.from_product_version_id
            or notification.to_product_version_id
            != self.migration_state.to_product_version_id
        ):
            raise ValueError("notification version transition must match its source state")
        if notification.source_state_sha256 != self.migration_state.state_sha256:
            raise ValueError("notification source fingerprint must match its source state")
        impact_ids: set[UUID] = set()
        for impact in self.gis_service_impacts:
            if impact.impact_id in impact_ids:
                raise ValueError("notification envelope must not repeat a GIS impact")
            impact_ids.add(impact.impact_id)
            if (
                impact.tenant_id != notification.tenant_id
                or impact.consumer_ref != self.binding.consumer_ref
            ):
                raise ValueError("GIS service impact does not bind its notification consumer")
            if (
                impact.migration_state_id != notification.migration_state_id
                or impact.notification_id != notification.notification_id
                or impact.source_product_urn != self.migration_state.product_urn
                or impact.from_product_version_id != self.migration_state.from_product_version_id
                or impact.to_product_version_id != self.migration_state.to_product_version_id
            ):
                raise ValueError("GIS service impact does not bind its migration notice")
        return self


class ConsumerBindingMigrationNotificationSettlement(BaseModel):
    """Atomic outbox terminal receipt and resulting CAS migration state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    notification: ConsumerBindingMigrationNotification
    migration_state: ConsumerBindingMigrationState | None = None

    @model_validator(mode="after")
    def _consistent_settlement(self) -> ConsumerBindingMigrationNotificationSettlement:
        if self.notification.status in {
            ConsumerMigrationNotificationDeliveryStatus.DONE,
            ConsumerMigrationNotificationDeliveryStatus.FAILED,
        }:
            if self.migration_state is None:
                raise ValueError("terminal receipt requires a migration state")
            expected_status = (
                ConsumerNotificationStatus.DELIVERED
                if self.notification.status
                is ConsumerMigrationNotificationDeliveryStatus.DONE
                else ConsumerNotificationStatus.FAILED
            )
            if self.migration_state.notification_status is not expected_status:
                raise ValueError("terminal receipt and migration status must match")
        elif self.migration_state is not None:
            raise ValueError("non-terminal delivery must not append migration state")
        return self


def _version_tuple(value: str) -> tuple[int, int, int]:
    match = _VERSION_KEY_RE.fullmatch(value)
    if match is None:
        raise ValueError("invalid product version")
    return tuple(int(part) for part in match.groups())


def _canonical(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _canonical(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    return value


def consumer_binding_fingerprint(binding: ConsumerBinding | dict[str, Any]) -> str:
    """Fingerprint every immutable field except the fingerprint itself."""
    if isinstance(binding, BaseModel):
        payload = binding.model_dump(mode="python", exclude={"binding_sha256"})
    else:
        payload = {key: value for key, value in binding.items() if key != "binding_sha256"}
    return canonical_json_fingerprint(_canonical(payload))


def consumer_binding_migration_state_fingerprint(
    state: ConsumerBindingMigrationState | dict[str, Any],
) -> str:
    """Fingerprint one immutable consumer migration state snapshot."""
    if isinstance(state, BaseModel):
        payload = state.model_dump(mode="python", exclude={"state_sha256"})
    else:
        payload = {key: value for key, value in state.items() if key != "state_sha256"}
    return canonical_json_fingerprint(_canonical(payload))


def build_consumer_binding_notification_terminal_state(
    notification: ConsumerBindingMigrationNotification,
    source_state: ConsumerBindingMigrationState,
    *,
    recorded_by: str,
) -> ConsumerBindingMigrationState:
    """Build the deterministic CAS successor for one terminal outbox receipt."""
    if notification.status not in {
        ConsumerMigrationNotificationDeliveryStatus.DONE,
        ConsumerMigrationNotificationDeliveryStatus.FAILED,
    }:
        raise ValueError("notification must be delivered or terminally failed")
    if notification.completed_at is None or notification.receipt_sha256 is None:
        raise ValueError("terminal notification receipt is incomplete")
    if notification.migration_state_id != source_state.migration_state_id:
        raise ValueError("notification does not bind the source migration state")
    if notification.source_state_sha256 != source_state.state_sha256:
        raise ValueError("notification source fingerprint is mismatched")
    status = (
        ConsumerNotificationStatus.DELIVERED
        if notification.status is ConsumerMigrationNotificationDeliveryStatus.DONE
        else ConsumerNotificationStatus.FAILED
    )
    evidence = ConsumerNotificationReceiptEvidence(
        notification_id=notification.notification_id,
        receipt_sha256=notification.receipt_sha256,
    ).model_dump(mode="json")
    identity = ":".join(
        (
            notification.tenant_id,
            str(notification.notification_id),
            notification.status.value,
            notification.receipt_sha256,
        )
    )
    payload: dict[str, Any] = {
        "tenant_id": source_state.tenant_id,
        "migration_state_id": uuid5(_NOTIFICATION_STATE_NAMESPACE, identity),
        "binding_id": source_state.binding_id,
        "product_urn": source_state.product_urn,
        "from_product_version_id": source_state.from_product_version_id,
        "to_product_version_id": source_state.to_product_version_id,
        "state_version": source_state.state_version + 1,
        "compatibility_conclusion": source_state.compatibility_conclusion,
        "compatibility_evidence": source_state.compatibility_evidence,
        "notification_status": status,
        "notification_evidence": evidence,
        "migration_deadline": source_state.migration_deadline,
        "consumer_acknowledgement": None,
        "previous_state_sha256": source_state.state_sha256,
        "recorded_by": recorded_by,
        "recorded_at": notification.completed_at,
    }
    payload["state_sha256"] = consumer_binding_migration_state_fingerprint(payload)
    return ConsumerBindingMigrationState.model_validate(payload)

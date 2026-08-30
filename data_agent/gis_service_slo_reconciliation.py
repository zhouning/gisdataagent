"""Contracts for automatic GIS ServiceSLO activation reconciliation."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .platform_contracts import TenantId

GIS_SERVICE_SLO_RECONCILIATION_WORKLOAD = "workload:gis-slo-binding-controller"
_SERVICE_URN_RE = re.compile(
    r"^gda://[a-z0-9][a-z0-9._-]{0,63}/gis_service/[a-z0-9][a-z0-9._-]{0,127}$"
)


class GISServiceSLOReconciliationStatus(StrEnum):
    PENDING = "pending"
    IN_FLIGHT = "in_flight"
    DONE = "done"
    FAILED = "failed"
    SUPERSEDED = "superseded"


class GISServiceSLOReconciliationTask(BaseModel):
    """One lease-controlled projection request for an exact SLO activation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: TenantId
    task_id: UUID
    service_urn: str
    slo_definition_ref: str
    active_version_ref: str
    definition_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    approval_case_ref: str
    activation_version: int = Field(ge=1)
    status: GISServiceSLOReconciliationStatus
    attempt_count: int = Field(ge=0)
    max_attempts: int = Field(ge=1, le=100)
    available_at: datetime
    claimed_by: str | None = None
    claimed_until: datetime | None = None
    binding_id: UUID | None = None
    last_error: str | None = None
    created_at: datetime
    completed_at: datetime | None = None

    @field_validator("available_at", "claimed_until", "created_at", "completed_at")
    @classmethod
    def _utc_time(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("reconciliation timestamps must include a timezone")
        return value.astimezone(UTC)

    @field_validator("service_urn")
    @classmethod
    def _valid_service_urn(cls, value: str) -> str:
        if _SERVICE_URN_RE.fullmatch(value) is None:
            raise ValueError("reconciliation service_urn is invalid")
        return value

    @model_validator(mode="after")
    def _consistent_task(self) -> GISServiceSLOReconciliationTask:
        if self.service_urn.split("/")[2] != self.tenant_id:
            raise ValueError("reconciliation service tenant must match tenant_id")
        if not self.active_version_ref.startswith(f"{self.slo_definition_ref}.v"):
            raise ValueError("reconciliation version must bind its definition")
        claimed = self.claimed_by is not None and self.claimed_until is not None
        if (self.claimed_by is None) != (self.claimed_until is None):
            raise ValueError("reconciliation claim owner and expiry must be paired")
        if self.status in {
            GISServiceSLOReconciliationStatus.PENDING,
            GISServiceSLOReconciliationStatus.IN_FLIGHT,
        }:
            if self.completed_at is not None or self.binding_id is not None:
                raise ValueError("open reconciliation task cannot retain completion evidence")
            if self.status is GISServiceSLOReconciliationStatus.PENDING and claimed:
                raise ValueError("pending reconciliation task cannot be claimed")
            if self.status is GISServiceSLOReconciliationStatus.IN_FLIGHT and not claimed:
                raise ValueError("in-flight reconciliation task requires a claim")
        elif self.status is GISServiceSLOReconciliationStatus.DONE:
            if claimed or self.completed_at is None or self.binding_id is None:
                raise ValueError("done reconciliation requires binding evidence")
        elif claimed or self.completed_at is None or self.binding_id is not None:
            raise ValueError("terminal failed reconciliation has invalid evidence")
        if self.status in {
            GISServiceSLOReconciliationStatus.FAILED,
            GISServiceSLOReconciliationStatus.SUPERSEDED,
        } and not self.last_error:
            raise ValueError("terminal reconciliation requires a bounded error")
        return self


__all__ = [
    "GIS_SERVICE_SLO_RECONCILIATION_WORKLOAD",
    "GISServiceSLOReconciliationStatus",
    "GISServiceSLOReconciliationTask",
]

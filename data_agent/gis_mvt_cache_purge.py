"""Contracts for durable cleanup of retired GIS MVT cache generations."""

from __future__ import annotations

import inspect
import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .gis_mvt_response_cache import (
    MVT_CACHE_NAMESPACE_SCHEMA,
    MVTCachePurgeResult,
    MVTResponseCache,
    mvt_response_cache_namespace,
)
from .platform_contracts import TenantId

GIS_MVT_CACHE_PURGE_WORKLOAD = "workload:gis-mvt-cache-purge-controller"
_SERVICE_URN_RE = re.compile(
    r"^gda://[a-z0-9][a-z0-9._-]{0,63}/gis_service/[a-z0-9][a-z0-9._-]{0,127}$"
)


class GISMVTCachePurgeSource(StrEnum):
    CUTOVER = "cutover"
    ROLLBACK = "rollback"


class GISMVTCachePurgeStatus(StrEnum):
    PENDING = "pending"
    IN_FLIGHT = "in_flight"
    DONE = "done"
    FAILED = "failed"
    BYPASSED = "bypassed"


@runtime_checkable
class GISMVTCachePurgeProvider(Protocol):
    """Provider-neutral execution boundary for one retired cache generation."""

    provider_kind: str
    enabled: bool

    async def purge_generation(
        self,
        generation_token: str,
        *,
        max_keys: int,
        scan_count: int,
    ) -> MVTCachePurgeResult: ...

    async def aclose(self) -> None: ...


class MVTResponseCachePurgeProvider:
    """Adapt the current response-cache projection to the purge contract."""

    provider_kind = "mvt_response_cache"

    def __init__(self, cache: MVTResponseCache) -> None:
        self.cache = cache

    @property
    def enabled(self) -> bool:
        return self.cache.enabled

    async def purge_generation(
        self,
        generation_token: str,
        *,
        max_keys: int,
        scan_count: int,
    ) -> MVTCachePurgeResult:
        return await self.cache.purge_namespace(
            generation_token,
            max_keys=max_keys,
            scan_count=scan_count,
        )

    async def aclose(self) -> None:
        close = getattr(self.cache, "aclose", None)
        if close is None:
            return
        result = close()
        if inspect.isawaitable(result):
            await result


class GISMVTCachePurgeTask(BaseModel):
    """One lease-controlled purge decision derived from a transition receipt."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: TenantId
    purge_task_id: UUID
    source_kind: GISMVTCachePurgeSource
    source_receipt_id: UUID
    source_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    service_urn: str
    endpoint_revision_id: UUID
    service_definition_version_id: UUID
    service_release_binding_id: UUID
    endpoint_state_version: int = Field(ge=0)
    cache_namespace: str | None = None
    cache_context: dict[str, Any] | None = None
    generation_token: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    status: GISMVTCachePurgeStatus
    bypass_reason: str | None = None
    attempt_count: int = Field(ge=0)
    max_attempts: int = Field(ge=1, le=100)
    available_at: datetime
    claimed_by: str | None = None
    claimed_until: datetime | None = None
    last_error: str | None = None
    matched_keys: int | None = Field(default=None, ge=0)
    deleted_keys: int | None = Field(default=None, ge=0)
    remaining_keys: int | None = Field(default=None, ge=0)
    created_at: datetime
    completed_at: datetime | None = None

    @field_validator("available_at", "claimed_until", "created_at", "completed_at")
    @classmethod
    def _utc_time(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("cache purge timestamps must include a timezone")
        return value.astimezone(UTC)

    @field_validator("service_urn")
    @classmethod
    def _valid_service_urn(cls, value: str) -> str:
        if _SERVICE_URN_RE.fullmatch(value) is None:
            raise ValueError("cache purge service_urn is invalid")
        return value

    @model_validator(mode="after")
    def _consistent_task(self) -> GISMVTCachePurgeTask:
        if self.service_urn.split("/")[2] != self.tenant_id:
            raise ValueError("cache purge service tenant must match tenant_id")
        claimed = self.claimed_by is not None and self.claimed_until is not None
        if (self.claimed_by is None) != (self.claimed_until is None):
            raise ValueError("cache purge claim owner and expiry must be paired")
        if self.status == GISMVTCachePurgeStatus.BYPASSED:
            if (
                self.cache_namespace is not None
                or self.cache_context is not None
                or self.generation_token is not None
                or not self.bypass_reason
                or claimed
                or self.completed_at is None
            ):
                raise ValueError("bypassed cache purge must retain only its reason")
            return self
        if (
            self.cache_namespace is None
            or self.cache_context is None
            or self.generation_token is None
            or self.bypass_reason is not None
        ):
            raise ValueError("executable cache purge requires its immutable context")
        if self.cache_context.get("namespace") != self.cache_namespace:
            raise ValueError("cache purge namespace does not match its context")
        if self.cache_context.get("schema") != MVT_CACHE_NAMESPACE_SCHEMA:
            raise ValueError("cache purge context schema is invalid")
        identity_fields = {
            "tenant_id": self.tenant_id,
            "service_urn": self.service_urn,
            "service_release_binding_id": str(self.service_release_binding_id),
            "endpoint_revision_id": str(self.endpoint_revision_id),
            "endpoint_state_version": self.endpoint_state_version,
        }
        if any(
            self.cache_context.get(field) != expected
            for field, expected in identity_fields.items()
        ):
            raise ValueError("cache purge task identity does not match its context")
        if mvt_response_cache_namespace(self.cache_context) != self.generation_token:
            raise ValueError("cache purge generation does not match its context")
        if self.status == GISMVTCachePurgeStatus.PENDING:
            valid_delivery = not claimed and self.completed_at is None
        elif self.status == GISMVTCachePurgeStatus.IN_FLIGHT:
            valid_delivery = claimed and self.completed_at is None
        else:
            valid_delivery = not claimed and self.completed_at is not None
        if not valid_delivery:
            raise ValueError("cache purge delivery state is inconsistent")
        if self.status == GISMVTCachePurgeStatus.DONE:
            if (
                self.matched_keys is None
                or self.deleted_keys is None
                or self.remaining_keys != 0
                or self.deleted_keys > self.matched_keys
            ):
                raise ValueError("completed cache purge requires a zero-residue result")
        elif any(
            value is not None
            for value in (self.matched_keys, self.deleted_keys, self.remaining_keys)
        ):
            raise ValueError("only completed cache purges may retain result counts")
        if self.status == GISMVTCachePurgeStatus.FAILED and not self.last_error:
            raise ValueError("failed cache purge requires a bounded error")
        return self


__all__ = [
    "GIS_MVT_CACHE_PURGE_WORKLOAD",
    "GISMVTCachePurgeProvider",
    "GISMVTCachePurgeSource",
    "GISMVTCachePurgeStatus",
    "GISMVTCachePurgeTask",
    "MVTResponseCachePurgeProvider",
]

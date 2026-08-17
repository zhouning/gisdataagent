"""Strict local HTTP emitter for claimed Metadata Fabric OpenLineage events."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Annotated, Self
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from .metadata_fabric_lineage_delivery_contract import (
    LineageDeliveryStatus,
    MetadataFabricLineageDelivery,
)
from .platform_contracts import canonical_json_bytes
from .platform_gateway import PlatformGateway

NonEmptyText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=512),
]


class LineageEmitterProfile(BaseModel):
    """Local-only endpoint profile; credentials and redirects are unsupported."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    target_name: NonEmptyText
    endpoint_url: NonEmptyText
    actor_subject: NonEmptyText
    timeout_seconds: Annotated[float, Field(gt=0, le=30)] = 5.0

    @model_validator(mode="after")
    def _bounded_local_endpoint(self) -> Self:
        parsed = urlsplit(self.endpoint_url)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "localhost"}
            or parsed.path != "/api/v1/lineage"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("local OpenLineage endpoint must be loopback /api/v1/lineage")
        if not self.actor_subject.startswith("workload:"):
            raise ValueError("lineage emitter must use workload identity")
        return self


class LineageHttpDeliveryError(RuntimeError):
    def __init__(
        self,
        code: str,
        *,
        retryable: bool,
        response_status: int | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable
        self.response_status = response_status


@dataclass(frozen=True)
class LineageHttpReceipt:
    response_status: int
    response_body_sha256: str


@dataclass(frozen=True)
class LineageDeliveryBatchResult:
    claimed: int
    delivered: int
    retry_pending: int
    failed: int
    delivery_ids: tuple[UUID, ...]


class OpenLineageHttpEmitter:
    def __init__(
        self,
        profile: LineageEmitterProfile,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.profile = profile
        self._client = httpx.Client(
            timeout=profile.timeout_seconds,
            follow_redirects=False,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> OpenLineageHttpEmitter:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def emit(self, delivery: MetadataFabricLineageDelivery) -> LineageHttpReceipt:
        if delivery.status != LineageDeliveryStatus.IN_FLIGHT or delivery.claimed_by is None:
            raise LineageHttpDeliveryError(
                "delivery_not_claimed",
                retryable=False,
            )
        if (
            delivery.target_name != self.profile.target_name
            or delivery.actor_subject != self.profile.actor_subject
        ):
            raise LineageHttpDeliveryError(
                "emitter_profile_mismatch",
                retryable=False,
            )
        body = canonical_json_bytes(delivery.event.model_dump(mode="json", by_alias=True))
        try:
            response = self._client.post(
                self.profile.endpoint_url,
                content=body,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "Idempotency-Key": delivery.idempotency_key,
                    "X-GDA-Delivery-ID": str(delivery.delivery_id),
                    "X-GDA-Event-SHA256": delivery.event_sha256,
                },
            )
        except httpx.TransportError:
            raise LineageHttpDeliveryError(
                "transport_error",
                retryable=True,
            ) from None
        status = response.status_code
        if 200 <= status < 300:
            return LineageHttpReceipt(
                response_status=status,
                response_body_sha256=hashlib.sha256(response.content).hexdigest(),
            )
        if status == 429:
            code = "http_429"
            retryable = True
        elif 500 <= status < 600:
            code = "http_5xx"
            retryable = True
        else:
            code = "http_4xx"
            retryable = False
        raise LineageHttpDeliveryError(
            code,
            retryable=retryable,
            response_status=status,
        )


class MetadataFabricLineageConsumer:
    """Deliver claimed events at least once; receiver idempotency handles replay."""

    def __init__(
        self,
        emitter: OpenLineageHttpEmitter,
        *,
        gateway: PlatformGateway,
        retry_delay_seconds: int = 5,
    ) -> None:
        if not 0 <= retry_delay_seconds <= 86400:
            raise ValueError("lineage retry delay must be between 0 and 86400")
        self.emitter = emitter
        self.gateway = gateway
        self.retry_delay_seconds = retry_delay_seconds

    def run_once(
        self,
        tenant_id: str,
        *,
        worker_id: str,
        limit: int = 10,
        lease_seconds: int = 60,
    ) -> LineageDeliveryBatchResult:
        deliveries = self.gateway.claim_metadata_fabric_lineage(
            tenant_id,
            worker_id,
            actor_subject=self.emitter.profile.actor_subject,
            limit=limit,
            lease_seconds=lease_seconds,
        )
        delivered = 0
        retry_pending = 0
        failed = 0
        for delivery in deliveries:
            try:
                receipt = self.emitter.emit(delivery)
            except LineageHttpDeliveryError as exc:
                outcome = self.gateway.fail_metadata_fabric_lineage(
                    delivery.tenant_id,
                    delivery.delivery_id,
                    worker_id=worker_id,
                    error_code=exc.code,
                    response_status=exc.response_status,
                    retryable=exc.retryable,
                    retry_delay_seconds=self.retry_delay_seconds,
                )
                if outcome.status == LineageDeliveryStatus.FAILED:
                    failed += 1
                else:
                    retry_pending += 1
                continue
            self.gateway.complete_metadata_fabric_lineage(
                delivery.tenant_id,
                delivery.delivery_id,
                worker_id=worker_id,
                response_status=receipt.response_status,
                response_body_sha256=receipt.response_body_sha256,
            )
            delivered += 1
        return LineageDeliveryBatchResult(
            claimed=len(deliveries),
            delivered=delivered,
            retry_pending=retry_pending,
            failed=failed,
            delivery_ids=tuple(item.delivery_id for item in deliveries),
        )

"""Thin consumer that durably stages Active Metadata activation requests."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from .active_metadata_change_contract import (
    build_metadata_activation_intent,
    build_metadata_activation_request,
)
from .platform_gateway import (
    GatewayConflictError,
    GatewayValidationError,
    PlatformGateway,
)


@dataclass(frozen=True)
class ActiveMetadataBatchResult:
    claimed: int
    staged: int
    replayed: int
    retry_pending: int
    failed: int
    request_ids: tuple[UUID, ...]


class ActiveMetadataConsumer:
    """Route changes to inert requests without owning authorization or execution."""

    def __init__(self, gateway: PlatformGateway, *, consumer_subject: str):
        if not consumer_subject.startswith("workload:"):
            raise ValueError("Active Metadata consumer must use workload identity")
        self.gateway = gateway
        self.consumer_subject = consumer_subject

    def run_once(
        self,
        tenant_id: str,
        *,
        worker_id: str,
        limit: int = 10,
        lease_seconds: int = 60,
    ) -> ActiveMetadataBatchResult:
        deliveries = self.gateway.claim_metadata_changes(
            tenant_id,
            worker_id,
            consumer_subject=self.consumer_subject,
            limit=limit,
            lease_seconds=lease_seconds,
        )
        staged = 0
        replayed = 0
        retry_pending = 0
        failed = 0
        request_ids: list[UUID] = []
        for delivery in deliveries:
            intent = build_metadata_activation_intent(
                delivery.event,
                routed_by=self.consumer_subject,
            )
            request = build_metadata_activation_request(intent)
            try:
                result = self.gateway.stage_metadata_activation_request(
                    tenant_id,
                    delivery.event.event_id,
                    worker_id=worker_id,
                    request=request,
                )
            except GatewayConflictError:
                # The commit outcome or lease owner is uncertain. Leave the
                # claim for deterministic reclaim instead of declaring failure.
                retry_pending += 1
                continue
            except GatewayValidationError:
                self.gateway.fail_metadata_change(
                    tenant_id,
                    delivery.event.event_id,
                    worker_id=worker_id,
                    error_code="activation_contract_rejected",
                    retryable=False,
                )
                failed += 1
                continue
            request_ids.append(request.request_id)
            if result.created:
                staged += 1
            else:
                replayed += 1
        return ActiveMetadataBatchResult(
            claimed=len(deliveries),
            staged=staged,
            replayed=replayed,
            retry_pending=retry_pending,
            failed=failed,
            request_ids=tuple(request_ids),
        )

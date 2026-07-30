from datetime import timedelta

import pytest

from data_agent.active_metadata_change_contract import (
    MetadataChangeDelivery,
    MetadataChangeDeliveryStatus,
    build_metadata_activation_intent,
    build_metadata_activation_request,
)
from data_agent.active_metadata_consumer import ActiveMetadataConsumer
from data_agent.metadata_fabric_active_metadata_outbox import (
    CONSUMER_SUBJECT,
    TENANT,
    WORKER_1,
    build_active_metadata_bundle,
)
from data_agent.platform_gateway import (
    GatewayConflictError,
    GatewayUnavailableError,
    GatewayValidationError,
    GatewayWriteResult,
)


def _claimed_delivery() -> MetadataChangeDelivery:
    event = build_active_metadata_bundle().registration.event
    return MetadataChangeDelivery(
        event=event,
        status=MetadataChangeDeliveryStatus.IN_FLIGHT,
        attempt_count=1,
        max_attempts=3,
        available_at=event.occurred_at,
        claimed_by=WORKER_1,
        claimed_until=event.occurred_at + timedelta(minutes=1),
    )


class _Gateway:
    def __init__(self, outcome=None):
        self.delivery = _claimed_delivery()
        self.outcome = outcome
        self.claim_calls = []
        self.stage_calls = []
        self.fail_calls = []

    def claim_metadata_changes(self, tenant_id, worker_id, **kwargs):
        self.claim_calls.append((tenant_id, worker_id, kwargs))
        return [self.delivery]

    def stage_metadata_activation_request(
        self, tenant_id, event_id, *, worker_id, request
    ):
        self.stage_calls.append((tenant_id, event_id, worker_id, request))
        if isinstance(self.outcome, Exception):
            raise self.outcome
        created = True if self.outcome is None else bool(self.outcome)
        return GatewayWriteResult(request, created)

    def fail_metadata_change(self, *args, **kwargs):
        self.fail_calls.append((args, kwargs))
        return self.delivery


def test_consumer_stages_deterministic_inert_request():
    gateway = _Gateway()
    consumer = ActiveMetadataConsumer(
        gateway,
        consumer_subject=CONSUMER_SUBJECT,
    )

    result = consumer.run_once(
        TENANT,
        worker_id=WORKER_1,
        limit=3,
        lease_seconds=45,
    )

    expected = build_metadata_activation_request(
        build_metadata_activation_intent(
            gateway.delivery.event,
            routed_by=CONSUMER_SUBJECT,
        )
    )
    assert result.claimed == result.staged == 1
    assert result.replayed == result.retry_pending == result.failed == 0
    assert result.request_ids == (expected.request_id,)
    assert gateway.stage_calls[0][3] == expected
    assert expected.status == "awaiting_authorization"
    assert expected.provider_apply_authorized is False
    assert expected.production_scheduler_submission_verified is False
    assert expected.production_ready is False


def test_consumer_reports_exact_stage_replay_without_duplicate_work():
    gateway = _Gateway(outcome=False)
    result = ActiveMetadataConsumer(
        gateway,
        consumer_subject=CONSUMER_SUBJECT,
    ).run_once(TENANT, worker_id=WORKER_1)

    assert result.claimed == result.replayed == 1
    assert result.staged == result.retry_pending == result.failed == 0


def test_consumer_leaves_conflict_for_lease_reclaim():
    gateway = _Gateway(GatewayConflictError("uncertain stage"))
    result = ActiveMetadataConsumer(
        gateway,
        consumer_subject=CONSUMER_SUBJECT,
    ).run_once(TENANT, worker_id=WORKER_1)

    assert result.claimed == result.retry_pending == 1
    assert result.staged == result.replayed == result.failed == 0
    assert gateway.fail_calls == []


def test_consumer_terminally_rejects_invalid_request_contract():
    gateway = _Gateway(GatewayValidationError("invalid request"))
    result = ActiveMetadataConsumer(
        gateway,
        consumer_subject=CONSUMER_SUBJECT,
    ).run_once(TENANT, worker_id=WORKER_1)

    assert result.claimed == result.failed == 1
    assert gateway.fail_calls[0][1] == {
        "worker_id": WORKER_1,
        "error_code": "activation_contract_rejected",
        "retryable": False,
    }


def test_consumer_propagates_database_unavailability_to_managed_worker():
    gateway = _Gateway(GatewayUnavailableError("database unavailable"))
    consumer = ActiveMetadataConsumer(
        gateway,
        consumer_subject=CONSUMER_SUBJECT,
    )

    with pytest.raises(GatewayUnavailableError):
        consumer.run_once(TENANT, worker_id=WORKER_1)


def test_consumer_requires_workload_subject():
    with pytest.raises(ValueError, match="workload identity"):
        ActiveMetadataConsumer(_Gateway(), consumer_subject="human:operator")

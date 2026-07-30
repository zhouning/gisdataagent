from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from data_agent.active_metadata_change_contract import (
    ActiveMetadataContractError,
    MetadataActivationIntent,
    MetadataActivationRequest,
    MetadataChangeDelivery,
    MetadataChangeEvent,
    build_active_metadata_registration,
    build_metadata_activation_intent,
    build_metadata_activation_request,
    build_metadata_change_delivery,
)
from data_agent.platform_contracts import ResourceVersion


TENANT = "tenant-a"
VERSION_ID = UUID("00000000-0000-4000-8000-000000000001")
NOW = datetime(2026, 7, 30, 8, 0, tzinfo=timezone.utc)
CONSUMER = "workload:metadata-router"


def _version(**overrides) -> ResourceVersion:
    values = {
        "tenant_id": TENANT,
        "resource_urn": "gda://tenant-a/dataset/parcels",
        "resource_version_id": VERSION_ID,
        "version_key": "snapshot-1",
        "content_sha256": "a" * 64,
        "authority_version_ref": {"snapshot_id": 1},
        "created_by": "human:operator",
        "created_at": NOW,
    }
    values.update(overrides)
    return ResourceVersion(**values)


def test_registration_event_and_activation_intent_are_deterministic():
    first = build_active_metadata_registration(
        _version(),
        consumer_subject=CONSUMER,
    )
    second = build_active_metadata_registration(
        _version(),
        consumer_subject=CONSUMER,
    )
    intent = build_metadata_activation_intent(
        first.event,
        routed_by=CONSUMER,
    )
    request = build_metadata_activation_request(intent)

    assert first == second
    assert str(first.event.event_id) == "23bce695-edf5-53ef-b266-f053628f3446"
    assert first.event.event_sha256 == (
        "21fd3a5bc5446869412787bdee548bc58c876b980901f437fce99e166cc3e3d0"
    )
    assert intent.route == "metadata_fabric.projection_plan"
    assert intent.provider_apply_authorized is False
    assert intent.provider_mutations_executed is False
    assert intent.production_ingestion_verified is False
    assert intent.intent_sha256 == (
        "169ac6b822d9af2ff75071eccc69a9468bffcacbe576bdad8430b95215d1a88c"
    )
    assert str(request.request_id) == "dc9257ee-7103-5eac-9c56-74830839a678"
    assert request.status == "awaiting_authorization"
    assert request.provider_apply_authorized is False
    assert request.production_scheduler_submission_verified is False
    assert request.production_ready is False
    assert request.request_sha256 == (
        "ce2cc874a5306d8370bbbcdb1f5d17df47051ab523deffe4eb9a800578b05771"
    )


def test_event_and_activation_intent_reject_content_tampering():
    registration = build_active_metadata_registration(
        _version(),
        consumer_subject=CONSUMER,
    )
    event_payload = registration.event.model_dump(mode="json", by_alias=True)
    event_payload["version_key"] = "snapshot-tampered"
    with pytest.raises(ValidationError, match="SHA-256"):
        MetadataChangeEvent.model_validate(event_payload)

    intent = build_metadata_activation_intent(
        registration.event,
        routed_by=CONSUMER,
    )
    intent_payload = intent.model_dump(mode="json", by_alias=True)
    intent_payload["resource_urn"] = "gda://tenant-a/dataset/private"
    with pytest.raises(ValidationError, match="SHA-256"):
        MetadataActivationIntent.model_validate(intent_payload)

    request = build_metadata_activation_request(intent)
    request_payload = request.model_dump(mode="json", by_alias=True)
    request_payload["production_ready"] = True
    with pytest.raises(ValidationError):
        MetadataActivationRequest.model_validate(request_payload)


def test_authenticated_producer_and_exact_consumer_are_required():
    with pytest.raises(ActiveMetadataContractError, match="authenticated subject"):
        build_active_metadata_registration(
            _version(created_by="anonymous"),
            consumer_subject=CONSUMER,
        )

    registration = build_active_metadata_registration(
        _version(),
        consumer_subject=CONSUMER,
    )
    with pytest.raises(ActiveMetadataContractError, match="event consumer"):
        build_metadata_activation_intent(
            registration.event,
            routed_by="workload:other-router",
        )


def test_delivery_state_machine_rejects_incoherent_claims_and_terminal_state():
    event = build_active_metadata_registration(
        _version(),
        consumer_subject=CONSUMER,
    ).event
    pending = build_metadata_change_delivery(event, max_attempts=3)
    assert pending.status.value == "pending"
    assert pending.available_at == event.occurred_at

    payload = pending.model_dump(mode="json", by_alias=True)
    payload.update(
        {
            "status": "in_flight",
            "attempt_count": 1,
            "claimed_by": "worker:router-1",
            "claimed_until": (NOW + timedelta(minutes=1)).isoformat(),
        }
    )
    claimed = MetadataChangeDelivery.model_validate(payload)
    assert claimed.status.value == "in_flight"

    payload["claimed_until"] = None
    with pytest.raises(ValidationError, match="claim fields"):
        MetadataChangeDelivery.model_validate(payload)

    terminal = pending.model_dump(mode="json", by_alias=True)
    terminal.update(
        {
            "status": "processed",
            "completed_at": (NOW + timedelta(minutes=2)).isoformat(),
        }
    )
    with pytest.raises(ValidationError, match="processed metadata change"):
        MetadataChangeDelivery.model_validate(terminal)

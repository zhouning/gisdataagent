from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

import pytest
import yaml

from data_agent.consumer_binding import (
    ConsumerBinding,
    ConsumerBindingMigrationNotification,
    ConsumerBindingMigrationNotificationEnvelope,
    ConsumerBindingMigrationState,
    consumer_binding_fingerprint,
    consumer_binding_migration_state_fingerprint,
)
from data_agent.consumer_binding_notification_worker import (
    ConsumerBindingNotificationWorker,
    ConsumerBindingNotificationWorkerConfig,
    render_consumer_binding_migration_alert,
)
from data_agent.incident_notification_worker import (
    IncidentNotificationConfigurationError,
    IncidentNotificationDeliveryError,
)

TENANT = "planning"
NOW = datetime(2026, 8, 7, 12, tzinfo=UTC)
BINDING_ID = UUID("00000000-0000-4000-8000-000000000201")
STATE_ID = UUID("00000000-0000-4000-8000-000000000202")
NOTICE_ID = UUID("00000000-0000-4000-8000-000000000203")
FROM_ID = UUID("00000000-0000-4000-8000-000000000204")
TO_ID = UUID("00000000-0000-4000-8000-000000000205")


def _binding() -> ConsumerBinding:
    payload = {
        "tenant_id": TENANT,
        "binding_id": BINDING_ID,
        "product_urn": "gda://planning/data_product/districts",
        "consumer_ref": "workload:planner-api",
        "purpose": "serve district search",
        "scope": {"operations": ["read"]},
        "min_product_version": "v1.0.0",
        "max_product_version": "v2.0.0",
        "credential_ref": "credential:planner-api",
        "quota": {"max_packages": 5},
        "expires_at": NOW + timedelta(days=30),
        "compatibility_fingerprint": "a" * 64,
        "compatibility_evidence": {"schema": "districts.v1"},
        "created_by": "human:data-steward",
        "created_at": NOW,
    }
    payload["binding_sha256"] = consumer_binding_fingerprint(payload)
    return ConsumerBinding.model_validate(payload)


def _state() -> ConsumerBindingMigrationState:
    payload = {
        "tenant_id": TENANT,
        "migration_state_id": STATE_ID,
        "binding_id": BINDING_ID,
        "product_urn": "gda://planning/data_product/districts",
        "from_product_version_id": FROM_ID,
        "to_product_version_id": TO_ID,
        "state_version": 1,
        "compatibility_conclusion": "breaking",
        "compatibility_evidence": {"removed_fields": ["legacy_code"]},
        "notification_status": "pending",
        "notification_evidence": {},
        "migration_deadline": NOW + timedelta(days=14),
        "consumer_acknowledgement": None,
        "previous_state_sha256": None,
        "recorded_by": "human:data-steward",
        "recorded_at": NOW,
    }
    payload["state_sha256"] = consumer_binding_migration_state_fingerprint(payload)
    return ConsumerBindingMigrationState.model_validate(payload)


def _notification(status: str = "in_flight") -> ConsumerBindingMigrationNotification:
    state = _state()
    claimed = status == "in_flight"
    terminal = status in {"done", "failed", "superseded"}
    values = {
        "tenant_id": TENANT,
        "notification_id": NOTICE_ID,
        "migration_state_id": STATE_ID,
        "binding_id": BINDING_ID,
        "product_urn": state.product_urn,
        "from_product_version_id": FROM_ID,
        "to_product_version_id": TO_ID,
        "source_state_sha256": state.state_sha256,
        "channel": "alertmanager",
        "destination_ref": "alertmanager:consumer-binding-default",
        "status": status,
        "attempt_count": 1,
        "max_attempts": 1 if status == "failed" else 10,
        "available_at": NOW,
        "claimed_by": "worker:test" if claimed else None,
        "claimed_until": NOW + timedelta(minutes=1) if claimed else None,
        "last_error": "provider unavailable" if status in {"failed", "superseded"} else None,
        "provider_receipt": (
            {
                "schema": "gda.alertmanager_provider_receipt.v1",
                "provider": "alertmanager",
                "accepted": True,
                "http_status": 202,
            }
            if status == "done"
            else {}
        ),
        "receipt_sha256": "e" * 64 if status in {"done", "failed"} else None,
        "terminal_worker_id": "worker:test" if status in {"done", "failed"} else None,
        "created_at": NOW,
        "completed_at": NOW + timedelta(minutes=1) if terminal else None,
    }
    return ConsumerBindingMigrationNotification.model_validate(values)


def _envelope() -> ConsumerBindingMigrationNotificationEnvelope:
    return ConsumerBindingMigrationNotificationEnvelope(
        notification=_notification(),
        binding=_binding(),
        migration_state=_state(),
    )


def test_alert_is_content_bound_and_uses_server_route_labels() -> None:
    alert = render_consumer_binding_migration_alert(
        _envelope(),
        route_namespace="gis-data-agent",
    )

    assert alert["labels"]["gda_binding_id"] == str(BINDING_ID)
    assert alert["labels"]["gda_consumer_ref"] == "workload:planner-api"
    assert alert["labels"]["namespace"] == "gis-data-agent"
    assert alert["annotations"]["gda_source_state_sha256"] == _state().state_sha256
    assert alert["annotations"]["gda_destination_ref"] == (
        "alertmanager:consumer-binding-default"
    )


class _Gateway:
    def __init__(self, *, failed_status: str = "pending") -> None:
        self.failed_status = failed_status
        self.completed = []
        self.failed = []

    def claim_consumer_binding_migration_notifications(self, *_args, **_kwargs):
        return (_envelope(),)

    def complete_consumer_binding_migration_notification(
        self, tenant_id, notification_id, **kwargs
    ):
        self.completed.append((tenant_id, notification_id, kwargs))
        return SimpleNamespace(notification=_notification("done"))

    def fail_consumer_binding_migration_notification(
        self, tenant_id, notification_id, **kwargs
    ):
        self.failed.append((tenant_id, notification_id, kwargs))
        return SimpleNamespace(notification=_notification(self.failed_status))


class _Client:
    def __init__(self, error=None) -> None:
        self.error = error
        self.delivered = []

    def deliver_alert(self, alert, **kwargs):
        if self.error is not None:
            raise self.error
        self.delivered.append((alert, kwargs))
        return {
            "schema": "gda.alertmanager_provider_receipt.v1",
            "provider": "alertmanager",
            "accepted": True,
            "http_status": 202,
            "destination_ref": kwargs["destination_ref"],
            "accepted_at": "2026-08-07T12:00:01Z",
        }


def _worker(gateway, client) -> ConsumerBindingNotificationWorker:
    return ConsumerBindingNotificationWorker(
        ConsumerBindingNotificationWorkerConfig(
            tenant_id=TENANT,
            worker_id="worker:test",
            recorded_by="service:consumer-binding-notification-worker",
            alertmanager_url="http://alerts.internal",
            route_namespace="gis-data-agent",
        ),
        gateway=gateway,
        client=client,
    )


def test_worker_records_provider_receipt_only_after_delivery() -> None:
    gateway = _Gateway()
    client = _Client()
    with (
        patch(
            "data_agent.consumer_binding_notification_worker._record_operation"
        ),
        patch("data_agent.consumer_binding_notification_worker._observe_cycle"),
        patch(
            "data_agent.consumer_binding_notification_worker._record_success_timestamp"
        ),
    ):
        cycle = _worker(gateway, client).run_once()

    assert (cycle.claimed, cycle.delivered, cycle.retrying) == (1, 1, 0)
    assert gateway.failed == []
    assert len(gateway.completed) == 1
    provider_receipt = gateway.completed[0][2]["provider_receipt"]
    assert provider_receipt["provider"] == "alertmanager"
    assert client.delivered[0][1]["expected_destination_ref"] == (
        "alertmanager:consumer-binding-default"
    )


def test_worker_retries_and_records_terminal_dead_letter() -> None:
    retry_gateway = _Gateway()
    retry = _worker(
        retry_gateway,
        _Client(IncidentNotificationDeliveryError("unavailable")),
    ).run_once()
    assert (retry.retrying, retry.dead_lettered) == (1, 0)

    dead_gateway = _Gateway(failed_status="failed")
    dead = _worker(
        dead_gateway,
        _Client(IncidentNotificationDeliveryError("unavailable")),
    ).run_once()
    assert (dead.retrying, dead.dead_lettered) == (0, 1)


@pytest.mark.parametrize(
    ("recorded_by", "route_namespace"),
    (("worker:invalid", None), ("service:valid", "Invalid_Namespace")),
)
def test_worker_rejects_untrusted_actor_or_route(
    recorded_by: str,
    route_namespace: str | None,
) -> None:
    config = ConsumerBindingNotificationWorkerConfig(
        tenant_id=TENANT,
        worker_id="worker:test",
        recorded_by=recorded_by,
        alertmanager_url="http://alerts.internal",
        route_namespace=route_namespace,
    )

    with pytest.raises(IncidentNotificationConfigurationError):
        config.validate()


def test_compose_alerts_profile_runs_dedicated_worker_configuration() -> None:
    compose = yaml.safe_load(
        (Path(__file__).resolve().parents[1] / "docker-compose.yml").read_text(
            encoding="utf-8"
        )
    )
    service = compose["services"]["consumer-binding-notification-worker"]
    environment = service["environment"]

    assert service["profiles"] == ["alerts"]
    assert service["restart"] == "unless-stopped"
    assert service["command"] == [
        "python",
        "-m",
        "data_agent.consumer_binding_notification_worker",
    ]
    assert "GDA_CONSUMER_BINDING_NOTIFICATION_TENANT_ID" in environment
    assert "GDA_CONSUMER_BINDING_NOTIFICATION_RECORDED_BY" in environment
    assert "GDA_ALERTMANAGER_URL" in environment
    assert "GDA_ALERTMANAGER_BEARER_TOKEN_FILE" in environment

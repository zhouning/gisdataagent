import json
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import UUID

import httpx
import pytest
from pydantic import ValidationError

from data_agent.incident_notification_worker import (
    AlertmanagerV2Client,
    IncidentNotificationConfigurationError,
    IncidentNotificationDeliveryError,
    IncidentNotificationWorker,
    IncidentNotificationWorkerConfig,
    normalize_alertmanager_api_url,
    render_alertmanager_alert,
)
from data_agent.platform_contracts import (
    DataIncident,
    DataIncidentEvent,
    IncidentNotification,
    IncidentNotificationEnvelope,
    data_incident_fingerprint,
)

TENANT = "tenant-a"
RUN_ID = UUID("00000000-0000-4000-8000-000000000020")
INCIDENT_ID = UUID("00000000-0000-4000-8000-000000000080")
OPEN_EVENT_ID = UUID("00000000-0000-4000-8000-000000000081")
RESOLVED_EVENT_ID = UUID("00000000-0000-4000-8000-000000000082")
NOW = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


def _incident(**overrides) -> DataIncident:
    details = {"provider_state": "FAILURE", "workflow_instance_id": 7}
    values = {
        "tenant_id": TENANT,
        "incident_id": INCIDENT_ID,
        "run_id": RUN_ID,
        "dedupe_key": "cancel-terminal:observation-1",
        "incident_type": "provider_cancel_terminal_mismatch",
        "severity": "high",
        "summary": "provider cancellation did not converge",
        "details": details,
        "detected_by": "workload:dataops-adapter",
        "status": "open",
        "state_version": 0,
        "opened_at": NOW,
        "updated_at": NOW,
    }
    values["incident_sha256"] = data_incident_fingerprint(
        tenant_id=TENANT,
        run_id=RUN_ID,
        dedupe_key=values["dedupe_key"],
        incident_type=values["incident_type"],
        severity=values["severity"],
        summary=values["summary"],
        trigger_observation_id=None,
        details=details,
        detected_by=values["detected_by"],
        opened_at=NOW,
    )
    values.update(overrides)
    return DataIncident(**values)


def _envelope(
    *, sequence_no: int = 0, to_status: str = "open"
) -> IncidentNotificationEnvelope:
    event_id = OPEN_EVENT_ID if sequence_no == 0 else RESOLVED_EVENT_ID
    occurred_at = NOW if sequence_no == 0 else NOW + timedelta(minutes=5)
    event = DataIncidentEvent(
        tenant_id=TENANT,
        event_id=event_id,
        incident_id=INCIDENT_ID,
        sequence_no=sequence_no,
        from_status=None if sequence_no == 0 else "acknowledged",
        to_status=to_status,
        actor_subject=(
            "workload:dataops-adapter" if sequence_no == 0 else "human:operator"
        ),
        reason="incident detected" if sequence_no == 0 else "remediation complete",
        occurred_at=occurred_at,
    )
    notification = IncidentNotification(
        tenant_id=TENANT,
        notification_id=UUID(
            f"00000000-0000-4000-8000-{sequence_no + 90:012d}"
        ),
        incident_id=INCIDENT_ID,
        incident_event_id=event_id,
        incident_sequence_no=sequence_no,
        channel="alertmanager",
        destination_ref="alertmanager:default",
        status="in_flight",
        attempt_count=1,
        claimed_by="worker:test",
        claimed_until=NOW + timedelta(minutes=1),
        available_at=NOW,
        created_at=NOW,
    )
    incident = _incident()
    if to_status == "resolved":
        incident = _incident(
            **{
                "status": "resolved",
                "state_version": sequence_no,
                "updated_at": occurred_at,
            }
        )
    return IncidentNotificationEnvelope(
        notification=notification,
        incident=incident,
        event=event,
    )


def test_alertmanager_payload_uses_stable_labels_and_resolves_same_alert():
    opened = render_alertmanager_alert(_envelope(), route_namespace="gis-agent")
    resolved = render_alertmanager_alert(
        _envelope(sequence_no=2, to_status="resolved"),
        route_namespace="gis-agent",
    )

    assert opened["labels"] == resolved["labels"]
    assert opened["labels"]["namespace"] == "gis-agent"
    assert opened["annotations"]["gda_status"] == "open"
    assert "endsAt" not in opened
    assert resolved["annotations"]["gda_status"] == "resolved"
    assert resolved["endsAt"] == "2026-08-01T12:05:00Z"


def test_alertmanager_client_posts_v2_array_without_following_redirects():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(202)

    with AlertmanagerV2Client(
        "https://alerts.internal",
        transport=httpx.MockTransport(handler),
    ) as client:
        client.deliver(_envelope())

    assert client.api_url == "https://alerts.internal/api/v2/alerts"
    assert len(requests) == 1
    assert requests[0].headers["user-agent"] == "gis-data-agent-incident-worker/1"
    payload = json.loads(requests[0].content)
    assert payload[0]["labels"]["gda_incident_id"] == str(INCIDENT_ID)


@pytest.mark.parametrize(
    "url",
    (
        "file:///tmp/alerts",
        "https://user:secret@alerts.internal",
        "https://alerts.internal/api/v2/alerts?token=secret",
    ),
)
def test_alertmanager_url_rejects_unsafe_endpoint_forms(url):
    with pytest.raises(IncidentNotificationConfigurationError):
        normalize_alertmanager_api_url(url)


def test_alertmanager_client_fails_closed_on_non_success_status():
    with AlertmanagerV2Client(
        "http://alerts.internal",
        transport=httpx.MockTransport(lambda _request: httpx.Response(503)),
    ) as client:
        with pytest.raises(IncidentNotificationDeliveryError, match="HTTP 503"):
            client.deliver(_envelope())


class _Gateway:
    def __init__(self, envelope, *, failed_status="pending"):
        self.envelope = envelope
        self.failed_status = failed_status
        self.completed = []
        self.failed = []

    def claim_incident_notifications(self, *_args, **_kwargs):
        return (self.envelope,)

    def complete_incident_notification(self, tenant_id, notification_id, **kwargs):
        self.completed.append((tenant_id, notification_id, kwargs))
        return IncidentNotification(
            **{
                **self.envelope.notification.model_dump(),
                "status": "done",
                "claimed_by": None,
                "claimed_until": None,
                "completed_at": NOW,
                "provider_receipt": kwargs.get(
                    "provider_receipt",
                    {
                        "schema": "gda.alertmanager_provider_receipt.v1",
                        "provider": "alertmanager",
                        "accepted": True,
                        "http_status": 202,
                        "destination_ref": "alertmanager:default",
                        "accepted_at": "2026-08-01T12:00:00Z",
                    },
                ),
                "receipt_sha256": "a" * 64,
                "terminal_worker_id": "worker:test",
            }
        )

    def fail_incident_notification(self, tenant_id, notification_id, **kwargs):
        self.failed.append((tenant_id, notification_id, kwargs))
        terminal = self.failed_status == "failed"
        return IncidentNotification(
            **{
                **self.envelope.notification.model_dump(),
                "status": self.failed_status,
                "claimed_by": None,
                "claimed_until": None,
                "completed_at": NOW if terminal else None,
                "last_error": kwargs.get("error") if terminal else None,
                "receipt_sha256": "b" * 64 if terminal else None,
                "terminal_worker_id": "worker:test" if terminal else None,
            }
        )


class _Client:
    def __init__(self, error=None):
        self.error = error
        self.delivered = []

    def deliver(self, envelope, *, route_namespace=None):
        if self.error:
            raise self.error
        self.delivered.append((envelope, route_namespace))
        return {
            "schema": "gda.alertmanager_provider_receipt.v1",
            "provider": "alertmanager",
            "accepted": True,
            "http_status": 202,
            "destination_ref": envelope.notification.destination_ref,
            "accepted_at": "2026-08-01T12:00:00Z",
        }


def _worker(gateway, client) -> IncidentNotificationWorker:
    return IncidentNotificationWorker(
        IncidentNotificationWorkerConfig(
            tenant_id=TENANT,
            worker_id="worker:test",
            alertmanager_url="http://alerts.internal",
            route_namespace="gis-agent",
        ),
        gateway=gateway,
        client=client,
    )


def test_worker_completes_only_after_alertmanager_accepts_delivery():
    envelope = _envelope()
    gateway = _Gateway(envelope)
    client = _Client()

    cycle = _worker(gateway, client).run_once()

    assert (cycle.claimed, cycle.delivered, cycle.retrying) == (1, 1, 0)
    assert client.delivered == [(envelope, "gis-agent")]
    assert len(gateway.completed) == 1
    assert gateway.failed == []


def test_worker_releases_failed_delivery_for_retry_and_tracks_dead_letter():
    envelope = _envelope()
    retry_gateway = _Gateway(envelope)
    retry_cycle = _worker(
        retry_gateway, _Client(IncidentNotificationDeliveryError("unavailable"))
    ).run_once()
    assert (retry_cycle.retrying, retry_cycle.dead_lettered) == (1, 0)
    assert len(retry_gateway.failed) == 1

    dead_gateway = _Gateway(envelope, failed_status="failed")
    dead_cycle = _worker(
        dead_gateway, _Client(IncidentNotificationDeliveryError("unavailable"))
    ).run_once()
    assert (dead_cycle.retrying, dead_cycle.dead_lettered) == (0, 1)


def test_worker_does_not_misclassify_programming_error_as_delivery_failure():
    gateway = _Gateway(_envelope())

    with (
        patch(
            "data_agent.incident_notification_worker._record_success_timestamp"
        ) as record_success,
        pytest.raises(ValueError, match="rendering bug"),
    ):
        _worker(gateway, _Client(ValueError("rendering bug"))).run_once()

    record_success.assert_not_called()
    assert gateway.completed == []
    assert gateway.failed == []


def test_notification_worker_config_rejects_invalid_delivery_bounds():
    with pytest.raises(IncidentNotificationConfigurationError, match="batch size"):
        IncidentNotificationWorkerConfig(
            tenant_id=TENANT,
            worker_id="worker:test",
            alertmanager_url="http://alerts.internal",
            batch_size=0,
        ).validate()

    with pytest.raises(IncidentNotificationConfigurationError, match="metrics port"):
        IncidentNotificationWorkerConfig(
            tenant_id=TENANT,
            worker_id="worker:test",
            alertmanager_url="http://alerts.internal",
            metrics_port=70_000,
        ).validate()

    with pytest.raises(ValidationError):
        IncidentNotification(
            **{
                **_envelope().notification.model_dump(),
                "claimed_by": None,
            }
        )


@pytest.mark.parametrize(
    "route_namespace",
    ("Monitoring", "gis_agent", "-gis-agent", "g" * 64),
)
def test_worker_route_namespace_must_be_a_kubernetes_dns_label(route_namespace):
    config = IncidentNotificationWorkerConfig(
        tenant_id=TENANT,
        worker_id="worker:test",
        alertmanager_url="http://alerts.internal",
        route_namespace=route_namespace,
    )

    with pytest.raises(IncidentNotificationConfigurationError, match="DNS label"):
        config.validate()

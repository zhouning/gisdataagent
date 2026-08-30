from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from data_agent.capability_registry import DATAOPS_MANUAL_RUN_SUBMIT
from data_agent.platform_contracts import PlatformRunEvent
from data_agent.platform_run_event_worker import (
    CloudEventsHttpClient,
    PlatformRunEventDeliveryError,
    PlatformRunEventWorker,
    PlatformRunEventWorkerConfig,
    PlatformRunEventWorkerConfigurationError,
    normalize_cloudevents_url,
)
from data_agent.platform_run_events import (
    PlatformRunEventDelivery,
    PlatformRunEventEnvelope,
)

TENANT = "run-event-worker-test"
RUN_ID = UUID("10000000-0000-4000-8000-000000000020")
EVENT_ID = UUID("10000000-0000-4000-8000-000000000021")
DELIVERY_ID = UUID("10000000-0000-4000-8000-000000000022")
NOW = datetime(2026, 8, 4, 1, 2, 3, tzinfo=UTC)


def _envelope() -> PlatformRunEventEnvelope:
    event = PlatformRunEvent(
        tenant_id=TENANT,
        event_id=EVENT_ID,
        run_id=RUN_ID,
        sequence_no=0,
        from_status=None,
        to_status="accepted",
        actor_subject="workload:platform-gateway",
        reason="run admitted",
        occurred_at=NOW,
    )
    delivery = PlatformRunEventDelivery(
        tenant_id=TENANT,
        delivery_id=DELIVERY_ID,
        run_id=RUN_ID,
        run_event_id=EVENT_ID,
        run_sequence_no=0,
        status="in_flight",
        attempt_count=1,
        max_attempts=10,
        available_at=NOW,
        claimed_by="worker:test",
        claimed_until=NOW + timedelta(minutes=1),
        created_at=NOW,
    )
    return PlatformRunEventEnvelope(delivery=delivery, event=event)


def test_cloudevent_is_bound_to_immutable_event_and_asyncapi_schema() -> None:
    envelope = _envelope()
    payload = envelope.to_cloudevent().model_dump(mode="json", exclude_none=True)
    asyncapi = DATAOPS_MANUAL_RUN_SUBMIT.asyncapi_projection()
    schema = asyncapi["components"]["messages"]["capabilityEvent"]["payload"]

    Draft202012Validator(
        schema,
        format_checker=FormatChecker(),
    ).validate(payload)
    assert payload["id"] == str(EVENT_ID)
    assert payload["type"] == "gda.platform-run.status-changed.v1"
    assert payload["subject"] == f"gda://{TENANT}/run/{RUN_ID}"
    assert payload["data"] == {
        "tenant_id": TENANT,
        "run_id": str(RUN_ID),
        "status": "accepted",
        "state_version": 0,
    }


def test_envelope_rejects_a_delivery_bound_to_another_event() -> None:
    envelope = _envelope()
    with pytest.raises(ValidationError, match="immutable run event"):
        PlatformRunEventEnvelope(
            delivery=PlatformRunEventDelivery(
                **{
                    **envelope.delivery.model_dump(),
                    "run_event_id": UUID(
                        "10000000-0000-4000-8000-000000000099"
                    ),
                }
            ),
            event=envelope.event,
        )


def test_http_client_sends_structured_cloudevent_and_bearer_token(tmp_path) -> None:
    token_file = tmp_path / "receiver.token"
    token_file.write_text("test-token\n", encoding="utf-8")
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(202)

    with CloudEventsHttpClient(
        "https://events.internal/platform-runs",
        bearer_token_file=token_file,
        transport=httpx.MockTransport(handler),
    ) as client:
        client.deliver(_envelope())

    assert len(requests) == 1
    request = requests[0]
    assert request.headers["content-type"] == "application/cloudevents+json"
    assert request.headers["authorization"] == "Bearer test-token"
    assert request.headers["user-agent"] == (
        "geospatial-data-agent-run-event-worker/1"
    )
    assert json.loads(request.content)["id"] == str(EVENT_ID)


@pytest.mark.parametrize(
    "url",
    (
        "file:///tmp/events",
        "https://user:secret@events.internal/platform-runs",
        "https://events.internal/platform-runs?token=secret",
        "https://events.internal/platform-runs#fragment",
    ),
)
def test_receiver_url_rejects_unsafe_endpoint_forms(url: str) -> None:
    with pytest.raises(PlatformRunEventWorkerConfigurationError):
        normalize_cloudevents_url(url)


def test_http_client_does_not_follow_redirect_or_accept_non_2xx() -> None:
    with CloudEventsHttpClient(
        "http://events.internal/platform-runs",
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                307,
                headers={"Location": "http://other.internal/events"},
            )
        ),
    ) as client:
        with pytest.raises(PlatformRunEventDeliveryError, match="HTTP 307"):
            client.deliver(_envelope())


class _Gateway:
    def __init__(self, envelope, *, failed_status="pending"):
        self.envelope = envelope
        self.failed_status = failed_status
        self.completed = []
        self.failed = []

    def claim_platform_run_event_deliveries(self, *_args, **_kwargs):
        return (self.envelope,)

    def complete_platform_run_event_delivery(
        self, tenant_id, delivery_id, **kwargs
    ):
        self.completed.append((tenant_id, delivery_id, kwargs))
        return PlatformRunEventDelivery(
            **{
                **self.envelope.delivery.model_dump(),
                "status": "done",
                "claimed_by": None,
                "claimed_until": None,
                "completed_at": NOW,
            }
        )

    def fail_platform_run_event_delivery(self, tenant_id, delivery_id, **kwargs):
        self.failed.append((tenant_id, delivery_id, kwargs))
        return PlatformRunEventDelivery(
            **{
                **self.envelope.delivery.model_dump(),
                "status": self.failed_status,
                "claimed_by": None,
                "claimed_until": None,
                "completed_at": NOW if self.failed_status == "failed" else None,
            }
        )


class _Client:
    def __init__(self, error=None):
        self.error = error
        self.delivered = []

    def deliver(self, envelope):
        if self.error:
            raise self.error
        self.delivered.append(envelope)


def _worker(gateway, client) -> PlatformRunEventWorker:
    return PlatformRunEventWorker(
        PlatformRunEventWorkerConfig(
            tenant_id=TENANT,
            worker_id="worker:test",
            receiver_url="http://events.internal/platform-runs",
        ),
        gateway=gateway,
        client=client,
    )


def test_worker_completes_only_after_receiver_accepts_delivery() -> None:
    envelope = _envelope()
    gateway = _Gateway(envelope)
    client = _Client()

    cycle = _worker(gateway, client).run_once()

    assert (cycle.claimed, cycle.delivered, cycle.retrying) == (1, 1, 0)
    assert client.delivered == [envelope]
    assert len(gateway.completed) == 1
    assert gateway.failed == []


def test_worker_retries_delivery_errors_and_tracks_dead_letter() -> None:
    envelope = _envelope()
    retry_gateway = _Gateway(envelope)
    retry_cycle = _worker(
        retry_gateway,
        _Client(PlatformRunEventDeliveryError("unavailable")),
    ).run_once()
    assert (retry_cycle.retrying, retry_cycle.dead_lettered) == (1, 0)
    assert len(retry_gateway.failed) == 1

    dead_gateway = _Gateway(envelope, failed_status="failed")
    dead_cycle = _worker(
        dead_gateway,
        _Client(PlatformRunEventDeliveryError("unavailable")),
    ).run_once()
    assert (dead_cycle.retrying, dead_cycle.dead_lettered) == (0, 1)


def test_worker_does_not_misclassify_programming_error_as_delivery_failure() -> None:
    gateway = _Gateway(_envelope())

    with pytest.raises(ValueError, match="rendering bug"):
        _worker(gateway, _Client(ValueError("rendering bug"))).run_once()

    assert gateway.completed == []
    assert gateway.failed == []

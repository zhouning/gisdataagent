from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import UUID

import pytest

from data_agent.approval_case_notification_worker import (
    ApprovalCaseNotificationWorker,
    ApprovalCaseNotificationWorkerConfig,
    render_approval_case_alert,
)
from data_agent.incident_notification_worker import (
    IncidentNotificationConfigurationError,
    IncidentNotificationDeliveryError,
)
from data_agent.platform_contracts import (
    ApprovalCase,
    ApprovalCaseEvent,
    ApprovalCaseNotification,
    ApprovalCaseNotificationEnvelope,
)

TENANT = "tenant-a"
CASE_REF = "gda://tenant-a/approval_case/schema-drift-1"
TARGET_REF = "gda://tenant-a/schema_drift/" + "a" * 64
NOW = datetime(2026, 8, 4, 12, tzinfo=UTC)


def _case(*, decided: bool = False) -> ApprovalCase:
    values = {
        "tenant_id": TENANT,
        "approval_case_ref": CASE_REF,
        "target_resource_urn": TARGET_REF,
        "target_fingerprint": "a" * 64,
        "action": "source_schema_drift.reconcile",
        "requester_subject": "workload:schema-drift-observer",
        "request_reason": "review breaking source schema drift",
        "requested_at": NOW,
        "expires_at": NOW + timedelta(hours=4),
    }
    if decided:
        values.update(
            status="approved",
            state_version=1,
            decided_by="human:data-steward",
            decision_reason="compatibility plan accepted",
            decided_at=NOW + timedelta(minutes=20),
        )
    return ApprovalCase(**values)


def _event(*, decided: bool = False) -> ApprovalCaseEvent:
    return ApprovalCaseEvent(
        tenant_id=TENANT,
        approval_event_id=UUID(
            "00000000-0000-4000-8000-000000000092"
            if decided
            else "00000000-0000-4000-8000-000000000091"
        ),
        approval_case_ref=CASE_REF,
        sequence_no=1 if decided else 0,
        from_status="pending" if decided else None,
        to_status="approved" if decided else "pending",
        actor_subject="human:data-steward" if decided else "workload:schema-drift-observer",
        reason="compatibility plan accepted" if decided else "review breaking drift",
        occurred_at=NOW + timedelta(minutes=20) if decided else NOW,
    )


def _notification(kind: str, *, failed_status: str = "in_flight") -> ApprovalCaseNotification:
    decided = kind == "decided"
    expired = kind == "expired"
    escalated = kind == "escalated"
    terminal = failed_status in {"done", "failed", "suppressed"}
    claimed = failed_status == "in_flight"
    return ApprovalCaseNotification(
        tenant_id=TENANT,
        notification_id=UUID(
            {
                "requested": "00000000-0000-4000-8000-000000000101",
                "expired": "00000000-0000-4000-8000-000000000102",
                "decided": "00000000-0000-4000-8000-000000000103",
                "escalated": "00000000-0000-4000-8000-000000000104",
            }[kind]
        ),
        approval_case_ref=CASE_REF,
        approval_event_sequence_no=None if expired or escalated else (1 if decided else 0),
        notification_kind=kind,
        channel="alertmanager",
        destination_ref="alertmanager:approval-default",
        delivery_order=1 if expired or decided or escalated else 0,
        status=failed_status,
        attempt_count=1,
        claimed_by="worker:test" if claimed else None,
        claimed_until=NOW + timedelta(minutes=1) if claimed else None,
        available_at=(
            _case().expires_at
            if expired
            else (NOW + timedelta(minutes=20) if decided else NOW)
        ),
        created_at=NOW,
        completed_at=NOW + timedelta(minutes=1) if terminal else None,
        escalation_stage=1 if escalated else None,
        escalation_target_subject="team:data-governance" if escalated else None,
        escalation_on_call_ref="oncall:data-governance" if escalated else None,
        escalation_actor_subject="workload:sla-monitor" if escalated else None,
        escalation_reason="approval is nearing expiry" if escalated else None,
        idempotency_key=("a" * 64) if escalated else None,
    )


def _envelope(kind: str) -> ApprovalCaseNotificationEnvelope:
    return ApprovalCaseNotificationEnvelope(
        notification=_notification(kind),
        approval_case=_case(decided=kind == "decided"),
            event=None if kind in {"expired", "escalated"} else _event(decided=kind == "decided"),
    )


def test_alert_uses_stable_labels_and_decision_closes_same_alert() -> None:
    requested = render_approval_case_alert(_envelope("requested"))
    decided = render_approval_case_alert(_envelope("decided"))

    assert requested["labels"] == decided["labels"]
    assert requested["annotations"]["gda_status"] == "pending"
    assert "endsAt" not in requested
    assert decided["annotations"]["gda_status"] == "approved"
    assert decided["endsAt"] == "2026-08-04T12:20:00Z"


def test_alert_route_namespace_is_stable_and_explicit() -> None:
    requested = render_approval_case_alert(
        _envelope("requested"),
        route_namespace="gis-agent",
    )
    decided = render_approval_case_alert(
        _envelope("decided"),
        route_namespace="gis-agent",
    )

    assert requested["labels"] == decided["labels"]
    assert requested["labels"]["namespace"] == "gis-agent"


def test_expiry_alert_is_an_sla_fact_not_a_verdict() -> None:
    alert = render_approval_case_alert(_envelope("expired"))

    assert alert["annotations"]["gda_status"] == "expired"
    assert alert["annotations"]["gda_notification_kind"] == "expired"
    assert "endsAt" not in alert
    assert _envelope("expired").approval_case.status.value == "pending"


def test_escalation_alert_preserves_case_and_identifies_on_call_target() -> None:
    alert = render_approval_case_alert(_envelope("escalated"))

    assert alert["annotations"]["gda_status"] == "escalated"
    assert alert["annotations"]["gda_notification_kind"] == "escalated"
    assert alert["annotations"]["gda_escalation_stage"] == "1"
    assert alert["annotations"]["gda_escalation_target"] == "team:data-governance"
    assert alert["annotations"]["gda_on_call_ref"] == "oncall:data-governance"
    assert alert["labels"]["severity"] == "warning"
    assert _envelope("escalated").approval_case.status.value == "pending"


class _Authority:
    def __init__(self, envelope, *, failed_status="pending"):
        self.envelope = envelope
        self.failed_status = failed_status
        self.completed = []
        self.failed = []
        self.materialized = []

    def materialize_sla_escalations(self, *_args, **_kwargs):
        self.materialized.append((_args, _kwargs))
        return ()

    def claim_notifications(self, *_args, **_kwargs):
        return (self.envelope,)

    def complete_notification(self, tenant_id, notification_id, **kwargs):
        self.completed.append((tenant_id, notification_id, kwargs))
        return _notification("requested", failed_status="done")

    def fail_notification(self, tenant_id, notification_id, **kwargs):
        self.failed.append((tenant_id, notification_id, kwargs))
        return _notification("requested", failed_status=self.failed_status)


class _Client:
    def __init__(self, error=None):
        self.error = error
        self.delivered = []

    def deliver_alert(self, alert, **kwargs):
        if self.error:
            raise self.error
        self.delivered.append((alert, kwargs))


def _worker(authority, client, *, route_namespace=None) -> ApprovalCaseNotificationWorker:
    return ApprovalCaseNotificationWorker(
        ApprovalCaseNotificationWorkerConfig(
            tenant_id=TENANT,
            worker_id="worker:test",
            alertmanager_url="http://alerts.internal",
            route_namespace=route_namespace,
        ),
        authority=authority,
        client=client,
    )


def test_worker_completes_only_after_delivery() -> None:
    authority = _Authority(_envelope("requested"))
    client = _Client()

    with (
        patch(
            "data_agent.approval_case_notification_worker._record_operation"
        ) as record_operation,
        patch(
            "data_agent.approval_case_notification_worker._observe_cycle"
        ) as observe_cycle,
        patch(
            "data_agent.approval_case_notification_worker._record_success_timestamp"
        ) as record_success,
    ):
        cycle = _worker(
            authority,
            client,
            route_namespace="gis-agent",
        ).run_once()

    assert (cycle.claimed, cycle.delivered, cycle.retrying) == (1, 1, 0)
    assert record_operation.call_args_list[0].args == ("claimed", 1)
    assert record_operation.call_args_list[1].args == ("delivered",)
    observe_cycle.assert_called_once()
    record_success.assert_called_once_with()
    assert client.delivered[0][0]["labels"]["namespace"] == "gis-agent"
    assert client.delivered[0][1]["expected_destination_ref"] == (
        "alertmanager:approval-default"
    )
    assert len(authority.completed) == 1
    assert authority.failed == []
    assert len(authority.materialized) == 1


def test_worker_retries_delivery_and_tracks_dead_letter() -> None:
    retry_authority = _Authority(_envelope("requested"))
    retry = _worker(
        retry_authority,
        _Client(IncidentNotificationDeliveryError("unavailable")),
    ).run_once()
    assert (retry.retrying, retry.dead_lettered) == (1, 0)

    dead_authority = _Authority(_envelope("requested"), failed_status="failed")
    dead = _worker(
        dead_authority,
        _Client(IncidentNotificationDeliveryError("unavailable")),
    ).run_once()
    assert (dead.retrying, dead.dead_lettered) == (0, 1)


def test_worker_does_not_swallow_programming_errors() -> None:
    with (
        patch(
            "data_agent.approval_case_notification_worker._record_success_timestamp"
        ) as record_success,
        pytest.raises(RuntimeError, match="bug"),
    ):
        _worker(
            _Authority(_envelope("requested")),
            _Client(RuntimeError("bug")),
        ).run_once()

    record_success.assert_not_called()


def test_worker_metrics_port_is_bounded() -> None:
    config = ApprovalCaseNotificationWorkerConfig(
        tenant_id=TENANT,
        worker_id="worker:test",
        alertmanager_url="http://alerts.internal",
        metrics_port=70_000,
    )

    with pytest.raises(IncidentNotificationConfigurationError, match="metrics port"):
        config.validate()


@pytest.mark.parametrize(
    "route_namespace",
    ("Monitoring", "gis_agent", "-gis-agent", "g" * 64),
)
def test_worker_route_namespace_must_be_a_kubernetes_dns_label(
    route_namespace: str,
) -> None:
    config = ApprovalCaseNotificationWorkerConfig(
        tenant_id=TENANT,
        worker_id="worker:test",
        alertmanager_url="http://alerts.internal",
        route_namespace=route_namespace,
    )

    with pytest.raises(IncidentNotificationConfigurationError, match="DNS label"):
        config.validate()

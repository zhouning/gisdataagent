"""Focused contract, gateway and REST tests for governed DataIncident recovery."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest
from fastapi import FastAPI
from pydantic import ValidationError

from data_agent.api import platform_gateway_routes as routes
from data_agent.platform_contracts import (
    IncidentNotification,
    IncidentNotificationRecoveryEvent,
)
from data_agent.platform_gateway import (
    GatewayForbiddenError,
    GatewayValidationError,
    PlatformGateway,
)

TENANT = "tenant-a"
INCIDENT_ID = UUID("00000000-0000-4000-8000-000000000180")
INCIDENT_EVENT_ID = UUID("00000000-0000-4000-8000-000000000181")
NOTIFICATION_ID = UUID("00000000-0000-4000-8000-000000000182")
RECOVERY_EVENT_ID = UUID("00000000-0000-4000-8000-000000000183")
NOW = datetime(2026, 8, 22, 12, tzinfo=UTC)
RECEIPT_SHA256 = "a" * 64


def _failed_notification(**overrides) -> IncidentNotification:
    values = {
        "tenant_id": TENANT,
        "notification_id": NOTIFICATION_ID,
        "incident_id": INCIDENT_ID,
        "incident_event_id": INCIDENT_EVENT_ID,
        "incident_sequence_no": 0,
        "channel": "alertmanager",
        "destination_ref": "alertmanager:default",
        "status": "failed",
        "attempt_count": 10,
        "max_attempts": 10,
        "available_at": NOW,
        "last_error": "Alertmanager returned HTTP 503",
        "provider_receipt": {},
        "receipt_sha256": RECEIPT_SHA256,
        "terminal_worker_id": "worker:incident-alerts",
        "created_at": NOW,
        "completed_at": NOW,
    }
    values.update(overrides)
    return IncidentNotification.model_validate(values)


def _recovery_event(**overrides) -> IncidentNotificationRecoveryEvent:
    values = {
        "tenant_id": TENANT,
        "recovery_event_id": RECOVERY_EVENT_ID,
        "notification_id": NOTIFICATION_ID,
        "incident_id": INCIDENT_ID,
        "incident_event_id": INCIDENT_EVENT_ID,
        "recovery_no": 1,
        "actor_subject": "human:platform-admin",
        "reason": "Alertmanager receiver route repaired",
        "previous_status": "failed",
        "previous_attempt_count": 10,
        "previous_max_attempts": 10,
        "previous_last_error": "Alertmanager returned HTTP 503",
        "previous_provider_receipt": {},
        "previous_receipt_sha256": RECEIPT_SHA256,
        "previous_terminal_worker_id": "worker:incident-alerts",
        "previous_completed_at": NOW,
        "occurred_at": NOW,
    }
    values.update(overrides)
    return IncidentNotificationRecoveryEvent.model_validate(values)


def _request(*, body=None, path=None, headers=None, query=None):
    request = MagicMock()
    request.json = MagicMock()

    async def read_json():
        return body or {}

    request.json.side_effect = read_json
    request.path_params = path or {}
    request.headers = headers or {"x-request-id": "recovery-test"}
    request.query_params = query or {}
    return request


def _user(*, role="platform_operator", subject_type="human", identifier="platform-admin"):
    return SimpleNamespace(
        identifier=identifier,
        metadata={
            "role": role,
            "tenant_id": TENANT,
            "subject_type": subject_type,
        },
    )


def test_incident_recovery_contract_requires_terminal_failed_evidence() -> None:
    recovered = _failed_notification(
        status="pending",
        attempt_count=0,
        last_error=None,
        receipt_sha256=None,
        terminal_worker_id=None,
        completed_at=None,
        recovery_count=1,
        last_recovered_by="human:platform-admin",
        last_recovery_reason="Alertmanager receiver route repaired",
        last_recovered_at=NOW,
    )
    assert recovered.recovery_count == 1

    with pytest.raises(ValidationError, match="complete recovery evidence"):
        IncidentNotification.model_validate(
            {
                **recovered.model_dump(mode="python"),
                "last_recovery_reason": None,
            }
        )
    with pytest.raises(ValidationError, match="human identity"):
        IncidentNotification.model_validate(
            {
                **recovered.model_dump(mode="python"),
                "last_recovered_by": "workload:auto-retry",
            }
        )

    with pytest.raises(ValidationError, match="bounded terminal attempts"):
        IncidentNotificationRecoveryEvent.model_validate(
            {
                **_recovery_event().model_dump(mode="python"),
                "previous_attempt_count": 9,
            }
        )
    with pytest.raises(ValidationError, match="provider acceptance"):
        IncidentNotificationRecoveryEvent.model_validate(
            {
                **_recovery_event().model_dump(mode="python"),
                "previous_provider_receipt": {"schema": "receipt"},
            }
        )


def test_governed_recovery_migration_is_cas_audited_immutable_and_least_privilege() -> None:
    sql = (
        Path(__file__).parent
        / "migrations/228_incident_notification_governed_recovery.sql"
    ).read_text(encoding="utf-8")
    for marker in (
        "ADD COLUMN IF NOT EXISTS recovery_count",
        "last_recovered_by",
        "last_recovery_reason",
        "last_recovered_at",
        "CHECK (recovery_count BETWEEN 0 AND 10)",
        "CREATE TABLE IF NOT EXISTS gda_control.data_incident_notification_recovery_event",
        "FOREIGN KEY (tenant_id, notification_id)",
        "FOREIGN KEY (tenant_id, incident_id)",
        "FOREIGN KEY (tenant_id, incident_id, incident_event_id)",
        "BEFORE UPDATE OR DELETE",
        "FORCE ROW LEVEL SECURITY",
        "p_incident_id UUID",
        "FOR UPDATE",
        "only a failed notification may be recovered",
        "notification failure evidence changed",
        "notification manual recovery limit reached",
        "v_notification.provider_receipt <> '{}'::jsonb",
        "attempt_count = 0",
        "status = 'pending'",
        "recovery_count = v_recovery_no",
        "GRANT SELECT ON TABLE gda_control.data_incident_notification_recovery_event",
        "GRANT EXECUTE ON FUNCTION gda_control.recover_data_incident_notification(",
    ):
        assert marker in sql
    assert "GRANT UPDATE ON TABLE gda_control.data_incident_notification_recovery_event" not in sql
    assert "GRANT INSERT ON TABLE gda_control.data_incident_notification_recovery_event" not in sql


@pytest.mark.parametrize(
    ("kwargs", "error_type", "message"),
    [
        (
            {
                "expected_attempt_count": 0,
                "expected_receipt_sha256": RECEIPT_SHA256,
                "actor_subject": "human:platform-admin",
                "reason": "repair",
            },
            GatewayValidationError,
            "positive",
        ),
        (
            {
                "expected_attempt_count": 10,
                "expected_receipt_sha256": "not-a-hash",
                "actor_subject": "human:platform-admin",
                "reason": "repair",
            },
            GatewayValidationError,
            "hash",
        ),
        (
            {
                "expected_attempt_count": 10,
                "expected_receipt_sha256": RECEIPT_SHA256,
                "actor_subject": "workload:auto-retry",
                "reason": "repair",
            },
            GatewayForbiddenError,
            "human identity",
        ),
        (
            {
                "expected_attempt_count": 10,
                "expected_receipt_sha256": RECEIPT_SHA256,
                "actor_subject": "human:platform-admin",
                "reason": "   ",
            },
            GatewayValidationError,
            "reason",
        ),
    ],
)
def test_gateway_recovery_rejects_invalid_input_before_opening_transaction(
    kwargs, error_type, message
) -> None:
    gateway = PlatformGateway(engine=MagicMock())
    with patch.object(gateway, "_transaction") as transaction:
        with pytest.raises(error_type, match=message):
            gateway.recover_incident_notification(
                TENANT,
                INCIDENT_ID,
                NOTIFICATION_ID,
                **kwargs,
            )
    transaction.assert_not_called()


def test_gateway_recovery_binds_incident_id_and_evidence_cas_to_sql() -> None:
    result = MagicMock()
    result.mappings.return_value.one.return_value = _failed_notification(
        status="pending",
        attempt_count=0,
        last_error=None,
        receipt_sha256=None,
        terminal_worker_id=None,
        completed_at=None,
        recovery_count=1,
        last_recovered_by="human:platform-admin",
        last_recovery_reason="Alertmanager receiver route repaired",
        last_recovered_at=NOW,
    ).model_dump(mode="python")
    connection = MagicMock()
    connection.execute.return_value = result
    transaction = MagicMock()
    transaction.__enter__.return_value = connection
    transaction.__exit__.return_value = False
    gateway = PlatformGateway(engine=MagicMock())

    with patch.object(gateway, "_transaction", return_value=transaction):
        recovered = gateway.recover_incident_notification(
            TENANT,
            INCIDENT_ID,
            NOTIFICATION_ID,
            expected_attempt_count=10,
            expected_receipt_sha256=RECEIPT_SHA256,
            actor_subject="human:platform-admin",
            reason="Alertmanager receiver route repaired",
        )

    assert recovered.recovery_count == 1
    statement = str(connection.execute.call_args.args[0].text)
    assert "recover_data_incident_notification" in statement
    assert ":incident_id" in statement
    assert connection.execute.call_args.args[1] == {
        "tenant_id": TENANT,
        "incident_id": INCIDENT_ID,
        "notification_id": NOTIFICATION_ID,
        "expected_attempt_count": 10,
        "expected_receipt_sha256": RECEIPT_SHA256,
        "actor_subject": "human:platform-admin",
        "reason": "Alertmanager receiver route repaired",
    }


def test_gateway_recovery_history_is_tenant_incident_notification_scoped() -> None:
    event = _recovery_event()
    result = MagicMock()
    result.mappings.return_value.all.return_value = [
        {
            **event.model_dump(mode="python"),
            "previous_provider_receipt": "{}",
        }
    ]
    connection = MagicMock()
    connection.execute.return_value = result
    transaction = MagicMock()
    transaction.__enter__.return_value = connection
    transaction.__exit__.return_value = False
    gateway = PlatformGateway(engine=MagicMock())

    with patch.object(gateway, "_transaction", return_value=transaction):
        recoveries = gateway.incident_notification_recoveries(
            TENANT, INCIDENT_ID, NOTIFICATION_ID
        )

    assert recoveries == (event,)
    assert connection.execute.call_args.args[1] == {
        "tenant_id": TENANT,
        "incident_id": INCIDENT_ID,
        "notification_id": NOTIFICATION_ID,
    }
    statement = str(connection.execute.call_args.args[0].text)
    assert "WHERE tenant_id = :tenant_id" in statement
    assert "AND incident_id = :incident_id" in statement
    assert "AND notification_id = :notification_id" in statement


def test_incident_notification_recovery_routes_are_human_scoped_and_openapi_visible() -> None:
    notification = _failed_notification()
    event = _recovery_event()
    gateway = MagicMock()
    gateway.list_incident_notifications.return_value = (notification,)
    gateway.incident_notification_recoveries.return_value = (event,)
    gateway.recover_incident_notification.return_value = notification.model_copy(
        update={
            "status": "pending",
            "attempt_count": 0,
            "last_error": None,
            "receipt_sha256": None,
            "terminal_worker_id": None,
            "completed_at": None,
            "recovery_count": 1,
            "last_recovered_by": "human:platform-admin",
            "last_recovery_reason": "Alertmanager receiver route repaired",
            "last_recovered_at": NOW,
        }
    )
    path = {
        "incident_id": str(INCIDENT_ID),
        "notification_id": str(NOTIFICATION_ID),
    }
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user(role="admin")),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        listed = asyncio.run(
            routes.list_incident_notifications(_request(path=path))
        )
        recoveries = asyncio.run(
            routes.list_incident_notification_recoveries(_request(path=path))
        )
        recovered = asyncio.run(
            routes.recover_incident_notification(
                _request(
                    path=path,
                    body={
                        "expected_attempt_count": 10,
                        "expected_receipt_sha256": RECEIPT_SHA256,
                        "reason": "Alertmanager receiver route repaired",
                    },
                )
            )
        )

    assert listed.status_code == 200
    assert json.loads(listed.body)["data"]["count"] == 1
    assert recoveries.status_code == 200
    assert json.loads(recoveries.body)["data"]["recovery_count"] == 1
    assert recovered.status_code == 200
    assert json.loads(recovered.body)["data"]["recovery_count"] == 1
    gateway.list_incident_notifications.assert_called_once_with(TENANT, INCIDENT_ID)
    gateway.incident_notification_recoveries.assert_called_once_with(
        TENANT, INCIDENT_ID, NOTIFICATION_ID
    )
    gateway.recover_incident_notification.assert_called_once_with(
        TENANT,
        INCIDENT_ID,
        NOTIFICATION_ID,
        expected_attempt_count=10,
        expected_receipt_sha256=RECEIPT_SHA256,
        actor_subject="human:platform-admin",
        reason="Alertmanager receiver route repaired",
    )

    with patch.object(
        routes,
        "_get_user_from_request",
        return_value=_user(subject_type="workload"),
    ):
        forbidden = asyncio.run(
            routes.recover_incident_notification(
                _request(
                    path=path,
                    body={
                        "expected_attempt_count": 10,
                        "expected_receipt_sha256": RECEIPT_SHA256,
                        "reason": "unauthorized retry",
                    },
                )
            )
        )
    assert forbidden.status_code == 403
    gateway.recover_incident_notification.assert_called_once()

    with patch.object(
        routes,
        "_get_user_from_request",
        return_value=_user(role="platform_operator"),
    ):
        non_admin = asyncio.run(
            routes.recover_incident_notification(
                _request(
                    path=path,
                    body={
                        "expected_attempt_count": 10,
                        "expected_receipt_sha256": RECEIPT_SHA256,
                        "reason": "operator retry",
                    },
                )
            )
        )
    assert non_admin.status_code == 403
    gateway.recover_incident_notification.assert_called_once()

    app = FastAPI()
    app.router.routes.extend(routes.get_platform_gateway_routes())
    schema = app.openapi()
    for route_path, method, operation_id in (
        (
            "/api/platform/v1/incidents/{incident_id}/notifications",
            "get",
            "platform_list_incident_notifications",
        ),
        (
            "/api/platform/v1/incidents/{incident_id}/notifications/{notification_id}/recoveries",
            "get",
            "platform_list_incident_notification_recoveries",
        ),
        (
            "/api/platform/v1/incidents/{incident_id}/notifications/{notification_id}/recoveries",
            "post",
            "platform_recover_incident_notification",
        ),
    ):
        operation = schema["paths"][route_path][method]
        assert operation["operationId"] == operation_id
        assert operation["security"] == [{"OAuth2PasswordBearerWithCookie": []}]

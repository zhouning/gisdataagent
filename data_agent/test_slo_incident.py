"""Contracts for exact SLO alert to DataIncident reconciliation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from pydantic import ValidationError

from data_agent.platform_contracts import (
    DataIncident,
    IncidentStatus,
    data_incident_fingerprint,
)
from data_agent.platform_gateway import (
    GatewayNotFoundError,
    GatewayWriteResult,
    PlatformGateway,
)
from data_agent.slo_authority import (
    SLOBurnRateWindow,
    SLODefinitionActivation,
    SLODefinitionEvent,
    SLODefinitionVersion,
    SLOEventRatioIndicator,
)
from data_agent.slo_incident import (
    AlertmanagerSLOAlert,
    AlertmanagerSLOWebhook,
    SLOIncidentAction,
    SLOIncidentReconciler,
    SLOIncidentValidationError,
)

TENANT = "tenant-a"
SLO_REF = f"gda://{TENANT}/slo_definition/approval-notification-delivery"
VERSION_REF = f"{SLO_REF}.v1"
SERVICE_REF = f"gda://{TENANT}/service/approval-notification"
APPROVAL_REF = f"gda://{TENANT}/approval_case/slo-v1-activation"
DETECTOR = "workload:slo-alert-ingestor"
NOW = datetime(2026, 8, 4, 10, tzinfo=UTC)


def _definition(**changes) -> SLODefinitionVersion:
    values = {
        "tenant_id": TENANT,
        "slo_definition_ref": SLO_REF,
        "slo_version_ref": VERSION_REF,
        "version": 1,
        "service_resource_urn": SERVICE_REF,
        "indicator": SLOEventRatioIndicator(
            metric_name="gda_approval_notification_operations_total",
            good_outcomes=("delivered",),
            bad_outcomes=("dead_lettered", "retrying"),
        ),
        "objective_basis_points": 9900,
        "objective_window_seconds": 30 * 24 * 60 * 60,
        "owner_subject": "team:data-platform",
        "oncall_ref": "oncall:approval-primary",
        "burn_rate_windows": (
            SLOBurnRateWindow(
                name="fast",
                short_window_seconds=300,
                long_window_seconds=3600,
                burn_rate_milli=14400,
                minimum_events=20,
                for_seconds=120,
                severity="critical",
            ),
        ),
        "created_by": "human:platform-sre",
        "creation_reason": "stage the objective for review",
        "created_at": NOW - timedelta(days=1),
        "definition_fingerprint": "a" * 64,
    }
    values.update(changes)
    return SLODefinitionVersion(**values)


def _activation() -> SLODefinitionActivation:
    return SLODefinitionActivation(
        tenant_id=TENANT,
        slo_definition_ref=SLO_REF,
        active_version_ref=VERSION_REF,
        active_fingerprint="a" * 64,
        approval_case_ref=APPROVAL_REF,
        activation_version=1,
        activated_by="human:platform-admin",
        activation_reason="activate the approved objective",
        activated_at=NOW - timedelta(hours=12),
    )


def _activation_event() -> SLODefinitionEvent:
    return SLODefinitionEvent(
        tenant_id=TENANT,
        slo_event_id=UUID("00000000-0000-4000-8000-0000000000d0"),
        slo_definition_ref=SLO_REF,
        slo_version_ref=VERSION_REF,
        definition_fingerprint="a" * 64,
        event_type="activated",
        approval_case_ref=APPROVAL_REF,
        actor_subject="human:platform-admin",
        reason="activate the approved objective",
        occurred_at=NOW - timedelta(hours=12),
    )


def _alert(**changes) -> AlertmanagerSLOAlert:
    values = {
        "status": "firing",
        "labels": {
            "alertname": "GDASLOErrorBudgetBurn",
            "slo_id": "approval-notification-delivery",
            "slo_version": "1",
            "slo_fingerprint": "a" * 64,
            "service": "approval-notification",
            "owner": "team:data-platform",
            "oncall": "oncall:approval-primary",
            "burn_window": "fast",
            "severity": "critical",
        },
        "annotations": {"approval_case_ref": APPROVAL_REF},
        "startsAt": NOW.isoformat(),
        "endsAt": (NOW + timedelta(hours=1)).isoformat(),
        "generatorURL": "https://prometheus.example.test/graph?g0.expr=slo",
        "fingerprint": "0123456789abcdef",
    }
    values.update(changes)
    return AlertmanagerSLOAlert.model_validate(values)


def _webhook(alert: AlertmanagerSLOAlert | None = None, **changes) -> AlertmanagerSLOWebhook:
    alert = alert or _alert()
    values = {
        "version": "4",
        "groupKey": "{}:{alertname=\"GDASLOErrorBudgetBurn\"}",
        "truncatedAlerts": 0,
        "status": alert.status.value,
        "receiver": "gda-slo-incident",
        "groupLabels": {"alertname": "GDASLOErrorBudgetBurn"},
        "commonLabels": {},
        "commonAnnotations": {},
        "externalURL": "https://alertmanager.example.test",
        "alerts": [alert.model_dump(mode="json", by_alias=True)],
    }
    values.update(changes)
    return AlertmanagerSLOWebhook.model_validate(values)


def _incident_from_submission(kwargs: dict, *, status=IncidentStatus.OPEN) -> DataIncident:
    opened_at = NOW
    values = {
        **kwargs,
        "run_id": None,
        "trigger_observation_id": None,
        "status": status,
        "state_version": 0 if status is IncidentStatus.OPEN else 1,
        "opened_at": opened_at,
        "updated_at": opened_at,
    }
    values["incident_sha256"] = data_incident_fingerprint(
        **{
            key: values[key]
            for key in (
                "tenant_id",
                "run_id",
                "dedupe_key",
                "incident_type",
                "severity",
                "summary",
                "trigger_observation_id",
                "details",
                "detected_by",
                "opened_at",
                "subject_resource_urn",
            )
        }
    )
    return DataIncident(**values)


def _reconciler():
    slo_authority = MagicMock()
    slo_authority.get.return_value = _definition()
    slo_authority.active.return_value = (_definition(), _activation())
    slo_authority.events.return_value = (_activation_event(),)
    gateway = MagicMock()
    reconciler = SLOIncidentReconciler(slo_authority, gateway)
    return reconciler, slo_authority, gateway


def test_alertmanager_contract_rejects_truncation_and_common_value_drift() -> None:
    with pytest.raises(ValidationError, match="truncated"):
        _webhook(truncatedAlerts=1)
    with pytest.raises(ValidationError, match="must agree"):
        _webhook(commonLabels={"severity": "warning"})
    with pytest.raises(ValidationError, match="lowercase hexadecimal"):
        _alert(fingerprint="NOT-A-FINGERPRINT")


def test_firing_alert_opens_one_idempotent_resource_incident() -> None:
    reconciler, slo_authority, gateway = _reconciler()

    def open_incident(**kwargs):
        return GatewayWriteResult(_incident_from_submission(kwargs), True)

    gateway.open_resource_incident.side_effect = open_incident
    result = reconciler.reconcile(TENANT, _webhook(), detector_subject=DETECTOR)

    assert result.created_count == 1
    assert result.resolved_count == 0
    assert result.items[0].action is SLOIncidentAction.CREATED
    submitted = gateway.open_resource_incident.call_args.kwargs
    assert submitted["subject_resource_urn"] == SERVICE_REF
    assert submitted["incident_type"] == "slo_error_budget_burn"
    assert submitted["severity"].value == "critical"
    assert submitted["details"]["definition_fingerprint"] == "a" * 64
    assert submitted["details"]["approval_case_ref"] == APPROVAL_REF
    assert len(submitted["dedupe_key"]) <= 128
    slo_authority.active.assert_called_once_with(TENANT, SLO_REF)

    first_identity = (submitted["incident_id"], submitted["dedupe_key"])
    gateway.open_resource_incident.side_effect = lambda **kwargs: GatewayWriteResult(
        _incident_from_submission(kwargs), False
    )
    replay = reconciler.reconcile(TENANT, _webhook(), detector_subject=DETECTOR)
    replayed = gateway.open_resource_incident.call_args.kwargs
    assert replay.items[0].action is SLOIncidentAction.EXISTING
    assert (replayed["incident_id"], replayed["dedupe_key"]) == first_identity


def test_firing_alert_fails_closed_on_fingerprint_or_active_pointer_drift() -> None:
    reconciler, slo_authority, gateway = _reconciler()
    alert = _alert(
        labels={**_alert().labels, "slo_fingerprint": "b" * 64},
    )
    with pytest.raises(SLOIncidentValidationError, match="slo_fingerprint"):
        reconciler.reconcile(TENANT, _webhook(alert), detector_subject=DETECTOR)
    gateway.open_resource_incident.assert_not_called()

    slo_authority.active.return_value = (
        _definition(),
        _activation().model_copy(update={"active_fingerprint": "b" * 64}),
    )
    with pytest.raises(SLOIncidentValidationError, match="exact active"):
        reconciler.reconcile(TENANT, _webhook(), detector_subject=DETECTOR)
    gateway.open_resource_incident.assert_not_called()


def test_firing_gis_alert_requires_exact_service_slo_binding() -> None:
    reconciler, _, gateway = _reconciler()
    definition = _definition(
        service_resource_urn=f"gda://{TENANT}/gis_service/approval-notification"
    )
    reconciler._slo_authority.get.return_value = definition
    reconciler._slo_authority.active.return_value = (definition, _activation())
    gateway.get_gis_service_slo_binding_for_authority.side_effect = (
        GatewayNotFoundError("binding missing")
    )

    with pytest.raises(SLOIncidentValidationError, match="ServiceSLO binding"):
        reconciler.reconcile(TENANT, _webhook(), detector_subject=DETECTOR)

    gateway.get_gis_service_slo_binding_for_authority.assert_called_once_with(
        TENANT,
        definition.service_resource_urn,
        slo_definition_ref=definition.slo_definition_ref,
        active_version_ref=definition.slo_version_ref,
        definition_fingerprint=definition.definition_fingerprint,
        approval_case_ref=APPROVAL_REF,
        activation_version=1,
    )
    gateway.open_resource_incident.assert_not_called()


def test_firing_gis_alert_uses_atomic_slo_incident_authority() -> None:
    reconciler, _, gateway = _reconciler()
    definition = _definition(
        service_resource_urn=f"gda://{TENANT}/gis_service/approval-notification"
    )
    reconciler._slo_authority.get.return_value = definition
    reconciler._slo_authority.active.return_value = (definition, _activation())
    def open_incident(**kwargs):
        incident_kwargs = {
            key: value
            for key, value in kwargs.items()
            if key
            not in {
                "service_urn",
                "slo_definition_ref",
                "active_version_ref",
                "definition_fingerprint",
                "approval_case_ref",
                "activation_version",
            }
        }
        incident_kwargs["subject_resource_urn"] = kwargs["service_urn"]
        return GatewayWriteResult(_incident_from_submission(incident_kwargs), True)

    gateway.open_gis_service_slo_incident.side_effect = open_incident

    result = reconciler.reconcile(TENANT, _webhook(), detector_subject=DETECTOR)

    assert result.items[0].action is SLOIncidentAction.CREATED
    submitted = gateway.open_gis_service_slo_incident.call_args.kwargs
    assert submitted["service_urn"] == definition.service_resource_urn
    assert submitted["active_version_ref"] == definition.slo_version_ref
    assert submitted["activation_version"] == 1


def test_gateway_gis_slo_incident_assertion_and_insert_share_one_transaction() -> None:
    row = _incident_from_submission(
        {
            "tenant_id": TENANT,
            "subject_resource_urn": f"gda://{TENANT}/gis_service/approval-notification",
            "incident_id": UUID("30000000-0000-4000-8000-000000000225"),
            "dedupe_key": "slo-burn:atomic-authority",
            "incident_type": "slo_error_budget_burn",
            "severity": "critical",
            "summary": "atomic authority test",
            "details": {"schema": "gda.slo_breach_incident.v1"},
            "detected_by": DETECTOR,
        }
    )
    authority_result = MagicMock()
    authority_result.scalar_one.return_value = None
    existing_result = MagicMock()
    existing_result.mappings.return_value.one_or_none.return_value = None
    insert_result = MagicMock()
    insert_result.first.return_value = (row.incident_id,)
    load_result = MagicMock()
    load_result.mappings.return_value.one_or_none.return_value = row.model_dump(
        mode="python"
    )
    clock_result = MagicMock()
    clock_result.scalar_one.return_value = row.opened_at
    connection = MagicMock()
    connection.execute.side_effect = [
        authority_result,
        existing_result,
        clock_result,
        insert_result,
        load_result,
    ]
    transaction = MagicMock()
    transaction.__enter__.return_value = connection
    transaction.__exit__.return_value = False
    gateway = PlatformGateway()

    from unittest.mock import patch

    with patch.object(gateway, "_transaction", return_value=transaction):
        written = gateway.open_gis_service_slo_incident(
            tenant_id=TENANT,
            service_urn=row.subject_resource_urn,
            slo_definition_ref=SLO_REF,
            active_version_ref=VERSION_REF,
            definition_fingerprint="a" * 64,
            approval_case_ref=APPROVAL_REF,
            activation_version=1,
            incident_id=row.incident_id,
            dedupe_key=row.dedupe_key,
            incident_type=row.incident_type,
            severity=row.severity,
            summary=row.summary,
            details=row.details,
            detected_by=row.detected_by,
        )

    assert written.created is True
    assert "assert_gis_service_slo_incident_authority" in str(
        connection.execute.call_args_list[0].args[0]
    )
    assert "INSERT INTO gda_control.data_incident" in str(
        connection.execute.call_args_list[3].args[0]
    )

def test_resolved_alert_cas_resolves_the_exact_existing_incident() -> None:
    reconciler, _, gateway = _reconciler()
    resolved_alert = _alert(
        status="resolved",
        endsAt=(NOW + timedelta(minutes=30)).isoformat(),
    )
    webhook = _webhook(resolved_alert, status="resolved")

    identity_reconciler, _, identity_gateway = _reconciler()
    identity_gateway.open_resource_incident.side_effect = lambda **kwargs: GatewayWriteResult(
        _incident_from_submission(kwargs), True
    )
    opened = identity_reconciler.reconcile(
        TENANT,
        _webhook(),
        detector_subject=DETECTOR,
    ).items[0].incident
    assert opened is not None
    resolved = opened.model_copy(
        update={
            "status": IncidentStatus.RESOLVED,
            "state_version": 1,
            "updated_at": NOW + timedelta(minutes=30),
        }
    )
    gateway.get_incident.return_value = opened
    gateway.transition_incident.return_value = resolved

    result = reconciler.reconcile(TENANT, webhook, detector_subject=DETECTOR)

    assert result.resolved_count == 1
    assert result.items[0].action is SLOIncidentAction.RESOLVED
    args = gateway.transition_incident.call_args.args
    assert args[0] == TENANT
    assert args[1] == opened.incident_id
    assert args[2] == 0
    assert args[3] is IncidentStatus.RESOLVED
    assert args[4] == DETECTOR

    gateway.get_incident.return_value = resolved
    replay = reconciler.reconcile(TENANT, webhook, detector_subject=DETECTOR)
    assert replay.items[0].action is SLOIncidentAction.ALREADY_RESOLVED
    assert gateway.transition_incident.call_count == 1


def test_resolution_without_a_firing_incident_is_observed_but_not_fabricated() -> None:
    reconciler, _, gateway = _reconciler()
    gateway.get_incident.side_effect = GatewayNotFoundError("not found")
    resolved_alert = _alert(status="resolved")

    result = reconciler.reconcile(
        TENANT,
        _webhook(resolved_alert, status="resolved"),
        detector_subject=DETECTOR,
    )

    assert result.items[0].action is SLOIncidentAction.RESOLUTION_WITHOUT_INCIDENT
    assert result.items[0].incident is None
    gateway.open_resource_incident.assert_not_called()
    gateway.transition_incident.assert_not_called()

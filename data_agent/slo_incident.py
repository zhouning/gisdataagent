"""Reconcile exact, approved SLO Alertmanager signals into DataIncident."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from .platform_contracts import (
    DataIncident,
    IncidentSeverity,
    IncidentStatus,
    TenantId,
    build_resource_urn,
    canonical_json_fingerprint,
    parse_resource_urn,
)
from .platform_gateway import (
    GatewayConflictError,
    GatewayNotFoundError,
    PlatformGateway,
)
from .slo_authority import (
    SLODefinitionActivation,
    SLODefinitionAuthority,
    SLODefinitionEvent,
    SLODefinitionVersion,
)

_LABEL_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
_FINGERPRINT_RE = re.compile(r"^[0-9a-f]{8,64}$")
_DETECTOR_RE = re.compile(r"^workload:[^\s]{1,128}$")


class _FrozenContract(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
    )


class AlertmanagerAlertStatus(StrEnum):
    FIRING = "firing"
    RESOLVED = "resolved"


class AlertmanagerSLOAlert(_FrozenContract):
    status: AlertmanagerAlertStatus
    labels: dict[str, str]
    annotations: dict[str, str] = Field(default_factory=dict)
    starts_at: datetime = Field(alias="startsAt")
    ends_at: datetime = Field(alias="endsAt")
    generator_url: str = Field(default="", alias="generatorURL", max_length=2048)
    fingerprint: str

    @field_validator("starts_at", "ends_at")
    @classmethod
    def _aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Alertmanager alert timestamps must include timezone")
        return value.astimezone(UTC)

    @field_validator("fingerprint")
    @classmethod
    def _valid_fingerprint(cls, value: str) -> str:
        if _FINGERPRINT_RE.fullmatch(value) is None:
            raise ValueError("Alertmanager fingerprint must be lowercase hexadecimal")
        return value

    @field_validator("labels", "annotations")
    @classmethod
    def _bounded_string_map(cls, values: dict[str, str]) -> dict[str, str]:
        if len(values) > 64:
            raise ValueError("Alertmanager map exceeds the supported size")
        for name, value in values.items():
            if _LABEL_NAME_RE.fullmatch(name) is None:
                raise ValueError("Alertmanager map key is invalid")
            if not isinstance(value, str) or len(value) > 2048:
                raise ValueError("Alertmanager map value is invalid")
        return dict(sorted(values.items()))


class AlertmanagerSLOWebhook(_FrozenContract):
    version: Literal["4"]
    group_key: str = Field(alias="groupKey", min_length=1, max_length=1024)
    truncated_alerts: int = Field(default=0, alias="truncatedAlerts", ge=0)
    status: AlertmanagerAlertStatus
    receiver: str = Field(min_length=1, max_length=256)
    group_labels: dict[str, str] = Field(alias="groupLabels", default_factory=dict)
    common_labels: dict[str, str] = Field(alias="commonLabels", default_factory=dict)
    common_annotations: dict[str, str] = Field(
        alias="commonAnnotations",
        default_factory=dict,
    )
    external_url: str = Field(default="", alias="externalURL", max_length=2048)
    alerts: tuple[AlertmanagerSLOAlert, ...] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def _complete_delivery(self) -> AlertmanagerSLOWebhook:
        if self.truncated_alerts != 0:
            raise ValueError("truncated Alertmanager deliveries are not authoritative")
        for alert in self.alerts:
            for common, actual in (
                (self.common_labels, alert.labels),
                (self.common_annotations, alert.annotations),
            ):
                if any(actual.get(name) != value for name, value in common.items()):
                    raise ValueError("Alertmanager common and alert values must agree")
        return self


class SLOIncidentAction(StrEnum):
    CREATED = "created"
    EXISTING = "existing"
    RESOLVED = "resolved"
    ALREADY_RESOLVED = "already_resolved"
    RESOLUTION_WITHOUT_INCIDENT = "resolution_without_incident"


class SLOAlertIncidentResult(_FrozenContract):
    alert_fingerprint: str
    alert_status: AlertmanagerAlertStatus
    action: SLOIncidentAction
    incident: DataIncident | None = None


class SLOAlertReconciliationResult(_FrozenContract):
    tenant_id: TenantId
    items: tuple[SLOAlertIncidentResult, ...]
    created_count: Annotated[int, Field(ge=0)]
    resolved_count: Annotated[int, Field(ge=0)]
    unchanged_count: Annotated[int, Field(ge=0)]


class SLOIncidentValidationError(ValueError):
    code = "slo_alert_validation_failed"


def _rfc3339(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _required_label(alert: AlertmanagerSLOAlert, name: str) -> str:
    value = alert.labels.get(name)
    if value is None or not value:
        raise SLOIncidentValidationError(f"SLO alert label {name!r} is required")
    return value


def _activation_event(
    events: tuple[SLODefinitionEvent, ...],
    definition: SLODefinitionVersion,
    approval_case_ref: str,
) -> SLODefinitionEvent | None:
    return next(
        (
            event
            for event in reversed(events)
            if event.event_type == "activated"
            and event.slo_version_ref == definition.slo_version_ref
            and event.definition_fingerprint == definition.definition_fingerprint
            and event.approval_case_ref == approval_case_ref
        ),
        None,
    )


class SLOIncidentReconciler:
    """Validate SLO rule identity and converge alert episodes into incidents."""

    def __init__(
        self,
        slo_authority: SLODefinitionAuthority,
        gateway: PlatformGateway,
    ) -> None:
        self._slo_authority = slo_authority
        self._gateway = gateway

    def _resolve_authority(
        self,
        tenant_id: str,
        alert: AlertmanagerSLOAlert,
    ) -> tuple[SLODefinitionVersion, SLODefinitionActivation | SLODefinitionEvent]:
        if _required_label(alert, "alertname") != "GDASLOErrorBudgetBurn":
            raise SLOIncidentValidationError("only GDASLOErrorBudgetBurn is accepted")
        slo_id = _required_label(alert, "slo_id")
        definition_ref = build_resource_urn(tenant_id, "slo_definition", slo_id)
        try:
            version = int(_required_label(alert, "slo_version"))
        except ValueError as exc:
            raise SLOIncidentValidationError("SLO alert version is invalid") from exc
        if not 1 <= version <= 1_000_000:
            raise SLOIncidentValidationError("SLO alert version is outside the supported range")
        version_ref = f"{definition_ref}.v{version}"
        definition = self._slo_authority.get(tenant_id, version_ref)

        expected_labels = {
            "slo_fingerprint": definition.definition_fingerprint,
            "service": parse_resource_urn(definition.service_resource_urn)["resource_id"],
            "owner": definition.owner_subject,
            "oncall": definition.oncall_ref,
        }
        for name, expected in expected_labels.items():
            if _required_label(alert, name) != expected:
                raise SLOIncidentValidationError(
                    f"SLO alert label {name!r} does not match authority"
                )
        burn_window = _required_label(alert, "burn_window")
        severity = _required_label(alert, "severity")
        if not any(
            policy.name == burn_window and policy.severity.value == severity
            for policy in definition.burn_rate_windows
        ):
            raise SLOIncidentValidationError(
                "SLO alert burn window or severity does not match authority"
            )
        approval_case_ref = alert.annotations.get("approval_case_ref", "")
        if not approval_case_ref:
            raise SLOIncidentValidationError(
                "SLO alert approval_case_ref annotation is required"
            )

        if alert.status is AlertmanagerAlertStatus.FIRING:
            _, activation = self._slo_authority.active(tenant_id, definition_ref)
            if (
                activation.active_version_ref != definition.slo_version_ref
                or activation.active_fingerprint != definition.definition_fingerprint
                or activation.approval_case_ref != approval_case_ref
            ):
                raise SLOIncidentValidationError(
                    "firing SLO alert does not bind the exact active authority"
                )
            return definition, activation

        event = _activation_event(
            self._slo_authority.events(tenant_id, definition_ref),
            definition,
            approval_case_ref,
        )
        if event is None:
            raise SLOIncidentValidationError(
                "resolved SLO alert has no approved activation evidence"
            )
        return definition, event

    @staticmethod
    def _incident_identity(
        tenant_id: str,
        definition: SLODefinitionVersion,
        alert: AlertmanagerSLOAlert,
    ) -> tuple[str, Any]:
        episode_sha256 = canonical_json_fingerprint(
            {
                "tenant_id": tenant_id,
                "slo_version_ref": definition.slo_version_ref,
                "definition_fingerprint": definition.definition_fingerprint,
                "alertmanager_fingerprint": alert.fingerprint,
                "starts_at": _rfc3339(alert.starts_at),
            }
        )
        dedupe_key = f"slo-burn:{episode_sha256[:48]}"
        incident_id = uuid5(
            NAMESPACE_URL,
            f"gda://{tenant_id}/data_incident/{dedupe_key}",
        )
        return dedupe_key, incident_id

    @staticmethod
    def _details(
        definition: SLODefinitionVersion,
        authority: SLODefinitionActivation | SLODefinitionEvent,
        alert: AlertmanagerSLOAlert,
    ) -> dict[str, Any]:
        approval_case_ref = (
            authority.approval_case_ref
            if isinstance(authority, SLODefinitionActivation)
            else authority.approval_case_ref
        )
        return {
            "schema": "gda.slo_breach_incident.v1",
            "slo_definition_ref": definition.slo_definition_ref,
            "slo_version_ref": definition.slo_version_ref,
            "definition_fingerprint": definition.definition_fingerprint,
            "approval_case_ref": approval_case_ref,
            "service_resource_urn": definition.service_resource_urn,
            "objective_basis_points": definition.objective_basis_points,
            "objective_window_seconds": definition.objective_window_seconds,
            "burn_window": _required_label(alert, "burn_window"),
            "alertmanager_fingerprint": alert.fingerprint,
            "alert_started_at": _rfc3339(alert.starts_at),
        }

    def _reconcile_one(
        self,
        tenant_id: str,
        alert: AlertmanagerSLOAlert,
        detector_subject: str,
    ) -> SLOAlertIncidentResult:
        definition, authority = self._resolve_authority(tenant_id, alert)
        dedupe_key, incident_id = self._incident_identity(tenant_id, definition, alert)
        details = self._details(definition, authority, alert)

        if alert.status is AlertmanagerAlertStatus.FIRING:
            severity = (
                IncidentSeverity.CRITICAL
                if alert.labels["severity"] == "critical"
                else IncidentSeverity.MEDIUM
            )
            result = self._gateway.open_resource_incident(
                tenant_id=tenant_id,
                subject_resource_urn=definition.service_resource_urn,
                incident_id=incident_id,
                dedupe_key=dedupe_key,
                incident_type="slo_error_budget_burn",
                severity=severity,
                summary=(
                    f"SLO error budget burn for "
                    f"{parse_resource_urn(definition.service_resource_urn)['resource_id']} "
                    f"({alert.labels['burn_window']})"
                ),
                details=details,
                detected_by=detector_subject,
            )
            return SLOAlertIncidentResult(
                alert_fingerprint=alert.fingerprint,
                alert_status=alert.status,
                action=(
                    SLOIncidentAction.CREATED
                    if result.created
                    else SLOIncidentAction.EXISTING
                ),
                incident=result.value,
            )

        try:
            incident = self._gateway.get_incident(tenant_id, incident_id)
        except GatewayNotFoundError:
            return SLOAlertIncidentResult(
                alert_fingerprint=alert.fingerprint,
                alert_status=alert.status,
                action=SLOIncidentAction.RESOLUTION_WITHOUT_INCIDENT,
            )
        if (
            incident.incident_type != "slo_error_budget_burn"
            or incident.subject_resource_urn != definition.service_resource_urn
            or incident.details != details
        ):
            raise SLOIncidentValidationError(
                "resolved SLO alert does not match the immutable incident"
            )
        if incident.status is IncidentStatus.RESOLVED:
            return SLOAlertIncidentResult(
                alert_fingerprint=alert.fingerprint,
                alert_status=alert.status,
                action=SLOIncidentAction.ALREADY_RESOLVED,
                incident=incident,
            )
        try:
            resolved = self._gateway.transition_incident(
                tenant_id,
                incident_id,
                incident.state_version,
                IncidentStatus.RESOLVED,
                detector_subject,
                "Alertmanager reported the exact SLO alert episode resolved",
                {
                    "schema": "gda.slo_alert_resolution.v1",
                    "alertmanager_fingerprint": alert.fingerprint,
                    "alert_ended_at": _rfc3339(alert.ends_at),
                },
            )
        except GatewayConflictError:
            current = self._gateway.get_incident(tenant_id, incident_id)
            if current.status is not IncidentStatus.RESOLVED:
                raise
            resolved = current
        return SLOAlertIncidentResult(
            alert_fingerprint=alert.fingerprint,
            alert_status=alert.status,
            action=SLOIncidentAction.RESOLVED,
            incident=resolved,
        )

    def reconcile(
        self,
        tenant_id: str,
        webhook: AlertmanagerSLOWebhook,
        *,
        detector_subject: str,
    ) -> SLOAlertReconciliationResult:
        if _DETECTOR_RE.fullmatch(detector_subject) is None:
            raise SLOIncidentValidationError(
                "SLO incident detector must use a workload identity"
            )
        items = tuple(
            self._reconcile_one(tenant_id, alert, detector_subject)
            for alert in webhook.alerts
        )
        return SLOAlertReconciliationResult(
            tenant_id=tenant_id,
            items=items,
            created_count=sum(item.action is SLOIncidentAction.CREATED for item in items),
            resolved_count=sum(item.action is SLOIncidentAction.RESOLVED for item in items),
            unchanged_count=sum(
                item.action
                in {
                    SLOIncidentAction.EXISTING,
                    SLOIncidentAction.ALREADY_RESOLVED,
                    SLOIncidentAction.RESOLUTION_WITHOUT_INCIDENT,
                }
                for item in items
            ),
        )

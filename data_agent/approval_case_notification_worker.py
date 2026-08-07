"""Durable Alertmanager delivery for ApprovalCase lifecycle and SLA facts."""

from __future__ import annotations

import argparse
import logging
import os
import re
import signal
import socket
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from prometheus_client import start_http_server

from .approval_case_authority import ApprovalCaseAuthority
from .incident_notification_worker import (
    AlertmanagerV2Client,
    IncidentNotificationConfigurationError,
    IncidentNotificationDeliveryError,
    normalize_alertmanager_api_url,
)
from .observability import (
    approval_notification_cycle_duration,
    approval_notification_last_success_timestamp,
    approval_notification_operations,
)
from .platform_contracts import (
    ApprovalCaseNotificationEnvelope,
    ApprovalCaseNotificationKind,
    ApprovalCaseNotificationStatus,
)

LOGGER = logging.getLogger(__name__)
DEFAULT_DESTINATION_REF = "alertmanager:approval-default"
_ROUTE_NAMESPACE_PATTERN = re.compile(r"^[a-z0-9](?:[-a-z0-9]*[a-z0-9])?$")


def _record_operation(outcome: str, count: int = 1) -> None:
    try:
        approval_notification_operations.labels(outcome=outcome).inc(count)
    except Exception:
        LOGGER.exception("Could not record ApprovalCase notification metric")


def _observe_cycle(duration_seconds: float) -> None:
    try:
        approval_notification_cycle_duration.observe(duration_seconds)
    except Exception:
        LOGGER.exception("Could not record ApprovalCase notification cycle duration")


def _record_success_timestamp() -> None:
    try:
        approval_notification_last_success_timestamp.set_to_current_time()
    except Exception:
        LOGGER.exception("Could not record ApprovalCase notification success timestamp")


def _rfc3339(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def render_approval_case_alert(
    envelope: ApprovalCaseNotificationEnvelope,
    *,
    route_namespace: str | None = None,
) -> dict[str, Any]:
    notification = envelope.notification
    approval_case = envelope.approval_case
    event = envelope.event
    kind = notification.notification_kind
    if kind is ApprovalCaseNotificationKind.REQUESTED:
        lifecycle_status = "pending"
        summary = f"Approval required: {approval_case.action}"
        actor = event.actor_subject if event is not None else approval_case.requester_subject
        reason = event.reason if event is not None else approval_case.request_reason
    elif kind is ApprovalCaseNotificationKind.EXPIRED:
        lifecycle_status = "expired"
        summary = f"Approval SLA expired: {approval_case.action}"
        actor = "workload:approval-sla-monitor"
        reason = "ApprovalCase reached expires_at without a terminal decision"
    else:
        lifecycle_status = approval_case.status.value
        summary = f"Approval closed: {approval_case.action}"
        actor = event.actor_subject if event is not None else approval_case.decided_by or "unknown"
        reason = event.reason if event is not None else approval_case.decision_reason or "decided"

    alert: dict[str, Any] = {
        "labels": {
            "alertname": "GDAApprovalCase",
            "gda_tenant": approval_case.tenant_id,
            "gda_approval_case": approval_case.approval_case_ref,
            "gda_approval_action": approval_case.action,
            "severity": "warning",
        },
        "annotations": {
            "summary": summary,
            "gda_status": lifecycle_status,
            "gda_notification_kind": kind.value,
            "gda_reason": reason,
            "gda_actor": actor,
            "gda_target_resource": approval_case.target_resource_urn,
            "gda_target_fingerprint": approval_case.target_fingerprint,
            "gda_requester": approval_case.requester_subject,
            "gda_expires_at": _rfc3339(approval_case.expires_at),
            "gda_destination_ref": notification.destination_ref,
        },
        "startsAt": _rfc3339(approval_case.requested_at),
    }
    if kind is ApprovalCaseNotificationKind.DECIDED and approval_case.decided_at is not None:
        alert["endsAt"] = _rfc3339(approval_case.decided_at)
    if route_namespace is not None:
        alert["labels"]["namespace"] = route_namespace
    return alert


@dataclass(frozen=True)
class ApprovalCaseNotificationWorkerConfig:
    tenant_id: str
    worker_id: str
    alertmanager_url: str
    bearer_token_file: Path | None = None
    batch_size: int = 10
    lease_seconds: int = 60
    retry_delay_seconds: int = 30
    poll_interval_seconds: float = 5.0
    timeout_seconds: float = 10.0
    metrics_port: int = 0
    route_namespace: str | None = None

    @classmethod
    def from_env(cls) -> ApprovalCaseNotificationWorkerConfig:
        tenant_id = os.environ.get("GDA_APPROVAL_NOTIFICATION_TENANT_ID", "").strip()
        alertmanager_url = os.environ.get("GDA_ALERTMANAGER_URL", "").strip()
        if not tenant_id:
            raise IncidentNotificationConfigurationError(
                "GDA_APPROVAL_NOTIFICATION_TENANT_ID is required"
            )
        if not alertmanager_url:
            raise IncidentNotificationConfigurationError(
                "GDA_ALERTMANAGER_URL is required"
            )
        worker_id = os.environ.get(
            "GDA_APPROVAL_NOTIFICATION_WORKER_ID",
            f"worker:approval-alertmanager:{socket.gethostname()}:{os.getpid()}",
        ).strip()
        token_value = os.environ.get("GDA_ALERTMANAGER_BEARER_TOKEN_FILE", "").strip()
        route_namespace = os.environ.get(
            "GDA_APPROVAL_NOTIFICATION_ROUTE_NAMESPACE", ""
        ).strip()
        return cls(
            tenant_id=tenant_id,
            worker_id=worker_id,
            alertmanager_url=alertmanager_url,
            bearer_token_file=Path(token_value) if token_value else None,
            batch_size=int(os.environ.get("GDA_APPROVAL_NOTIFICATION_BATCH_SIZE", "10")),
            lease_seconds=int(
                os.environ.get("GDA_APPROVAL_NOTIFICATION_LEASE_SECONDS", "60")
            ),
            retry_delay_seconds=int(
                os.environ.get("GDA_APPROVAL_NOTIFICATION_RETRY_SECONDS", "30")
            ),
            poll_interval_seconds=float(
                os.environ.get("GDA_APPROVAL_NOTIFICATION_POLL_SECONDS", "5")
            ),
            timeout_seconds=float(os.environ.get("GDA_ALERTMANAGER_TIMEOUT_SECONDS", "10")),
            metrics_port=int(
                os.environ.get("GDA_APPROVAL_NOTIFICATION_METRICS_PORT", "0")
            ),
            route_namespace=route_namespace or None,
        )

    def validate(self) -> None:
        if not self.worker_id:
            raise IncidentNotificationConfigurationError("worker identity is required")
        if not 1 <= self.batch_size <= 100:
            raise IncidentNotificationConfigurationError(
                "notification batch size must be between 1 and 100"
            )
        if not 5 <= self.lease_seconds <= 3600:
            raise IncidentNotificationConfigurationError(
                "notification lease must be between 5 and 3600 seconds"
            )
        if not 0 <= self.retry_delay_seconds <= 86400:
            raise IncidentNotificationConfigurationError(
                "notification retry delay must be between 0 and 86400 seconds"
            )
        if self.poll_interval_seconds <= 0 or self.poll_interval_seconds > 300:
            raise IncidentNotificationConfigurationError(
                "notification poll interval must be between 0 and 300 seconds"
            )
        if not 0 <= self.metrics_port <= 65535:
            raise IncidentNotificationConfigurationError(
                "notification metrics port must be between 0 and 65535"
            )
        if self.route_namespace is not None and (
            len(self.route_namespace) > 63
            or _ROUTE_NAMESPACE_PATTERN.fullmatch(self.route_namespace) is None
        ):
            raise IncidentNotificationConfigurationError(
                "notification route namespace must be a Kubernetes DNS label"
            )
        normalize_alertmanager_api_url(self.alertmanager_url)


@dataclass(frozen=True)
class ApprovalCaseNotificationCycle:
    claimed: int
    delivered: int
    retrying: int
    dead_lettered: int


class ApprovalCaseNotificationWorker:
    def __init__(
        self,
        config: ApprovalCaseNotificationWorkerConfig,
        *,
        authority: ApprovalCaseAuthority | None = None,
        client: AlertmanagerV2Client | None = None,
    ) -> None:
        config.validate()
        self.config = config
        self.authority = authority or ApprovalCaseAuthority()
        self.client = client or AlertmanagerV2Client(
            config.alertmanager_url,
            timeout_seconds=config.timeout_seconds,
            bearer_token_file=config.bearer_token_file,
        )

    def run_once(self) -> ApprovalCaseNotificationCycle:
        started_at = time.monotonic()
        try:
            envelopes = self.authority.claim_notifications(
                self.config.tenant_id,
                self.config.worker_id,
                limit=self.config.batch_size,
                lease_seconds=self.config.lease_seconds,
            )
            _record_operation("claimed", len(envelopes))
            delivered = 0
            retrying = 0
            dead_lettered = 0
            for envelope in envelopes:
                notification = envelope.notification
                try:
                    self.client.deliver_alert(
                        render_approval_case_alert(
                            envelope,
                            route_namespace=self.config.route_namespace,
                        ),
                        destination_ref=notification.destination_ref,
                        expected_destination_ref=DEFAULT_DESTINATION_REF,
                        user_agent="gis-data-agent-approval-worker/1",
                    )
                except (
                    IncidentNotificationConfigurationError,
                    IncidentNotificationDeliveryError,
                ) as exc:
                    failed = self.authority.fail_notification(
                        notification.tenant_id,
                        notification.notification_id,
                        worker_id=self.config.worker_id,
                        error=f"{type(exc).__name__}: {exc}",
                        retry_delay_seconds=self.config.retry_delay_seconds,
                    )
                    if failed.status is ApprovalCaseNotificationStatus.FAILED:
                        dead_lettered += 1
                        _record_operation("dead_lettered")
                    else:
                        retrying += 1
                        _record_operation("retrying")
                    LOGGER.warning(
                        "ApprovalCase notification %s delivery failed (%s)",
                        notification.notification_id,
                        failed.status.value,
                    )
                    continue
                self.authority.complete_notification(
                    notification.tenant_id,
                    notification.notification_id,
                    worker_id=self.config.worker_id,
                )
                delivered += 1
                _record_operation("delivered")
            cycle = ApprovalCaseNotificationCycle(
                claimed=len(envelopes),
                delivered=delivered,
                retrying=retrying,
                dead_lettered=dead_lettered,
            )
            _record_success_timestamp()
            return cycle
        except Exception:
            _record_operation("cycle_error")
            raise
        finally:
            _observe_cycle(time.monotonic() - started_at)

    def run(self, stop_event: threading.Event) -> None:
        while not stop_event.is_set():
            cycle = self.run_once()
            if cycle.claimed == 0:
                stop_event.wait(self.config.poll_interval_seconds)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Deliver governed ApprovalCase lifecycle and SLA alerts"
    )
    parser.add_argument("--once", action="store_true", help="Process one batch and exit")
    args = parser.parse_args(argv)
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    config = ApprovalCaseNotificationWorkerConfig.from_env()
    if config.metrics_port:
        start_http_server(config.metrics_port)
        LOGGER.info(
            "ApprovalCase notification metrics listening on port %s",
            config.metrics_port,
        )
    stop_event = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_args: stop_event.set())
    worker = ApprovalCaseNotificationWorker(config)
    try:
        if args.once:
            cycle = worker.run_once()
            LOGGER.info("ApprovalCase notification cycle: %s", cycle)
        else:
            worker.run(stop_event)
    finally:
        worker.client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

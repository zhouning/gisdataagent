"""Durable Alertmanager delivery for governed DataIncident events."""

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
from urllib.parse import urlsplit, urlunsplit

import httpx
from prometheus_client import start_http_server

from .observability import (
    incident_notification_cycle_duration,
    incident_notification_last_success_timestamp,
    incident_notification_operations,
)
from .platform_contracts import (
    IncidentNotificationEnvelope,
    IncidentNotificationStatus,
    IncidentStatus,
)
from .platform_gateway import PlatformGateway

LOGGER = logging.getLogger(__name__)
DEFAULT_DESTINATION_REF = "alertmanager:default"
_ROUTE_NAMESPACE_PATTERN = re.compile(r"^[a-z0-9](?:[-a-z0-9]*[a-z0-9])?$")


def _record_operation(outcome: str, count: int = 1) -> None:
    try:
        incident_notification_operations.labels(outcome=outcome).inc(count)
    except Exception:
        LOGGER.exception("Could not record DataIncident notification metric")


def _observe_cycle(duration_seconds: float) -> None:
    try:
        incident_notification_cycle_duration.observe(duration_seconds)
    except Exception:
        LOGGER.exception("Could not record DataIncident notification cycle duration")


def _record_success_timestamp() -> None:
    try:
        incident_notification_last_success_timestamp.set_to_current_time()
    except Exception:
        LOGGER.exception("Could not record DataIncident notification success timestamp")


class IncidentNotificationConfigurationError(RuntimeError):
    """Incident delivery worker configuration is incomplete or unsafe."""


class IncidentNotificationDeliveryError(RuntimeError):
    """Alertmanager did not accept an incident lifecycle update."""


def _rfc3339(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def normalize_alertmanager_api_url(value: str) -> str:
    """Validate a server-owned endpoint and resolve its v2 alerts route."""
    parts = urlsplit(value.strip())
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise IncidentNotificationConfigurationError(
            "Alertmanager URL must be an absolute http(s) endpoint"
        )
    if parts.username or parts.password:
        raise IncidentNotificationConfigurationError(
            "Alertmanager URL must not contain credentials"
        )
    if parts.query or parts.fragment:
        raise IncidentNotificationConfigurationError(
            "Alertmanager URL must not contain a query or fragment"
        )
    path = parts.path.rstrip("/")
    if not path.endswith("/api/v2/alerts"):
        path = f"{path}/api/v2/alerts"
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def render_alertmanager_alert(
    envelope: IncidentNotificationEnvelope,
    *,
    route_namespace: str | None = None,
) -> dict[str, Any]:
    """Render one stable-label Alertmanager v2 alert."""
    notification = envelope.notification
    incident = envelope.incident
    event = envelope.event
    alert: dict[str, Any] = {
        "labels": {
            "alertname": "GDADataIncident",
            "gda_tenant": incident.tenant_id,
            "gda_incident_id": str(incident.incident_id),
            "gda_run_id": str(incident.run_id),
            "gda_incident_type": incident.incident_type,
            "severity": incident.severity.value,
        },
        "annotations": {
            "summary": incident.summary,
            "gda_status": event.to_status.value,
            "gda_event_sequence": str(event.sequence_no),
            "gda_event_reason": event.reason,
            "gda_event_actor": event.actor_subject,
            "gda_incident_sha256": incident.incident_sha256,
            "gda_destination_ref": notification.destination_ref,
        },
        "startsAt": _rfc3339(incident.opened_at),
    }
    if event.to_status == IncidentStatus.RESOLVED:
        alert["endsAt"] = _rfc3339(event.occurred_at)
    if route_namespace is not None:
        alert["labels"]["namespace"] = route_namespace
    return alert


class AlertmanagerV2Client:
    """Small synchronous client for Alertmanager's v2 alert ingestion API."""

    def __init__(
        self,
        api_url: str,
        *,
        timeout_seconds: float = 10.0,
        bearer_token_file: Path | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if timeout_seconds <= 0 or timeout_seconds > 120:
            raise IncidentNotificationConfigurationError(
                "Alertmanager timeout must be between 0 and 120 seconds"
            )
        if bearer_token_file is not None:
            token_path = bearer_token_file.expanduser().resolve()
            if not token_path.is_file():
                raise IncidentNotificationConfigurationError(
                    "Alertmanager bearer token file does not exist"
                )
            self._bearer_token_file = token_path
        else:
            self._bearer_token_file = None
        self.api_url = normalize_alertmanager_api_url(api_url)
        self._client = httpx.Client(
            timeout=timeout_seconds,
            follow_redirects=False,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> AlertmanagerV2Client:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _headers(
        self,
        user_agent: str = "gis-data-agent-incident-worker/1",
    ) -> dict[str, str]:
        headers = {"User-Agent": user_agent}
        if self._bearer_token_file is not None:
            token = self._bearer_token_file.read_text(encoding="utf-8").strip()
            if not token:
                raise IncidentNotificationConfigurationError(
                    "Alertmanager bearer token file is empty"
                )
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def deliver_alert(
        self,
        alert: dict[str, Any],
        *,
        destination_ref: str,
        expected_destination_ref: str = DEFAULT_DESTINATION_REF,
        user_agent: str = "gis-data-agent-incident-worker/1",
    ) -> dict[str, Any]:
        if destination_ref != expected_destination_ref:
            raise IncidentNotificationDeliveryError(
                "no Alertmanager adapter is configured for the destination"
            )
        try:
            response = self._client.post(
                self.api_url,
                json=[alert],
                headers=self._headers(user_agent),
            )
        except (httpx.HTTPError, OSError) as exc:
            raise IncidentNotificationDeliveryError(
                f"Alertmanager request failed: {type(exc).__name__}"
            ) from exc
        if not 200 <= response.status_code < 300:
            raise IncidentNotificationDeliveryError(
                f"Alertmanager rejected notification with HTTP {response.status_code}"
            )
        return {
            "schema": "gda.alertmanager_provider_receipt.v1",
            "provider": "alertmanager",
            "accepted": True,
            "http_status": response.status_code,
            "destination_ref": destination_ref,
            "accepted_at": _rfc3339(datetime.now(UTC)),
        }

    def deliver(
        self,
        envelope: IncidentNotificationEnvelope,
        *,
        route_namespace: str | None = None,
    ) -> dict[str, Any]:
        return self.deliver_alert(
            render_alertmanager_alert(envelope, route_namespace=route_namespace),
            destination_ref=envelope.notification.destination_ref,
        )


@dataclass(frozen=True)
class IncidentNotificationWorkerConfig:
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
    def from_env(cls) -> IncidentNotificationWorkerConfig:
        tenant_id = os.environ.get("GDA_INCIDENT_NOTIFICATION_TENANT_ID", "").strip()
        alertmanager_url = os.environ.get("GDA_ALERTMANAGER_URL", "").strip()
        if not tenant_id:
            raise IncidentNotificationConfigurationError(
                "GDA_INCIDENT_NOTIFICATION_TENANT_ID is required"
            )
        if not alertmanager_url:
            raise IncidentNotificationConfigurationError(
                "GDA_ALERTMANAGER_URL is required"
            )
        worker_id = os.environ.get(
            "GDA_INCIDENT_NOTIFICATION_WORKER_ID",
            f"worker:incident-alertmanager:{socket.gethostname()}:{os.getpid()}",
        ).strip()
        token_value = os.environ.get("GDA_ALERTMANAGER_BEARER_TOKEN_FILE", "").strip()
        route_namespace = os.environ.get(
            "GDA_INCIDENT_NOTIFICATION_ROUTE_NAMESPACE", ""
        ).strip()
        return cls(
            tenant_id=tenant_id,
            worker_id=worker_id,
            alertmanager_url=alertmanager_url,
            bearer_token_file=Path(token_value) if token_value else None,
            batch_size=int(os.environ.get("GDA_INCIDENT_NOTIFICATION_BATCH_SIZE", "10")),
            lease_seconds=int(
                os.environ.get("GDA_INCIDENT_NOTIFICATION_LEASE_SECONDS", "60")
            ),
            retry_delay_seconds=int(
                os.environ.get("GDA_INCIDENT_NOTIFICATION_RETRY_SECONDS", "30")
            ),
            poll_interval_seconds=float(
                os.environ.get("GDA_INCIDENT_NOTIFICATION_POLL_SECONDS", "5")
            ),
            timeout_seconds=float(os.environ.get("GDA_ALERTMANAGER_TIMEOUT_SECONDS", "10")),
            metrics_port=int(
                os.environ.get("GDA_INCIDENT_NOTIFICATION_METRICS_PORT", "0")
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
class IncidentNotificationCycle:
    claimed: int
    delivered: int
    retrying: int
    dead_lettered: int


class IncidentNotificationWorker:
    """Claim, deliver, and acknowledge incident notification outbox rows."""

    def __init__(
        self,
        config: IncidentNotificationWorkerConfig,
        *,
        gateway: PlatformGateway | None = None,
        client: AlertmanagerV2Client | None = None,
    ) -> None:
        config.validate()
        self.config = config
        self.gateway = gateway or PlatformGateway()
        self.client = client or AlertmanagerV2Client(
            config.alertmanager_url,
            timeout_seconds=config.timeout_seconds,
            bearer_token_file=config.bearer_token_file,
        )

    def run_once(self) -> IncidentNotificationCycle:
        started_at = time.monotonic()
        try:
            envelopes = self.gateway.claim_incident_notifications(
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
                    provider_receipt = self.client.deliver(
                        envelope, route_namespace=self.config.route_namespace
                    )
                    if not isinstance(provider_receipt, dict):
                        raise IncidentNotificationDeliveryError(
                            "Alertmanager adapter returned no provider receipt"
                        )
                except (
                    IncidentNotificationConfigurationError,
                    IncidentNotificationDeliveryError,
                ) as exc:
                    failed = self.gateway.fail_incident_notification(
                        notification.tenant_id,
                        notification.notification_id,
                        worker_id=self.config.worker_id,
                        error=f"{type(exc).__name__}: {exc}",
                        retry_delay_seconds=self.config.retry_delay_seconds,
                    )
                    if failed.status == IncidentNotificationStatus.FAILED:
                        dead_lettered += 1
                        _record_operation("dead_lettered")
                    else:
                        retrying += 1
                        _record_operation("retrying")
                    LOGGER.warning(
                        "Incident notification %s delivery failed (%s)",
                        notification.notification_id,
                        failed.status.value,
                    )
                    continue
                self.gateway.complete_incident_notification(
                    notification.tenant_id,
                    notification.notification_id,
                    worker_id=self.config.worker_id,
                    provider_receipt=provider_receipt,
                )
                delivered += 1
                _record_operation("delivered")
            cycle = IncidentNotificationCycle(
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
        description="Deliver governed DataIncident lifecycle events to Alertmanager"
    )
    parser.add_argument("--once", action="store_true", help="Process one batch and exit")
    args = parser.parse_args(argv)
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    config = IncidentNotificationWorkerConfig.from_env()
    if config.metrics_port:
        start_http_server(config.metrics_port)
        LOGGER.info(
            "Incident notification metrics listening on port %s", config.metrics_port
        )
    stop_event = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_args: stop_event.set())
    worker = IncidentNotificationWorker(config)
    try:
        if args.once:
            cycle = worker.run_once()
            LOGGER.info("Incident notification cycle: %s", cycle)
        else:
            worker.run(stop_event)
    finally:
        worker.client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

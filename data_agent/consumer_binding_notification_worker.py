"""Durable Alertmanager delivery for ConsumerBinding migration notices."""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import signal
import socket
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from prometheus_client import start_http_server

from .consumer_binding import (
    ConsumerBindingMigrationNotificationEnvelope,
    ConsumerMigrationNotificationDeliveryStatus,
)
from .incident_notification_worker import (
    AlertmanagerV2Client,
    IncidentNotificationConfigurationError,
    IncidentNotificationDeliveryError,
    normalize_alertmanager_api_url,
)
from .observability import (
    consumer_binding_notification_cycle_duration,
    consumer_binding_notification_last_success_timestamp,
    consumer_binding_notification_operations,
)
from .platform_gateway import PlatformGateway

LOGGER = logging.getLogger(__name__)
DEFAULT_DESTINATION_REF = "alertmanager:consumer-binding-default"
_ROUTE_NAMESPACE_PATTERN = re.compile(r"^[a-z0-9](?:[-a-z0-9]*[a-z0-9])?$")
_ACTOR_PATTERN = re.compile(r"^(human|workload|agent|service):[^\s]{1,511}$")


def _record_operation(outcome: str, count: int = 1) -> None:
    try:
        consumer_binding_notification_operations.labels(outcome=outcome).inc(count)
    except Exception:
        LOGGER.exception("Could not record ConsumerBinding notification metric")


def _observe_cycle(duration_seconds: float) -> None:
    try:
        consumer_binding_notification_cycle_duration.observe(duration_seconds)
    except Exception:
        LOGGER.exception("Could not record ConsumerBinding notification cycle duration")


def _record_success_timestamp() -> None:
    try:
        consumer_binding_notification_last_success_timestamp.set_to_current_time()
    except Exception:
        LOGGER.exception("Could not record ConsumerBinding notification success timestamp")


def render_consumer_binding_migration_alert(
    envelope: ConsumerBindingMigrationNotificationEnvelope,
    *,
    route_namespace: str | None = None,
) -> dict[str, Any]:
    notification = envelope.notification
    binding = envelope.binding
    state = envelope.migration_state
    alert: dict[str, Any] = {
        "labels": {
            "alertname": "GDAConsumerBindingMigration",
            "gda_tenant": binding.tenant_id,
            "gda_binding_id": str(binding.binding_id),
            "gda_consumer_ref": binding.consumer_ref,
            "gda_from_product_version_id": str(state.from_product_version_id),
            "gda_to_product_version_id": str(state.to_product_version_id),
            "severity": "warning",
        },
        "annotations": {
            "summary": f"Consumer migration required: {binding.consumer_ref}",
            "gda_product_urn": binding.product_urn,
            "gda_purpose": binding.purpose,
            "gda_compatibility_conclusion": state.compatibility_conclusion.value,
            "gda_migration_deadline": (
                state.migration_deadline.isoformat()
                if state.migration_deadline is not None
                else ""
            ),
            "gda_source_state_sha256": state.state_sha256,
            "gda_destination_ref": notification.destination_ref,
        },
        "startsAt": state.recorded_at.isoformat().replace("+00:00", "Z"),
    }
    if route_namespace is not None:
        alert["labels"]["namespace"] = route_namespace
    impacts = envelope.gis_service_impacts
    if impacts:
        alert["labels"]["gda_gis_service_impact_count"] = str(len(impacts))
        if len(impacts) == 1:
            impact = impacts[0]
            alert["labels"].update(
                {
                    "gda_service_urn": impact.service_urn,
                    "gda_service_consumer_binding_id": str(
                        impact.source_service_consumer_binding_id
                    ),
                    "gda_source_service_release_binding_id": str(
                        impact.source_service_release_binding_id
                    ),
                    "gda_target_service_release_binding_id": str(
                        impact.target_service_release_binding_id
                    ),
                    "gda_service_impact_sha256": impact.impact_sha256,
                }
            )
            alert["annotations"].update(
                {
                    "gda_source_service_definition_version_id": str(
                        impact.source_service_definition_version_id
                    ),
                    "gda_target_service_definition_version_id": str(
                        impact.target_service_definition_version_id
                    ),
                    "gda_source_service_consumer_binding_sha256": (
                        impact.source_binding_sha256
                    ),
                    "gda_source_service_release_binding_id": str(
                        impact.source_service_release_binding_id
                    ),
                    "gda_target_service_release_binding_id": str(
                        impact.target_service_release_binding_id
                    ),
                    "gda_service_impact_sha256": impact.impact_sha256,
                }
            )
        else:
            alert["annotations"]["gda_service_impacts_json"] = json.dumps(
                [impact.model_dump(mode="json") for impact in impacts],
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            )
    return alert


@dataclass(frozen=True)
class ConsumerBindingNotificationWorkerConfig:
    tenant_id: str
    worker_id: str
    recorded_by: str
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
    def from_env(cls) -> ConsumerBindingNotificationWorkerConfig:
        tenant_id = os.environ.get(
            "GDA_CONSUMER_BINDING_NOTIFICATION_TENANT_ID", ""
        ).strip()
        alertmanager_url = os.environ.get("GDA_ALERTMANAGER_URL", "").strip()
        if not tenant_id:
            raise IncidentNotificationConfigurationError(
                "GDA_CONSUMER_BINDING_NOTIFICATION_TENANT_ID is required"
            )
        if not alertmanager_url:
            raise IncidentNotificationConfigurationError(
                "GDA_ALERTMANAGER_URL is required"
            )
        worker_id = os.environ.get(
            "GDA_CONSUMER_BINDING_NOTIFICATION_WORKER_ID",
            f"worker:consumer-binding-alertmanager:{socket.gethostname()}:{os.getpid()}",
        ).strip()
        recorded_by = os.environ.get(
            "GDA_CONSUMER_BINDING_NOTIFICATION_RECORDED_BY",
            "service:consumer-binding-notification-worker",
        ).strip()
        token_value = os.environ.get("GDA_ALERTMANAGER_BEARER_TOKEN_FILE", "").strip()
        route_namespace = os.environ.get(
            "GDA_CONSUMER_BINDING_NOTIFICATION_ROUTE_NAMESPACE", ""
        ).strip()
        return cls(
            tenant_id=tenant_id,
            worker_id=worker_id,
            recorded_by=recorded_by,
            alertmanager_url=alertmanager_url,
            bearer_token_file=Path(token_value) if token_value else None,
            batch_size=int(
                os.environ.get("GDA_CONSUMER_BINDING_NOTIFICATION_BATCH_SIZE", "10")
            ),
            lease_seconds=int(
                os.environ.get("GDA_CONSUMER_BINDING_NOTIFICATION_LEASE_SECONDS", "60")
            ),
            retry_delay_seconds=int(
                os.environ.get("GDA_CONSUMER_BINDING_NOTIFICATION_RETRY_SECONDS", "30")
            ),
            poll_interval_seconds=float(
                os.environ.get("GDA_CONSUMER_BINDING_NOTIFICATION_POLL_SECONDS", "5")
            ),
            timeout_seconds=float(os.environ.get("GDA_ALERTMANAGER_TIMEOUT_SECONDS", "10")),
            metrics_port=int(
                os.environ.get("GDA_CONSUMER_BINDING_NOTIFICATION_METRICS_PORT", "0")
            ),
            route_namespace=route_namespace or None,
        )

    def validate(self) -> None:
        if not self.worker_id:
            raise IncidentNotificationConfigurationError("worker identity is required")
        if _ACTOR_PATTERN.fullmatch(self.recorded_by) is None:
            raise IncidentNotificationConfigurationError(
                "recorded_by must use a typed platform subject"
            )
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
class ConsumerBindingNotificationCycle:
    claimed: int
    delivered: int
    retrying: int
    dead_lettered: int


class ConsumerBindingNotificationWorker:
    def __init__(
        self,
        config: ConsumerBindingNotificationWorkerConfig,
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

    def run_once(self) -> ConsumerBindingNotificationCycle:
        started_at = time.monotonic()
        try:
            envelopes = self.gateway.claim_consumer_binding_migration_notifications(
                self.config.tenant_id,
                self.config.worker_id,
                recorded_by=self.config.recorded_by,
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
                    provider_receipt = self.client.deliver_alert(
                        render_consumer_binding_migration_alert(
                            envelope,
                            route_namespace=self.config.route_namespace,
                        ),
                        destination_ref=notification.destination_ref,
                        expected_destination_ref=DEFAULT_DESTINATION_REF,
                        user_agent="gis-data-agent-consumer-binding-worker/1",
                    )
                except (
                    IncidentNotificationConfigurationError,
                    IncidentNotificationDeliveryError,
                ) as exc:
                    settlement = (
                        self.gateway.fail_consumer_binding_migration_notification(
                            notification.tenant_id,
                            notification.notification_id,
                            worker_id=self.config.worker_id,
                            recorded_by=self.config.recorded_by,
                            error=f"{type(exc).__name__}: {exc}",
                            retry_delay_seconds=self.config.retry_delay_seconds,
                        )
                    )
                    if (
                        settlement.notification.status
                        is ConsumerMigrationNotificationDeliveryStatus.FAILED
                    ):
                        dead_lettered += 1
                        _record_operation("dead_lettered")
                    else:
                        retrying += 1
                        _record_operation("retrying")
                    LOGGER.warning(
                        "ConsumerBinding notification %s delivery failed (%s)",
                        notification.notification_id,
                        settlement.notification.status.value,
                    )
                    continue
                self.gateway.complete_consumer_binding_migration_notification(
                    notification.tenant_id,
                    notification.notification_id,
                    worker_id=self.config.worker_id,
                    recorded_by=self.config.recorded_by,
                    provider_receipt=provider_receipt,
                )
                delivered += 1
                _record_operation("delivered")
            cycle = ConsumerBindingNotificationCycle(
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
        description="Deliver governed ConsumerBinding migration notifications"
    )
    parser.add_argument("--once", action="store_true", help="Process one batch and exit")
    args = parser.parse_args(argv)
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    config = ConsumerBindingNotificationWorkerConfig.from_env()
    if config.metrics_port:
        start_http_server(config.metrics_port)
        LOGGER.info(
            "ConsumerBinding notification metrics listening on port %s",
            config.metrics_port,
        )
    stop_event = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_args: stop_event.set())
    worker = ConsumerBindingNotificationWorker(config)
    try:
        if args.once:
            cycle = worker.run_once()
            LOGGER.info("ConsumerBinding notification cycle: %s", cycle)
        else:
            worker.run(stop_event)
    finally:
        worker.client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Durable HTTP CloudEvents delivery for immutable PlatformRun events."""

from __future__ import annotations

import argparse
import logging
import os
import signal
import socket
import threading
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import httpx

from .platform_gateway import PlatformGateway
from .platform_run_events import (
    DEFAULT_PLATFORM_RUN_EVENT_DESTINATION,
    PlatformRunEventDeliveryStatus,
    PlatformRunEventEnvelope,
)

LOGGER = logging.getLogger(__name__)


class PlatformRunEventWorkerConfigurationError(RuntimeError):
    """Run event delivery worker configuration is incomplete or unsafe."""


class PlatformRunEventDeliveryError(RuntimeError):
    """The configured CloudEvents receiver did not accept an event."""


def normalize_cloudevents_url(value: str) -> str:
    """Validate a server-owned HTTP CloudEvents receiver URL."""
    parts = urlsplit(value.strip())
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise PlatformRunEventWorkerConfigurationError(
            "CloudEvents receiver URL must be an absolute http(s) endpoint"
        )
    if parts.username or parts.password:
        raise PlatformRunEventWorkerConfigurationError(
            "CloudEvents receiver URL must not contain credentials"
        )
    if parts.query or parts.fragment:
        raise PlatformRunEventWorkerConfigurationError(
            "CloudEvents receiver URL must not contain a query or fragment"
        )
    return urlunsplit((parts.scheme, parts.netloc, parts.path or "/", "", ""))


class CloudEventsHttpClient:
    """Small synchronous client for CloudEvents structured-content delivery."""

    def __init__(
        self,
        receiver_url: str,
        *,
        timeout_seconds: float = 10.0,
        bearer_token_file: Path | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if timeout_seconds <= 0 or timeout_seconds > 120:
            raise PlatformRunEventWorkerConfigurationError(
                "CloudEvents timeout must be between 0 and 120 seconds"
            )
        if bearer_token_file is not None:
            token_path = bearer_token_file.expanduser().resolve()
            if not token_path.is_file():
                raise PlatformRunEventWorkerConfigurationError(
                    "CloudEvents bearer token file does not exist"
                )
            self._bearer_token_file = token_path
        else:
            self._bearer_token_file = None
        self.receiver_url = normalize_cloudevents_url(receiver_url)
        self._client = httpx.Client(
            timeout=timeout_seconds,
            follow_redirects=False,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> CloudEventsHttpClient:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _headers(
        self,
        user_agent: str = "geospatial-data-agent-run-event-worker/1",
    ) -> dict[str, str]:
        headers = {
            "Content-Type": "application/cloudevents+json",
            "User-Agent": user_agent,
        }
        if self._bearer_token_file is not None:
            token = self._bearer_token_file.read_text(encoding="utf-8").strip()
            if not token:
                raise PlatformRunEventWorkerConfigurationError(
                    "CloudEvents bearer token file is empty"
                )
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def deliver(
        self,
        envelope: PlatformRunEventEnvelope,
        *,
        expected_destination_ref: str = DEFAULT_PLATFORM_RUN_EVENT_DESTINATION,
    ) -> None:
        if envelope.delivery.destination_ref != expected_destination_ref:
            raise PlatformRunEventDeliveryError(
                "no CloudEvents adapter is configured for the destination"
            )
        payload = envelope.to_cloudevent().model_dump(
            mode="json",
            exclude_none=True,
        )
        try:
            response = self._client.post(
                self.receiver_url,
                json=payload,
                headers=self._headers(),
            )
        except (httpx.HTTPError, OSError) as exc:
            raise PlatformRunEventDeliveryError(
                f"CloudEvents request failed: {type(exc).__name__}"
            ) from exc
        if not 200 <= response.status_code < 300:
            raise PlatformRunEventDeliveryError(
                f"CloudEvents receiver rejected delivery with HTTP {response.status_code}"
            )


@dataclass(frozen=True)
class PlatformRunEventWorkerConfig:
    tenant_id: str
    worker_id: str
    receiver_url: str
    bearer_token_file: Path | None = None
    batch_size: int = 10
    lease_seconds: int = 60
    retry_delay_seconds: int = 30
    poll_interval_seconds: float = 5.0
    timeout_seconds: float = 10.0

    @classmethod
    def from_env(cls) -> PlatformRunEventWorkerConfig:
        tenant_id = os.environ.get("GDA_PLATFORM_RUN_EVENT_TENANT_ID", "").strip()
        receiver_url = os.environ.get("GDA_PLATFORM_RUN_EVENT_URL", "").strip()
        if not tenant_id:
            raise PlatformRunEventWorkerConfigurationError(
                "GDA_PLATFORM_RUN_EVENT_TENANT_ID is required"
            )
        if not receiver_url:
            raise PlatformRunEventWorkerConfigurationError(
                "GDA_PLATFORM_RUN_EVENT_URL is required"
            )
        worker_id = os.environ.get(
            "GDA_PLATFORM_RUN_EVENT_WORKER_ID",
            f"worker:platform-run-events:{socket.gethostname()}:{os.getpid()}",
        ).strip()
        token_value = os.environ.get(
            "GDA_PLATFORM_RUN_EVENT_BEARER_TOKEN_FILE", ""
        ).strip()
        return cls(
            tenant_id=tenant_id,
            worker_id=worker_id,
            receiver_url=receiver_url,
            bearer_token_file=Path(token_value) if token_value else None,
            batch_size=int(os.environ.get("GDA_PLATFORM_RUN_EVENT_BATCH_SIZE", "10")),
            lease_seconds=int(
                os.environ.get("GDA_PLATFORM_RUN_EVENT_LEASE_SECONDS", "60")
            ),
            retry_delay_seconds=int(
                os.environ.get("GDA_PLATFORM_RUN_EVENT_RETRY_SECONDS", "30")
            ),
            poll_interval_seconds=float(
                os.environ.get("GDA_PLATFORM_RUN_EVENT_POLL_SECONDS", "5")
            ),
            timeout_seconds=float(
                os.environ.get("GDA_PLATFORM_RUN_EVENT_TIMEOUT_SECONDS", "10")
            ),
        )

    def validate(self) -> None:
        if not self.worker_id:
            raise PlatformRunEventWorkerConfigurationError(
                "worker identity is required"
            )
        if not 1 <= self.batch_size <= 100:
            raise PlatformRunEventWorkerConfigurationError(
                "delivery batch size must be between 1 and 100"
            )
        if not 5 <= self.lease_seconds <= 3600:
            raise PlatformRunEventWorkerConfigurationError(
                "delivery lease must be between 5 and 3600 seconds"
            )
        if not 0 <= self.retry_delay_seconds <= 86400:
            raise PlatformRunEventWorkerConfigurationError(
                "delivery retry delay must be between 0 and 86400 seconds"
            )
        if self.poll_interval_seconds <= 0 or self.poll_interval_seconds > 300:
            raise PlatformRunEventWorkerConfigurationError(
                "delivery poll interval must be between 0 and 300 seconds"
            )
        normalize_cloudevents_url(self.receiver_url)


@dataclass(frozen=True)
class PlatformRunEventCycle:
    claimed: int
    delivered: int
    retrying: int
    dead_lettered: int


class PlatformRunEventWorker:
    """Claim, deliver, and acknowledge PlatformRun event outbox rows."""

    def __init__(
        self,
        config: PlatformRunEventWorkerConfig,
        *,
        gateway: PlatformGateway | None = None,
        client: CloudEventsHttpClient | None = None,
    ) -> None:
        config.validate()
        self.config = config
        self.gateway = gateway or PlatformGateway()
        self.client = client or CloudEventsHttpClient(
            config.receiver_url,
            timeout_seconds=config.timeout_seconds,
            bearer_token_file=config.bearer_token_file,
        )

    def run_once(self) -> PlatformRunEventCycle:
        envelopes = self.gateway.claim_platform_run_event_deliveries(
            self.config.tenant_id,
            self.config.worker_id,
            limit=self.config.batch_size,
            lease_seconds=self.config.lease_seconds,
        )
        delivered = 0
        retrying = 0
        dead_lettered = 0
        for envelope in envelopes:
            delivery = envelope.delivery
            try:
                self.client.deliver(envelope)
            except (
                PlatformRunEventWorkerConfigurationError,
                PlatformRunEventDeliveryError,
            ) as exc:
                failed = self.gateway.fail_platform_run_event_delivery(
                    delivery.tenant_id,
                    delivery.delivery_id,
                    worker_id=self.config.worker_id,
                    error=f"{type(exc).__name__}: {exc}",
                    retry_delay_seconds=self.config.retry_delay_seconds,
                )
                if failed.status == PlatformRunEventDeliveryStatus.FAILED:
                    dead_lettered += 1
                else:
                    retrying += 1
                LOGGER.warning(
                    "PlatformRun event delivery %s failed (%s)",
                    delivery.delivery_id,
                    failed.status.value,
                )
                continue
            self.gateway.complete_platform_run_event_delivery(
                delivery.tenant_id,
                delivery.delivery_id,
                worker_id=self.config.worker_id,
            )
            delivered += 1
        return PlatformRunEventCycle(
            claimed=len(envelopes),
            delivered=delivered,
            retrying=retrying,
            dead_lettered=dead_lettered,
        )

    def run(self, stop_event: threading.Event) -> None:
        while not stop_event.is_set():
            cycle = self.run_once()
            if cycle.claimed == 0:
                stop_event.wait(self.config.poll_interval_seconds)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Deliver immutable PlatformRun status events as CloudEvents"
    )
    parser.add_argument("--once", action="store_true", help="Process one batch and exit")
    args = parser.parse_args(argv)
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    config = PlatformRunEventWorkerConfig.from_env()
    stop_event = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_args: stop_event.set())
    worker = PlatformRunEventWorker(config)
    try:
        if args.once:
            cycle = worker.run_once()
            LOGGER.info("PlatformRun event delivery cycle: %s", cycle)
        else:
            worker.run(stop_event)
    finally:
        worker.client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

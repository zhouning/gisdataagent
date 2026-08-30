"""Reconciled OpenMetadata projection for governed lineage outbox changes."""

from __future__ import annotations

import argparse
import logging
import os
import signal
import socket
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit
from uuid import UUID

import httpx

from .metadata_fabric import (
    MetadataChangeStatus,
    MetadataFabricBinding,
    MetadataLineageProjectionEnvelope,
)
from .platform_gateway import PlatformGateway
from .provider_credentials import (
    resolve_bearer_token_file,
    validate_bearer_token_file,
)

LOGGER = logging.getLogger(__name__)
DEFAULT_DESTINATION_REF = "openmetadata:default"
MAX_HTTP_REQUESTS_PER_DELIVERY = 3


class OpenMetadataLineageConfigurationError(RuntimeError):
    """OpenMetadata projection configuration is incomplete or unsafe."""


class OpenMetadataLineageDeliveryError(RuntimeError):
    """OpenMetadata lineage could not be proven after a delivery attempt."""


class OpenMetadataLineageBindingError(OpenMetadataLineageDeliveryError):
    """A lineage endpoint has no usable OpenMetadata crosswalk binding."""


def normalize_openmetadata_api_url(value: str) -> str:
    """Validate a server-owned URL and resolve its OpenMetadata v1 API root."""
    parts = urlsplit(value.strip())
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise OpenMetadataLineageConfigurationError(
            "OpenMetadata URL must be an absolute http(s) endpoint"
        )
    if parts.username or parts.password:
        raise OpenMetadataLineageConfigurationError(
            "OpenMetadata URL must not contain credentials"
        )
    if parts.query or parts.fragment:
        raise OpenMetadataLineageConfigurationError(
            "OpenMetadata URL must not contain a query or fragment"
        )
    try:
        hostname = parts.hostname
        _port = parts.port
    except ValueError as exc:
        raise OpenMetadataLineageConfigurationError(
            "OpenMetadata URL contains an invalid host or port"
        ) from exc
    if not hostname:
        raise OpenMetadataLineageConfigurationError(
            "OpenMetadata URL must contain a host"
        )

    path = parts.path.rstrip("/")
    if path.endswith("/api/v1"):
        api_path = path
    else:
        if path.endswith("/api") or "/api/" in path:
            raise OpenMetadataLineageConfigurationError(
                "OpenMetadata URL must identify the server root or /api/v1"
            )
        api_path = f"{path}/api/v1"
    return urlunsplit((parts.scheme, parts.netloc, api_path, "", ""))


def _resolve_token_file(path: Path) -> Path:
    return validate_bearer_token_file(
        path,
        error_factory=OpenMetadataLineageConfigurationError,
        label="OpenMetadata bearer token file",
    )


def render_openmetadata_lineage(
    source: MetadataFabricBinding,
    target: MetadataFabricBinding,
) -> dict[str, Any]:
    """Render the minimal provider edge; causal detail remains in the GDA ledger."""
    return {
        "edge": {
            "fromEntity": {
                "id": str(UUID(source.external_object_id)),
                "type": source.external_object_type,
            },
            "toEntity": {
                "id": str(UUID(target.external_object_id)),
                "type": target.external_object_type,
            },
        }
    }


class OpenMetadataLineageClient:
    """OpenMetadata 1.13.1 lineage client with read-after-write reconciliation."""

    def __init__(
        self,
        api_url: str,
        *,
        bearer_token_file: Path,
        timeout_seconds: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if timeout_seconds <= 0 or timeout_seconds > 120:
            raise OpenMetadataLineageConfigurationError(
                "OpenMetadata timeout must be between 0 and 120 seconds"
            )
        self.api_url = normalize_openmetadata_api_url(api_url)
        self._bearer_token_file = _resolve_token_file(bearer_token_file)
        self._client = httpx.Client(
            timeout=timeout_seconds,
            follow_redirects=False,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> OpenMetadataLineageClient:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _headers(self) -> dict[str, str]:
        try:
            token = self._bearer_token_file.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise OpenMetadataLineageConfigurationError(
                "OpenMetadata bearer token file could not be read"
            ) from exc
        if not token or any(character.isspace() for character in token):
            raise OpenMetadataLineageConfigurationError(
                "OpenMetadata bearer token file must contain one non-empty token"
            )
        return {
            "Authorization": f"Bearer {token}",
            "User-Agent": "gis-data-agent-openmetadata-lineage-worker/1",
        }

    def _lineage_exists(
        self,
        source: MetadataFabricBinding,
        target: MetadataFabricBinding,
    ) -> bool:
        source_id = str(UUID(source.external_object_id))
        target_id = str(UUID(target.external_object_id))
        source_type = quote(source.external_object_type, safe="")
        url = f"{self.api_url}/lineage/{source_type}/{source_id}"
        try:
            response = self._client.get(
                url,
                params={"upstreamDepth": 0, "downstreamDepth": 1},
                headers=self._headers(),
            )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise OpenMetadataLineageDeliveryError(
                f"OpenMetadata lineage query failed: {type(exc).__name__}"
            ) from exc
        if not 200 <= response.status_code < 300:
            raise OpenMetadataLineageDeliveryError(
                f"OpenMetadata lineage query returned HTTP {response.status_code}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise OpenMetadataLineageDeliveryError(
                "OpenMetadata lineage query returned invalid JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise OpenMetadataLineageDeliveryError(
                "OpenMetadata lineage query returned an invalid document"
            )
        entity = payload.get("entity")
        if not isinstance(entity, dict) or entity.get("id") != source_id:
            raise OpenMetadataLineageDeliveryError(
                "OpenMetadata lineage query returned the wrong source entity"
            )
        downstream_edges = payload.get("downstreamEdges") or []
        if not isinstance(downstream_edges, list):
            raise OpenMetadataLineageDeliveryError(
                "OpenMetadata lineage query returned invalid downstream edges"
            )
        return any(
            isinstance(edge, dict)
            and edge.get("fromEntity") == source_id
            and edge.get("toEntity") == target_id
            for edge in downstream_edges
        )

    def deliver(self, envelope: MetadataLineageProjectionEnvelope) -> None:
        change = envelope.change
        if change.destination_ref != DEFAULT_DESTINATION_REF:
            raise OpenMetadataLineageDeliveryError(
                "no OpenMetadata adapter is configured for the destination"
            )
        source = envelope.source_binding
        target = envelope.target_binding
        if source is None or target is None:
            missing = []
            if source is None:
                missing.append("source")
            if target is None:
                missing.append("target")
            raise OpenMetadataLineageBindingError(
                f"OpenMetadata {' and '.join(missing)} binding is missing"
            )

        if self._lineage_exists(source, target):
            return

        request = render_openmetadata_lineage(source, target)
        try:
            response = self._client.put(
                f"{self.api_url}/lineage",
                json=request,
                headers=self._headers(),
            )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            try:
                confirmed = self._lineage_exists(source, target)
            except OpenMetadataLineageDeliveryError as reconciliation_error:
                raise OpenMetadataLineageDeliveryError(
                    "OpenMetadata write outcome is unknown and reconciliation failed"
                ) from reconciliation_error
            if confirmed:
                return
            raise OpenMetadataLineageDeliveryError(
                f"OpenMetadata write was not confirmed after {type(exc).__name__}"
            ) from exc

        try:
            confirmed = self._lineage_exists(source, target)
        except OpenMetadataLineageDeliveryError as reconciliation_error:
            raise OpenMetadataLineageDeliveryError(
                f"OpenMetadata PUT returned HTTP {response.status_code} "
                "but reconciliation failed"
            ) from reconciliation_error
        if confirmed:
            return
        if not 200 <= response.status_code < 300:
            raise OpenMetadataLineageDeliveryError(
                f"OpenMetadata rejected lineage with HTTP {response.status_code}"
            )
        raise OpenMetadataLineageDeliveryError(
            "OpenMetadata accepted the request but the lineage edge was not confirmed"
        )


@dataclass(frozen=True)
class OpenMetadataLineageWorkerConfig:
    tenant_id: str
    worker_id: str
    openmetadata_url: str
    bearer_token_file: Path
    batch_size: int = 10
    lease_seconds: int = 360
    retry_delay_seconds: int = 30
    poll_interval_seconds: float = 5.0
    timeout_seconds: float = 10.0

    @classmethod
    def from_env(cls) -> OpenMetadataLineageWorkerConfig:
        tenant_id = os.environ.get("GDA_METADATA_FABRIC_TENANT_ID", "").strip()
        openmetadata_url = os.environ.get("GDA_OPENMETADATA_URL", "").strip()
        if not tenant_id:
            raise OpenMetadataLineageConfigurationError(
                "GDA_METADATA_FABRIC_TENANT_ID is required"
            )
        if not openmetadata_url:
            raise OpenMetadataLineageConfigurationError(
                "GDA_OPENMETADATA_URL is required"
            )
        token_path = resolve_bearer_token_file(
            file_env_name="GDA_OPENMETADATA_BEARER_TOKEN_FILE",
            source_env_name="GDA_OPENMETADATA_BEARER_TOKEN_SOURCE",
            error_factory=OpenMetadataLineageConfigurationError,
            required=True,
        )
        worker_id = os.environ.get(
            "GDA_METADATA_FABRIC_WORKER_ID",
            f"worker:metadata-fabric:openmetadata:{socket.gethostname()}:{os.getpid()}",
        ).strip()
        try:
            return cls(
                tenant_id=tenant_id,
                worker_id=worker_id,
                openmetadata_url=openmetadata_url,
                bearer_token_file=token_path,
                batch_size=int(os.environ.get("GDA_METADATA_FABRIC_BATCH_SIZE", "10")),
                lease_seconds=int(
                    os.environ.get("GDA_METADATA_FABRIC_LEASE_SECONDS", "360")
                ),
                retry_delay_seconds=int(
                    os.environ.get("GDA_METADATA_FABRIC_RETRY_SECONDS", "30")
                ),
                poll_interval_seconds=float(
                    os.environ.get("GDA_METADATA_FABRIC_POLL_SECONDS", "5")
                ),
                timeout_seconds=float(
                    os.environ.get("GDA_OPENMETADATA_TIMEOUT_SECONDS", "10")
                ),
            )
        except ValueError as exc:
            raise OpenMetadataLineageConfigurationError(
                "OpenMetadata worker numeric configuration is invalid"
            ) from exc

    def validate(self) -> None:
        if not self.tenant_id:
            raise OpenMetadataLineageConfigurationError("tenant identity is required")
        if not self.worker_id:
            raise OpenMetadataLineageConfigurationError("worker identity is required")
        if not 1 <= self.batch_size <= 100:
            raise OpenMetadataLineageConfigurationError(
                "metadata batch size must be between 1 and 100"
            )
        if not 5 <= self.lease_seconds <= 3600:
            raise OpenMetadataLineageConfigurationError(
                "metadata lease must be between 5 and 3600 seconds"
            )
        if not 0 <= self.retry_delay_seconds <= 86400:
            raise OpenMetadataLineageConfigurationError(
                "metadata retry delay must be between 0 and 86400 seconds"
            )
        if self.poll_interval_seconds <= 0 or self.poll_interval_seconds > 300:
            raise OpenMetadataLineageConfigurationError(
                "metadata poll interval must be between 0 and 300 seconds"
            )
        if self.timeout_seconds <= 0 or self.timeout_seconds > 120:
            raise OpenMetadataLineageConfigurationError(
                "OpenMetadata timeout must be between 0 and 120 seconds"
            )
        worst_case_batch_seconds = (
            self.batch_size * MAX_HTTP_REQUESTS_PER_DELIVERY * self.timeout_seconds
        )
        if self.lease_seconds <= worst_case_batch_seconds:
            raise OpenMetadataLineageConfigurationError(
                "metadata lease must exceed the worst-case HTTP time for the batch"
            )
        normalize_openmetadata_api_url(self.openmetadata_url)
        _resolve_token_file(self.bearer_token_file)


@dataclass(frozen=True)
class OpenMetadataLineageCycle:
    claimed: int
    delivered: int
    retrying: int
    dead_lettered: int


class OpenMetadataLineageWorker:
    """Claim, reconcile, project, and acknowledge lineage outbox rows."""

    def __init__(
        self,
        config: OpenMetadataLineageWorkerConfig,
        *,
        gateway: PlatformGateway | None = None,
        client: OpenMetadataLineageClient | None = None,
    ) -> None:
        config.validate()
        self.config = config
        self.gateway = gateway or PlatformGateway()
        self.client = client or OpenMetadataLineageClient(
            config.openmetadata_url,
            bearer_token_file=config.bearer_token_file,
            timeout_seconds=config.timeout_seconds,
        )

    def run_once(self) -> OpenMetadataLineageCycle:
        envelopes = self.gateway.claim_metadata_changes(
            self.config.tenant_id,
            self.config.worker_id,
            limit=self.config.batch_size,
            lease_seconds=self.config.lease_seconds,
        )
        delivered = 0
        retrying = 0
        dead_lettered = 0
        for envelope in envelopes:
            change = envelope.change
            try:
                self.client.deliver(envelope)
            except (
                OpenMetadataLineageConfigurationError,
                OpenMetadataLineageDeliveryError,
            ) as exc:
                failed = self.gateway.fail_metadata_change(
                    change.tenant_id,
                    change.change_id,
                    worker_id=self.config.worker_id,
                    error=f"{type(exc).__name__}: {exc}",
                    retry_delay_seconds=self.config.retry_delay_seconds,
                )
                if failed.status == MetadataChangeStatus.FAILED:
                    dead_lettered += 1
                else:
                    retrying += 1
                LOGGER.warning(
                    "Metadata change %s projection failed (%s)",
                    change.change_id,
                    failed.status.value,
                )
                continue
            self.gateway.complete_metadata_change(
                change.tenant_id,
                change.change_id,
                worker_id=self.config.worker_id,
            )
            delivered += 1
        return OpenMetadataLineageCycle(
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
        description="Project governed GIS Data Agent lineage into OpenMetadata"
    )
    parser.add_argument("--once", action="store_true", help="Process one batch and exit")
    args = parser.parse_args(argv)
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    config = OpenMetadataLineageWorkerConfig.from_env()
    stop_event = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_args: stop_event.set())
    worker = OpenMetadataLineageWorker(config)
    try:
        if args.once:
            cycle = worker.run_once()
            LOGGER.info("OpenMetadata lineage cycle: %s", cycle)
        else:
            worker.run(stop_event)
    finally:
        worker.client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

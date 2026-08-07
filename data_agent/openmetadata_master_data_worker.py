"""Reconciled OpenMetadata glossary projection for active master versions."""

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
from uuid import UUID

import httpx

from .metadata_fabric import (
    MasterMetadataProjectionEnvelope,
    MetadataChangeStatus,
)
from .openmetadata_lineage_worker import (
    OpenMetadataLineageConfigurationError,
    normalize_openmetadata_api_url,
)
from .platform_gateway import PlatformGateway

LOGGER = logging.getLogger(__name__)
DEFAULT_DESTINATION_REF = "openmetadata:default"
MAX_HTTP_REQUESTS_PER_DELIVERY = 3


class OpenMetadataMasterDataConfigurationError(RuntimeError):
    """Master-data projection configuration is incomplete or unsafe."""


class OpenMetadataMasterDataDeliveryError(RuntimeError):
    """A glossary projection could not be proven after delivery."""


class OpenMetadataMasterDataBindingError(OpenMetadataMasterDataDeliveryError):
    """A master entity has no usable OpenMetadata glossary-term binding."""


def _normalize_api_url(value: str) -> str:
    try:
        return normalize_openmetadata_api_url(value)
    except OpenMetadataLineageConfigurationError as exc:
        raise OpenMetadataMasterDataConfigurationError(str(exc)) from exc


def _resolve_token_file(path: Path) -> Path:
    if not path.is_absolute():
        raise OpenMetadataMasterDataConfigurationError(
            "OpenMetadata bearer token file must be an absolute path"
        )
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise OpenMetadataMasterDataConfigurationError(
            "OpenMetadata bearer token file does not exist"
        ) from exc
    if not resolved.is_file():
        raise OpenMetadataMasterDataConfigurationError(
            "OpenMetadata bearer token path must be a file"
        )
    return resolved


def render_master_glossary_term(
    envelope: MasterMetadataProjectionEnvelope,
) -> dict[str, str]:
    """Render only the fields owned by the GDA master-data projection."""
    master = envelope.master_version
    return {
        "displayName": master.canonical_name,
        "description": "\n".join(
            (
                f"Canonical master entity for {master.business_key}.",
                "",
                f"Domain: {master.domain.value}",
                f"ResourceURN: {master.entity_ref}",
                f"Master version: {master.entity_version_ref}",
                f"Fingerprint: {master.entity_fingerprint}",
            )
        ),
    }


class OpenMetadataMasterDataClient:
    """Patch an explicitly bound glossary term and confirm exact provider state."""

    def __init__(
        self,
        api_url: str,
        *,
        bearer_token_file: Path,
        timeout_seconds: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if timeout_seconds <= 0 or timeout_seconds > 120:
            raise OpenMetadataMasterDataConfigurationError(
                "OpenMetadata timeout must be between 0 and 120 seconds"
            )
        self.api_url = _normalize_api_url(api_url)
        self._bearer_token_file = _resolve_token_file(bearer_token_file)
        self._client = httpx.Client(
            timeout=timeout_seconds,
            follow_redirects=False,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> OpenMetadataMasterDataClient:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _headers(self) -> dict[str, str]:
        try:
            token = self._bearer_token_file.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise OpenMetadataMasterDataConfigurationError(
                "OpenMetadata bearer token file could not be read"
            ) from exc
        if not token or any(character.isspace() for character in token):
            raise OpenMetadataMasterDataConfigurationError(
                "OpenMetadata bearer token file must contain one non-empty token"
            )
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "gis-data-agent-openmetadata-master-data-worker/1",
        }

    def _get_term(
        self,
        envelope: MasterMetadataProjectionEnvelope,
    ) -> dict[str, Any]:
        binding = envelope.openmetadata_binding
        if binding is None:
            raise OpenMetadataMasterDataBindingError(
                "OpenMetadata glossaryTerm binding is missing"
            )
        if binding.external_object_type != "glossaryTerm":
            raise OpenMetadataMasterDataBindingError(
                "OpenMetadata binding is not a glossaryTerm"
            )
        object_id = str(UUID(binding.external_object_id))
        try:
            response = self._client.get(
                f"{self.api_url}/glossaryTerms/{object_id}",
                headers=self._headers(),
            )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise OpenMetadataMasterDataDeliveryError(
                f"OpenMetadata glossaryTerm query failed: {type(exc).__name__}"
            ) from exc
        if response.status_code == 404:
            raise OpenMetadataMasterDataBindingError(
                "OpenMetadata glossaryTerm binding is stale"
            )
        if not 200 <= response.status_code < 300:
            raise OpenMetadataMasterDataDeliveryError(
                f"OpenMetadata glossaryTerm query returned HTTP {response.status_code}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise OpenMetadataMasterDataDeliveryError(
                "OpenMetadata glossaryTerm query returned invalid JSON"
            ) from exc
        if not isinstance(payload, dict) or payload.get("id") != object_id:
            raise OpenMetadataMasterDataDeliveryError(
                "OpenMetadata glossaryTerm query returned the wrong entity"
            )
        glossary = payload.get("glossary")
        namespace = None
        if isinstance(glossary, dict):
            namespace = glossary.get("fullyQualifiedName") or glossary.get("name")
        if namespace != binding.external_namespace:
            raise OpenMetadataMasterDataBindingError(
                "OpenMetadata glossaryTerm namespace does not match the binding"
            )
        if payload.get("deleted") is True:
            raise OpenMetadataMasterDataBindingError(
                "OpenMetadata glossaryTerm binding points to a deleted entity"
            )
        return payload

    @staticmethod
    def _matches(payload: dict[str, Any], desired: dict[str, str]) -> bool:
        return all(payload.get(field) == value for field, value in desired.items())

    def deliver(self, envelope: MasterMetadataProjectionEnvelope) -> None:
        if envelope.change.destination_ref != DEFAULT_DESTINATION_REF:
            raise OpenMetadataMasterDataDeliveryError(
                "no OpenMetadata adapter is configured for the destination"
            )
        binding = envelope.openmetadata_binding
        if binding is None:
            raise OpenMetadataMasterDataBindingError(
                "OpenMetadata glossaryTerm binding is missing"
            )
        current = self._get_term(envelope)
        desired = render_master_glossary_term(envelope)
        if self._matches(current, desired):
            return

        patch = [
            {"op": "add", "path": f"/{field}", "value": value}
            for field, value in desired.items()
        ]
        headers = {
            **self._headers(),
            "Content-Type": "application/json-patch+json",
        }
        object_id = str(UUID(binding.external_object_id))
        try:
            response = self._client.patch(
                f"{self.api_url}/glossaryTerms/{object_id}",
                json=patch,
                headers=headers,
            )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            try:
                confirmed = self._matches(self._get_term(envelope), desired)
            except OpenMetadataMasterDataDeliveryError as reconciliation_error:
                raise OpenMetadataMasterDataDeliveryError(
                    "OpenMetadata glossaryTerm outcome is unknown and reconciliation failed"
                ) from reconciliation_error
            if confirmed:
                return
            raise OpenMetadataMasterDataDeliveryError(
                f"OpenMetadata glossaryTerm patch was not confirmed after {type(exc).__name__}"
            ) from exc

        try:
            confirmed = self._matches(self._get_term(envelope), desired)
        except OpenMetadataMasterDataDeliveryError as reconciliation_error:
            raise OpenMetadataMasterDataDeliveryError(
                f"OpenMetadata PATCH returned HTTP {response.status_code} "
                "but reconciliation failed"
            ) from reconciliation_error
        if confirmed:
            return
        if not 200 <= response.status_code < 300:
            raise OpenMetadataMasterDataDeliveryError(
                f"OpenMetadata rejected glossaryTerm patch with HTTP {response.status_code}"
            )
        raise OpenMetadataMasterDataDeliveryError(
            "OpenMetadata accepted the patch but exact glossaryTerm state was not confirmed"
        )


@dataclass(frozen=True)
class OpenMetadataMasterDataWorkerConfig:
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
    def from_env(cls) -> OpenMetadataMasterDataWorkerConfig:
        tenant_id = os.environ.get("GDA_METADATA_FABRIC_TENANT_ID", "").strip()
        openmetadata_url = os.environ.get("GDA_OPENMETADATA_URL", "").strip()
        token_value = os.environ.get(
            "GDA_OPENMETADATA_BEARER_TOKEN_FILE", ""
        ).strip()
        if not tenant_id:
            raise OpenMetadataMasterDataConfigurationError(
                "GDA_METADATA_FABRIC_TENANT_ID is required"
            )
        if not openmetadata_url:
            raise OpenMetadataMasterDataConfigurationError(
                "GDA_OPENMETADATA_URL is required"
            )
        if not token_value:
            raise OpenMetadataMasterDataConfigurationError(
                "GDA_OPENMETADATA_BEARER_TOKEN_FILE is required"
            )
        worker_id = os.environ.get(
            "GDA_MASTER_METADATA_WORKER_ID",
            f"worker:master-metadata:openmetadata:{socket.gethostname()}:{os.getpid()}",
        ).strip()
        try:
            return cls(
                tenant_id=tenant_id,
                worker_id=worker_id,
                openmetadata_url=openmetadata_url,
                bearer_token_file=Path(token_value),
                batch_size=int(os.environ.get("GDA_MASTER_METADATA_BATCH_SIZE", "10")),
                lease_seconds=int(
                    os.environ.get("GDA_MASTER_METADATA_LEASE_SECONDS", "360")
                ),
                retry_delay_seconds=int(
                    os.environ.get("GDA_MASTER_METADATA_RETRY_SECONDS", "30")
                ),
                poll_interval_seconds=float(
                    os.environ.get("GDA_MASTER_METADATA_POLL_SECONDS", "5")
                ),
                timeout_seconds=float(
                    os.environ.get("GDA_OPENMETADATA_TIMEOUT_SECONDS", "10")
                ),
            )
        except ValueError as exc:
            raise OpenMetadataMasterDataConfigurationError(
                "OpenMetadata master-data worker numeric configuration is invalid"
            ) from exc

    def validate(self) -> None:
        if not self.tenant_id:
            raise OpenMetadataMasterDataConfigurationError(
                "tenant identity is required"
            )
        if not self.worker_id:
            raise OpenMetadataMasterDataConfigurationError(
                "worker identity is required"
            )
        if not 1 <= self.batch_size <= 100:
            raise OpenMetadataMasterDataConfigurationError(
                "master metadata batch size must be between 1 and 100"
            )
        if not 5 <= self.lease_seconds <= 3600:
            raise OpenMetadataMasterDataConfigurationError(
                "master metadata lease must be between 5 and 3600 seconds"
            )
        if not 0 <= self.retry_delay_seconds <= 86400:
            raise OpenMetadataMasterDataConfigurationError(
                "master metadata retry delay must be between 0 and 86400 seconds"
            )
        if self.poll_interval_seconds <= 0 or self.poll_interval_seconds > 300:
            raise OpenMetadataMasterDataConfigurationError(
                "master metadata poll interval must be between 0 and 300 seconds"
            )
        if self.timeout_seconds <= 0 or self.timeout_seconds > 120:
            raise OpenMetadataMasterDataConfigurationError(
                "OpenMetadata timeout must be between 0 and 120 seconds"
            )
        worst_case_batch_seconds = (
            self.batch_size * MAX_HTTP_REQUESTS_PER_DELIVERY * self.timeout_seconds
        )
        if self.lease_seconds <= worst_case_batch_seconds:
            raise OpenMetadataMasterDataConfigurationError(
                "master metadata lease must exceed the worst-case HTTP time for the batch"
            )
        _normalize_api_url(self.openmetadata_url)
        _resolve_token_file(self.bearer_token_file)


@dataclass(frozen=True)
class OpenMetadataMasterDataCycle:
    claimed: int
    delivered: int
    retrying: int
    dead_lettered: int


class OpenMetadataMasterDataWorker:
    """Claim, reconcile, patch and acknowledge master metadata projections."""

    def __init__(
        self,
        config: OpenMetadataMasterDataWorkerConfig,
        *,
        gateway: PlatformGateway | None = None,
        client: OpenMetadataMasterDataClient | None = None,
    ) -> None:
        config.validate()
        self.config = config
        self.gateway = gateway or PlatformGateway()
        self.client = client or OpenMetadataMasterDataClient(
            config.openmetadata_url,
            bearer_token_file=config.bearer_token_file,
            timeout_seconds=config.timeout_seconds,
        )

    def run_once(self) -> OpenMetadataMasterDataCycle:
        envelopes = self.gateway.claim_master_metadata_projections(
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
                OpenMetadataMasterDataConfigurationError,
                OpenMetadataMasterDataDeliveryError,
            ) as exc:
                failed = self.gateway.fail_master_metadata_projection(
                    change.tenant_id,
                    change.projection_change_id,
                    worker_id=self.config.worker_id,
                    error=f"{type(exc).__name__}: {exc}",
                    retry_delay_seconds=self.config.retry_delay_seconds,
                )
                if failed.status == MetadataChangeStatus.FAILED:
                    dead_lettered += 1
                else:
                    retrying += 1
                LOGGER.warning(
                    "Master metadata projection %s failed (%s)",
                    change.projection_change_id,
                    failed.status.value,
                )
                continue
            self.gateway.complete_master_metadata_projection(
                change.tenant_id,
                change.projection_change_id,
                worker_id=self.config.worker_id,
            )
            delivered += 1
        return OpenMetadataMasterDataCycle(
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
        description="Project active GDA master versions into OpenMetadata glossary terms"
    )
    parser.add_argument("--once", action="store_true", help="Process one batch and exit")
    args = parser.parse_args(argv)
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    config = OpenMetadataMasterDataWorkerConfig.from_env()
    stop_event = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_args: stop_event.set())
    worker = OpenMetadataMasterDataWorker(config)
    try:
        if args.once:
            cycle = worker.run_once()
            LOGGER.info("OpenMetadata master-data cycle: %s", cycle)
        else:
            worker.run(stop_event)
    finally:
        worker.client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

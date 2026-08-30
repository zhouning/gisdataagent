"""Managed worker for exact cache-generation cleanup after GIS transitions."""

from __future__ import annotations

import argparse
import asyncio
import inspect
import logging
import os
import signal
import socket
import threading
from dataclasses import dataclass
from pathlib import Path

from .gis_mvt_cache_purge import (
    GIS_MVT_CACHE_PURGE_WORKLOAD,
    GISMVTCachePurgeProvider,
    GISMVTCachePurgeTask,
    MVTResponseCachePurgeProvider,
)
from .gis_mvt_http_purge_provider import HTTPGISMVTCachePurgeProvider
from .gis_mvt_response_cache import MVTCachePurgeError, get_mvt_response_cache
from .platform_gateway import PlatformGateway

LOGGER = logging.getLogger(__name__)


class GISMVTCachePurgeWorkerConfigurationError(ValueError):
    """Worker configuration is incomplete or unsafe."""


@dataclass(frozen=True)
class GISMVTCachePurgeWorkerConfig:
    tenant_id: str
    worker_id: str
    batch_size: int = 10
    lease_seconds: int = 60
    retry_delay_seconds: int = 30
    poll_interval_seconds: float = 5.0
    max_keys: int = 10_000
    scan_count: int = 100
    provider_kind: str = "redis"
    http_endpoint_url: str | None = None
    http_bearer_token_file: Path | None = None
    http_timeout_seconds: float = 5.0

    @classmethod
    def from_env(cls) -> GISMVTCachePurgeWorkerConfig:
        tenant_id = os.environ.get("GDA_GIS_MVT_CACHE_PURGE_TENANT_ID", "").strip()
        if not tenant_id:
            raise GISMVTCachePurgeWorkerConfigurationError(
                "GDA_GIS_MVT_CACHE_PURGE_TENANT_ID is required"
            )
        worker_id = os.environ.get(
            "GDA_GIS_MVT_CACHE_PURGE_WORKER_ID",
            f"worker:gis-mvt-cache-purge:{socket.gethostname()}:{os.getpid()}",
        ).strip()
        return cls(
            tenant_id=tenant_id,
            worker_id=worker_id,
            batch_size=int(os.environ.get("GDA_GIS_MVT_CACHE_PURGE_BATCH_SIZE", "10")),
            lease_seconds=int(
                os.environ.get("GDA_GIS_MVT_CACHE_PURGE_LEASE_SECONDS", "60")
            ),
            retry_delay_seconds=int(
                os.environ.get("GDA_GIS_MVT_CACHE_PURGE_RETRY_SECONDS", "30")
            ),
            poll_interval_seconds=float(
                os.environ.get("GDA_GIS_MVT_CACHE_PURGE_POLL_SECONDS", "5")
            ),
            max_keys=int(os.environ.get("GDA_GIS_MVT_CACHE_PURGE_MAX_KEYS", "10000")),
            scan_count=int(
                os.environ.get("GDA_GIS_MVT_CACHE_PURGE_SCAN_COUNT", "100")
            ),
            provider_kind=os.environ.get(
                "GDA_GIS_MVT_CACHE_PURGE_PROVIDER", "redis"
            ).strip().lower(),
            http_endpoint_url=(
                os.environ.get("GDA_GIS_MVT_CACHE_PURGE_HTTP_ENDPOINT_URL", "").strip()
                or None
            ),
            http_bearer_token_file=(
                Path(value)
                if (value := os.environ.get(
                    "GDA_GIS_MVT_CACHE_PURGE_HTTP_BEARER_TOKEN_FILE", ""
                ).strip())
                else None
            ),
            http_timeout_seconds=float(
                os.environ.get("GDA_GIS_MVT_CACHE_PURGE_HTTP_TIMEOUT_SECONDS", "5")
            ),
        )

    def validate(self) -> None:
        if not self.tenant_id or not self.worker_id:
            raise GISMVTCachePurgeWorkerConfigurationError(
                "tenant and worker identity are required"
            )
        if not 1 <= self.batch_size <= 100:
            raise GISMVTCachePurgeWorkerConfigurationError(
                "purge batch size must be between 1 and 100"
            )
        if not 5 <= self.lease_seconds <= 3600:
            raise GISMVTCachePurgeWorkerConfigurationError(
                "purge lease must be between 5 and 3600 seconds"
            )
        if not 0 <= self.retry_delay_seconds <= 86400:
            raise GISMVTCachePurgeWorkerConfigurationError(
                "purge retry delay must be between 0 and 86400 seconds"
            )
        if self.poll_interval_seconds <= 0 or self.poll_interval_seconds > 300:
            raise GISMVTCachePurgeWorkerConfigurationError(
                "purge poll interval must be between 0 and 300 seconds"
            )
        if not 1 <= self.max_keys <= 100_000:
            raise GISMVTCachePurgeWorkerConfigurationError(
                "purge max keys must be between 1 and 100000"
            )
        if not 1 <= self.scan_count <= 10_000:
            raise GISMVTCachePurgeWorkerConfigurationError(
                "purge scan count must be between 1 and 10000"
            )
        if self.provider_kind not in {"redis", "http"}:
            raise GISMVTCachePurgeWorkerConfigurationError(
                "purge provider must be redis or http"
            )
        if self.provider_kind == "http":
            if not self.http_endpoint_url:
                raise GISMVTCachePurgeWorkerConfigurationError(
                    "HTTP purge provider endpoint is required"
                )
            if self.http_timeout_seconds <= 0 or self.http_timeout_seconds > 60:
                raise GISMVTCachePurgeWorkerConfigurationError(
                    "HTTP purge provider timeout must be between 0 and 60 seconds"
                )
        elif self.http_endpoint_url or self.http_bearer_token_file is not None:
            raise GISMVTCachePurgeWorkerConfigurationError(
                "HTTP purge settings require provider=http"
            )


@dataclass(frozen=True)
class GISMVTCachePurgeWorkerCycle:
    claimed: int
    completed: int
    retrying: int
    failed: int


class GISMVTCachePurgeWorker:
    """Claim and certify exact-generation Redis purges."""

    def __init__(
        self,
        config: GISMVTCachePurgeWorkerConfig,
        *,
        gateway: PlatformGateway | None = None,
        cache=None,
        purge_provider: GISMVTCachePurgeProvider | None = None,
    ) -> None:
        config.validate()
        self.config = config
        self.gateway = gateway or PlatformGateway()
        if cache is not None and purge_provider is not None:
            raise GISMVTCachePurgeWorkerConfigurationError(
                "provide cache or purge_provider, not both"
            )
        if purge_provider is None:
            if config.provider_kind == "http":
                if cache is not None:
                    raise GISMVTCachePurgeWorkerConfigurationError(
                        "cache cannot be supplied with provider=http"
                    )
                assert config.http_endpoint_url is not None
                purge_provider = HTTPGISMVTCachePurgeProvider(
                    config.http_endpoint_url,
                    bearer_token_file=config.http_bearer_token_file,
                    timeout_seconds=config.http_timeout_seconds,
                )
            else:
                purge_provider = MVTResponseCachePurgeProvider(
                    cache or get_mvt_response_cache()
                )
        self.purge_provider = purge_provider
        if not purge_provider.enabled:
            raise GISMVTCachePurgeWorkerConfigurationError(
                f"cache purge provider {purge_provider.provider_kind!r} is disabled"
            )
        self._runner = asyncio.Runner()

    @staticmethod
    def _error_message(exc: Exception) -> str:
        return f"{type(exc).__name__}: {exc}"[:2048]

    def _purge(self, task: GISMVTCachePurgeTask):
        if task.generation_token is None:
            raise MVTCachePurgeError("purge task has no generation token")
        result = self._runner.run(
            self.purge_provider.purge_generation(
                task.generation_token,
                max_keys=self.config.max_keys,
                scan_count=self.config.scan_count,
            )
        )
        if not result.enabled:
            raise MVTCachePurgeError(
                f"cache purge provider {self.purge_provider.provider_kind!r} was not enabled"
            )
        return result

    def close(self) -> None:
        result = self.purge_provider.aclose()
        if inspect.isawaitable(result):
            self._runner.run(result)
        self._runner.close()

    def run_once(self) -> GISMVTCachePurgeWorkerCycle:
        tasks = self.gateway.claim_gis_mvt_cache_purges(
            self.config.tenant_id,
            self.config.worker_id,
            actor_subject=GIS_MVT_CACHE_PURGE_WORKLOAD,
            limit=self.config.batch_size,
            lease_seconds=self.config.lease_seconds,
        )
        completed = 0
        retrying = 0
        failed = 0
        for task in tasks:
            try:
                result = self._purge(task)
                self.gateway.complete_gis_mvt_cache_purge(
                    task.tenant_id,
                    task.purge_task_id,
                    worker_id=self.config.worker_id,
                    matched_keys=result.matched_keys,
                    deleted_keys=result.deleted_keys,
                    remaining_keys=result.remaining_keys,
                )
                completed += 1
            except Exception as exc:
                failed_task = self.gateway.fail_gis_mvt_cache_purge(
                    task.tenant_id,
                    task.purge_task_id,
                    worker_id=self.config.worker_id,
                    error=self._error_message(exc),
                    retry_delay_seconds=self.config.retry_delay_seconds,
                )
                if failed_task.status.value == "failed":
                    failed += 1
                else:
                    retrying += 1
                LOGGER.warning(
                    "GIS MVT cache purge task %s failed status=%s",
                    task.purge_task_id,
                    failed_task.status.value,
                )
        return GISMVTCachePurgeWorkerCycle(
            claimed=len(tasks),
            completed=completed,
            retrying=retrying,
            failed=failed,
        )

    def run(self, stop_event: threading.Event) -> None:
        while not stop_event.is_set():
            cycle = self.run_once()
            if cycle.claimed == 0:
                stop_event.wait(self.config.poll_interval_seconds)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Purge retired GIS MVT cache generations"
    )
    parser.add_argument("--once", action="store_true", help="Process one batch and exit")
    args = parser.parse_args(argv)
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    config = GISMVTCachePurgeWorkerConfig.from_env()
    stop_event = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_args: stop_event.set())
    worker = GISMVTCachePurgeWorker(config)
    try:
        if args.once:
            LOGGER.info("GIS MVT cache purge cycle: %s", worker.run_once())
        else:
            worker.run(stop_event)
    finally:
        worker.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

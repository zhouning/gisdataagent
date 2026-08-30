"""Managed worker for exact GIS ServiceSLO activation projection."""

from __future__ import annotations

import argparse
import logging
import os
import signal
import socket
import threading
from dataclasses import dataclass

from .gis_service_slo_reconciliation import (
    GIS_SERVICE_SLO_RECONCILIATION_WORKLOAD,
    GISServiceSLOReconciliationStatus,
)
from .platform_gateway import PlatformGateway

LOGGER = logging.getLogger(__name__)


class GISServiceSLOReconciliationWorkerConfigurationError(ValueError):
    """Worker configuration is incomplete or unsafe."""


@dataclass(frozen=True)
class GISServiceSLOReconciliationWorkerConfig:
    tenant_id: str
    worker_id: str
    batch_size: int = 10
    lease_seconds: int = 60
    retry_delay_seconds: int = 30
    poll_interval_seconds: float = 5.0

    @classmethod
    def from_env(cls) -> GISServiceSLOReconciliationWorkerConfig:
        tenant_id = os.environ.get("GDA_GIS_SLO_RECONCILIATION_TENANT_ID", "").strip()
        if not tenant_id:
            raise GISServiceSLOReconciliationWorkerConfigurationError(
                "GDA_GIS_SLO_RECONCILIATION_TENANT_ID is required"
            )
        worker_id = os.environ.get(
            "GDA_GIS_SLO_RECONCILIATION_WORKER_ID",
            f"worker:gis-slo-reconciliation:{socket.gethostname()}:{os.getpid()}",
        ).strip()
        return cls(
            tenant_id=tenant_id,
            worker_id=worker_id,
            batch_size=int(os.environ.get("GDA_GIS_SLO_RECONCILIATION_BATCH_SIZE", "10")),
            lease_seconds=int(
                os.environ.get("GDA_GIS_SLO_RECONCILIATION_LEASE_SECONDS", "60")
            ),
            retry_delay_seconds=int(
                os.environ.get("GDA_GIS_SLO_RECONCILIATION_RETRY_SECONDS", "30")
            ),
            poll_interval_seconds=float(
                os.environ.get("GDA_GIS_SLO_RECONCILIATION_POLL_SECONDS", "5")
            ),
        )

    def validate(self) -> None:
        if not self.tenant_id or not self.worker_id:
            raise GISServiceSLOReconciliationWorkerConfigurationError(
                "tenant and worker identity are required"
            )
        if not 1 <= self.batch_size <= 100:
            raise GISServiceSLOReconciliationWorkerConfigurationError(
                "reconciliation batch size must be between 1 and 100"
            )
        if not 5 <= self.lease_seconds <= 3600:
            raise GISServiceSLOReconciliationWorkerConfigurationError(
                "reconciliation lease must be between 5 and 3600 seconds"
            )
        if not 0 <= self.retry_delay_seconds <= 86400:
            raise GISServiceSLOReconciliationWorkerConfigurationError(
                "reconciliation retry delay must be between 0 and 86400 seconds"
            )
        if self.poll_interval_seconds <= 0 or self.poll_interval_seconds > 300:
            raise GISServiceSLOReconciliationWorkerConfigurationError(
                "reconciliation poll interval must be between 0 and 300 seconds"
            )


@dataclass(frozen=True)
class GISServiceSLOReconciliationWorkerCycle:
    claimed: int
    completed: int
    superseded: int
    retrying: int
    failed: int


class GISServiceSLOReconciliationWorker:
    """Claim activation tasks and let the database recheck exact authority."""

    def __init__(
        self,
        config: GISServiceSLOReconciliationWorkerConfig,
        *,
        gateway: PlatformGateway | None = None,
    ) -> None:
        config.validate()
        self.config = config
        self.gateway = gateway or PlatformGateway()

    @staticmethod
    def _error_message(exc: Exception) -> str:
        return f"{type(exc).__name__}: {exc}"[:2048]

    def run_once(self) -> GISServiceSLOReconciliationWorkerCycle:
        tasks = self.gateway.claim_gis_service_slo_reconciliations(
            self.config.tenant_id,
            self.config.worker_id,
            actor_subject=GIS_SERVICE_SLO_RECONCILIATION_WORKLOAD,
            limit=self.config.batch_size,
            lease_seconds=self.config.lease_seconds,
        )
        completed = 0
        superseded = 0
        retrying = 0
        failed = 0
        for task in tasks:
            try:
                settled = self.gateway.complete_gis_service_slo_reconciliation(
                    task.tenant_id,
                    task.task_id,
                    worker_id=self.config.worker_id,
                )
                if settled.status is GISServiceSLOReconciliationStatus.SUPERSEDED:
                    superseded += 1
                else:
                    completed += 1
            except Exception as exc:
                failed_task = self.gateway.fail_gis_service_slo_reconciliation(
                    task.tenant_id,
                    task.task_id,
                    worker_id=self.config.worker_id,
                    error=self._error_message(exc),
                    retry_delay_seconds=self.config.retry_delay_seconds,
                )
                if failed_task.status is GISServiceSLOReconciliationStatus.FAILED:
                    failed += 1
                else:
                    retrying += 1
                LOGGER.warning(
                    "GIS ServiceSLO reconciliation task %s failed status=%s",
                    task.task_id,
                    failed_task.status.value,
                )
        return GISServiceSLOReconciliationWorkerCycle(
            claimed=len(tasks),
            completed=completed,
            superseded=superseded,
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
        description="Reconcile exact GIS ServiceSLO activation bindings"
    )
    parser.add_argument("--once", action="store_true", help="Process one batch and exit")
    args = parser.parse_args(argv)
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    config = GISServiceSLOReconciliationWorkerConfig.from_env()
    stop_event = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_args: stop_event.set())
    worker = GISServiceSLOReconciliationWorker(config)
    if args.once:
        LOGGER.info("GIS ServiceSLO reconciliation cycle: %s", worker.run_once())
    else:
        worker.run(stop_event)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

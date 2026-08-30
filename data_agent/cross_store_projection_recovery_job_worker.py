"""Deployable loop for durable cross-store projection recovery jobs."""

from __future__ import annotations

import argparse
import os
import socket
import time

from .cross_store_projection_recovery_compensation import (
    ProjectionRecoveryCompensationResolver,
)
from .cross_store_projection_recovery_job import (
    PostgresProjectionRecoveryJobRepository,
    ProjectionRecoveryJobWorker,
)
from .cross_store_projection_recovery_runtime import (
    ProjectionRecoveryControllerBindingResolver,
    ProjectionRecoveryProviderResolver,
    SealedProjectionRowsFileResolver,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run durable cross-store projection recovery jobs"
    )
    parser.add_argument(
        "--tenant-id",
        default=os.environ.get("GDA_PROJECTION_RECOVERY_TENANT_ID", ""),
    )
    parser.add_argument(
        "--worker-id",
        default=os.environ.get(
            "GDA_PROJECTION_RECOVERY_WORKER_ID",
            f"worker:projection-recovery:{socket.gethostname()}:{os.getpid()}",
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=int(os.environ.get("GDA_PROJECTION_RECOVERY_WORKER_LIMIT", "1")),
    )
    parser.add_argument(
        "--lease-seconds",
        type=int,
        default=int(os.environ.get("GDA_PROJECTION_RECOVERY_WORKER_LEASE_SECONDS", "120")),
    )
    parser.add_argument(
        "--heartbeat-seconds",
        type=float,
        default=float(
            os.environ.get("GDA_PROJECTION_RECOVERY_WORKER_HEARTBEAT_SECONDS", "0")
        ),
    )
    parser.add_argument(
        "--retry-delay-seconds",
        type=int,
        default=int(
            os.environ.get("GDA_PROJECTION_RECOVERY_WORKER_RETRY_DELAY_SECONDS", "30")
        ),
    )
    parser.add_argument(
        "--poll-seconds",
        type=float,
        default=float(os.environ.get("GDA_PROJECTION_RECOVERY_WORKER_POLL_SECONDS", "5")),
    )
    parser.add_argument(
        "--rows-directory",
        default=os.environ.get("GDA_PROJECTION_RECOVERY_ROWS_DIRECTORY", ""),
    )
    parser.add_argument("--once", action="store_true")
    return parser


def _validate(args: argparse.Namespace) -> None:
    if not args.tenant_id or not args.tenant_id.strip():
        raise SystemExit("--tenant-id or GDA_PROJECTION_RECOVERY_TENANT_ID is required")
    if not args.worker_id.startswith("worker:"):
        raise SystemExit("--worker-id must start with worker:")
    if args.limit < 1 or args.limit > 100:
        raise SystemExit("--limit must be between 1 and 100")
    if args.lease_seconds < 5 or args.lease_seconds > 3600:
        raise SystemExit("--lease-seconds must be between 5 and 3600")
    if args.heartbeat_seconds < 0 or args.heartbeat_seconds >= args.lease_seconds:
        raise SystemExit("--heartbeat-seconds must be zero or shorter than --lease-seconds")
    if args.retry_delay_seconds < 0 or args.retry_delay_seconds > 86400:
        raise SystemExit("--retry-delay-seconds must be between 0 and 86400")
    if args.poll_seconds <= 0 or args.poll_seconds > 3600:
        raise SystemExit("--poll-seconds must be between 0 and 3600")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    _validate(args)
    repository = PostgresProjectionRecoveryJobRepository()
    rows_resolver = (
        SealedProjectionRowsFileResolver(args.rows_directory)
        if args.rows_directory.strip()
        else None
    )
    provider_resolver = ProjectionRecoveryProviderResolver.from_environment(
        repository.get_engine(),
        rows_resolver=rows_resolver,
    )
    controller_binding_resolver = (
        ProjectionRecoveryControllerBindingResolver.from_environment(
            repository.get_engine()
        )
    )
    compensation_resolver = ProjectionRecoveryCompensationResolver.from_environment(
        authority=repository,
    )
    worker = ProjectionRecoveryJobWorker(
        repository=repository,
        provider_resolver=provider_resolver,
        compensation_resolver=compensation_resolver,
        controller_binding_resolver=controller_binding_resolver,
    )
    heartbeat_seconds = args.heartbeat_seconds or None
    while True:
        worker.run_once(
            args.tenant_id.strip(),
            args.worker_id.strip(),
            limit=args.limit,
            lease_seconds=args.lease_seconds,
            retry_delay_seconds=args.retry_delay_seconds,
            heartbeat_interval_seconds=heartbeat_seconds,
        )
        if args.once:
            return 0
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())

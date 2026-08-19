"""Small deployable worker loop for asynchronous Chongqing reconciliation jobs."""

from __future__ import annotations

import argparse
import os
import time

from .chongqing_data_package_reconciliation_job import (
    ChongqingDataPackageReconciliationJobWorker,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the governed Chongqing reconciliation job worker"
    )
    parser.add_argument(
        "--tenant-id",
        default=os.environ.get("GDA_CHONGQING_RECONCILIATION_TENANT_ID", ""),
    )
    parser.add_argument(
        "--worker-id",
        default=os.environ.get(
            "GDA_CHONGQING_RECONCILIATION_WORKER_ID", "worker:chongqing-reconciliation"
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=int(os.environ.get("GDA_CHONGQING_RECONCILIATION_WORKER_LIMIT", "1")),
    )
    parser.add_argument(
        "--lease-seconds",
        type=int,
        default=int(
            os.environ.get("GDA_CHONGQING_RECONCILIATION_WORKER_LEASE_SECONDS", "600")
        ),
    )
    parser.add_argument(
        "--retry-delay-seconds",
        type=int,
        default=int(
            os.environ.get(
                "GDA_CHONGQING_RECONCILIATION_WORKER_RETRY_DELAY_SECONDS", "30"
            )
        ),
    )
    parser.add_argument(
        "--poll-seconds",
        type=float,
        default=float(
            os.environ.get("GDA_CHONGQING_RECONCILIATION_WORKER_POLL_SECONDS", "5")
        ),
    )
    parser.add_argument("--once", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.tenant_id or not args.tenant_id.strip():
        raise SystemExit("--tenant-id or GDA_CHONGQING_RECONCILIATION_TENANT_ID is required")
    if not args.worker_id.startswith("worker:"):
        raise SystemExit("--worker-id must start with worker:")
    if args.limit < 1 or args.limit > 100:
        raise SystemExit("--limit must be between 1 and 100")
    if args.lease_seconds < 30 or args.lease_seconds > 3600:
        raise SystemExit("--lease-seconds must be between 30 and 3600")
    if args.poll_seconds <= 0:
        raise SystemExit("--poll-seconds must be positive")

    worker = ChongqingDataPackageReconciliationJobWorker()
    while True:
        worker.run_once(
            args.tenant_id.strip(),
            args.worker_id.strip(),
            limit=args.limit,
            lease_seconds=args.lease_seconds,
            retry_delay_seconds=args.retry_delay_seconds,
        )
        if args.once:
            return 0
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Run the disposable AgentOps discovery-worker failover rehearsal."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from data_agent.agentops_temporal_discovery_worker_postgres_rehearsal import (
    run_agentops_temporal_discovery_worker_postgres_rehearsal,
    write_agentops_temporal_discovery_worker_postgres_rehearsal_report,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/reports/agentops_temporal_discovery_worker_postgres_rehearsal_2026-08-27.json"),
    )
    args = parser.parse_args()
    if not args.database_url:
        parser.error("--database-url or DATABASE_URL is required")
    report = run_agentops_temporal_discovery_worker_postgres_rehearsal(args.database_url)
    write_agentops_temporal_discovery_worker_postgres_rehearsal_report(report, args.output)
    print(report.model_dump_json(indent=2))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

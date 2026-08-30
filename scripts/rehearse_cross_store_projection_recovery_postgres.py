#!/usr/bin/env python3
"""Run the temporary PostgreSQL recovery-ledger rehearsal."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from data_agent.cross_store_projection_recovery_postgres_rehearsal import (
    run_cross_store_projection_recovery_postgres_rehearsal,
    write_cross_store_projection_recovery_postgres_rehearsal_report,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Rehearse the durable cross-store projection recovery ledger"
    )
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if not args.database_url:
        parser.error("--database-url or DATABASE_URL is required")
    report = run_cross_store_projection_recovery_postgres_rehearsal(args.database_url)
    if args.output is not None:
        write_cross_store_projection_recovery_postgres_rehearsal_report(report, args.output)
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

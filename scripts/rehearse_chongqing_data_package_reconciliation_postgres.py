#!/usr/bin/env python3
"""Run an isolated PostgreSQL rehearsal for Chongqing reconciliation jobs."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from data_agent.chongqing_data_package_reconciliation_postgres_rehearsal import (
    run_chongqing_reconciliation_postgres_rehearsal,
    write_chongqing_reconciliation_postgres_rehearsal_report,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", ""),
        help="superuser PostgreSQL URL used only to create an isolated temporary database",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if not args.database_url:
        parser.error("--database-url or DATABASE_URL is required")
    report = run_chongqing_reconciliation_postgres_rehearsal(args.database_url)
    if args.output is not None:
        write_chongqing_reconciliation_postgres_rehearsal_report(report, args.output)
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

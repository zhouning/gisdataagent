#!/usr/bin/env python3
"""Run the bounded, non-production Chongqing reconciliation resilience rehearsal."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from data_agent.chongqing_data_package_reconciliation_resilience import (
    run_chongqing_reconciliation_resilience_rehearsal,
    write_chongqing_reconciliation_resilience_report,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Rehearse Chongqing reconciliation failure boundaries"
    )
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = run_chongqing_reconciliation_resilience_rehearsal(
        iterations=args.iterations
    )
    if args.output is not None:
        write_chongqing_reconciliation_resilience_report(report, args.output)
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report.failed_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

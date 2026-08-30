#!/usr/bin/env python3
"""Run the non-production cross-store recovery state-machine rehearsal."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from data_agent.cross_store_projection_recovery_rehearsal import (
    run_cross_store_projection_recovery_rehearsal,
    write_cross_store_projection_recovery_report,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rehearse cross-store projection recovery")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = run_cross_store_projection_recovery_rehearsal()
    if args.output is not None:
        write_cross_store_projection_recovery_report(report, args.output)
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report.failed_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Certify PostGIS architecture drift admission into ApprovalCase authority."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from certify_postgis_architecture_reconciliation import certify

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = REPO_ROOT / ".tmp" / "data-architecture-change-approval" / "acceptance-report.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", default="postgis/postgis:16-3.4")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    report = certify(
        args.image,
        args.report,
        report_schema="gda.architecture_change_approval.acceptance.v1",
    )
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

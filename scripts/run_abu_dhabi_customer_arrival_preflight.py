#!/usr/bin/env python3
"""Run the private Abu Dhabi customer-data arrival preflight."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from data_agent.uwm.abu_dhabi_flood.customer_arrival_preflight import (
    render_customer_arrival_preflight_markdown,
    run_customer_arrival_preflight,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fail-closed preflight for the next private Abu Dhabi customer delivery."
    )
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--receipt-workbook", type=Path)
    parser.add_argument("--issue-register", type=Path)
    parser.add_argument("--data-root", type=Path, action="append", default=[])
    parser.add_argument("--gdb", dest="gdb_path", type=Path)
    parser.add_argument("--source-archive", type=Path)
    parser.add_argument("--compile-network", action="store_true")
    parser.add_argument("--event-csv", type=Path)
    parser.add_argument("--event-metadata", type=Path)
    parser.add_argument(
        "--event-kind",
        choices=("rainfall", "coastal_boundary", "inundation_observation", "pump_operation"),
    )
    parser.add_argument("--validate-event", action="store_true")
    parser.add_argument("--timestamp-column", default="timestamp")
    parser.add_argument("--value-column", default="value")
    parser.add_argument("--cadence-minutes", type=int)
    parser.add_argument("--event-id")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="return exit code 2 unless the next gate is engineering review",
    )
    args = parser.parse_args()
    payload = run_customer_arrival_preflight(
        output_root=args.output_root,
        receipt_workbook=args.receipt_workbook,
        issue_register=args.issue_register,
        data_roots=args.data_root,
        gdb_path=args.gdb_path,
        source_archive_path=args.source_archive,
        compile_network=args.compile_network,
        event_csv=args.event_csv,
        event_metadata=args.event_metadata,
        event_kind=args.event_kind,
        validate_event=args.validate_event,
        timestamp_column=args.timestamp_column,
        value_column=args.value_column,
        cadence_minutes=args.cadence_minutes,
        event_id=args.event_id,
    )
    output_root = args.output_root.expanduser().resolve()
    markdown_path = output_root / "abu_dhabi_customer_arrival_preflight.md"
    markdown_path.write_text(render_customer_arrival_preflight_markdown(payload), encoding="utf-8")
    print(
        json.dumps(
            {
                "status": payload["status"],
                "next_gate": payload["next_gate"],
                "json": payload["report"]["json"],
                "markdown": str(markdown_path),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return (
        0
        if not args.strict
        or payload["next_gate"] == "engineering_network_audit_and_SWMM_binding"
        else 2
    )


if __name__ == "__main__":
    raise SystemExit(main())

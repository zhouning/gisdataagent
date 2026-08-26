#!/usr/bin/env python3
"""Validate a private customer event time-series CSV."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from data_agent.uwm.abu_dhabi_flood.customer_event_validation import (
    EventValidationPolicy,
    validate_customer_event_csv,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument(
        "--event-kind",
        choices=sorted(
            {"rainfall", "coastal_boundary", "inundation_observation", "pump_operation"}
        ),
        required=True,
    )
    parser.add_argument("--timestamp-column", default="timestamp")
    parser.add_argument("--value-column", default="value")
    parser.add_argument("--cadence-minutes", type=int)
    parser.add_argument("--event-id")
    args = parser.parse_args()
    result = validate_customer_event_csv(
        csv_path=args.csv,
        metadata_path=args.metadata,
        output_root=args.output_root,
        policy=EventValidationPolicy(
            event_kind=args.event_kind,
            timestamp_column=args.timestamp_column,
            value_column=args.value_column,
            cadence_minutes=args.cadence_minutes,
            event_id=args.event_id,
        ),
    )
    print(
        json.dumps(
            {
                "status": result["status"],
                "accepted": result["accepted"],
                "reasons": result["reasons"],
                "output_root": str(args.output_root.expanduser().resolve()),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()

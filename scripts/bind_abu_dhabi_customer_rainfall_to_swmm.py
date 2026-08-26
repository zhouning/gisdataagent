#!/usr/bin/env python3
"""Bind an accepted customer rainfall CSV to a private SWMM input."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from data_agent.uwm.abu_dhabi_flood.customer_swmm_forcing_binding import (
    bind_customer_rainfall_to_swmm,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--swmm-input", type=Path, required=True)
    parser.add_argument("--rainfall-csv", type=Path, required=True)
    parser.add_argument("--validation-receipt", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--output-name", default="customer_swmm_with_customer_rainfall.inp")
    parser.add_argument("--source-timeseries-id", default="TS_PUBLIC")
    parser.add_argument("--timeseries-id", default="TS_CUSTOMER")
    parser.add_argument("--raingage-id", default="RG_PUBLIC")
    parser.add_argument("--timestamp-column", default="timestamp")
    parser.add_argument("--value-column", default="value")
    args = parser.parse_args()
    result = bind_customer_rainfall_to_swmm(
        swmm_input=args.swmm_input,
        rainfall_csv=args.rainfall_csv,
        validation_receipt=args.validation_receipt,
        output_root=args.output_root,
        output_name=args.output_name,
        source_timeseries_id=args.source_timeseries_id,
        timeseries_id=args.timeseries_id,
        raingage_id=args.raingage_id,
        timestamp_column=args.timestamp_column,
        value_column=args.value_column,
    )
    print(
        json.dumps(
            {"status": result["status"], "binding": result["binding"]},
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()

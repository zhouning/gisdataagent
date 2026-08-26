#!/usr/bin/env python3
"""Export private Abu Dhabi SWMM dynamic diagnostics to CSV."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from data_agent.uwm.abu_dhabi_flood.swmm_dynamic_export import (
    export_customer_swmm_dynamic_diagnostic,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-npz", type=Path, required=True)
    parser.add_argument("--input-manifest", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    result = export_customer_swmm_dynamic_diagnostic(
        input_npz=args.input_npz,
        input_manifest=args.input_manifest,
        output_root=args.output_root,
    )
    print(
        json.dumps(
            {
                "status": result["status"],
                "files": result["files"],
                "output_root": str(args.output_root.expanduser().resolve()),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()

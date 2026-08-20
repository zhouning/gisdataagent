#!/usr/bin/env python3
"""Download a governed, field-minimized snapshot from Makani source 13."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from data_agent.uwm.abu_dhabi_flood.registered_makani_acquisition import (
    download_registered_makani_snapshot,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET_ROOT = ROOT / "benchmarks/abu_dhabi_stormwater_data_v1"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", type=Path, default=DEFAULT_DATASET_ROOT)
    parser.add_argument("--owner", default="abu-dhabi-site-operator")
    parser.add_argument("--page-size", type=int, default=5000)
    args = parser.parse_args()
    try:
        snapshot = download_registered_makani_snapshot(
            args.dataset_root,
            owner=args.owner,
            page_size=args.page_size,
        )
    except (OSError, RuntimeError, ValueError):
        print(
            json.dumps(
                {
                    "status": "error",
                    "error": "registered_makani_download_failed",
                }
            )
        )
        return 1
    print(
        json.dumps(
            {
                "status": "ok",
                "snapshot_id": snapshot["snapshot_id"],
                "layer_count": len(snapshot["layers"]),
                "record_count": snapshot["record_count"],
                "page_count": snapshot["page_count"],
                "contains_personal_fields": False,
                "admitted": False,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

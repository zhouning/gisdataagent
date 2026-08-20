#!/usr/bin/env python3
"""Freeze resumable SmartMakani feature snapshots for flood-model work."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from data_agent.uwm.abu_dhabi_flood.smartmakani_acquisition import download_layers

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET_ROOT = ROOT / "benchmarks/abu_dhabi_stormwater_data_v1"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-root", type=Path, default=DEFAULT_DATASET_ROOT)
    parser.add_argument(
        "--layers",
        default="2,3,30,32,37",
        help="comma-separated allowlisted SmartMakani layer IDs",
    )
    parser.add_argument("--page-size", type=int, default=1000)
    args = parser.parse_args()
    layer_ids = [int(value.strip()) for value in args.layers.split(",") if value.strip()]
    manifests = asyncio.run(
        download_layers(
            args.dataset_root,
            layer_ids=layer_ids,
            page_size=args.page_size,
        )
    )
    print(
        json.dumps(
            {
                "dataset_root": str(args.dataset_root.resolve()),
                "layers": [
                    {
                        "layer_id": item["layer_id"],
                        "status": item["status"],
                        "records": item["completed_record_count"],
                        "pages": item["completed_page_count"],
                        "content_fingerprint": item.get("content_fingerprint"),
                    }
                    for item in manifests
                ],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()

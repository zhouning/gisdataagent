#!/usr/bin/env python3
"""Freeze public SmartMakani surface-support feature snapshots."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from data_agent.uwm.abu_dhabi_flood.supporting_surfaces import (
    SUPPORTING_LAYER_SPECS,
    download_supporting_layers,
    freeze_supporting_evidence,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET_ROOT = ROOT / "benchmarks/abu_dhabi_stormwater_data_v1"


async def _run(
    dataset_root: Path,
    dataset_keys: tuple[str, ...],
    page_size: int,
) -> dict:
    evidence = await freeze_supporting_evidence(dataset_root)
    manifests = await download_supporting_layers(
        dataset_root,
        dataset_keys=dataset_keys,
        page_size=page_size,
    )
    return {
        "evidence": evidence,
        "layers": [
            {
                "dataset_key": item["dataset_key"],
                "status": item["status"],
                "records": item["completed_record_count"],
                "pages": item["completed_page_count"],
                "content_fingerprint": item.get("content_fingerprint"),
            }
            for item in manifests
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-root", type=Path, default=DEFAULT_DATASET_ROOT)
    parser.add_argument(
        "--datasets",
        default=",".join(SUPPORTING_LAYER_SPECS),
        help="comma-separated allowlisted supporting dataset keys",
    )
    parser.add_argument("--page-size", type=int, default=1000)
    args = parser.parse_args()
    dataset_keys = tuple(
        value.strip() for value in args.datasets.split(",") if value.strip()
    )
    result = asyncio.run(_run(args.dataset_root, dataset_keys, args.page_size))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()

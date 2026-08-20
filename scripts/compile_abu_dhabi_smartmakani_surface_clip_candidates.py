#!/usr/bin/env python3
"""Compile target-clipped SmartMakani surface-support candidates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from data_agent.uwm.abu_dhabi_flood.supporting_surfaces import (
    SUPPORTING_LAYER_SPECS,
)
from data_agent.uwm.abu_dhabi_flood.surface_clip_compiler import (
    compile_surface_clip_bundle,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET_ROOT = ROOT / "benchmarks/abu_dhabi_stormwater_data_v1"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", type=Path, default=DEFAULT_DATASET_ROOT)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument(
        "--dataset-key",
        action="append",
        choices=tuple(SUPPORTING_LAYER_SPECS),
        dest="dataset_keys",
    )
    args = parser.parse_args()
    payload = compile_surface_clip_bundle(
        args.dataset_root,
        output_root=args.output_root,
        dataset_keys=tuple(args.dataset_keys or SUPPORTING_LAYER_SPECS),
    )
    print(
        json.dumps(
            {
                "output": payload["output"],
                "summary": payload["summary"],
                "admission": payload["admission"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()

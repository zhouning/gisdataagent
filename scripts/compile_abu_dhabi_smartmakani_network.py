#!/usr/bin/env python3
"""Compile frozen SmartMakani pipelines into an audited topology candidate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from data_agent.uwm.abu_dhabi_flood.network_compiler import (
    PipelineCompilePolicy,
    compile_frozen_pipeline_network,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET_ROOT = ROOT / "benchmarks/abu_dhabi_stormwater_data_v1"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-root", type=Path, default=DEFAULT_DATASET_ROOT)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--snap-tolerance-m", type=float, default=1.0)
    parser.add_argument("--without-geopackage", action="store_true")
    args = parser.parse_args()
    manifest = compile_frozen_pipeline_network(
        args.dataset_root,
        output_root=args.output_root,
        policy=PipelineCompilePolicy(snap_tolerance_m=args.snap_tolerance_m),
        write_geopackage=not args.without_geopackage,
    )
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    main()

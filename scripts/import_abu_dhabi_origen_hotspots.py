#!/usr/bin/env python3
"""Compile private Origen stormwater workbooks into the GWM serving bundle."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from data_agent.uwm.abu_dhabi_flood.hotspot_inventory import (  # noqa: E402
    DEFAULT_BUNDLE_ROOT,
    build_private_bundle,
)


def _depth_result(value: str) -> tuple[int, Path]:
    period, separator, path = value.partition("=")
    if not separator:
        raise argparse.ArgumentTypeError("expected RETURN_PERIOD=GEOJSON")
    try:
        return int(period), Path(path)
    except ValueError as error:
        raise argparse.ArgumentTypeError("return period must be an integer") from error


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_BUNDLE_ROOT)
    parser.add_argument("--depth-result", action="append", type=_depth_result, default=[])
    parser.add_argument("--swmm-nodes", type=Path)
    parser.add_argument("--maximum-node-distance-m", type=float, default=500.0)
    args = parser.parse_args()
    manifest = build_private_bundle(
        args.source_root,
        args.output_root,
        depth_results=dict(args.depth_result),
        node_path=args.swmm_nodes,
        maximum_node_distance_m=args.maximum_node_distance_m,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

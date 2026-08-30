#!/usr/bin/env python3
"""Publish the real Chongqing OSM roads as a governed DataProductVersion."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_agent.data_products.chongqing_osm_roads import build_and_publish  # noqa: E402

DEFAULT_SOURCE = (
    REPO_ROOT
    / ".tmp/twm_standard_1128/自然资源一张图数据库标准1128/"
    "规划院提供数据样例及Demo系统功能演示建议/01数据样例/"
    "02重庆市OSM道路数据2021年/OSM_roads.shp"
)
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "data_agent/uploads/data_products"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--version", default="v1.0.0")
    parser.add_argument(
        "--profile",
        choices=("lightweight", "lightweight_layered"),
        default="lightweight",
    )
    parser.add_argument(
        "--published-at",
        type=lambda value: datetime.fromisoformat(value.replace("Z", "+00:00")),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    receipt = build_and_publish(
        source_path=args.source,
        output_root=args.output_root,
        version_key=args.version,
        published_at=args.published_at,
        publication_profile=args.profile,
    )
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

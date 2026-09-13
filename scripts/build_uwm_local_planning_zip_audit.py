#!/usr/bin/env python3
"""Build UWM audit artifacts for the local planning-institute zip."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from data_agent.uwm.local_planning_zip_audit import write_local_planning_zip_audit_snapshot


DEFAULT_SOURCE_ZIP = "/Users/zhouning/Downloads/规划院提供数据样例及Demo系统功能演示建议.zip"
DEFAULT_SOURCE_ROOT = (
    ".tmp/twm_standard_1128/自然资源一张图数据库标准1128/"
    "规划院提供数据样例及Demo系统功能演示建议/01数据样例"
)
DEFAULT_OUTPUT_DIR = "data/uwm_public_proxy/chongqing_central/local_planning_zip_audit_2026_07_05"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build UWM local planning zip audit artifacts.")
    parser.add_argument("--source-zip", default=DEFAULT_SOURCE_ZIP)
    parser.add_argument("--source-root", default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    manifest = write_local_planning_zip_audit_snapshot(
        source_root=Path(args.source_root),
        source_zip=Path(args.source_zip),
        output_dir=Path(args.output_dir),
        created_at=created_at,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

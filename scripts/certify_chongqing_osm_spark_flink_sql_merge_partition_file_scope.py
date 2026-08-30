#!/usr/bin/env python3
"""Certify Spark SQL MERGE physical file scope across two Iceberg partitions."""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.certify_chongqing_osm_spark_flink_sql_merge_multi_target import (
    SPARK_SOURCE,
    build_sql_merge_multi_target_plan,
)
from scripts.certify_chongqing_osm_spark_flink_sql_merge_multi_target import (
    main as _main,
)

__all__ = ["SPARK_SOURCE", "build_sql_merge_multi_target_plan", "main"]


def main() -> int:
    # Reuse the proven multi-target harness while making the physical-file contract explicit.
    if "--file-scope-contract" not in sys.argv[1:]:
        sys.argv.append("--file-scope-contract")
    return _main()


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Run the bounded SQL MERGE phase with multiple successful fresh retries."""

from scripts.spark_chongqing_osm_iceberg_sql_merge_auto_retry import main  # noqa: F401

if __name__ == "__main__":
    raise SystemExit(main())

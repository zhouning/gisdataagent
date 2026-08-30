#!/usr/bin/env python3
"""Run the bounded SQL MERGE retry-budget phase through the existing worker."""

from scripts.spark_chongqing_osm_iceberg_sql_merge_auto_retry import main

if __name__ == "__main__":
    raise SystemExit(main())

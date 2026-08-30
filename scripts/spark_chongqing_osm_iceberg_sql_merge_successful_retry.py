#!/usr/bin/env python3
"""Run the bounded successful fresh-state SQL MERGE retry phase."""

from scripts.spark_chongqing_osm_iceberg_sql_merge_auto_retry import main

if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Run one phase of the cross-process successful SQL MERGE retry slice."""

from scripts.spark_chongqing_osm_iceberg_sql_merge_auto_retry import main

if __name__ == "__main__":
    raise SystemExit(main())

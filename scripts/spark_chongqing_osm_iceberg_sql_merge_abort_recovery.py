#!/usr/bin/env python3
"""Run one phase of the bounded Spark SQL MERGE provider-abort recovery slice."""

from __future__ import annotations

from scripts.spark_chongqing_osm_iceberg_sql_merge_auto_retry import main

if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Run the existing SQL UPDATE acceptance phases with a complex predicate plan."""

from scripts.spark_chongqing_osm_iceberg_sql_update_multi_conflict import main

if __name__ == "__main__":
    raise SystemExit(main())

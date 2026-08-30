#!/usr/bin/env python3
"""Compatibility entry point for the partition file-scope MERGE writer."""

from scripts.iceberg_file_scope import (  # noqa: F401
    _file_scope_evidence,
    _partition_road_id,
    _stable_partition_value,
)
from scripts.spark_chongqing_osm_iceberg_sql_merge_multi_target import (  # noqa: F401
    _file_inventory,
)

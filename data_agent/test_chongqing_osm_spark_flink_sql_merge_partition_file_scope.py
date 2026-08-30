from __future__ import annotations

from pathlib import Path

from scripts.certify_chongqing_osm_flink_iceberg_interop import DEFAULT_SOURCE
from scripts.certify_chongqing_osm_spark_flink_sql_merge_partition_file_scope import (
    SPARK_SOURCE,
    build_sql_merge_multi_target_plan,
)
from scripts.iceberg_file_scope import _file_scope_evidence


def test_partition_file_scope_plan_is_explicit_and_deterministic() -> None:
    first = build_sql_merge_multi_target_plan(DEFAULT_SOURCE, file_scope_contract=True)
    second = build_sql_merge_multi_target_plan(DEFAULT_SOURCE, file_scope_contract=True)

    assert first == second
    assert first["file_scope_contract"] is True
    assert len(first["target_road_ids"]) == 2
    assert len(first["expected_unchanged_partition_ids"]) == 1
    assert not set(first["target_road_ids"]) & set(first["expected_unchanged_partition_ids"])


def test_partition_file_scope_detects_only_target_partition_replacements() -> None:
    plan = {
        "target_road_ids": [101, 102],
        "expected_unchanged_partition_ids": [103],
    }
    before = (
        {"file_path": "a-v1.parquet", "partition": {"road_id": 101}, "road_id": 101},
        {"file_path": "b-v1.parquet", "partition": {"road_id": 102}, "road_id": 102},
        {"file_path": "c-v1.parquet", "partition": {"road_id": 103}, "road_id": 103},
    )
    after = (
        {"file_path": "a-v2.parquet", "partition": {"road_id": 101}, "road_id": 101},
        {"file_path": "b-v2.parquet", "partition": {"road_id": 102}, "road_id": 102},
        {"file_path": "c-v1.parquet", "partition": {"road_id": 103}, "road_id": 103},
    )

    evidence = _file_scope_evidence(before, after, plan)

    assert all(evidence["checks"].values())
    assert evidence["changed_partition_ids"] == [101, 102]


def test_partition_file_scope_entry_points_use_same_writer_contract() -> None:
    source = SPARK_SOURCE.read_text(encoding="utf-8")
    helper = _file_scope_evidence.__module__
    assert 'spark.table(f"{table}.files")' in source
    assert "file_scope_contract" in source
    assert helper == "scripts.iceberg_file_scope"
    helper_source = Path(_file_scope_evidence.__code__.co_filename).read_text(encoding="utf-8")
    assert "file_scope_changed_partitions_exact" in helper_source

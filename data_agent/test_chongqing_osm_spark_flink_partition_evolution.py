from __future__ import annotations

from pathlib import Path

from scripts.certify_chongqing_osm_flink_iceberg_interop import DEFAULT_SOURCE
from scripts.certify_chongqing_osm_spark_flink_partition_evolution import (
    SPARK_SOURCE,
)
from scripts.spark_chongqing_osm_iceberg_partition_evolution import _file_inventory


def test_partition_evolution_plan_is_bound_to_real_source_and_flink_append() -> None:
    from scripts.certify_chongqing_osm_spark_flink_update_conflict import (
        build_update_conflict_plan,
    )

    first = build_update_conflict_plan(DEFAULT_SOURCE)
    second = build_update_conflict_plan(DEFAULT_SOURCE)

    assert first == second
    assert first["source"]["source_feature_count"] == 50_366
    assert len(first["baseline_rows"]) == 3
    assert first["flink_row"]["revision"] == 2
    assert first["after_flink_content_sha256"]


def test_partition_evolution_runner_records_spec_id_and_partition_scope() -> None:
    source = SPARK_SOURCE.read_text(encoding="utf-8")

    assert 'ALTER TABLE {args.table} ADD PARTITION FIELD identity(road_id)' in source
    assert '"spec_id"' in source
    assert "both_partition_specs_materialized" in source
    assert "legacy_unpartitioned_file_retained" in source
    assert "new_identity_partition_file_bound" in source
    assert _file_inventory.__module__ == "scripts.spark_chongqing_osm_iceberg_partition_evolution"


def test_partition_evolution_certifier_declares_mixed_spec_boundary() -> None:
    certifier = Path(
        "/Users/zhouning/gisdataagent/scripts/certify_chongqing_osm_spark_flink_partition_evolution.py"
    ).read_text(encoding="utf-8")

    assert '"partition_evolution": "identity(road_id)"' in certifier
    assert "MOR/delete-file evolution" in certifier
    assert "production HA" in certifier

from __future__ import annotations

from pathlib import Path

from scripts.certify_chongqing_osm_flink_iceberg_interop import DEFAULT_SOURCE
from scripts.certify_chongqing_osm_spark_flink_mixed_spec_mor_delete import (
    SPARK_SOURCE,
    build_mixed_spec_mor_delete_plan,
)


def test_mixed_spec_mor_delete_plan_is_deterministic_and_targets_both_revisions() -> None:
    first = build_mixed_spec_mor_delete_plan(DEFAULT_SOURCE)
    second = build_mixed_spec_mor_delete_plan(DEFAULT_SOURCE)

    assert first == second
    assert first["source"]["source_feature_count"] == 50_366
    target = first["target_road_id"]
    assert sum(row["road_id"] == target for row in first["baseline_rows"]) == 1
    assert sum(row["road_id"] == target for row in first["after_flink_rows"]) == 2
    assert all(row["road_id"] != target for row in first["after_mixed_delete_rows"])


def test_mixed_spec_runner_has_physical_mor_scope_checks() -> None:
    source = SPARK_SOURCE.read_text(encoding="utf-8")

    assert "ALTER TABLE {args.table} ADD PARTITION FIELD identity(road_id)" in source
    assert "DELETE FROM {args.table} WHERE road_id = {target}" in source
    assert "copy_on_write_observed_without_delete_files" in source
    assert "copy_on_write_removed_target_files_exactly" in source
    assert "copy_on_write_did_not_rewrite_guard_file" in source


def test_mixed_spec_certifier_keeps_production_boundaries_explicit() -> None:
    certifier = Path(
        "/Users/zhouning/gisdataagent/scripts/certify_chongqing_osm_spark_flink_mixed_spec_mor_delete.py"
    ).read_text(encoding="utf-8")

    assert '"delete_mode": "merge-on-read"' in certifier
    assert "copy-on-write" in certifier
    assert "multiple concurrent destructive writers" in certifier
    assert "production HA" in certifier

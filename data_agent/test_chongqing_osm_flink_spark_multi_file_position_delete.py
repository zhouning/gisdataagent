"""Focused contracts for the bounded multi-file Flink position-delete slice."""

from __future__ import annotations

from pathlib import Path

from scripts.certify_chongqing_osm_flink_iceberg_interop import DEFAULT_SOURCE
from scripts.certify_chongqing_osm_flink_spark_multi_file_position_delete import (
    JAVA_SOURCE,
    SPARK_SOURCE,
    build_multi_file_position_delete_plan,
)


def test_multi_file_position_delete_plan_is_real_and_deterministic() -> None:
    first = build_multi_file_position_delete_plan(DEFAULT_SOURCE)
    second = build_multi_file_position_delete_plan(DEFAULT_SOURCE)

    assert first == second
    assert first["source"]["source_feature_count"] == 50_366
    assert len(first["target_road_ids"]) == 2
    assert len(first["baseline_rows"]) == 3
    assert len(first["final_rows"]) == 1
    assert all(row["road_id"] not in first["target_road_ids"] for row in first["final_rows"])
    assert len(first["flink_commit_token"]) == 64


def test_multi_file_spark_runner_binds_two_files_and_two_positions() -> None:
    source = SPARK_SOURCE.read_text(encoding="utf-8")

    assert "two_data_files_materialized" in source
    assert "target_bindings_exact" in source
    assert "one_multi_row_position_delete_file" in source
    assert "both_file_positions_bound_exactly" in source
    assert '["append", "append", "delete"]' in source


def test_multi_file_flink_writer_uses_one_row_delta_for_two_files() -> None:
    source = JAVA_SOURCE.read_text(encoding="utf-8")

    assert "requires exactly two deletes" in source
    assert "for (DeleteSpec spec : options.deletes)" in source
    assert ".addDeletes(deleteFile)" in source
    assert ".validateDataFilesExist(dataFiles)" in source
    assert '"gda.delete-count"' in source
    assert "Expressions.alwaysTrue()" in source
    assert ".executeAndCollect()" in source
    assert "RestartStrategies.noRestart()" in source


def test_multi_file_flink_writer_isolates_stale_conflict_and_cleans_orphan() -> None:
    source = JAVA_SOURCE.read_text(encoding="utf-8")

    assert "expectConflict" in source
    assert "ValidationException expected" in source
    assert "table.io().deleteFile(deleteFile.path().toString())" in source
    assert "GDA_MULTI_POSITION_DELETE_CONFLICT_REJECTED" in source
    assert "orphan_cleanup=%s" in source


def test_multi_file_certifier_keeps_production_boundary_explicit() -> None:
    certifier = Path(
        "/Users/zhouning/gisdataagent/scripts/"
        "certify_chongqing_osm_flink_spark_multi_file_position_delete.py"
    ).read_text(encoding="utf-8")

    assert "explicit_bounded_multi_file_delete" in certifier
    assert "multiple delete files" in certifier
    assert "production HA/RPO/RTO" in certifier

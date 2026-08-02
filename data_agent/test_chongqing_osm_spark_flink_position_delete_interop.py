"""Focused contracts for Spark/Flink position-delete interoperability."""

from __future__ import annotations

from scripts.certify_chongqing_osm_flink_iceberg_interop import DEFAULT_SOURCE
from scripts.certify_chongqing_osm_spark_flink_position_delete_interop import (
    JAVA_SOURCE,
    build_position_delete_plan,
    parse_flink_read_marker,
)
from scripts.spark_chongqing_osm_iceberg_position_delete_interop import (
    is_single_position_delete_file,
    position_targets_single_data_file,
)


def test_position_delete_plan_is_real_deterministic_and_targeted() -> None:
    first = build_position_delete_plan(DEFAULT_SOURCE)
    second = build_position_delete_plan(DEFAULT_SOURCE)

    assert first == second
    assert first["source"]["source_feature_count"] == 50_366
    assert len(first["baseline_rows"]) == 3
    assert len(first["final_rows"]) == 2
    assert first["target_road_id"] == first["baseline_rows"][1]["road_id"]
    assert all(row["road_id"] != first["target_road_id"] for row in first["final_rows"])
    assert first["baseline_content_sha256"] != first["final_content_sha256"]


def test_delete_file_type_gate_rejects_equality_and_copy_on_write() -> None:
    position = {
        "content": 1,
        "file_path": "s3://bucket/delete.parquet",
        "file_format": "PARQUET",
        "record_count": 1,
        "equality_ids": [],
    }

    assert is_single_position_delete_file([position])
    assert not is_single_position_delete_file([{**position, "content": 2}])
    assert not is_single_position_delete_file([{**position, "equality_ids": [1]}])
    assert not is_single_position_delete_file([])


def test_deleted_position_must_reference_the_original_data_file() -> None:
    data_files = [{"file_path": "s3://bucket/data.parquet"}]
    positions = [{"file_path": "s3://bucket/data.parquet", "pos": 1}]

    assert position_targets_single_data_file(data_files, positions)
    assert not position_targets_single_data_file(
        data_files, [{"file_path": "s3://bucket/other.parquet", "pos": 1}]
    )
    assert not position_targets_single_data_file(data_files, [{**positions[0], "pos": -1}])


def test_flink_read_job_has_one_data_query_lifecycle() -> None:
    source = JAVA_SOURCE.read_text(encoding="utf-8")

    assert source.count("TableResult result = tableEnvironment.executeSql(query);") == 1
    assert source.count("SELECT COUNT(*)") == 1
    assert "INSERT INTO" not in source
    assert "classloader.check-leaked-classloader" not in source


def test_flink_read_marker_is_exact_and_fail_closed() -> None:
    plan = build_position_delete_plan(DEFAULT_SOURCE)
    marker = (
        "GDA_POSITION_DELETE_FLINK_READ rows=2 target_rows=0 distinct_roads=2 "
        f"target_road_id={plan['target_road_id']}"
    )

    assert parse_flink_read_marker(marker, plan)["status"] == "passed"
    assert parse_flink_read_marker(marker.replace("target_rows=0", "target_rows=1"), plan)[
        "status"
    ] == "failed"
    assert parse_flink_read_marker("no marker", plan)["status"] == "failed"

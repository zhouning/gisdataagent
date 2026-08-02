"""Focused contracts for Flink/Spark equality-delete interoperability."""

from __future__ import annotations

import io

import pyarrow as pa
import pyarrow.parquet as pq

from scripts.certify_chongqing_osm_flink_iceberg_interop import DEFAULT_SOURCE
from scripts.certify_chongqing_osm_flink_spark_equality_delete_interop import (
    JAVA_SOURCE,
    SPARK_SOURCE,
    _read_equality_delete_payload,
    build_equality_delete_plan,
    parse_flink_equality_delete_markers,
)
from scripts.spark_chongqing_osm_iceberg_equality_delete_interop import (
    is_single_equality_delete_file,
)


def test_equality_delete_plan_is_real_deterministic_and_key_scoped() -> None:
    first = build_equality_delete_plan(DEFAULT_SOURCE)
    second = build_equality_delete_plan(DEFAULT_SOURCE)

    assert first == second
    assert first["source"]["source_feature_count"] == 50_366
    assert len(first["baseline_rows"]) == 3
    assert len(first["final_rows"]) == 2
    assert first["delete_row"]["road_id"] == first["target_road_id"]
    assert len(first["flink_commit_token"]) == 64
    assert all(row["road_id"] != first["target_road_id"] for row in first["final_rows"])


def test_equality_delete_file_gate_rejects_position_and_wrong_field_ids() -> None:
    equality = {
        "content": 2,
        "file_path": "s3://bucket/delete.parquet",
        "file_format": "PARQUET",
        "record_count": 1,
        "equality_ids": [1],
    }

    assert is_single_equality_delete_file([equality], road_id_field_id=1)
    assert not is_single_equality_delete_file(
        [{**equality, "content": 1}], road_id_field_id=1
    )
    assert not is_single_equality_delete_file([equality], road_id_field_id=2)
    assert not is_single_equality_delete_file([], road_id_field_id=1)


def test_flink_equality_delete_job_has_one_provider_query() -> None:
    source = JAVA_SOURCE.read_text(encoding="utf-8")

    assert source.count("TableResult result = tableEnvironment.executeSql(") == 1
    assert source.count("RowKind.DELETE") == 2
    assert "RuntimeExecutionMode.STREAMING" in source
    assert "enableCheckpointing" not in source
    assert ".primaryKey(\"road_id\")" in source
    assert "SELECT COUNT(*)" not in source
    assert "classloader.check-leaked-classloader" not in source


def test_spark_baseline_creates_required_key_before_identifier_promotion() -> None:
    source = SPARK_SOURCE.read_text(encoding="utf-8")

    required = source.index('"road_id BIGINT NOT NULL')
    identifier = source.index("iceberg.updateSchema().setIdentifierFields(")
    assert required < identifier
    assert "allowIncompatibleChanges" not in source


def test_flink_equality_delete_markers_bind_key_and_token() -> None:
    plan = build_equality_delete_plan(DEFAULT_SOURCE)
    output = (
        "GDA_EQUALITY_DELETE_FLINK_STARTED "
        f"road_id={plan['target_road_id']} token={plan['flink_commit_token']}\n"
        "GDA_EQUALITY_DELETE_FLINK_COMMITTED "
        f"road_id={plan['target_road_id']} token={plan['flink_commit_token']}\n"
    )

    assert parse_flink_equality_delete_markers(output, plan)["status"] == "passed"
    assert parse_flink_equality_delete_markers(
        output.replace("GDA_EQUALITY_DELETE_FLINK_COMMITTED", "missing"), plan
    )["status"] == "failed"


def test_equality_delete_payload_reader_binds_minio_prefix_and_key() -> None:
    stream = io.BytesIO()
    pq.write_table(pa.table({"road_id": [102262020]}), stream)

    class Client:
        def get_object(self, **kwargs):
            assert kwargs == {
                "Bucket": "gis-agent-lakehouse",
                "Key": "acceptance/flink-iceberg/gda_flink_iceberg_0123456789/delete.parquet",
            }
            return {"Body": io.BytesIO(stream.getvalue())}

    evidence = _read_equality_delete_payload(
        Client(),
        delete_files=[
            {
                "file_path": (
                    "s3://gis-agent-lakehouse/acceptance/flink-iceberg/"
                    "gda_flink_iceberg_0123456789/delete.parquet"
                )
            }
        ],
        prefix="acceptance/flink-iceberg/gda_flink_iceberg_0123456789/",
    )

    assert evidence["road_ids"] == [102262020]
    assert len(evidence["sha256"]) == 64

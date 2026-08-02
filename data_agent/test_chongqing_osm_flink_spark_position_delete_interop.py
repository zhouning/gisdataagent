"""Focused contracts for Flink/Spark position-delete write interoperability."""

from __future__ import annotations

import io

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from scripts.certify_chongqing_osm_flink_iceberg_interop import DEFAULT_SOURCE
from scripts.certify_chongqing_osm_flink_spark_position_delete_interop import (
    JAVA_SOURCE,
    SPARK_SOURCE,
    _read_position_delete_payload,
    build_flink_position_delete_plan,
    parse_flink_commit_marker,
)


class _Body:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def read(self) -> bytes:
        return self.payload


class _S3:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.request: tuple[str, str] | None = None

    def get_object(self, *, Bucket: str, Key: str):  # noqa: N803
        self.request = (Bucket, Key)
        return {"Body": _Body(self.payload)}


def _position_parquet(data_file: str, position: int) -> bytes:
    output = io.BytesIO()
    pq.write_table(
        pa.table({"file_path": [data_file], "pos": pa.array([position], pa.int64())}),
        output,
    )
    return output.getvalue()


def test_flink_position_delete_plan_is_real_deterministic_and_bound() -> None:
    first = build_flink_position_delete_plan(DEFAULT_SOURCE)
    second = build_flink_position_delete_plan(DEFAULT_SOURCE)

    assert first == second
    assert first["source"]["source_feature_count"] == 50_366
    assert len(first["baseline_rows"]) == 3
    assert len(first["final_rows"]) == 2
    assert first["target_road_id"] == first["baseline_rows"][1]["road_id"]
    assert len(first["flink_commit_token"]) == 64


def test_flink_position_delete_marker_binds_snapshot_files_position_and_token() -> None:
    plan = build_flink_position_delete_plan(DEFAULT_SOURCE)
    warehouse = (
        "s3://gis-agent-lakehouse/acceptance/flink-iceberg/"
        "gda_flink_iceberg_0123456789/warehouse"
    )
    data_file = f"{warehouse}/gda_interop_0123456789/roads/data/base.parquet"
    delete_file = f"{warehouse}/gda_interop_0123456789/roads/data/delete.parquet"
    marker = (
        "GDA_POSITION_DELETE_FLINK_COMMITTED snapshot_id=123 "
        f"delete_file={delete_file} data_file={data_file} position=1 "
        f"target_road_id={plan['target_road_id']} token={plan['flink_commit_token']}"
    )

    evidence = parse_flink_commit_marker(
        marker,
        plan,
        data_file_path=data_file,
        row_position=1,
        warehouse_uri=warehouse,
    )

    assert evidence["status"] == "passed"
    assert evidence["snapshot_id"] == "123"
    assert parse_flink_commit_marker(
        marker.replace("position=1", "position=2"),
        plan,
        data_file_path=data_file,
        row_position=1,
        warehouse_uri=warehouse,
    )["status"] == "failed"


def test_flink_writer_is_one_non_restarting_taskmanager_row_delta() -> None:
    source = JAVA_SOURCE.read_text(encoding="utf-8")

    assert ".executeAndCollect()" in source
    assert "RestartStrategies.noRestart()" in source
    assert source.count(".addDeletes(deleteFile)") == 1
    assert source.count("delta.commit();") == 1
    assert ".validateFromSnapshot(options.baselineSnapshotId)" in source
    assert ".validateDataFilesExist(Collections.singleton(options.dataFilePath))" in source
    assert "newPosDeleteWriter" in source
    assert "INSERT INTO" not in source
    assert "tableEnvironment" not in source


def test_spark_owners_bind_hidden_position_and_independently_verify() -> None:
    source = SPARK_SOURCE.read_text(encoding="utf-8")

    assert "_file AS file_path, _pos AS pos" in source
    assert "target_physical_position_bound" in source
    assert "baseline_time_travel_exact" in source
    assert "flink_commit_token_bound" in source


def test_physical_position_delete_reader_returns_exact_payload() -> None:
    prefix = "acceptance/flink-iceberg/gda_flink_iceberg_0123456789/"
    data_file = f"s3://gis-agent-lakehouse/{prefix}warehouse/table/data/base.parquet"
    delete_file = f"s3://gis-agent-lakehouse/{prefix}warehouse/table/data/delete.parquet"
    client = _S3(_position_parquet(data_file, 7))

    evidence = _read_position_delete_payload(
        client,
        file_path=delete_file,
        prefix=prefix,
    )

    assert evidence["rows"] == 1
    assert evidence["columns"] == ["file_path", "pos"]
    assert evidence["referenced_data_files"] == [data_file]
    assert evidence["positions"] == [7]
    assert client.request == (
        "gis-agent-lakehouse",
        f"{prefix}warehouse/table/data/delete.parquet",
    )


def test_physical_reader_rejects_delete_file_outside_acceptance_prefix() -> None:
    client = _S3(b"")

    with pytest.raises(RuntimeError, match="outside acceptance prefix"):
        _read_position_delete_payload(
            client,
            file_path="s3://gis-agent-lakehouse/other/delete.parquet",
            prefix="acceptance/flink-iceberg/gda_flink_iceberg_0123456789/",
        )
    assert client.request is None

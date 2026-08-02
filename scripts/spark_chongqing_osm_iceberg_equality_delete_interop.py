#!/usr/bin/env python3
"""Create and verify one Flink equality delete for Spark interoperability."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.spark_chongqing_osm_iceberg_concurrent_append import COLUMNS, _schema
from scripts.spark_chongqing_osm_iceberg_delete_conflict import _iceberg_table, _snapshots
from scripts.spark_chongqing_osm_iceberg_interop import (
    CATALOG,
    _canonical_sha256,
    _spark,
)
from scripts.spark_chongqing_osm_iceberg_position_delete_interop import (
    _data_files,
    _delete_files,
)


def _rows(frame) -> tuple[dict[str, Any], ...]:
    return tuple(
        {key: row[key] for key in COLUMNS}
        for row in frame.select(*COLUMNS).orderBy("road_id").collect()
    )


def is_single_equality_delete_file(
    delete_files: list[dict[str, Any]], *, road_id_field_id: int
) -> bool:
    return (
        len(delete_files) == 1
        and delete_files[0]["content"] == 2
        and delete_files[0]["file_format"].upper() == "PARQUET"
        and delete_files[0]["record_count"] == 1
        and delete_files[0]["equality_ids"] == [road_id_field_id]
    )


def _identifier_evidence(spark, table: str) -> dict[str, Any]:
    iceberg = _iceberg_table(spark, table)
    schema = iceberg.schema()
    field_id = int(schema.findField("road_id").fieldId())
    names = sorted(str(name) for name in schema.identifierFieldNames())
    return {
        "road_id_field_id": field_id,
        "identifier_field_names": names,
        "road_id_is_identifier": names == ["road_id"],
    }


def _baseline(spark, args: argparse.Namespace, plan: dict[str, Any]) -> dict[str, Any]:
    namespace = args.table.split(".")[1]
    spark.sql(f"CREATE NAMESPACE IF NOT EXISTS {CATALOG}.{namespace}")
    if spark.catalog.tableExists(args.table):
        raise RuntimeError("isolated equality delete table already exists")
    frame = spark.createDataFrame(plan["baseline_rows"], schema=_schema()).coalesce(1)
    spark.sql(
        f"CREATE TABLE {args.table} ("
        "road_id BIGINT NOT NULL, revision INT NOT NULL, "
        "road_name_base64 STRING NOT NULL, geometry_sha256 STRING NOT NULL, "
        "writer_engine STRING NOT NULL, commit_token STRING) USING iceberg "
        "TBLPROPERTIES ("
        "'format-version'='2', 'write.upsert.enabled'='true', "
        "'write.delete.mode'='merge-on-read', "
        "'gda.acceptance'='flink-spark-equality-delete-interop', "
        f"'gda.source_sha256'='{plan['source']['source_parquet_sha256']}')"
    )
    frame.writeTo(args.table).append()
    iceberg = _iceberg_table(spark, args.table)
    iceberg.updateSchema().setIdentifierFields(
        spark._jvm.java.util.Collections.singletonList("road_id")  # noqa: SLF001
    ).commit()
    iceberg.refresh()
    actual = _rows(spark.table(args.table))
    snapshots = _snapshots(spark, args.table)
    data_files = _data_files(spark, args.table)
    delete_files = _delete_files(spark, args.table)
    identifiers = _identifier_evidence(spark, args.table)
    checks = {
        "baseline_rows_exact": list(actual) == plan["baseline_rows"],
        "baseline_content_exact": _canonical_sha256(actual)
        == plan["baseline_content_sha256"],
        "road_id_identifier_field_exact": identifiers["road_id_is_identifier"],
        "upsert_property_enabled": iceberg.properties().get("write.upsert.enabled")
        == "true",
        "one_three_row_data_file": len(data_files) == 1
        and data_files[0]["content"] == 0
        and data_files[0]["record_count"] == 3,
        "no_baseline_delete_files": delete_files == [],
        "one_append_snapshot": len(snapshots) == 1
        and snapshots[0]["operation"] == "append",
    }
    return {
        "phase": "baseline",
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "rows": len(actual),
        "content_sha256": _canonical_sha256(actual),
        "snapshots": snapshots,
        "data_files": data_files,
        "delete_files": delete_files,
        "identifiers": identifiers,
        "baseline_snapshot_id": snapshots[0]["snapshot_id"],
    }


def _verify(spark, args: argparse.Namespace, plan: dict[str, Any]) -> dict[str, Any]:
    actual = _rows(spark.table(args.table))
    baseline = _rows(
        spark.read.option("snapshot-id", args.baseline_snapshot_id).table(args.table)
    )
    snapshots = _snapshots(spark, args.table)
    data_files = _data_files(spark, args.table)
    delete_files = _delete_files(spark, args.table)
    identifiers = _identifier_evidence(spark, args.table)
    checks = {
        "final_rows_exact": list(actual) == plan["final_rows"],
        "final_content_exact": _canonical_sha256(actual) == plan["final_content_sha256"],
        "target_road_absent": all(
            row["road_id"] != plan["target_road_id"] for row in actual
        ),
        "baseline_time_travel_exact": list(baseline) == plan["baseline_rows"],
        "original_data_file_retained": len(data_files) == 1
        and data_files[0]["record_count"] == 3,
        "one_equality_delete_file_materialized": is_single_equality_delete_file(
            delete_files,
            road_id_field_id=identifiers["road_id_field_id"],
        ),
        "one_child_snapshot_committed": len(snapshots) == 2
        and snapshots[1]["parent_id"] == args.baseline_snapshot_id,
    }
    return {
        "phase": "verify",
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "rows": len(actual),
        "content_sha256": _canonical_sha256(actual),
        "snapshots": snapshots,
        "data_files": data_files,
        "delete_files": delete_files,
        "identifiers": identifiers,
        "baseline_time_travel_rows": len(baseline),
        "delete_snapshot_id": snapshots[-1]["snapshot_id"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("baseline", "verify"))
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--warehouse-uri", required=True)
    parser.add_argument("--table", required=True)
    parser.add_argument("--endpoint-url", default="http://minio:9000")
    parser.add_argument("--baseline-snapshot-id")
    args = parser.parse_args()
    if args.phase == "verify" and not args.baseline_snapshot_id:
        parser.error("verify requires --baseline-snapshot-id")
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        if not os.environ.get(name):
            raise RuntimeError(f"missing required environment variable {name}")

    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    spark = _spark(args)
    try:
        spark.sparkContext.setLogLevel("WARN")
        phase = _baseline(spark, args, plan) if args.phase == "baseline" else _verify(
            spark, args, plan
        )
    finally:
        spark.stop()
    report = {
        "schema": "gda.flink_spark_iceberg_equality_delete_phase.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        **phase,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"phase": args.phase, "status": report["status"]}))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

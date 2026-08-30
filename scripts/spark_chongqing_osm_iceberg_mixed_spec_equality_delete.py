#!/usr/bin/env python3
"""Verify a Flink equality delete across legacy and evolved Iceberg specs."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.spark_chongqing_osm_iceberg_concurrent_append import _schema
from scripts.spark_chongqing_osm_iceberg_delete_conflict import _iceberg_table, _snapshots
from scripts.spark_chongqing_osm_iceberg_equality_delete_interop import (
    _identifier_evidence,
    _rows,
)
from scripts.spark_chongqing_osm_iceberg_interop import CATALOG, _canonical_sha256, _spark
from scripts.spark_chongqing_osm_iceberg_mixed_spec_mor_delete import (
    _delete_files,
    _evolve,
    _files,
    _spec_fields,
)


def _baseline(spark, args: argparse.Namespace, plan: dict[str, Any]) -> dict[str, Any]:
    namespace = args.table.split(".")[1]
    spark.sql(f"CREATE NAMESPACE IF NOT EXISTS {CATALOG}.{namespace}")
    if spark.catalog.tableExists(args.table):
        raise RuntimeError("isolated mixed-spec equality delete table already exists")
    frame = spark.createDataFrame(plan["baseline_rows"], schema=_schema()).coalesce(1)
    spark.sql(
        f"CREATE TABLE {args.table} ("
        "road_id BIGINT NOT NULL, revision INT NOT NULL, "
        "road_name_base64 STRING NOT NULL, geometry_sha256 STRING NOT NULL, "
        "writer_engine STRING NOT NULL, commit_token STRING) USING iceberg "
        "TBLPROPERTIES ("
        "'format-version'='2', 'write.upsert.enabled'='true', "
        "'write.delete.mode'='merge-on-read', "
        "'gda.acceptance'='spark-flink-mixed-spec-equality-delete', "
        f"'gda.source_sha256'='{plan['source']['source_parquet_sha256']}')"
    )
    frame.writeTo(args.table).append()
    actual = _rows(spark.table(args.table))
    snapshots = _snapshots(spark, args.table)
    files = _files(spark, args.table)
    iceberg = _iceberg_table(spark, args.table)
    iceberg.updateSchema().setIdentifierFields(
        spark._jvm.java.util.Collections.singletonList("road_id")  # noqa: SLF001
    ).commit()
    iceberg.refresh()
    identifiers = _identifier_evidence(spark, args.table)
    properties = dict(iceberg.properties())
    checks = {
        "baseline_rows_exact": list(actual) == plan["baseline_rows"],
        "baseline_content_exact": _canonical_sha256(actual) == plan["baseline_content_sha256"],
        "road_id_identifier_field_exact": identifiers["road_id_is_identifier"],
        "merge_on_read_enabled": properties.get("write.delete.mode") == "merge-on-read",
        "baseline_spec_unpartitioned": _spec_fields(spark, args.table) == [],
        "baseline_files_spec_zero": bool(files) and {item["spec_id"] for item in files} == {0},
        "one_append_snapshot": len(snapshots) == 1 and snapshots[0]["operation"] == "append",
        "no_baseline_delete_files": _delete_files(spark, args.table) == [],
    }
    return {
        "phase": "baseline",
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "rows": len(actual),
        "actual_rows": list(actual),
        "content_sha256": _canonical_sha256(actual),
        "snapshots": snapshots,
        "files": files,
        "identifiers": identifiers,
        "baseline_snapshot_id": snapshots[0]["snapshot_id"],
    }


def _verify(spark, args: argparse.Namespace, plan: dict[str, Any]) -> dict[str, Any]:
    actual = _rows(spark.table(args.table))
    baseline = _rows(spark.read.option("snapshot-id", args.baseline_snapshot_id).table(args.table))
    flink = _rows(spark.read.option("snapshot-id", args.flink_snapshot_id).table(args.table))
    snapshots = _snapshots(spark, args.table)
    files = _files(spark, args.table, include_deletes=True)
    data_files = [item for item in files if item["content"] == 0]
    delete_files = _delete_files(spark, args.table)
    identifiers = _identifier_evidence(spark, args.table)
    field_id = identifiers["road_id_field_id"]
    target = int(plan["target_road_id"])
    rewrite_rows = None
    if args.rewrite_snapshot_id:
        rewrite_rows = _rows(
            spark.read.option("snapshot-id", args.rewrite_snapshot_id).table(args.table)
        )
    controlled_rewrite = args.rewrite_snapshot_id is not None
    expected_operations = (
        ["append", "overwrite", "delete", "append", "delete"]
        if controlled_rewrite
        else ["append", "overwrite", "delete"]
    )
    data_spec_ids = {item["spec_id"] for item in data_files}
    checks = {
        "final_rows_exact": list(actual) == plan["after_mixed_delete_rows"],
        "final_content_exact": _canonical_sha256(actual)
        == plan["after_mixed_delete_content_sha256"],
        "target_logical_key_removed": all(row["road_id"] != target for row in actual),
        "baseline_time_travel_exact": list(baseline) == plan["baseline_rows"],
        "flink_time_travel_exact": list(flink) == plan["after_flink_rows"],
        "controlled_rewrite_time_travel_exact": rewrite_rows is None
        or list(rewrite_rows) == plan["after_flink_rows"],
        "final_data_files_are_single_current_spec": controlled_rewrite
        and data_spec_ids == {1},
        "both_specs_still_have_data_files_under_mor": controlled_rewrite
        or (len(data_files) >= 2 and data_spec_ids == {0, 1}),
        "equality_delete_files_materialized": bool(delete_files)
        and all(
            item["content"] == 2
            and item["file_format"].upper() == "PARQUET"
            and item["record_count"] == 1
            for item in delete_files
        ),
        "equality_delete_targets_identifier_key": bool(delete_files)
        and all(item["equality_ids"] == [field_id] for item in delete_files),
        "evolved_spec_target_row_removed": not any(
            row["road_id"] == target and row["revision"] == 2 for row in actual
        ),
        "legacy_spec_target_row_survives": controlled_rewrite
        or any(row["road_id"] == target and row["revision"] == 1 for row in actual),
        "cross_spec_equality_delete_applied": controlled_rewrite
        and all(row["road_id"] != target for row in actual),
        "snapshot_chain_exact": len(snapshots) == len(expected_operations)
        and [item["operation"] for item in snapshots] == expected_operations
        and all(
            snapshots[index]["parent_id"] == snapshots[index - 1]["snapshot_id"]
            for index in range(1, len(snapshots))
        ),
    }
    return {
        "phase": "verify",
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "rows": len(actual),
        "actual_rows": list(actual),
        "content_sha256": _canonical_sha256(actual),
        "controlled_rewrite": controlled_rewrite,
        "data_spec_ids": sorted(data_spec_ids),
        "snapshots": snapshots,
        "files": files,
        "delete_files": delete_files,
        "identifiers": identifiers,
        "baseline_time_travel_rows": len(baseline),
        "baseline_time_travel_data": list(baseline),
        "flink_time_travel_rows": len(flink),
        "flink_time_travel_data": list(flink),
        "rewrite_time_travel_rows": len(rewrite_rows) if rewrite_rows is not None else None,
        "observed_snapshot_operations": [item["operation"] for item in snapshots],
    }


def _rewrite(spark, args: argparse.Namespace, plan: dict[str, Any]) -> dict[str, Any]:
    before_files = _files(spark, args.table)
    snapshots = _snapshots(spark, args.table)
    if len(snapshots) != 2 or snapshots[-1]["snapshot_id"] != args.flink_snapshot_id:
        raise RuntimeError("controlled rewrite did not start from exact Flink state")
    spark.sql(
        "CREATE OR REPLACE TEMP VIEW gda_mixed_spec_rewrite_source AS "
        f"SELECT road_id, revision, road_name_base64, geometry_sha256, writer_engine, "
        f"commit_token FROM {args.table}"
    )
    source_rows = _rows(spark.table("gda_mixed_spec_rewrite_source"))
    if list(source_rows) != plan["after_flink_rows"]:
        raise RuntimeError("controlled rewrite source was not materialized from Flink state")
    materialized = spark.createDataFrame(list(source_rows), schema=_schema())
    spark.sql(f"DELETE FROM {args.table} WHERE road_id IS NOT NULL").collect()
    after_delete_snapshots = _snapshots(spark, args.table)
    after_delete_files = _files(spark, args.table)
    materialized.writeTo(args.table).append()
    spark.catalog.clearCache()
    spark.catalog.refreshTable(args.table)
    actual = _rows(spark.table(args.table))
    after_files = _files(spark, args.table)
    after_snapshots = _snapshots(spark, args.table)
    data_spec_ids = {item["spec_id"] for item in after_files}
    checks = {
        "rewrite_source_materialized_exact": list(source_rows) == plan["after_flink_rows"],
        "rewrite_delete_removed_all_active_files": not after_delete_files,
        "rewrite_rows_exact": list(actual) == plan["after_flink_rows"],
        "rewrite_content_exact": _canonical_sha256(actual)
        == plan["after_flink_content_sha256"],
        "legacy_spec_files_removed": {item["spec_id"] for item in before_files} == {0, 1}
        and data_spec_ids == {1},
        "rewrite_delete_snapshot_child_of_flink": len(after_delete_snapshots) == 3
        and after_delete_snapshots[-1]["parent_id"] == args.flink_snapshot_id
        and after_delete_snapshots[-1]["operation"] == "delete",
        "rewrite_append_snapshot_child_of_delete": len(after_snapshots) == 4
        and after_snapshots[-1]["parent_id"] == after_delete_snapshots[-1]["snapshot_id"]
        and after_snapshots[-1]["operation"] == "append",
    }
    return {
        "phase": "rewrite",
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "rows": len(actual),
        "content_sha256": _canonical_sha256(actual),
        "before_files": before_files,
        "after_delete_files": after_delete_files,
        "after_delete_snapshots": after_delete_snapshots,
        "after_files": after_files,
        "snapshots": after_snapshots,
        "rewrite_snapshot_id": after_snapshots[-1]["snapshot_id"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("baseline", "evolve", "rewrite", "verify"))
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--warehouse-uri", required=True)
    parser.add_argument("--table", required=True)
    parser.add_argument("--endpoint-url", default="http://minio:9000")
    parser.add_argument("--baseline-snapshot-id")
    parser.add_argument("--flink-snapshot-id")
    parser.add_argument("--rewrite-snapshot-id")
    args = parser.parse_args()
    if args.phase != "baseline" and not args.baseline_snapshot_id:
        parser.error(f"{args.phase} requires --baseline-snapshot-id")
    if args.phase in ("rewrite", "verify") and not args.flink_snapshot_id:
        parser.error(f"{args.phase} requires --flink-snapshot-id")
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        if not os.environ.get(name):
            raise RuntimeError(f"missing required environment variable {name}")
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    spark = _spark(args)
    try:
        spark.sparkContext.setLogLevel("WARN")
        if args.phase == "baseline":
            phase = _baseline(spark, args, plan)
        elif args.phase == "evolve":
            phase = _evolve(spark, args, plan)
        elif args.phase == "rewrite":
            phase = _rewrite(spark, args, plan)
        else:
            phase = _verify(spark, args, plan)
    finally:
        spark.stop()
    report = {
        "schema": "gda.spark_flink_iceberg_mixed_spec_equality_delete_phase.v1",
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

#!/usr/bin/env python3
"""Run cardinality fail-closed and automatic fresh-state SQL MERGE retry in one worker."""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pyspark.sql.functions import col
from pyspark.sql.types import (
    IntegerType,
    LongType,
    StringType,
    StructField,
    StructType,
)

from scripts.spark_chongqing_osm_iceberg_concurrent_append import COLUMNS
from scripts.spark_chongqing_osm_iceberg_interop import (
    CATALOG,
    _canonical_sha256,
    _snapshots,
    _spark,
)

BARRIER_RE = re.compile(
    r"^/workspace/\.tmp/source-sync-certification/"
    r"flink_iceberg_sql_merge_auto_retry_[0-9a-f]{10}/spark-ready\.json$"
)


def _schema():
    return StructType(
        [
            StructField("road_id", LongType(), False),
            StructField("revision", IntegerType(), False),
            StructField("road_name_base64", StringType(), False),
            StructField("geometry_sha256", StringType(), False),
            StructField("writer_engine", StringType(), False),
            StructField("commit_token", StringType(), True),
        ]
    )


def _merge_schema():
    return StructType(
        [
            StructField("road_id", LongType(), False),
            StructField("expected_revision", IntegerType(), False),
            StructField("new_revision", IntegerType(), False),
            StructField("road_name_base64", StringType(), False),
            StructField("geometry_sha256", StringType(), False),
            StructField("writer_engine", StringType(), False),
            StructField("commit_token", StringType(), False),
            StructField("source_row_id", StringType(), False),
        ]
    )


def _rows(frame) -> tuple[dict[str, Any], ...]:
    return tuple(
        {key: row[key] for key in COLUMNS}
        for row in frame.select(*COLUMNS).orderBy("road_id", "revision", "writer_engine").collect()
    )


def _validate_barriers(args: argparse.Namespace) -> None:
    if not args.ready_marker or not args.release_marker:
        raise ValueError("automatic SQL MERGE retry requires both barrier paths")
    if not BARRIER_RE.fullmatch(args.ready_marker.as_posix()):
        raise ValueError("unsafe automatic SQL MERGE barrier path")
    if not BARRIER_RE.fullmatch(
        args.release_marker.as_posix().replace("spark-release.json", "spark-ready.json")
    ):
        raise ValueError("unsafe automatic SQL MERGE barrier path")
    if args.release_marker.as_posix() != args.ready_marker.as_posix().replace(
        "spark-ready.json", "spark-release.json"
    ):
        raise ValueError(
            "automatic SQL MERGE release marker must share the acceptance work directory"
        )


def _baseline(spark, args: argparse.Namespace, plan: dict[str, Any]) -> dict[str, Any]:
    namespace = args.table.split(".")[1]
    spark.sql(f"CREATE NAMESPACE IF NOT EXISTS {CATALOG}.{namespace}")
    if spark.catalog.tableExists(args.table):
        raise RuntimeError("isolated automatic-retry SQL MERGE table already exists")
    frame = spark.createDataFrame(plan["baseline_rows"], schema=_schema())
    (
        frame.writeTo(args.table)
        .using("iceberg")
        .partitionedBy(col("road_id"))
        .tableProperty("format-version", "2")
        .tableProperty("gda.acceptance", "spark-sql-merge-auto-retry")
        .tableProperty("gda.source_sha256", plan["source"]["source_parquet_sha256"])
        .create()
    )
    actual = _rows(spark.table(args.table))
    snapshots = _snapshots(spark, args.table)
    checks = {
        "baseline_rows_exact": list(actual) == plan["baseline_rows"],
        "baseline_content_exact": _canonical_sha256(actual) == plan["baseline_content_sha256"],
        "one_baseline_snapshot": len(snapshots) == 1 and snapshots[0]["operation"] == "append",
    }
    return {
        "phase": "baseline",
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "rows": len(actual),
        "content_sha256": _canonical_sha256(actual),
        "snapshots": snapshots,
        "baseline_snapshot_id": snapshots[0]["snapshot_id"],
    }


def _wait_partition(rows, *, marker: Path, release: Path, payload: dict[str, Any], timeout: int):
    values = list(rows)
    marker.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and not release.is_file():
        time.sleep(0.1)
    if not release.is_file():
        raise RuntimeError("automatic SQL MERGE retry barrier timed out")
    yield from values


def _merge_source(
    spark, args: argparse.Namespace, sources: list[dict[str, Any]], *, wait: bool
) -> None:
    columns = tuple(field.name for field in _merge_schema().fields)
    normalized_sources = [{key: source[key] for key in columns} for source in sources]
    frame = spark.createDataFrame(normalized_sources, schema=_merge_schema()).repartition(1)
    if wait:
        _validate_barriers(args)
        payload = {
            "schema": "gda.spark_sql_merge_auto_retry_ready.v1",
            "baseline_snapshot_id": args.baseline_snapshot_id,
            "source_row_count": len(sources),
            "source_row_ids": [source["source_row_id"] for source in sources],
            "target_road_id": sources[0]["road_id"],
            "expected_revision": sources[0]["expected_revision"],
        }
        frame = frame.rdd.mapPartitions(
            lambda rows: _wait_partition(
                rows,
                marker=args.ready_marker,
                release=args.release_marker,
                payload=payload,
                timeout=args.barrier_timeout_seconds,
            ),
            preservesPartitioning=True,
        ).toDF(_merge_schema())
    frame.createOrReplaceTempView("gda_sql_merge_source")


def _run_merge(
    spark, args: argparse.Namespace, sources: list[dict[str, Any]], *, wait: bool
) -> dict[str, Any]:
    _merge_source(spark, args, sources, wait=wait)
    merge_committed = False
    conflict: dict[str, Any] | None = None
    try:
        spark.sql(
            f"""
            MERGE INTO {args.table} AS target
            USING gda_sql_merge_source AS source
            ON target.road_id = source.road_id
               AND target.revision = source.expected_revision
            WHEN MATCHED THEN UPDATE SET
              target.revision = source.new_revision,
              target.road_name_base64 = source.road_name_base64,
              target.geometry_sha256 = source.geometry_sha256,
              target.writer_engine = source.writer_engine,
              target.commit_token = source.commit_token
            """
        )
        merge_committed = True
    except Exception as exc:
        text = str(exc)
        lower = text.lower()
        conflict = {
            "conflict_type": "multiple_source_rows_match_target",
            "source_row_conflict": any(
                phrase in lower
                for phrase in (
                    "multiple source rows",
                    "multiple rows",
                    "multiple matches",
                    "more than one source row",
                    "matched more than one",
                    "duplicate source",
                    "bitmapcardinalityvalidator",
                    "mergerows",
                    "duplicate",
                )
            ),
            "is_iceberg_validation_failure": "validationexception" in lower,
            "error_type": type(exc).__name__,
            "error": text[-2000:],
        }
    spark.catalog.clearCache()
    spark.catalog.refreshTable(args.table)
    actual = _rows(spark.table(args.table))
    snapshots = _snapshots(spark, args.table)
    source_tokens = {source["commit_token"] for source in sources}
    token_count = sum(row["commit_token"] in source_tokens for row in actual)
    checks = {
        "merge_not_committed": merge_committed if not wait else True,
        "source_row_conflict_observed": bool(conflict and conflict["source_row_conflict"])
        if wait
        else True,
    }
    return {
        "merge_committed": merge_committed,
        "conflict": conflict,
        "actual_rows": list(actual),
        "snapshots": snapshots,
        "commit_token_count": token_count,
        "checks": checks,
    }


def _concurrent_merge(spark, args: argparse.Namespace, plan: dict[str, Any]) -> dict[str, Any]:
    before = _snapshots(spark, args.table)
    if len(before) != 1 or before[0]["snapshot_id"] != args.baseline_snapshot_id:
        raise RuntimeError("SQL MERGE did not start from exact baseline snapshot")
    result = _run_merge(spark, args, plan["merge_source_stale_rows"], wait=True)
    release = json.loads(args.release_marker.read_text(encoding="utf-8"))
    target_rows = [row for row in result["actual_rows"] if row["road_id"] == plan["target_road_id"]]
    checks = {
        **result["checks"],
        "merge_not_committed": not result["merge_committed"],
        "baseline_and_flink_rows_preserved": result["actual_rows"] == plan["after_flink_rows"],
        "stale_merge_token_absent": result["commit_token_count"] == 0,
        "target_revisions_one_and_two_visible": sorted(row["revision"] for row in target_rows)
        == [1, 2],
        "source_row_conflict_observed": bool(
            result["conflict"] and result["conflict"].get("source_row_conflict")
        ),
        "release_marker_exact": release.get("schema")
        == "gda.spark_sql_merge_auto_retry_release.v1"
        and release.get("flink_commit_token") == plan["flink_commit_token"]
        and release.get("source_row_count") == 2
        and release.get("source_row_ids") == plan["stale_source_row_ids"],
        "catalog_snapshot_chain_unchanged": len(result["snapshots"]) == 2
        and result["snapshots"][-1]["snapshot_id"] == str(release.get("flink_snapshot_id")),
    }
    return {
        "phase": "concurrent-merge",
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "rows": len(result["actual_rows"]),
        "content_sha256": _canonical_sha256(result["actual_rows"]),
        "snapshots": result["snapshots"],
        "conflict": result["conflict"],
        "release": release,
        "merge_committed": result["merge_committed"],
        "stale_merge_token_count": result["commit_token_count"],
    }


def _automatic_retry(spark, args: argparse.Namespace, plan: dict[str, Any]) -> dict[str, Any]:
    conflict = _concurrent_merge(spark, args, plan)
    if conflict["status"] != "passed":
        return {
            "phase": "auto-retry",
            "status": "failed",
            "checks": {"cardinality_conflict_phase_passed": False},
            "conflict": conflict,
        }
    release = conflict["release"]
    flink_snapshot_id = str(release["flink_snapshot_id"])
    current = _rows(spark.table(args.table))
    before = _snapshots(spark, args.table)
    if (
        list(current) != plan["after_flink_rows"]
        or before[-1]["snapshot_id"] != flink_snapshot_id
    ):
        raise RuntimeError("automatic SQL MERGE retry did not read exact Flink state")
    candidates = plan.get("merge_source_candidates")
    selected_source = plan["merge_source_fresh"]
    selection: dict[str, Any] = {
        "policy": plan.get("deduplication_policy"),
        "candidate_source_row_ids": [row["source_row_id"] for row in candidates or ()],
        "selected_source_row_id": selected_source["source_row_id"],
    }
    if candidates:
        selected_source = sorted(
            candidates,
            key=lambda row: (-int(row["dedup_rank"]), str(row["source_row_id"])),
        )[0]
        selection["selected_source_row_id"] = selected_source["source_row_id"]
    retry_backoff = plan.get("successful_retry_backoff_policy")
    retry_delay = float(retry_backoff.get("delay_seconds", 0.0)) if retry_backoff else 0.0
    retry_started = time.monotonic()
    if retry_delay > 0:
        time.sleep(retry_delay)
    retry_observed = time.monotonic() - retry_started
    result = _run_merge(spark, args, [selected_source], wait=False)
    actual = result["actual_rows"]
    snapshots = result["snapshots"]
    first_retry_actual = actual
    first_retry_snapshots = snapshots
    retry_sequence: list[dict[str, Any]] = []
    for sequence_source in plan.get("successful_retry_sequence", []):
        sequence_result = _run_merge(spark, args, [sequence_source], wait=False)
        retry_sequence.append(
            {
                "source_row_id": sequence_source["source_row_id"],
                "commit_token": sequence_source["commit_token"],
                "merge_committed": sequence_result["merge_committed"],
                "actual_rows": sequence_result["actual_rows"],
                "snapshots": sequence_result["snapshots"],
            }
        )
        actual = sequence_result["actual_rows"]
        snapshots = sequence_result["snapshots"]
    unselected_tokens = {
        row["commit_token"]
        for row in candidates or ()
        if row["source_row_id"] != selected_source["source_row_id"]
    }
    checks = {
        "cardinality_conflict_phase_passed": conflict["status"] == "passed",
        "fresh_sql_merge_committed": result["merge_committed"],
        "final_rows_exact": actual == plan["final_merge_rows"],
        "fresh_merge_token_once": sum(
            row["commit_token"] == selected_source["commit_token"]
            for row in first_retry_actual
        )
        == 1,
        "automatic_deduplication_selected": not candidates
        or selection["selected_source_row_id"] == plan["merge_source_fresh"]["source_row_id"],
        "unselected_candidate_tokens_absent": not any(
            row["commit_token"] in unselected_tokens for row in actual
        ),
        "automatic_retry_snapshot_child_of_flink": len(snapshots) >= 3
        and snapshots[2]["parent_id"] == flink_snapshot_id
        and snapshots[2]["operation"] == "overwrite",
        "successful_retry_sequence_committed": all(
            item["merge_committed"] for item in retry_sequence
        ),
        "successful_retry_sequence_tokens_once": all(
            sum(row["commit_token"] == item["commit_token"] for row in actual) == 1
            for item in retry_sequence
        ),
        "successful_retry_sequence_snapshot_chain": len(snapshots)
        == 3 + len(retry_sequence)
        and all(
            snapshots[index]["parent_id"] == snapshots[index - 1]["snapshot_id"]
            and snapshots[index]["operation"] == "overwrite"
            for index in range(3, len(snapshots))
        ),
    }
    if retry_backoff:
        checks["successful_retry_backoff_observed_lower_bound"] = (
            retry_observed + 0.001 >= retry_delay
        )
    return {
        "phase": "auto-retry",
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "rows": len(actual),
        "content_sha256": _canonical_sha256(actual),
        "snapshots": snapshots,
        "conflict": conflict,
        "automatic_retry_snapshot_id": snapshots[-1]["snapshot_id"],
        "automatic_retry_source_row_id": plan["merge_source_fresh"]["source_row_id"],
        "first_retry_snapshot_id": first_retry_snapshots[-1]["snapshot_id"],
        "successful_retry_sequence": retry_sequence,
        "deduplication": selection,
        "retry_backoff": (
            {
                **retry_backoff,
                "observed_seconds": retry_observed,
            }
            if retry_backoff
            else None
        ),
    }


def _intermediate_retry_rows(plan: dict[str, Any]) -> list[dict[str, Any]]:
    fresh = plan["merge_source_fresh"]
    fresh_row = {
        "road_id": fresh["road_id"],
        "revision": fresh["new_revision"],
        "road_name_base64": fresh["road_name_base64"],
        "geometry_sha256": fresh["geometry_sha256"],
        "writer_engine": fresh["writer_engine"],
        "commit_token": fresh["commit_token"],
    }
    return sorted(
        [row for row in plan["after_flink_rows"] if row["road_id"] != fresh["road_id"]]
        + [
            row
            for row in plan["after_flink_rows"]
            if row["road_id"] == fresh["road_id"] and row["revision"] == 1
        ]
        + [fresh_row],
        key=lambda row: (int(row["road_id"]), int(row["revision"]), str(row["writer_engine"])),
    )


def _wait_for_release(args: argparse.Namespace) -> None:
    if args.release_marker is None:
        raise ValueError("cross-process SQL MERGE worker requires a release marker")
    deadline = time.monotonic() + args.barrier_timeout_seconds
    while time.monotonic() < deadline and not args.release_marker.is_file():
        time.sleep(0.1)
    if not args.release_marker.is_file():
        raise RuntimeError("cross-process SQL MERGE release marker timed out")


def _cross_process_first(spark, args: argparse.Namespace, plan: dict[str, Any]) -> dict[str, Any]:
    _wait_for_release(args)
    intermediate_rows = _intermediate_retry_rows(plan)
    release = json.loads(args.release_marker.read_text(encoding="utf-8"))
    before = _snapshots(spark, args.table)
    current = _rows(spark.table(args.table))
    if (
        len(before) != 2
        or before[-1]["snapshot_id"] != str(release["flink_snapshot_id"])
        or list(current) != plan["after_flink_rows"]
    ):
        raise RuntimeError("first worker did not observe exact Flink child state")
    stale = _run_merge(spark, args, plan["merge_source_stale_rows"], wait=False)
    stale_rows = stale["actual_rows"]
    stale_snapshots = stale["snapshots"]
    fresh = _run_merge(spark, args, [plan["merge_source_fresh"]], wait=False)
    checks = {
        "first_worker_stale_rejected": not stale["merge_committed"]
        and bool(stale["conflict"] and stale["conflict"].get("source_row_conflict")),
        "first_worker_stale_tokens_absent": not any(
            row["commit_token"] in set(plan["sql_merge_stale_tokens"])
            for row in stale_rows
        ),
        "first_worker_stale_left_flink_snapshot": stale_snapshots == before,
        "first_worker_fresh_committed": fresh["merge_committed"],
        "first_worker_final_rows_revision_3": fresh["actual_rows"] == intermediate_rows,
        "first_worker_snapshot_parent_is_flink": len(fresh["snapshots"]) == 3
        and fresh["snapshots"][-1]["parent_id"] == str(release["flink_snapshot_id"])
        and fresh["snapshots"][-1]["operation"] == "overwrite",
    }
    return {
        "phase": "cross-process-first",
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "worker_role": "first-successful-retry",
        "rows": len(fresh["actual_rows"]),
        "content_sha256": _canonical_sha256(fresh["actual_rows"]),
        "snapshots": fresh["snapshots"],
        "stale": stale,
        "fresh": fresh,
    }


def _cross_process_second(spark, args: argparse.Namespace, plan: dict[str, Any]) -> dict[str, Any]:
    before = _snapshots(spark, args.table)
    expected_rows = _intermediate_retry_rows(plan)
    current = _rows(spark.table(args.table))
    if len(before) != 3 or list(current) != expected_rows:
        raise RuntimeError("second worker did not observe exact revision-3 first-worker state")
    source = plan["successful_retry_sequence"][0]
    result = _run_merge(spark, args, [source], wait=False)
    snapshots = result["snapshots"]
    actual = result["actual_rows"]
    checks = {
        "second_worker_committed": result["merge_committed"],
        "second_worker_observed_revision_3": list(current) == expected_rows,
        "final_rows_exact": actual == plan["final_merge_rows"],
        "second_retry_token_once": sum(
            row["commit_token"] == source["commit_token"] for row in actual
        )
        == 1,
        "second_snapshot_parent_is_first_worker": len(snapshots) == 4
        and snapshots[-1]["parent_id"] == snapshots[-2]["snapshot_id"]
        and snapshots[-1]["operation"] == "overwrite",
    }
    return {
        "phase": "cross-process-second",
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "worker_role": "second-successful-retry",
        "rows": len(actual),
        "content_sha256": _canonical_sha256(actual),
        "snapshots": snapshots,
        "source_row_id": source["source_row_id"],
        "commit_token": source["commit_token"],
    }


def _abort_after_commit(spark, args: argparse.Namespace, plan: dict[str, Any]) -> dict[str, Any]:
    if args.commit_marker is None or args.release_marker is None:
        raise ValueError("abort-after-commit requires commit and release markers")
    result = _run_merge(spark, args, [plan["merge_source_fresh"]], wait=False)
    if not result["merge_committed"]:
        raise RuntimeError("abort-after-commit MERGE did not commit")
    marker = {
        "schema": "gda.spark_sql_merge_abort_after_commit.v1",
        "snapshot_id": result["snapshots"][-1]["snapshot_id"],
        "parent_snapshot_id": result["snapshots"][-1]["parent_id"],
        "commit_token": plan["merge_source_fresh"]["commit_token"],
        "source_row_id": plan["merge_source_fresh"]["source_row_id"],
        "content_sha256": _canonical_sha256(result["actual_rows"]),
        "snapshot_count": len(result["snapshots"]),
    }
    args.commit_marker.write_text(
        json.dumps(marker, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    deadline = time.monotonic() + args.barrier_timeout_seconds
    while time.monotonic() < deadline and not args.release_marker.is_file():
        time.sleep(0.1)
    raise RuntimeError("abort-after-commit provider hold ended without external release")


def _abort_reconcile(spark, args: argparse.Namespace, plan: dict[str, Any]) -> dict[str, Any]:
    if args.commit_marker is None or not args.commit_marker.is_file():
        raise ValueError("abort-reconcile requires an existing commit marker")
    marker = json.loads(args.commit_marker.read_text(encoding="utf-8"))
    snapshots = _snapshots(spark, args.table)
    actual = _rows(spark.table(args.table))
    expected = plan["final_merge_rows"]
    token = plan["merge_source_fresh"]["commit_token"]
    checks = {
        "marker_schema_exact": marker.get("schema") == "gda.spark_sql_merge_abort_after_commit.v1",
        "committed_snapshot_present": any(
            item["snapshot_id"] == str(marker.get("snapshot_id")) for item in snapshots
        ),
        "current_snapshot_matches_marker": snapshots[-1]["snapshot_id"]
        == str(marker.get("snapshot_id")),
        "parent_snapshot_matches_marker": snapshots[-1]["parent_id"]
        == marker.get("parent_snapshot_id"),
        "final_rows_exact": list(actual) == expected,
        "commit_token_once": sum(row["commit_token"] == token for row in actual) == 1,
        "content_hash_matches_marker": _canonical_sha256(actual) == marker.get("content_sha256"),
        "no_duplicate_snapshot": len(snapshots) == int(marker.get("snapshot_count", -1)),
    }
    return {
        "phase": "abort-reconcile",
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "reconciliation_status": "committed_unacknowledged",
        "marker": marker,
        "rows": len(actual),
        "content_sha256": _canonical_sha256(actual),
        "snapshots": snapshots,
    }


def _budget_exhausted(spark, args: argparse.Namespace, plan: dict[str, Any]) -> dict[str, Any]:
    retry_rows = plan["retry_budget_rows"]
    budget = int(plan["retry_budget"])
    forced_failures = int(plan["forced_retry_attempts"])
    attempts: list[dict[str, Any]] = []
    _merge_source(spark, args, retry_rows, wait=True)
    before = _snapshots(spark, args.table)
    if not before:
        raise RuntimeError("retry budget phase could not observe a Flink child snapshot")
    flink_snapshot_id = before[-1]["snapshot_id"]
    flink_rows = _rows(spark.table(args.table))
    source_rows = [row.asDict() for row in spark.table("gda_sql_merge_source").collect()]
    target_id = retry_rows[0]["road_id"]
    expected_revision = retry_rows[0]["expected_revision"]
    duplicate_matches = sum(
        row["road_id"] == target_id and row["expected_revision"] == expected_revision
        for row in source_rows
    )
    backoff_policy = plan.get("retry_backoff_policy")
    backoff_delays: list[float] = []
    for attempt in range(1, budget + 1):
        delay = 0.0
        if backoff_policy:
            delay = (
                float(backoff_policy.get("first_attempt_delay_seconds", 0.0))
                if attempt == 1
                else min(
                    float(backoff_policy["max_seconds"]),
                    float(backoff_policy["initial_seconds"])
                    * float(backoff_policy["multiplier"]) ** (attempt - 2),
                )
            )
        started = time.monotonic()
        if delay > 0:
            time.sleep(delay)
        observed_delay = time.monotonic() - started
        backoff_delays.append(delay)
        attempts.append(
            {
                "attempt": attempt,
                "merge_committed": False,
                "source_row_conflict_observed": duplicate_matches > 1,
                "admission": "duplicate_source_rejected_before_merge",
                "snapshot_count": len(before),
                **(
                    {
                        "backoff_delay_seconds": delay,
                        "backoff_observed_seconds": observed_delay,
                    }
                    if backoff_policy
                    else {}
                ),
            }
        )
    after = _snapshots(spark, args.table)
    final_rows = _rows(spark.table(args.table))
    checks = {
        "retry_budget_positive": budget > 0,
        "forced_failures_exceed_budget": forced_failures > budget,
        "attempt_count_equals_budget": len(attempts) == budget,
        "all_budget_attempts_failed_closed": all(
            not item["merge_committed"] and item["source_row_conflict_observed"]
            for item in attempts
        ),
        "duplicate_source_admission_detected": duplicate_matches == len(retry_rows)
        and duplicate_matches > 1,
        "catalog_unchanged_after_budget": after == before
        and after[-1]["snapshot_id"] == flink_snapshot_id,
        "flink_state_rows_observed": bool(flink_rows),
        "rows_unchanged_after_budget": final_rows == flink_rows,
        "attempts_after_budget_not_submitted": forced_failures - len(attempts) > 0,
    }
    if backoff_policy:
        expected_delays = [
            (
                float(backoff_policy.get("first_attempt_delay_seconds", 0.0))
                if attempt == 1
                else min(
                    float(backoff_policy["max_seconds"]),
                    float(backoff_policy["initial_seconds"])
                    * float(backoff_policy["multiplier"]) ** (attempt - 2),
                )
            )
            for attempt in range(1, budget + 1)
        ]
        checks.update(
            {
                "adaptive_backoff_sequence_exact": backoff_delays == expected_delays,
                "adaptive_backoff_observed_lower_bound": all(
                    item["backoff_observed_seconds"] + 0.001
                    >= item["backoff_delay_seconds"]
                    for item in attempts
                ),
            }
        )
    return {
        "phase": "budget-exhausted",
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "retry_budget": budget,
        "forced_retry_attempts": forced_failures,
        "attempts": attempts,
        "prevented_attempts": forced_failures - len(attempts),
        "snapshots": after,
        "rows": len(final_rows),
        "content_sha256": _canonical_sha256(final_rows),
        "flink_snapshot_id": flink_snapshot_id,
        "backoff_policy": backoff_policy,
    }


def _verify(spark, args: argparse.Namespace, plan: dict[str, Any]) -> dict[str, Any]:
    actual = _rows(spark.table(args.table))
    snapshots = _snapshots(spark, args.table)
    baseline = _rows(spark.read.option("snapshot-id", args.baseline_snapshot_id).table(args.table))
    flink = _rows(spark.read.option("snapshot-id", args.flink_snapshot_id).table(args.table))
    first_retry = _rows(
        spark.read.option("snapshot-id", snapshots[2]["snapshot_id"]).table(args.table)
    )
    first_retry_row = {
        "road_id": plan["merge_source_fresh"]["road_id"],
        "revision": plan["merge_source_fresh"]["new_revision"],
        "road_name_base64": plan["merge_source_fresh"]["road_name_base64"],
        "geometry_sha256": plan["merge_source_fresh"]["geometry_sha256"],
        "writer_engine": plan["merge_source_fresh"]["writer_engine"],
        "commit_token": plan["merge_source_fresh"]["commit_token"],
    }
    expected_first_retry_rows = sorted(
        [
            row
            for row in plan["after_flink_rows"]
            if row["road_id"] != first_retry_row["road_id"]
        ]
        + [
            row
            for row in plan["after_flink_rows"]
            if row["road_id"] == first_retry_row["road_id"] and row["revision"] == 1
        ]
        + [first_retry_row],
        key=lambda row: (int(row["road_id"]), int(row["revision"]), str(row["writer_engine"])),
    )
    expected_snapshot_operations = ["append", "append"] + [
        "overwrite"
    ] * (1 + len(plan.get("successful_retry_sequence", [])))
    checks = {
        "final_rows_exact": list(actual) == plan["final_merge_rows"],
        "final_content_exact": _canonical_sha256(actual) == plan["final_merge_content_sha256"],
        "baseline_time_travel_exact": list(baseline) == plan["baseline_rows"],
        "flink_time_travel_exact": list(flink) == plan["after_flink_rows"],
        "first_retry_time_travel_exact": list(first_retry) == expected_first_retry_rows,
        "snapshot_chain_exact": [item["operation"] for item in snapshots]
        == expected_snapshot_operations,
        "road_ids_remain_bounded": len(actual) == 4,
    }
    return {
        "phase": "verify",
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "rows": len(actual),
        "content_sha256": _canonical_sha256(actual),
        "snapshots": snapshots,
        "first_retry_rows": first_retry,
        "expected_first_retry_rows": expected_first_retry_rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "phase",
        choices=(
            "baseline",
            "auto-retry",
            "budget-exhausted",
            "cross-process-first",
            "cross-process-second",
            "abort-after-commit",
            "abort-reconcile",
            "verify",
        ),
    )
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--warehouse-uri", required=True)
    parser.add_argument("--table", required=True)
    parser.add_argument("--endpoint-url", default="http://minio:9000")
    parser.add_argument("--baseline-snapshot-id")
    parser.add_argument("--flink-snapshot-id")
    parser.add_argument("--ready-marker", type=Path)
    parser.add_argument("--release-marker", type=Path)
    parser.add_argument("--commit-marker", type=Path)
    parser.add_argument("--barrier-timeout-seconds", type=int, default=180)
    args = parser.parse_args()
    if args.phase != "baseline" and not args.baseline_snapshot_id:
        parser.error(f"{args.phase} requires --baseline-snapshot-id")
    if args.phase == "verify" and not args.flink_snapshot_id:
        parser.error(f"{args.phase} requires --flink-snapshot-id")
    if not 30 <= args.barrier_timeout_seconds <= 300:
        parser.error("barrier timeout must be between 30 and 300 seconds")
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        if not os.environ.get(name):
            raise RuntimeError(f"missing required environment variable {name}")
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    spark = _spark(args)
    try:
        spark.sparkContext.setLogLevel("WARN")
        if args.phase == "baseline":
            phase = _baseline(spark, args, plan)
        elif args.phase == "auto-retry":
            phase = _automatic_retry(spark, args, plan)
        elif args.phase == "budget-exhausted":
            phase = _budget_exhausted(spark, args, plan)
        elif args.phase == "cross-process-first":
            phase = _cross_process_first(spark, args, plan)
        elif args.phase == "cross-process-second":
            phase = _cross_process_second(spark, args, plan)
        elif args.phase == "abort-after-commit":
            phase = _abort_after_commit(spark, args, plan)
        elif args.phase == "abort-reconcile":
            phase = _abort_reconcile(spark, args, plan)
        else:
            phase = _verify(spark, args, plan)
    finally:
        spark.stop()
    report = {
        "schema": "gda.spark_flink_iceberg_sql_merge_auto_retry_phase.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        **phase,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"phase": args.phase, "status": report["status"]}))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

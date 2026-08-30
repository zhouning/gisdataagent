#!/usr/bin/env python3
"""Certify cross-process retry-budget admission in the shared PostgreSQL authority."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import psycopg2

from data_agent.connectors.database import _connection_url
from data_agent.lakehouse_retry_budget import (
    drop_retry_budget_schema,
    ensure_retry_budget_schema,
    initialize_retry_budget,
    read_retry_budget_ledger,
)
from scripts.certify_chongqing_osm_flink_iceberg_interop import DEFAULT_SOURCE
from scripts.certify_chongqing_osm_incremental_sync import _main_sync_counts
from scripts.certify_chongqing_osm_spark_flink_update_conflict import build_update_conflict_plan
from scripts.certify_source_sync_authority import _settings

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = (
    REPO_ROOT
    / "docs/reports/chongqing_osm_spark_flink_sql_merge_cross_process_budget_2026-08-24.json"
)


def _worker(args: argparse.Namespace) -> int:
    ready = Path(args.ready)
    release = Path(args.release)
    output = Path(args.output)
    ready.write_text(args.worker_id, encoding="utf-8")
    deadline = time.monotonic() + args.timeout_seconds
    while time.monotonic() < deadline and not release.is_file():
        time.sleep(0.02)
    if not release.is_file():
        raise RuntimeError("cross-process budget release timed out")
    from data_agent.lakehouse_retry_budget import admit_retry

    results = [
        admit_retry(
            os.environ["GDA_RETRY_DATABASE_URL"],
            schema=args.schema,
            operation_key=args.operation_key,
            worker_id=args.worker_id,
        ).as_dict()
        for _ in range(args.attempts)
    ]
    output.write_text(json.dumps(results, sort_keys=True) + "\n", encoding="utf-8")
    return 0


def _summary(
    results: list[dict[str, object]], ledger: dict[str, object], max_attempts: int
) -> dict[str, bool]:
    events = list(ledger["events"])
    admitted = [item for item in events if item["admitted"]]
    denied = [item for item in events if not item["admitted"]]
    return {
        "two_workers_observed": len({str(item["worker_id"]) for item in results}) == 2,
        "shared_budget_exact": ledger["attempt_count"] == max_attempts
        and ledger["status"] == "exhausted",
        "admitted_count_equals_budget": len(admitted) == max_attempts,
        "denied_count_is_one": len(denied) == 1,
        "attempt_numbers_are_unique_and_ordered": sorted(
            int(item["attempt_number"]) for item in events
        )
        == list(range(1, max_attempts + 2)),
        "all_denials_fail_closed": all(
            item["reason"] == "retry_budget_exhausted" for item in denied
        ),
        "worker_results_complete": len(results) == 4,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--database-url")
    parser.add_argument("--schema")
    parser.add_argument("--operation-key")
    parser.add_argument("--worker-id")
    parser.add_argument("--ready")
    parser.add_argument("--release")
    parser.add_argument("--output")
    parser.add_argument("--attempts", type=int, default=2)
    parser.add_argument("--timeout-seconds", type=int, default=60)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    if args.worker:
        return _worker(args)

    settings = _settings()
    database_url = _connection_url(
        settings.get("POSTGRES_URL", "postgresql://127.0.0.1:5433/gis_agent"),
        {
            "type": "basic",
            "username": settings.get("POSTGRES_USER", "postgres"),
            "password": settings.get(
                "POSTGRES_ADMIN_PASSWORD", settings.get("POSTGRES_PASSWORD", "postgres")
            ),
        },
    )
    token = secrets.token_hex(5)
    schema = f"gda_retry_budget_{token}"
    operation_key = f"chongqing-osm-merge-{token}"
    work_dir = REPO_ROOT / ".tmp/source-sync-certification" / f"cross_process_budget_{token}"
    work_dir.mkdir(parents=True, exist_ok=False)
    ready_dir = work_dir / "ready"
    ready_dir.mkdir()
    release = work_dir / "release"
    worker_outputs = [work_dir / "worker-a.json", work_dir / "worker-b.json"]
    admin_url = database_url
    before_counts = _main_sync_counts(admin_url)
    source = build_update_conflict_plan(DEFAULT_SOURCE)["source"]
    connection = psycopg2.connect(database_url)
    workers: list[subprocess.Popen[str]] = []
    report: dict[str, object] | None = None
    cleanup: dict[str, object] = {}
    error: str | None = None
    try:
        ensure_retry_budget_schema(connection, schema)
        initialize_retry_budget(connection, schema, operation_key, 3)
        env = {**os.environ, "GDA_RETRY_DATABASE_URL": database_url}
        for worker_id, output in (
            ("worker-a", worker_outputs[0]),
            ("worker-b", worker_outputs[1]),
        ):
            workers.append(
                subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "scripts.certify_chongqing_osm_spark_flink_sql_merge_cross_process_budget",
                        "--worker",
                        "--schema",
                        schema,
                        "--operation-key",
                        operation_key,
                        "--worker-id",
                        worker_id,
                        "--ready",
                        str(ready_dir / f"{worker_id}.ready"),
                        "--release",
                        str(release),
                        "--output",
                        str(output),
                        "--attempts",
                        "2",
                    ],
                    cwd=REPO_ROOT,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
            )
        deadline = time.monotonic() + args.timeout_seconds
        while time.monotonic() < deadline and len(list(ready_dir.glob("*.ready"))) < 2:
            time.sleep(0.02)
        if len(list(ready_dir.glob("*.ready"))) != 2:
            diagnostics = []
            for worker in workers:
                if worker.poll() is None:
                    worker.terminate()
                stdout, stderr = worker.communicate(timeout=15)
                diagnostics.append(
                    {
                        "returncode": worker.returncode,
                        "stdout": stdout,
                        "stderr": stderr,
                    }
                )
            raise RuntimeError(
                "cross-process workers did not rendezvous: "
                f"{diagnostics}"
            )
        release.write_text("release\n", encoding="utf-8")
        worker_errors = []
        for worker in workers:
            stdout, stderr = worker.communicate(timeout=args.timeout_seconds)
            if worker.returncode != 0:
                worker_errors.append(
                    {"returncode": worker.returncode, "stdout": stdout, "stderr": stderr}
                )
        if worker_errors:
            raise RuntimeError(f"cross-process worker failure: {worker_errors}")
        results = [
            item
            for path in worker_outputs
            for item in json.loads(path.read_text(encoding="utf-8"))
        ]
        ledger = read_retry_budget_ledger(connection, schema, operation_key)
        checks = _summary(results, ledger, 3)
        report = {
            "schema": "gda.chongqing_osm_spark_flink_sql_merge_cross_process_budget.acceptance.v1",
            "status": "passed" if all(checks.values()) else "failed",
            "generated_at": datetime.now(UTC).isoformat(),
            "checks": checks,
            "source": {**source, "source_feature_count": source["source_feature_count"]},
            "authority": {
                "database": "PostgreSQL",
                "schema": schema,
                "operation_key": operation_key,
                "max_attempts": 3,
                "worker_ids": ["worker-a", "worker-b"],
                "ledger": ledger,
            },
            "not_claimed": [
                "cross-process Iceberg destructive write or provider abort recovery",
                (
                    "successful retry after shared admission, cross-system exactly-once or "
                    "production HA"
                ),
            ],
        }
        if report["status"] != "passed":
            raise RuntimeError(f"cross-process budget checks failed: {checks}")
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        for worker in workers:
            if worker.poll() is None:
                worker.terminate()
                worker.wait(timeout=15)
        try:
            drop_retry_budget_schema(connection, schema)
            cleanup["schema_removed"] = True
        except Exception:
            cleanup["schema_removed"] = False
        connection.close()
        shutil.rmtree(work_dir, ignore_errors=True)
        cleanup["work_directory_removed"] = not work_dir.exists()
        after_counts = _main_sync_counts(admin_url)
        cleanup["main_source_sync_unchanged"] = after_counts == before_counts
        cleanup["main_source_sync_counts"] = list(after_counts)
    if report is None:
        report = {
            "schema": "gda.chongqing_osm_spark_flink_sql_merge_cross_process_budget.acceptance.v1",
            "status": "failed",
            "generated_at": datetime.now(UTC).isoformat(),
            "checks": {},
            "error": error,
        }
    report["cleanup"] = cleanup
    if not all(
        cleanup.get(key) is True
        for key in ("schema_removed", "work_directory_removed", "main_source_sync_unchanged")
    ):
        report["status"] = "failed"
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "report": str(args.report),
                "checks": report["checks"],
                "cleanup": cleanup,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

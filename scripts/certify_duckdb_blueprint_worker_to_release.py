#!/usr/bin/env python3
"""Certify scoped S3 worker redelivery through the live Blueprint release gate."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from certify_duckdb_blueprint_worker_object_store import _provision_worker
from certify_metric_query_s3_result_store import _DisposableMinio

from data_agent.platform_contracts import canonical_json_fingerprint

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = REPO_ROOT / ".tmp/duckdb-blueprint-worker-to-release/report.json"


def certify(*, database_url: str) -> dict[str, Any]:
    sandbox = _DisposableMinio()
    cleanup: dict[str, bool] = {}
    pytest_output = ""
    return_code = 1
    try:
        sandbox.start()
        worker_access, worker_secret = _provision_worker(
            sandbox,
            "worker-release-secret-" + sandbox.container,
        )
        environment = {
            **os.environ,
            "DATABASE_URL": database_url,
            "GDA_BLUEPRINT_ACCEPTANCE_S3_ENDPOINT": sandbox.endpoint,
            "GDA_BLUEPRINT_ACCEPTANCE_S3_BUCKET": sandbox.bucket,
            "GDA_BLUEPRINT_ACCEPTANCE_S3_ADMIN_ACCESS_KEY": (
                sandbox.root_access_key
            ),
            "GDA_BLUEPRINT_ACCEPTANCE_S3_ADMIN_SECRET_KEY": (
                sandbox.root_secret_key
            ),
            "GDA_BLUEPRINT_ACCEPTANCE_S3_WORKER_ACCESS_KEY": worker_access,
            "GDA_BLUEPRINT_ACCEPTANCE_S3_WORKER_SECRET_KEY": worker_secret,
        }
        completed = subprocess.run(
            [
                str(REPO_ROOT / ".venv/bin/pytest"),
                "-q",
                "data_agent/test_data_product_blueprint_postgres.py",
            ],
            cwd=REPO_ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=180,
        )
        return_code = completed.returncode
        pytest_output = "\n".join(
            line
            for line in (completed.stdout + "\n" + completed.stderr).splitlines()
            if line.strip()
        )[-2000:]
    finally:
        cleanup = sandbox.cleanup()

    checks = {
        "postgres_s3_worker_to_release_acceptance": return_code == 0,
        "bucket_removed": cleanup.get("bucket_removed", False),
        "container_removed": cleanup.get("container_removed", False),
    }
    report: dict[str, Any] = {
        "schema": "gda.duckdb_blueprint_worker_to_release_certification.v1",
        "status": "passed" if all(checks.values()) else "failed",
        "scope": "postgresql_disposable_database_and_scoped_minio_identity",
        "checks": checks,
        "pytest_exit_code": return_code,
        "pytest_summary": pytest_output,
        "cleanup": cleanup,
        "observed_at": datetime.now(UTC).isoformat(),
    }
    report["report_sha256"] = canonical_json_fingerprint(report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=(
            "postgresql+psycopg2://postgres:postgres@127.0.0.1:5433/gis_agent"
        ),
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)
    report = certify(database_url=args.database_url)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Certify migration 113 in a disposable PostgreSQL 16 container."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = (
    REPO_ROOT
    / ".tmp"
    / "data-architecture-version-authority"
    / "acceptance-report.json"
)
POSTGRES_TEST = "data_agent/test_data_architecture_ledger_postgres.py"
ARCHITECTURE_TABLES = (
    "schema_version",
    "data_contract_version",
    "physical_location",
    "resource_version_architecture_binding",
)


def _docker(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args],
        check=check,
        capture_output=True,
        text=True,
    )


def _start_postgres(image: str) -> tuple[str, int]:
    container = f"gda-data-architecture-{secrets.token_hex(5)}"
    _docker(
        "run",
        "--rm",
        "--detach",
        "--name",
        container,
        "--publish",
        "127.0.0.1::5432",
        "--env",
        "POSTGRES_HOST_AUTH_METHOD=trust",
        image,
    )
    for _ in range(120):
        ready = _docker(
            "exec",
            container,
            "pg_isready",
            "-U",
            "postgres",
            check=False,
        )
        if ready.returncode == 0:
            binding = _docker("port", container, "5432/tcp").stdout.strip()
            return container, int(binding.splitlines()[0].rsplit(":", 1)[1])
        time.sleep(0.25)
    raise RuntimeError("disposable PostgreSQL did not become ready")


def _wait_for_host_connection(engine) -> None:
    last_error = None
    for _ in range(120):
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return
        except DBAPIError as error:
            last_error = error
            engine.dispose()
            time.sleep(0.25)
    raise RuntimeError("PostgreSQL host port did not become ready") from last_error


def _run_postgres_test(database_url: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", POSTGRES_TEST],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def _collect_database_evidence(engine) -> dict[str, object]:
    with engine.begin() as connection:
        row_counts = {
            table: int(
                connection.exec_driver_sql(
                    f"SELECT count(*) FROM gda_control.{table}"
                ).scalar_one()
            )
            for table in ARCHITECTURE_TABLES
        }
        rls_flags = connection.execute(
            text(
                "SELECT relname, relrowsecurity, relforcerowsecurity "
                "FROM pg_class WHERE oid IN ("
                "'gda_control.schema_version'::regclass, "
                "'gda_control.data_contract_version'::regclass, "
                "'gda_control.physical_location'::regclass, "
                "'gda_control.resource_version_architecture_binding'::regclass) "
                "ORDER BY relname"
            )
        ).all()
        immutable_trigger_count = int(
            connection.execute(
                text(
                    "SELECT count(*) FROM pg_trigger "
                    "WHERE NOT tgisinternal "
                    "AND tgname = 'trg_gda_architecture_immutable' "
                    "AND tgrelid IN ("
                    "'gda_control.schema_version'::regclass, "
                    "'gda_control.data_contract_version'::regclass, "
                    "'gda_control.physical_location'::regclass, "
                    "'gda_control.resource_version_architecture_binding'::regclass)"
                )
            ).scalar_one()
        )
        gateway_privileges = connection.execute(
            text(
                "SELECT "
                "has_table_privilege('gda_control_gateway', "
                "'gda_control.schema_version', 'SELECT,INSERT'), "
                "has_table_privilege('gda_control_gateway', "
                "'gda_control.schema_version', 'UPDATE'), "
                "has_table_privilege('gda_control_gateway', "
                "'gda_control.schema_version', 'DELETE')"
            )
        ).one()
    return {
        "row_counts": row_counts,
        "rls": [
            {
                "table": row.relname,
                "enabled": row.relrowsecurity,
                "forced": row.relforcerowsecurity,
            }
            for row in rls_flags
        ],
        "immutable_trigger_count": immutable_trigger_count,
        "gateway_privileges": {
            "select_insert": gateway_privileges[0],
            "update": gateway_privileges[1],
            "delete": gateway_privileges[2],
        },
    }


def certify(image: str, report_path: Path) -> dict[str, object]:
    container = ""
    engine = None
    try:
        container, port = _start_postgres(image)
        database_url = (
            f"postgresql+psycopg2://postgres@127.0.0.1:{port}/postgres"
        )
        engine = create_engine(database_url)
        _wait_for_host_connection(engine)
        result = _run_postgres_test(database_url)
        if result.returncode != 0:
            raise RuntimeError(
                "PostgreSQL architecture test failed:\n"
                f"{result.stdout}\n{result.stderr}"
            )
        evidence = _collect_database_evidence(engine)
        postgres_version = _docker(
            "exec",
            container,
            "psql",
            "-U",
            "postgres",
            "-Atc",
            "SHOW server_version",
        ).stdout.strip()
        checks = {
            "postgres_test_passed": "1 passed" in result.stdout,
            "two_complete_resource_versions_recorded": all(
                count == 2 for count in evidence["row_counts"].values()
            ),
            "rls_enabled_and_forced": all(
                row["enabled"] and row["forced"] for row in evidence["rls"]
            ),
            "all_tables_have_immutable_trigger": (
                evidence["immutable_trigger_count"] == len(ARCHITECTURE_TABLES)
            ),
            "gateway_is_append_only": (
                evidence["gateway_privileges"]["select_insert"]
                and not evidence["gateway_privileges"]["update"]
                and not evidence["gateway_privileges"]["delete"]
            ),
        }
        report = {
            "schema_version": "gda.data_architecture.acceptance.v1",
            "postgres_image": image,
            "postgres_version": postgres_version,
            "test": POSTGRES_TEST,
            "test_output": result.stdout.strip(),
            "evidence": evidence,
            "checks": checks,
            "passed": all(checks.values()),
        }
        if not report["passed"]:
            raise RuntimeError(f"architecture certification checks failed: {checks}")
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report, ensure_ascii=True, indent=2) + "\n",
            encoding="utf-8",
        )
        return report
    finally:
        if engine is not None:
            engine.dispose()
        if container:
            _docker("rm", "--force", container, check=False)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", default="postgres:16-alpine")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    report = certify(args.image, args.report)
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

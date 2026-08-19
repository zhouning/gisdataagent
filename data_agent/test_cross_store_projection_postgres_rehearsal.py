from __future__ import annotations

import json
import os

import pytest

from data_agent.cross_store_projection_postgres_rehearsal import (
    CrossStoreProjectionPostgresRehearsalReport,
    _execute_migration,
    _report_hash,
    run_cross_store_projection_postgres_rehearsal,
    write_cross_store_projection_postgres_rehearsal_report,
)


def test_postgres_rehearsal_report_writer_preserves_hash(tmp_path) -> None:
    payload = {
        "schema_id": "gda.cross-store-projection-postgres-rehearsal.v1",
        "checked_at": "2026-08-15T00:00:00Z",
        "database_scope": "temporary_database_only",
        "migration_ids": ["092", "094", "169"],
        "checks": {"idempotent_replay": True},
        "passed": True,
        "failure_reasons": [],
        "technical_baseline_status": "technical_baseline_unreviewed",
        "decision_status": "assisted_precheck_not_for_production_decision",
    }
    payload["report_sha256"] = _report_hash(payload)
    report = CrossStoreProjectionPostgresRehearsalReport.model_validate(payload)

    target = write_cross_store_projection_postgres_rehearsal_report(
        report,
        tmp_path / "projection-postgres-rehearsal.json",
    )
    stored = json.loads(target.read_text(encoding="utf-8"))
    supplied = stored.pop("report_sha256")

    assert supplied == _report_hash(stored)


def test_migration_execution_escapes_dbapi_percent_binding() -> None:
    class Connection:
        statement = None

        def exec_driver_sql(self, statement):
            self.statement = statement

    connection = Connection()
    _execute_migration(connection, "SELECT 7 % 4;")

    assert connection.statement == "SELECT 7 %% 4;"


@pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL is not configured",
)
def test_real_postgres_rehearsal() -> None:
    report = run_cross_store_projection_postgres_rehearsal(
        os.environ["DATABASE_URL"]
    )

    assert report.passed, report.failure_reasons

from __future__ import annotations

import json

import pytest

from data_agent.chongqing_data_package_reconciliation_postgres_rehearsal import (
    _execute_migration,
    _report_hash,
    write_chongqing_reconciliation_postgres_rehearsal_report,
)


def test_postgres_rehearsal_report_writer_preserves_hash(tmp_path):
    payload = {
        "schema_id": "gda.chongqing-reconciliation-postgres-rehearsal.v1",
        "checked_at": "2026-08-14T15:00:00Z",
        "database_scope": "temporary_database_only",
        "migration_ids": ["167", "168"],
        "checks": {"completion_honors_cancel": True},
        "passed": True,
        "failure_reasons": [],
        "technical_baseline_status": "technical_baseline_unreviewed",
        "decision_status": "assisted_precheck_not_for_production_decision",
    }
    from data_agent.chongqing_data_package_reconciliation_postgres_rehearsal import (
        ChongqingReconciliationPostgresRehearsalReport,
    )

    payload["report_sha256"] = _report_hash(payload)
    report = ChongqingReconciliationPostgresRehearsalReport.model_validate(payload)
    target = write_chongqing_reconciliation_postgres_rehearsal_report(
        report,
        tmp_path / "postgres-rehearsal.json",
    )
    stored = json.loads(target.read_text(encoding="utf-8"))
    supplied = stored.pop("report_sha256")
    assert supplied == _report_hash(stored)


def test_migration_execution_escapes_dbapi_percent_binding_for_full_sql_text():
    class Connection:
        def __init__(self):
            self.statement = None

        def exec_driver_sql(self, statement):
            self.statement = statement

        def execute(self, *_args, **_kwargs):
            raise AssertionError("migration must preserve multi-statement DB-API execution")

    connection = Connection()
    _execute_migration(connection, "SELECT 7 % 4;")

    assert connection.statement is not None
    assert connection.statement.strip() == "SELECT 7 %% 4;"


@pytest.mark.skipif(
    not __import__("os").environ.get("DATABASE_URL"),
    reason="DATABASE_URL is not configured",
)
def test_real_postgres_rehearsal():
    from data_agent.chongqing_data_package_reconciliation_postgres_rehearsal import (
        run_chongqing_reconciliation_postgres_rehearsal,
    )

    report = run_chongqing_reconciliation_postgres_rehearsal(
        __import__("os").environ["DATABASE_URL"]
    )
    assert report.passed, report.failure_reasons

from __future__ import annotations

import json
import os

import pytest
from sqlalchemy import create_engine

from data_agent.cross_store_projection_recovery_authority import (
    PROJECTION_RECOVERY_LEDGER_MIGRATION,
    PostgresProjectionRecoveryLedger,
    ProjectionRecoveryAuthorityConfigurationError,
)
from data_agent.cross_store_projection_recovery_postgres_rehearsal import (
    CrossStoreProjectionRecoveryPostgresRehearsalReport,
    _report_hash,
    run_cross_store_projection_recovery_postgres_rehearsal,
    write_cross_store_projection_recovery_postgres_rehearsal_report,
)


def test_migration_exposes_only_controlled_append_path() -> None:
    migration = PROJECTION_RECOVERY_LEDGER_MIGRATION.read_text(encoding="utf-8")

    assert "cross_store_projection_recovery_event_history" in migration
    assert "cross_store_projection_recovery_snapshot_history" in migration
    assert "cross_store_projection_recovery_snapshot_current" in migration
    assert "SECURITY DEFINER" in migration
    assert "SET row_security = on" in migration
    assert "ENABLE ROW LEVEL SECURITY" in migration
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "BEFORE UPDATE OR DELETE" in migration
    assert "gda_control.reject_immutable_mutation()" in migration
    assert "REVOKE ALL ON TABLE gda_control.cross_store_projection_recovery" in migration
    assert "GRANT INSERT" not in migration
    assert "append-only" in migration


def test_repository_requires_postgresql() -> None:
    ledger = PostgresProjectionRecoveryLedger("cq-recovery-test", create_engine("sqlite://"))

    with pytest.raises(
        ProjectionRecoveryAuthorityConfigurationError,
        match="requires PostgreSQL",
    ):
        ledger.current("a" * 64)


def test_rehearsal_report_writer_preserves_hash(tmp_path) -> None:
    payload = {
        "schema_id": "gda.cross-store-projection-recovery-postgres-rehearsal.v1",
        "checked_at": "2026-08-15T00:00:00Z",
        "database_scope": "temporary_database_only",
        "migration_ids": [
            "092",
            "094",
            "102",
            "103",
            "169",
            "170",
            "171",
            "172",
            "173",
            "174",
        ],
        "checks": {"reload_current_and_history": True},
        "passed": True,
        "failure_reasons": [],
        "technical_baseline_status": "technical_baseline_unreviewed",
        "decision_status": "assisted_precheck_not_for_production_decision",
    }
    payload["report_sha256"] = _report_hash(payload)
    report = CrossStoreProjectionRecoveryPostgresRehearsalReport.model_validate(payload)

    target = write_cross_store_projection_recovery_postgres_rehearsal_report(
        report,
        tmp_path / "projection-recovery-postgres-rehearsal.json",
    )
    stored = json.loads(target.read_text(encoding="utf-8"))
    supplied = stored.pop("report_sha256")

    assert supplied == _report_hash(stored)


@pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL is not configured",
)
def test_real_postgres_recovery_rehearsal() -> None:
    report = run_cross_store_projection_recovery_postgres_rehearsal(
        os.environ["DATABASE_URL"]
    )

    assert report.passed, report.failure_reasons

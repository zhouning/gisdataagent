from __future__ import annotations

import json
import os

import pytest

from data_agent.agentops_temporal_start_target_authority import (
    AGENTOPS_TEMPORAL_START_TARGET_AUTHORITY_MIGRATION,
)
from data_agent.agentops_temporal_start_target_postgres_rehearsal import (
    AgentOpsTemporalStartTargetPostgresRehearsalReport,
    _report_hash,
    run_agentops_temporal_start_target_postgres_rehearsal,
    write_agentops_temporal_start_target_postgres_rehearsal_report,
)


def test_start_target_migration_has_controlled_discovery_and_immutable_receipt() -> None:
    migration = AGENTOPS_TEMPORAL_START_TARGET_AUTHORITY_MIGRATION.read_text()
    assert "agentops_temporal_start_target" in migration
    assert "pending_start_reconciliation" in migration
    assert "FOR UPDATE SKIP LOCKED" in migration
    assert "SECURITY DEFINER" in migration
    assert "ENABLE ROW LEVEL SECURITY" in migration
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "registration evidence is immutable" in migration
    assert "GRANT INSERT" not in migration


def test_start_target_report_writer_preserves_hash(tmp_path) -> None:
    payload = {
        "schema_id": "gda.agentops-temporal-start-target-postgres-rehearsal.v1",
        "checked_at": "2026-08-27T00:00:00Z",
        "database_scope": "temporary_database_only",
        "migration_ids": ["092", "094", "240", "241", "242"],
        "checks": {"expired_claim_is_recoverable": True},
        "passed": True,
        "failure_reasons": [],
    }
    payload["report_sha256"] = _report_hash(payload)
    report = AgentOpsTemporalStartTargetPostgresRehearsalReport.model_validate(payload)
    target = write_agentops_temporal_start_target_postgres_rehearsal_report(
        report, tmp_path / "start-target.json"
    )
    stored = json.loads(target.read_text())
    assert stored["report_sha256"] == _report_hash(stored)


@pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"), reason="DATABASE_URL is not configured"
)
def test_real_postgres_start_target_rehearsal() -> None:
    report = run_agentops_temporal_start_target_postgres_rehearsal(
        os.environ["DATABASE_URL"]
    )
    assert report.passed, report.failure_reasons

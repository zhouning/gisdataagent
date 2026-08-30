from __future__ import annotations

import json
import os

import pytest

from data_agent.agentops_temporal_checkpoint_postgres_rehearsal import (
    AgentOpsTemporalCheckpointPostgresRehearsalReport,
    _report_hash,
    run_agentops_temporal_checkpoint_postgres_rehearsal,
    write_agentops_temporal_checkpoint_postgres_rehearsal_report,
)


def test_postgres_rehearsal_report_writer_preserves_hash(tmp_path) -> None:
    payload = {
        "schema_id": "gda.agentops-temporal-checkpoint-postgres-rehearsal.v1",
        "checked_at": "2026-08-27T00:00:00Z",
        "database_scope": "temporary_database_only",
        "migration_ids": ["092", "094", "169", "240"],
        "source_evidence_prefix": (
            "agentops_temporal_checkpoint_reconciliation_2026-08-27"
        ),
        "checkpoint_count": 2,
        "reconciliation_count": 2,
        "checks": {"new_repository_instance_recovers_typed_state": True},
        "passed": True,
        "failure_reasons": [],
        "technical_baseline_status": "technical_baseline_unreviewed",
        "decision_status": "assisted_precheck_not_for_production_decision",
    }
    payload["report_sha256"] = _report_hash(payload)
    report = AgentOpsTemporalCheckpointPostgresRehearsalReport.model_validate(payload)

    target = write_agentops_temporal_checkpoint_postgres_rehearsal_report(
        report,
        tmp_path / "agentops-temporal-checkpoint-postgres.json",
    )
    stored = json.loads(target.read_text(encoding="utf-8"))
    supplied = stored.pop("report_sha256")

    assert supplied == _report_hash(stored)


@pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL is not configured",
)
def test_real_postgres_rehearsal() -> None:
    report = run_agentops_temporal_checkpoint_postgres_rehearsal(
        os.environ["DATABASE_URL"]
    )

    assert report.passed, report.failure_reasons

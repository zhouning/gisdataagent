import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from data_agent.agentops_temporal_checkpoint_authority import (
    AGENTOPS_TEMPORAL_CHECKPOINT_AUTHORITY_MIGRATION,
    AgentOpsTemporalCheckpointAuthorityConfigurationError,
    AgentOpsTemporalCheckpointAuthorityValidationError,
    PostgresAgentOpsTemporalCheckpointAuthority,
)
from data_agent.agentops_temporal_reconciliation import (
    TemporalCheckpointReconciliation,
    TemporalProviderWorkflowHistoryObservation,
)
from data_agent.agentops_temporal_workflow import TemporalTaskGraphWorkflowCheckpoint

_REPORTS = Path(__file__).resolve().parents[1] / "docs" / "reports"
_PREFIX = "agentops_temporal_checkpoint_reconciliation_2026-08-27"


def _document(suffix: str) -> dict[str, object]:
    return json.loads((_REPORTS / f"{_PREFIX}_{suffix}.json").read_text())


def _checkpoint(suffix: str = "checkpoint_after") -> TemporalTaskGraphWorkflowCheckpoint:
    return TemporalTaskGraphWorkflowCheckpoint.model_validate(_document(suffix))


def _observation() -> TemporalProviderWorkflowHistoryObservation:
    return TemporalProviderWorkflowHistoryObservation.model_validate(
        _document("observation")
    )


def _reconciliation(suffix: str = "matched") -> TemporalCheckpointReconciliation:
    return TemporalCheckpointReconciliation.model_validate(_document(suffix))


def test_migration_exposes_only_controlled_append_paths() -> None:
    migration = AGENTOPS_TEMPORAL_CHECKPOINT_AUTHORITY_MIGRATION.read_text()

    assert "agentops_temporal_checkpoint_history" in migration
    assert "agentops_temporal_reconciliation_evidence" in migration
    assert "SECURITY DEFINER" in migration
    assert "SET row_security = on" in migration
    assert migration.count("ENABLE ROW LEVEL SECURITY") == 2
    assert migration.count("FORCE ROW LEVEL SECURITY") == 2
    assert migration.count("BEFORE UPDATE OR DELETE") == 2
    assert "gda_control.reject_immutable_mutation()" in migration
    assert "pg_advisory_xact_lock" in migration
    assert "p_previous_checkpoint_sha256" in migration
    assert "v_run_id IS DISTINCT FROM v_current.run_id" in migration
    assert "v_run_state_version < v_current.run_state_version" in migration
    assert "p_fingerprint_payload::JSONB" in migration
    assert "public.digest" in migration
    assert "GRANT INSERT" not in migration
    assert "GRANT EXECUTE ON FUNCTION" in migration


def test_repository_requires_postgresql() -> None:
    authority = PostgresAgentOpsTemporalCheckpointAuthority(create_engine("sqlite://"))
    checkpoint = _checkpoint()

    with pytest.raises(
        AgentOpsTemporalCheckpointAuthorityConfigurationError,
        match="requires PostgreSQL",
    ):
        authority.record_checkpoint(
            checkpoint,
            recorded_by="workload:agentops-checkpoint-writer",
        )


def test_checkpoint_actor_is_validated_before_database_access() -> None:
    with pytest.raises(
        AgentOpsTemporalCheckpointAuthorityValidationError,
        match="typed subject",
    ):
        PostgresAgentOpsTemporalCheckpointAuthority().record_checkpoint(
            _checkpoint(),
            recorded_by="anonymous",
        )


def test_stored_checkpoint_tamper_is_rejected() -> None:
    document = _document("checkpoint_after")
    document["run"]["status"] = "failed"  # type: ignore[index]

    with pytest.raises(
        AgentOpsTemporalCheckpointAuthorityConfigurationError,
        match="stored AgentOps checkpoint is invalid",
    ):
        PostgresAgentOpsTemporalCheckpointAuthority._checkpoint(document)


def test_reconciliation_pair_is_validated_before_database_access() -> None:
    with pytest.raises(
        AgentOpsTemporalCheckpointAuthorityValidationError,
        match="observation and checkpoint reconciliation differ",
    ):
        PostgresAgentOpsTemporalCheckpointAuthority().record_reconciliation(
            _observation(),
            _reconciliation("provider_behind"),
            recorded_by="workload:agentops-reconciler",
        )


def test_history_query_identity_is_validated_before_database_access() -> None:
    with pytest.raises(
        AgentOpsTemporalCheckpointAuthorityValidationError,
        match="workflow_id",
    ):
        PostgresAgentOpsTemporalCheckpointAuthority().checkpoint_history(
            tenant_id="planning",
            workflow_id="bad workflow",
        )

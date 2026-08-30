from datetime import UTC, datetime, timedelta

import pytest

from data_agent.agentops_temporal_checkpoint_authority import (
    AGENTOPS_TEMPORAL_RECONCILER_FENCING_MIGRATION,
    AgentOpsTemporalCheckpointAuthorityValidationError,
    AgentOpsTemporalReconcilerLease,
    PostgresAgentOpsTemporalCheckpointAuthority,
)
from data_agent.test_agentops_temporal_checkpoint_authority import _checkpoint

_NOW = datetime(2026, 8, 27, 0, 0, tzinfo=UTC)


def _lease(**overrides) -> AgentOpsTemporalReconcilerLease:
    values = {
        "tenant_id": "planning",
        "workflow_id": (
            _checkpoint().workflow_input.identity.workflow_id
        ),
        "lease_owner": "workload:agentops-reconciler-a",
        "lease_epoch": 1,
        "lease_acquired_at": _NOW,
        "lease_expires_at": _NOW + timedelta(seconds=60),
        "lease_updated_at": _NOW,
    }
    values.update(overrides)
    return AgentOpsTemporalReconcilerLease(**values)


def test_fencing_migration_removes_unfenced_gateway_writes() -> None:
    migration = AGENTOPS_TEMPORAL_RECONCILER_FENCING_MIGRATION.read_text()

    assert "agentops_temporal_reconciler_lease" in migration
    assert "lease_epoch = lease.lease_epoch + 1" in migration
    assert "assert_agentops_temporal_reconciler_lease" in migration
    assert "FOR UPDATE" in migration
    assert "record_agentops_temporal_checkpoint_fenced" in migration
    assert "record_agentops_temporal_reconciliation_fenced" in migration
    assert "agentops_temporal_checkpoint_lease_binding" in migration
    assert "agentops_temporal_reconciliation_lease_binding" in migration
    assert "BEFORE UPDATE OR DELETE" in migration
    assert "REVOKE ALL ON FUNCTION gda_control.record_agentops_temporal_checkpoint(" in migration
    assert "TO gda_control_gateway" in migration
    assert "GRANT INSERT" not in migration


def test_lease_rejects_inconsistent_timestamps() -> None:
    with pytest.raises(ValueError, match="timestamps are inconsistent"):
        _lease(lease_expires_at=_NOW - timedelta(seconds=1))


def test_checkpoint_write_rejects_cross_workflow_lease_before_database_access() -> None:
    checkpoint = _checkpoint()
    lease = _lease(workflow_id="gda-agent-planning-other")

    with pytest.raises(
        AgentOpsTemporalCheckpointAuthorityValidationError,
        match="identity differs",
    ):
        PostgresAgentOpsTemporalCheckpointAuthority().record_checkpoint(
            checkpoint,
            recorded_by=lease.lease_owner,
            lease=lease,
        )


def test_checkpoint_write_rejects_lease_owner_drift_before_database_access() -> None:
    checkpoint = _checkpoint()
    lease = _lease()

    with pytest.raises(
        AgentOpsTemporalCheckpointAuthorityValidationError,
        match="owner differs",
    ):
        PostgresAgentOpsTemporalCheckpointAuthority().record_checkpoint(
            checkpoint,
            recorded_by="workload:agentops-reconciler-b",
            lease=lease,
        )


@pytest.mark.parametrize("seconds", [0, 3601])
def test_lease_duration_is_bounded_before_database_access(seconds: int) -> None:
    checkpoint = _checkpoint()

    with pytest.raises(
        AgentOpsTemporalCheckpointAuthorityValidationError,
        match="1..3600",
    ):
        PostgresAgentOpsTemporalCheckpointAuthority().acquire_reconciler_lease(
            tenant_id=checkpoint.workflow_input.tenant_id,
            workflow_id=checkpoint.workflow_input.identity.workflow_id,
            lease_owner="workload:agentops-reconciler-a",
            lease_seconds=seconds,
        )

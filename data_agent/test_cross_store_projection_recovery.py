from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from data_agent.cross_store_projection_consistency import (
    InMemoryProjectionCheckpointLedger,
    ProjectionDesiredState,
    ProjectionEngine,
    ProjectionTargetObservation,
    build_projection_repair_plan,
)
from data_agent.cross_store_projection_recovery import (
    InMemoryProjectionRecoveryLedger,
    ProjectionRecoveryCoordinator,
    ProjectionRecoveryError,
    ProjectionRecoveryState,
)
from data_agent.cross_store_projection_recovery_rehearsal import (
    run_cross_store_projection_recovery_rehearsal,
)

TENANT = "cq-recovery-test"
PROJECTION = "cq.land_parcel"
TARGET_REF = "postgis://cq-db/public.land_parcel_current"
SOURCE_SHA = "a" * 64
TARGET_SHA = "b" * 64
NOW = datetime(2026, 8, 15, 16, 0, tzinfo=UTC)


def _plan():
    desired = ProjectionDesiredState(
        tenant_id=TENANT,
        projection_id=PROJECTION,
        source_resource_version_ref="gda://cq-recovery-test/data_product/parcel-v1",
        source_content_sha256=SOURCE_SHA,
        target_engine=ProjectionEngine.POSTGIS,
        target_ref=TARGET_REF,
        target_exists=True,
        expected_target_content_sha256=TARGET_SHA,
        expected_row_count=455,
    )
    observation = ProjectionTargetObservation(
        tenant_id=TENANT,
        projection_id=PROJECTION,
        target_engine=ProjectionEngine.POSTGIS,
        target_ref=TARGET_REF,
        target_exists=False,
        observed_content_sha256=None,
        observed_row_count=0,
        observed_by="workload:recovery-observer",
        observed_at=NOW,
    )
    return build_projection_repair_plan(desired, observation, None)


def _post_observation(**overrides):
    values = {
        "tenant_id": TENANT,
        "projection_id": PROJECTION,
        "target_engine": ProjectionEngine.POSTGIS,
        "target_ref": TARGET_REF,
        "target_exists": True,
        "observed_content_sha256": TARGET_SHA,
        "observed_row_count": 455,
        "observed_by": "workload:recovery-observer",
        "observed_at": NOW + timedelta(seconds=1),
    }
    values.update(overrides)
    return ProjectionTargetObservation(**values)


def _receipt(plan):
    commit_ref = {
        "provider": "postgis",
        "provider_commit": "public.land_parcel_current:1",
        "plan_sha256": plan.plan_sha256,
        "idempotency_key": plan.plan_idempotency_key,
    }
    return SimpleNamespace(
        plan_sha256=plan.plan_sha256,
        idempotency_key=plan.plan_idempotency_key,
        provider_commit_ref=commit_ref,
    )


class _FailOnceAuthority:
    def __init__(self):
        self.ledger = InMemoryProjectionCheckpointLedger()
        self.fail = True

    def record(self, checkpoint, *, previous_checkpoint_sha256=None):
        if self.fail:
            self.fail = False
            raise RuntimeError("postgresql_unavailable")
        return self.ledger.record(
            checkpoint,
            previous_checkpoint_sha256=previous_checkpoint_sha256,
        )

    def history(self, **identity):
        return self.ledger.history(**identity)


def test_known_provider_commit_recovers_authority_without_provider_replay():
    plan = _plan()
    authority = _FailOnceAuthority()
    recovery = ProjectionRecoveryCoordinator(
        plan,
        checkpointed_by="workload:recovery-worker",
        ledger=InMemoryProjectionRecoveryLedger(),
        now=lambda: NOW + timedelta(seconds=2),
    )

    committed = recovery.provider_committed(_receipt(plan))
    assert committed.state is ProjectionRecoveryState.PROVIDER_COMMITTED
    assert committed.next_action == "retry_authority"

    pending = recovery.authority_failed("postgresql_unavailable")
    assert pending.state is ProjectionRecoveryState.AUTHORITY_PENDING
    assert pending.next_action == "retry_authority"
    # The first service attempt already consumed the simulated outage.
    authority.fail = False

    snapshot, checkpoint = recovery.recover_authority(_post_observation(), authority)

    assert snapshot.state is ProjectionRecoveryState.AUTHORITY_COMMITTED
    assert snapshot.next_action == "none"
    assert checkpoint is not None
    assert checkpoint.checkpoint_version == 1
    assert checkpoint.target_commit_ref["plan_sha256"] == plan.plan_sha256
    assert (
        len(
            authority.ledger.history(
                tenant_id=TENANT,
                projection_id=PROJECTION,
                target_engine=ProjectionEngine.POSTGIS,
                target_ref=TARGET_REF,
            )
        )
        == 1
    )


def test_recovery_target_drift_requires_manual_compensation():
    plan = _plan()
    recovery = ProjectionRecoveryCoordinator(plan, checkpointed_by="agent:recovery")
    recovery.provider_committed(_receipt(plan))

    snapshot, checkpoint = recovery.recover_authority(
        _post_observation(observed_content_sha256="c" * 64),
        InMemoryProjectionCheckpointLedger(),
    )

    assert checkpoint is None
    assert snapshot.state is ProjectionRecoveryState.RECONCILIATION_REQUIRED
    assert snapshot.next_action == "manual_compensation"
    assert snapshot.last_error_code is None


def test_unknown_provider_outcome_requires_reobservation_and_blocks_retry():
    plan = _plan()
    recovery = ProjectionRecoveryCoordinator(plan, checkpointed_by="workload:recovery")

    snapshot = recovery.provider_failed("worker_hard_kill", outcome_known=False)

    assert snapshot.state is ProjectionRecoveryState.RECONCILIATION_REQUIRED
    assert snapshot.next_action == "reobserve_target"
    assert snapshot.provider_commit_ref is None
    with pytest.raises(ProjectionRecoveryError, match="no provider commit evidence"):
        recovery.recover_authority(_post_observation(), InMemoryProjectionCheckpointLedger())


def test_exact_provider_receipt_can_close_unknown_outcome_without_new_attempt():
    plan = _plan()
    recovery = ProjectionRecoveryCoordinator(plan, checkpointed_by="workload:recovery")
    unknown = recovery.provider_failed("client_connection_lost", outcome_known=False)

    recovered = recovery.provider_receipt_recovered(_receipt(plan))

    assert unknown.provider_attempts == 1
    assert recovered.state is ProjectionRecoveryState.PROVIDER_COMMITTED
    assert recovered.next_action == "retry_authority"
    assert recovered.provider_attempts == 1
    assert recovered.events[-1].detail["receipt_recovered"] is True


def test_known_provider_failure_remains_safe_to_reexecute():
    plan = _plan()
    recovery = ProjectionRecoveryCoordinator(plan, checkpointed_by="workload:recovery")

    failed = recovery.provider_failed("validation_error", outcome_known=True)

    assert failed.state is ProjectionRecoveryState.PROVIDER_FAILED
    assert failed.next_action == "execute_provider"
    committed = recovery.provider_committed(_receipt(plan))
    assert committed.state is ProjectionRecoveryState.PROVIDER_COMMITTED


def test_unbound_provider_receipt_is_rejected():
    plan = _plan()
    recovery = ProjectionRecoveryCoordinator(plan, checkpointed_by="workload:recovery")
    receipt = _receipt(plan)
    receipt.plan_sha256 = "f" * 64

    with pytest.raises(ProjectionRecoveryError, match="not bound"):
        recovery.provider_committed(receipt)


def test_recovery_ledger_is_append_only_and_idempotent():
    plan = _plan()
    ledger = InMemoryProjectionRecoveryLedger()
    recovery = ProjectionRecoveryCoordinator(
        plan,
        checkpointed_by="workload:recovery",
        ledger=ledger,
    )
    first = recovery.snapshot
    assert ledger.append(first) == first
    assert len(ledger.history(plan.plan_sha256)) == 1


def test_recovery_rehearsal_report_covers_the_control_plane_failure_matrix():
    report = run_cross_store_projection_recovery_rehearsal()

    assert report.passed_count == 4
    assert report.failed_count == 0
    assert report.production_recovery_certified is False
    assert report.recovery_scope == "in_memory_recovery_orchestration_only"

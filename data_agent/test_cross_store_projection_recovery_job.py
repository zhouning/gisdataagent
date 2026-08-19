from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event, Thread
from types import SimpleNamespace

import pytest

from data_agent.cross_store_projection_consistency import (
    InMemoryProjectionCheckpointLedger,
)
from data_agent.cross_store_projection_recovery import InMemoryProjectionRecoveryLedger
from data_agent.cross_store_projection_recovery_job import (
    ProjectionRecoveryJob,
    ProjectionRecoveryJobConflictError,
    ProjectionRecoveryJobWorker,
    projection_recovery_job_id,
)
from data_agent.cross_store_projection_recovery_rehearsal import (
    _plan,
    _post_observation,
    _receipt,
)
from data_agent.cross_store_projection_recovery_worker import ProjectionProviderFailure

NOW = datetime(2026, 8, 15, 19, 0, tzinfo=UTC)


def _job(plan, **updates):
    values = {
        "tenant_id": plan.tenant_id,
        "job_id": projection_recovery_job_id(plan),
        "plan_sha256": plan.plan_sha256,
        "plan_idempotency_key": plan.plan_idempotency_key,
        "projection_id": plan.projection_id,
        "target_engine": plan.target_engine.value,
        "target_ref": plan.target_ref,
        "plan": plan,
        "status": "running",
        "next_action": None,
        "attempt_count": 1,
        "max_attempts": 5,
        "claimed_by": "worker:projection-test",
        "lease_expires_at": NOW + timedelta(minutes=2),
        "lease_generation": 1,
        "available_at": NOW,
        "submitted_by": "agent:projection-test",
        "submitted_at": NOW,
        "resumed_by": None,
        "resumed_at": None,
        "resume_approval_case_ref": None,
        "resume_reason": None,
        "resume_snapshot_sha256": None,
        "updated_at": NOW,
        "completed_at": None,
        "snapshot_sha256": None,
        "error_code": None,
        "error_message": None,
    }
    values.update(updates)
    return ProjectionRecoveryJob(**values)


class _Repository:
    def __init__(self, job, *, lose_lease=False):
        self.job = job
        self.lose_lease = lose_lease
        self.finished = []
        self.failed = []
        self.renew_calls = 0
        self.heartbeat_seen = Event()

    def claim(self, tenant_id, worker_id, *, limit, lease_seconds):
        return (SimpleNamespace(job=self.job),)

    def renew(self, job, worker_id, *, lease_seconds):
        self.renew_calls += 1
        if self.renew_calls >= 2:
            self.heartbeat_seen.set()
        if self.lose_lease:
            raise ProjectionRecoveryJobConflictError("stale lease")
        return job

    def finish(self, job, worker_id, result, *, retry_delay_seconds):
        self.finished.append(result)
        terminal = result.snapshot.next_action == "none"
        return job.model_copy(
            update={
                "status": "succeeded" if terminal else "queued",
                "next_action": result.snapshot.next_action,
                "claimed_by": None,
                "lease_expires_at": None,
                "completed_at": NOW if terminal else None,
                "snapshot_sha256": result.snapshot.snapshot_sha256,
            }
        )

    def fail(self, job, worker_id, error, *, retry_delay_seconds):
        self.failed.append(error)
        return job.model_copy(
            update={
                "status": "queued",
                "claimed_by": None,
                "lease_expires_at": None,
            }
        )


class _Provider:
    def __init__(self, *, unknown=False):
        self.unknown = unknown
        self.executions = 0

    def execute(self, plan):
        self.executions += 1
        if self.unknown:
            raise ProjectionProviderFailure("provider_connection_lost", outcome_known=False)
        return _receipt(plan)

    def observe(self, plan):
        return _post_observation()


class _BlockingProvider(_Provider):
    def __init__(self, release: Event, *, fail: bool = False):
        super().__init__()
        self.started = Event()
        self.release = release
        self.fail = fail

    def execute(self, plan):
        self.started.set()
        assert self.release.wait(timeout=3)
        if self.fail:
            raise RuntimeError("provider failed while lease heartbeat was lost")
        return super().execute(plan)


def test_recovery_job_identity_is_plan_and_tenant_bound():
    plan = _plan()
    assert projection_recovery_job_id(plan) == projection_recovery_job_id(plan)
    other = plan.model_copy(update={"tenant_id": "other-customer"})
    assert projection_recovery_job_id(other) != projection_recovery_job_id(plan)


def test_recovery_job_requires_complete_resume_evidence():
    with pytest.raises(ValueError, match="resume evidence"):
        _job(_plan(), resumed_by="human:operator", resumed_at=None)


def test_recovery_job_binds_resume_approval_to_tenant_and_kind():
    plan = _plan()
    evidence = {
        "resumed_by": "human:operator",
        "resumed_at": NOW,
        "resume_reason": "authorized compensation after target reconciliation",
        "resume_snapshot_sha256": "a" * 64,
    }
    with pytest.raises(ValueError, match="approval identity"):
        _job(
            plan,
            **evidence,
            resume_approval_case_ref=(
                "gda://chongqing-other/approval_case/projection-recovery-1"
            ),
        )
    with pytest.raises(ValueError, match="approval identity"):
        _job(
            plan,
            **evidence,
            resume_approval_case_ref=(
                "gda://chongqing-customer/data_product/projection-recovery-1"
            ),
        )


def test_job_worker_completes_one_durable_claim():
    plan = _plan()
    repository = _Repository(_job(plan))
    provider = _Provider()
    ledger = InMemoryProjectionRecoveryLedger()
    compensation_bindings = []

    outcomes = ProjectionRecoveryJobWorker(
        repository=repository,
        provider_resolver=lambda _plan: provider,
        authority_resolver=lambda _plan: InMemoryProjectionCheckpointLedger(),
        ledger_resolver=lambda _plan: ledger,
        compensation_resolver=lambda job, bound_provider, bound_ledger: (
            compensation_bindings.append((job, bound_provider, bound_ledger)) or None
        ),
    ).run_once(plan.tenant_id, "worker:projection-test")

    assert outcomes[0].status == "succeeded"
    assert outcomes[0].next_action == "none"
    assert provider.executions == 1
    assert len(repository.finished) == 1
    assert compensation_bindings == [(repository.job, provider, ledger)]


def test_job_worker_persists_unknown_outcome_for_later_reobservation():
    plan = _plan()
    repository = _Repository(_job(plan))
    provider = _Provider(unknown=True)

    outcomes = ProjectionRecoveryJobWorker(
        repository=repository,
        provider_resolver=lambda _plan: provider,
        authority_resolver=lambda _plan: InMemoryProjectionCheckpointLedger(),
        ledger_resolver=lambda _plan: InMemoryProjectionRecoveryLedger(),
    ).run_once(plan.tenant_id, "worker:projection-test")

    assert outcomes[0].status == "queued"
    assert outcomes[0].next_action == "reobserve_target"
    assert repository.finished[0].error_code == "provider_connection_lost"


def test_job_worker_drops_stale_owner_terminal_write():
    plan = _plan()
    repository = _Repository(_job(plan), lose_lease=True)

    outcomes = ProjectionRecoveryJobWorker(
        repository=repository,
        provider_resolver=lambda _plan: _Provider(),
        authority_resolver=lambda _plan: InMemoryProjectionCheckpointLedger(),
        ledger_resolver=lambda _plan: InMemoryProjectionRecoveryLedger(),
    ).run_once(plan.tenant_id, "worker:projection-test")

    assert outcomes == ()
    assert not repository.finished
    assert not repository.failed


def test_job_worker_heartbeats_during_long_provider_execution():
    plan = _plan()
    repository = _Repository(_job(plan))
    provider = _BlockingProvider(Event())
    worker = ProjectionRecoveryJobWorker(
        repository=repository,
        provider_resolver=lambda _plan: provider,
        authority_resolver=lambda _plan: InMemoryProjectionCheckpointLedger(),
        ledger_resolver=lambda _plan: InMemoryProjectionRecoveryLedger(),
    )

    release = provider.release
    thread = Thread(
        target=lambda: worker.run_once(
            plan.tenant_id,
            "worker:projection-test",
            lease_seconds=6,
            heartbeat_interval_seconds=0.01,
        )
    )
    thread.start()
    assert provider.started.wait(timeout=3)
    assert repository.heartbeat_seen.wait(timeout=3)
    release.set()
    thread.join(timeout=3)

    assert not thread.is_alive()
    assert repository.renew_calls >= 2
    assert len(repository.finished) == 1


def test_job_worker_drops_result_when_heartbeat_loses_lease():
    plan = _plan()
    repository = _Repository(_job(plan))
    provider = _BlockingProvider(Event())
    worker = ProjectionRecoveryJobWorker(
        repository=repository,
        provider_resolver=lambda _plan: provider,
        authority_resolver=lambda _plan: InMemoryProjectionCheckpointLedger(),
        ledger_resolver=lambda _plan: InMemoryProjectionRecoveryLedger(),
    )

    thread = Thread(
        target=lambda: worker.run_once(
            plan.tenant_id,
            "worker:projection-test",
            lease_seconds=6,
            heartbeat_interval_seconds=0.01,
        )
    )
    thread.start()
    assert provider.started.wait(timeout=3)
    repository.lose_lease = True
    assert repository.heartbeat_seen.wait(timeout=3)
    provider.release.set()
    thread.join(timeout=3)

    assert not thread.is_alive()
    assert not repository.finished
    assert not repository.failed


def test_job_worker_prioritizes_heartbeat_loss_over_provider_error():
    plan = _plan()
    repository = _Repository(_job(plan))
    provider = _BlockingProvider(Event(), fail=True)
    worker = ProjectionRecoveryJobWorker(
        repository=repository,
        provider_resolver=lambda _plan: provider,
        authority_resolver=lambda _plan: InMemoryProjectionCheckpointLedger(),
        ledger_resolver=lambda _plan: InMemoryProjectionRecoveryLedger(),
    )

    thread = Thread(
        target=lambda: worker.run_once(
            plan.tenant_id,
            "worker:projection-test",
            lease_seconds=6,
            heartbeat_interval_seconds=0.01,
        )
    )
    thread.start()
    assert provider.started.wait(timeout=3)
    repository.lose_lease = True
    assert repository.heartbeat_seen.wait(timeout=3)
    provider.release.set()
    thread.join(timeout=3)

    assert not thread.is_alive()
    assert not repository.finished
    assert not repository.failed


def test_recovery_job_migration_has_fenced_queue_contract():
    sql = (
        Path(__file__).resolve().parent
        / "migrations"
        / "171_cross_store_projection_recovery_job.sql"
    ).read_text(encoding="utf-8")

    for marker in (
        "FOR UPDATE SKIP LOCKED",
        "lease_generation",
        "lease_expires_at > clock_timestamp()",
        "waiting_operator",
        "resume_cross_store_projection_recovery_job",
        "SECURITY DEFINER",
        "FORCE ROW LEVEL SECURITY",
        "REVOKE ALL ON TABLE",
    ):
        assert marker in sql
    assert "GRANT INSERT" not in sql


def test_compensation_approval_migration_is_exact_and_least_privilege():
    sql = (
        Path(__file__).resolve().parent
        / "migrations"
        / "172_projection_recovery_compensation_approval.sql"
    ).read_text(encoding="utf-8")

    for marker in (
        "resume_approval_case_ref",
        "resume_snapshot_sha256",
        "cross_store_projection_recovery_resume_event",
        "projection.recovery.compensate",
        "v_approval.target_resource_urn IS DISTINCT FROM v_expected_target",
        "v_approval.target_fingerprint IS DISTINCT FROM v_job.snapshot_sha256",
        "v_approval.status IS DISTINCT FROM 'approved'",
        "clock_timestamp() >= v_approval.expires_at",
        "DROP FUNCTION gda_control.resume_cross_store_projection_recovery_job",
        "TEXT, UUID, TEXT, TEXT, TEXT",
        "SECURITY DEFINER",
        "FORCE ROW LEVEL SECURITY",
        "ApprovalCase was already consumed",
    ):
        assert marker in sql
    assert "GRANT INSERT ON TABLE" not in sql
    assert "GRANT UPDATE ON TABLE" not in sql


def test_compensation_execution_migration_closes_provider_crash_gap():
    sql = (
        Path(__file__).resolve().parent
        / "migrations"
        / "173_projection_recovery_compensation_execution.sql"
    ).read_text(encoding="utf-8")

    for marker in (
        "cross_store_projection_compensation_event",
        "begin_projection_recovery_compensation",
        "finish_projection_recovery_compensation",
        "approved_reapply_sealed_plan",
        "indeterminate",
        "failed_known",
        "failed_unknown",
        "lease_generation",
        "lease_expires_at <= clock_timestamp()",
        "FORCE ROW LEVEL SECURITY",
        "SECURITY DEFINER",
        "GRANT SELECT ON TABLE",
        "reject_immutable_mutation()",
    ):
        assert marker in sql
    assert "GRANT INSERT ON TABLE" not in sql
    assert "GRANT UPDATE ON TABLE" not in sql
    assert "GRANT DELETE ON TABLE" not in sql


def test_compensation_reconciliation_migration_requires_explicit_ruling():
    sql = (
        Path(__file__).resolve().parent
        / "migrations"
        / "174_projection_recovery_compensation_reconciliation.sql"
    ).read_text(encoding="utf-8")

    for marker in (
        "cross_store_projection_compensation_reconciliation_event",
        "reconcile_projection_recovery_compensation",
        "provider_committed",
        "provider_not_committed",
        "reconciliation_approval_case_ref",
        "projection.recovery.compensation.reconcile_committed",
        "projection.recovery.compensation.reconcile_not_committed",
        "operator_verified_not_committed",
        "FORCE ROW LEVEL SECURITY",
        "SECURITY DEFINER",
        "gda.projection_compensation_reconciliation_write_allowed",
        "resumed_automatically",
    ):
        assert marker in sql
    assert "GRANT INSERT ON TABLE" not in sql
    assert "GRANT UPDATE ON TABLE" not in sql
    assert "GRANT DELETE ON TABLE" not in sql

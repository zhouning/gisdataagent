from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from data_agent.chongqing_data_package_reconciliation import (
    ChongqingDataPackageReconciliationCancelledError,
)
from data_agent.chongqing_data_package_reconciliation_job import (
    ChongqingDataPackageReconciliationJob,
    ChongqingDataPackageReconciliationJobConflictError,
    ChongqingDataPackageReconciliationJobWorker,
    reconciliation_job_id,
)
from data_agent.chongqing_data_package_reconciliation_service import (
    ChongqingDataPackageReconciliationRequest,
    ChongqingDataPackageReconciliationResponse,
)
from data_agent.chongqing_entity_link_baseline import (
    build_chongqing_entity_link_baseline,
)

TENANT = "chongqing-customer"
ACTOR = "agent:package-agent"
BASELINE = build_chongqing_entity_link_baseline(tenant_id=TENANT)
EFFECTIVE_AT = BASELINE.link_assertion_drafts[0].valid_from + timedelta(days=1)


def _request() -> ChongqingDataPackageReconciliationRequest:
    return ChongqingDataPackageReconciliationRequest(
        tenant_id=TENANT,
        previous_baseline=BASELINE,
        desired_baseline=BASELINE,
        effective_at=EFFECTIVE_AT,
        evaluated_at=EFFECTIVE_AT + timedelta(hours=1),
        idempotency_key="cq.package.async.job-001",
        recorded_by=ACTOR,
    )


def _response(request: ChongqingDataPackageReconciliationRequest):
    return ChongqingDataPackageReconciliationResponse(
        tenant_id=request.tenant_id,
        idempotency_key=request.idempotency_key,
        recorded_by=request.recorded_by,
        request_sha256=request.request_sha256,
        previous_customer_bundle_version=BASELINE.customer_bundle_version,
        desired_customer_bundle_version=BASELINE.customer_bundle_version,
        effective_at=request.effective_at,
        evaluated_at=request.evaluated_at,
        plan_sha256="a" * 64,
        receipt_sha256="b" * 64,
        previous_baseline_sha256="c" * 64,
        desired_baseline_sha256="c" * 64,
        authority_state_sha256="d" * 64,
        operation_count=0,
        batch_count=0,
        unchanged_entity_count=len(BASELINE.temporal_entity_drafts),
        unchanged_source_count=len(BASELINE.source_binding_drafts),
        retained_retired_source_count=0,
        entity_correction_count=0,
        entity_addition_count=0,
        entity_activation_count=0,
        source_binding_count=0,
        entity_retirement_count=0,
        link_operation_count=0,
        link_correction_count=0,
        link_retraction_count=0,
        link_restoration_count=0,
        link_addition_count=0,
        replay_verification="passed",
        write_mode="phased_chunked_atomic_authority_batches",
        atomicity_status="atomic_per_batch_resumable_across_phases",
    )


def _job(
    request: ChongqingDataPackageReconciliationRequest,
    *,
    status="running",
    phase="planning",
    phase_detail="planning",
    progress_percent=5,
    result=None,
    cancel_requested=False,
):
    now = datetime.now(UTC)
    return ChongqingDataPackageReconciliationJob(
        tenant_id=request.tenant_id,
        job_id=reconciliation_job_id(request),
        idempotency_key=request.idempotency_key,
        request_sha256=request.request_sha256,
        status=status,
        phase=phase,
        phase_detail=phase_detail,
        phase_completed=1 if status == "succeeded" else 0,
        phase_total=1,
        progress_percent=100 if status == "succeeded" else progress_percent,
        attempt_count=1,
        max_attempts=5,
        submitted_by=request.recorded_by,
        submitted_at=now,
        started_at=now,
        updated_at=now,
        completed_at=now if status in {"cancelled", "succeeded", "failed"} else None,
        lease_expires_at=(
            None
            if status in {"cancelled", "succeeded", "failed"}
            else now + timedelta(minutes=10)
        ),
        cancel_requested_by=ACTOR if cancel_requested else None,
        cancel_reason="operator requested stop" if cancel_requested else None,
        cancel_requested_at=now if cancel_requested else None,
        result=result,
        error_code=None,
        error_message=None,
    )


class _FakeRepository:
    def __init__(self, request, *, cancel=False):
        self.request = request
        self.cancel = cancel
        self.job = _job(request)
        self.checkpoints = []

    def claim(self, tenant_id, worker_id, *, limit, lease_seconds):
        assert tenant_id == TENANT
        return [SimpleNamespace(job=self.job, request=self.request)]

    def checkpoint(self, job, worker_id, **kwargs):
        self.checkpoints.append(kwargs)
        if self.cancel:
            self.job = _job(
                self.request,
                status="cancel_requested",
                cancel_requested=True,
            )
        return self.job

    def mark_cancelled(self, job, worker_id):
        self.job = _job(
            self.request,
            status="cancelled",
            phase="cancelled",
            phase_detail="cancelled_at_atomic_batch_boundary",
            progress_percent=job.progress_percent,
            cancel_requested=True,
        )
        return self.job

    def succeed(self, job, worker_id, result):
        self.job = _job(
            self.request,
            status="succeeded",
            phase="completed",
            phase_detail="completed",
            result=result,
        )
        return self.job

    def fail(self, *args, **kwargs):
        pytest.fail("the happy-path fake must not fail")


class _RetryRepository(_FakeRepository):
    def __init__(self, request):
        super().__init__(request)
        self.claim_count = 0
        self.failure_count = 0

    def claim(self, tenant_id, worker_id, *, limit, lease_seconds):
        self.claim_count += 1
        if self.claim_count == 1:
            return [SimpleNamespace(job=self.job, request=self.request)]
        if self.job.status == "queued":
            self.job = _job(self.request)
            return [SimpleNamespace(job=self.job, request=self.request)]
        return []

    def fail(self, job, worker_id, **kwargs):
        self.failure_count += 1
        self.job = _job(self.request, status="queued", phase="queued")
        return self.job


class _LeaseLostRepository(_FakeRepository):
    def checkpoint(self, job, worker_id, **kwargs):
        raise ChongqingDataPackageReconciliationJobConflictError(
            "reconciliation job claim changed concurrently"
        )

    def fail(self, *args, **kwargs):
        pytest.fail("a stale worker must not overwrite the new lease")


class _TerminalLeaseLostRepository(_FakeRepository):
    def succeed(self, *args, **kwargs):
        raise ChongqingDataPackageReconciliationJobConflictError(
            "reconciliation job completion claim changed concurrently"
        )

    def mark_cancelled(self, *args, **kwargs):
        raise ChongqingDataPackageReconciliationJobConflictError(
            "reconciliation cancellation claim changed concurrently"
        )

    def fail(self, *args, **kwargs):
        raise ChongqingDataPackageReconciliationJobConflictError(
            "reconciliation failure claim changed concurrently"
        )


def test_job_identity_is_tenant_and_idempotency_bound():
    request = _request()
    assert reconciliation_job_id(request) == reconciliation_job_id(request)
    other = request.model_copy(update={"tenant_id": "other-customer"})
    assert reconciliation_job_id(request) != reconciliation_job_id(other)


def test_worker_reports_progress_and_completes_the_durable_job():
    request = _request()
    repository = _FakeRepository(request)
    result = _response(request)

    def executor(request, *, progress_callback, cancel_check):
        progress_callback("planning", 1, 1)
        progress_callback("applying:entity_corrections", 1, 2)
        progress_callback("applying:link_additions", 2, 2)
        progress_callback("finalizing", 0, 1)
        return result

    outcomes = ChongqingDataPackageReconciliationJobWorker(
        repository=repository,
        executor=executor,
    ).run_once(TENANT, "worker:test")

    assert outcomes[0].status == "succeeded"
    assert outcomes[0].result == result
    assert [item["phase_detail"] for item in repository.checkpoints] == [
        "planning",
        "applying:entity_corrections",
        "applying:link_additions",
        "finalizing",
    ]


def test_worker_converges_cancel_at_batch_boundary_without_claiming_rollback():
    request = _request()
    repository = _FakeRepository(request, cancel=True)

    def executor(request, *, progress_callback, cancel_check):
        progress_callback("applying:entity_corrections", 1, 2)
        raise AssertionError("the cancellation checkpoint should stop execution")

    outcomes = ChongqingDataPackageReconciliationJobWorker(
        repository=repository,
        executor=executor,
    ).run_once(TENANT, "worker:test")

    assert outcomes[0].status == "cancelled"
    assert outcomes[0].cancellation_mode == (
        "cooperative_between_atomic_batches_no_rollback"
    )


def test_worker_retries_execution_failure_without_replanning_the_request():
    request = _request()
    repository = _RetryRepository(request)
    result = _response(request)
    calls = []

    def executor(request, *, progress_callback, cancel_check):
        calls.append(request.request_sha256)
        if len(calls) == 1:
            raise RuntimeError("temporary database disconnect")
        progress_callback("finalizing", 0, 1)
        return result

    worker = ChongqingDataPackageReconciliationJobWorker(
        repository=repository,
        executor=executor,
    )
    first = worker.run_once(TENANT, "worker:test")
    second = worker.run_once(TENANT, "worker:test")

    assert first[0].status == "queued"
    assert second[0].status == "succeeded"
    assert repository.failure_count == 1
    assert calls == [request.request_sha256, request.request_sha256]


def test_worker_drops_stale_lease_without_marking_new_owner_failed():
    request = _request()
    repository = _LeaseLostRepository(request)

    def executor(request, *, progress_callback, cancel_check):
        progress_callback("applying", 1, 2)
        raise AssertionError("the lease loss should stop the stale worker")

    outcomes = ChongqingDataPackageReconciliationJobWorker(
        repository=repository,
        executor=executor,
    ).run_once(TENANT, "worker:stale")

    assert outcomes == ()


@pytest.mark.parametrize("terminal", ["succeed", "cancel", "fail"])
def test_worker_drops_terminal_write_when_lease_expires(terminal):
    request = _request()
    repository = _TerminalLeaseLostRepository(request)
    result = _response(request)

    def executor(request, *, progress_callback, cancel_check):
        if terminal == "cancel":
            progress_callback("applying", 1, 2)
            raise ChongqingDataPackageReconciliationCancelledError("cancelled")
        if terminal == "fail":
            raise RuntimeError("temporary failure")
        return result

    outcomes = ChongqingDataPackageReconciliationJobWorker(
        repository=repository,
        executor=executor,
    ).run_once(TENANT, "worker:stale-terminal")

    assert outcomes == ()


def test_completion_migration_honors_cancellation_at_final_boundary():
    sql = (
        Path(__file__).resolve().parent
        / "migrations"
        / "168_chongqing_data_package_reconciliation_cancel_race.sql"
    ).read_text(encoding="utf-8")
    assert "cancelled_at_completion_boundary" in sql
    assert "IF v_job.status = 'cancel_requested' THEN" in sql
    assert "response_document = NULL" in sql

"""Repeatable, non-production rehearsal for Chongqing reconciliation failures."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace
from typing import Literal

from pydantic import Field, model_validator

from .chongqing_data_package_reconciliation import (
    ChongqingDataPackageReconciliationCancelledError,
)
from .chongqing_data_package_reconciliation_job import (
    ChongqingDataPackageReconciliationJob,
    ChongqingDataPackageReconciliationJobConflictError,
    ChongqingDataPackageReconciliationJobWorker,
    reconciliation_job_id,
)
from .chongqing_data_package_reconciliation_service import (
    ChongqingDataPackageReconciliationRequest,
    ChongqingDataPackageReconciliationResponse,
)
from .chongqing_entity_link_baseline import build_chongqing_entity_link_baseline
from .platform_contracts import FrozenContract, canonical_json_fingerprint

TENANT = "chongqing-customer"
ACTOR = "agent:reconciliation-rehearsal"
SCENARIOS = (
    "executor_failure_retry",
    "progress_lease_loss",
    "terminal_succeed_lease_loss",
    "terminal_cancel_lease_loss",
    "terminal_fail_lease_loss",
    "cancel_at_batch_boundary",
    "duplicate_claim_prevention",
    "max_attempts_fail_closed",
)


class ChongqingReconciliationResilienceScenario(FrozenContract):
    schema_id: Literal[
        "gda.chongqing-reconciliation-resilience-scenario-result.v1"
    ] = "gda.chongqing-reconciliation-resilience-scenario-result.v1"
    scenario: str
    status: Literal["passed", "failed"]
    expected_outcome: str
    observed_outcome: str
    events: tuple[str, ...]
    duration_ms: float = Field(ge=0)


class ChongqingReconciliationResilienceReport(FrozenContract):
    schema_id: Literal["gda.chongqing-reconciliation-resilience-report.v1"] = (
        "gda.chongqing-reconciliation-resilience-report.v1"
    )
    generated_at: datetime
    scenario_results: tuple[ChongqingReconciliationResilienceScenario, ...]
    passed_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    capacity_scope: Literal["in_memory_worker_orchestration_only"] = (
        "in_memory_worker_orchestration_only"
    )
    capacity_iterations: int = Field(ge=1)
    capacity_elapsed_ms: float = Field(ge=0)
    capacity_jobs_per_second: float = Field(ge=0)
    production_capacity_certified: Literal[False] = False
    technical_baseline_status: Literal["technical_baseline_unreviewed"] = (
        "technical_baseline_unreviewed"
    )
    decision_status: Literal[
        "assisted_precheck_not_for_production_decision"
    ] = "assisted_precheck_not_for_production_decision"
    report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _counts_match(self) -> ChongqingReconciliationResilienceReport:
        if self.passed_count + self.failed_count != len(self.scenario_results):
            raise ValueError("scenario counts do not match scenario results")
        expected = _report_sha256(self.model_dump(mode="json"))
        if self.report_sha256 != expected:
            raise ValueError("resilience report fingerprint is invalid")
        return self


class _HarnessRepository:
    def __init__(
        self,
        request: ChongqingDataPackageReconciliationRequest,
        scenario: str,
    ) -> None:
        self.request = request
        self.scenario = scenario
        self.job = _job(request)
        self.claim_count = 0
        self.executor_count = 0
        self.failure_count = 0
        self.events: list[str] = []

    def claim(self, tenant_id, worker_id, *, limit, lease_seconds):
        self.claim_count += 1
        if self.scenario == "duplicate_claim_prevention" and self.claim_count > 1:
            self.events.append("second_claim_empty")
            return []
        self.events.append("claim")
        return [SimpleNamespace(job=self.job, request=self.request)]

    def checkpoint(self, job, worker_id, **kwargs):
        self.events.append(f"checkpoint:{kwargs['phase_detail']}")
        if self.scenario == "progress_lease_loss":
            self.events.append("lease_lost_at_checkpoint")
            raise ChongqingDataPackageReconciliationJobConflictError(
                "injected checkpoint lease loss"
            )
        if self.scenario == "cancel_at_batch_boundary":
            self.events.append("cancel_requested")
            self.job = _job(
                self.request,
                status="cancel_requested",
                phase="applying",
                phase_detail="applying",
                cancel_requested=True,
            )
        return self.job

    def succeed(self, job, worker_id, result):
        self.events.append("succeed")
        if self.scenario == "terminal_succeed_lease_loss":
            self.events.append("lease_lost_at_succeed")
            raise ChongqingDataPackageReconciliationJobConflictError(
                "injected completion lease loss"
            )
        self.job = _job(
            self.request,
            status="succeeded",
            phase="completed",
            phase_detail="completed",
            progress_percent=100,
            result=result,
        )
        return self.job

    def mark_cancelled(self, job, worker_id):
        self.events.append("mark_cancelled")
        if self.scenario == "terminal_cancel_lease_loss":
            self.events.append("lease_lost_at_cancel")
            raise ChongqingDataPackageReconciliationJobConflictError(
                "injected cancellation lease loss"
            )
        self.job = _job(
            self.request,
            status="cancelled",
            phase="cancelled",
            phase_detail="cancelled_at_atomic_batch_boundary",
            progress_percent=job.progress_percent,
            cancel_requested=True,
        )
        return self.job

    def fail(self, job, worker_id, **kwargs):
        self.events.append("fail")
        if self.scenario == "terminal_fail_lease_loss":
            self.events.append("lease_lost_at_fail")
            raise ChongqingDataPackageReconciliationJobConflictError(
                "injected failure lease loss"
            )
        self.failure_count += 1
        if self.scenario == "max_attempts_fail_closed":
            self.job = _job(
                self.request,
                status="failed",
                phase="failed",
                phase_detail="failed_after_max_attempts",
                progress_percent=0,
                error_code="injected_failure",
                error_message="injected failure reached max attempts",
            )
            return self.job
        self.job = _job(self.request, status="queued", phase="queued")
        return self.job


def _request() -> ChongqingDataPackageReconciliationRequest:
    baseline = build_chongqing_entity_link_baseline(tenant_id=TENANT)
    effective_at = baseline.link_assertion_drafts[0].valid_from + timedelta(days=1)
    return ChongqingDataPackageReconciliationRequest(
        tenant_id=TENANT,
        previous_baseline=baseline,
        desired_baseline=baseline,
        effective_at=effective_at,
        evaluated_at=effective_at + timedelta(hours=1),
        idempotency_key="cq.reconciliation.resilience.rehearsal-001",
        recorded_by=ACTOR,
    )


def _job(
    request: ChongqingDataPackageReconciliationRequest,
    *,
    status: str = "running",
    phase: str = "planning",
    phase_detail: str = "planning",
    progress_percent: int = 5,
    result: ChongqingDataPackageReconciliationResponse | None = None,
    cancel_requested: bool = False,
    error_code: str | None = None,
    error_message: str | None = None,
) -> ChongqingDataPackageReconciliationJob:
    now = datetime.now(UTC)
    terminal = status in {"cancelled", "succeeded", "failed"}
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
        progress_percent=progress_percent,
        attempt_count=1,
        max_attempts=1 if status == "failed" else 5,
        submitted_by=request.recorded_by,
        submitted_at=now,
        started_at=None if status == "queued" else now,
        updated_at=now,
        completed_at=now if terminal else None,
        lease_expires_at=None if terminal or status == "queued" else now + timedelta(minutes=10),
        cancel_requested_by=ACTOR if cancel_requested else None,
        cancel_reason="injected cancellation" if cancel_requested else None,
        cancel_requested_at=now if cancel_requested else None,
        result=result,
        error_code=error_code,
        error_message=error_message,
    )


def _response(
    request: ChongqingDataPackageReconciliationRequest,
) -> ChongqingDataPackageReconciliationResponse:
    return ChongqingDataPackageReconciliationResponse(
        tenant_id=request.tenant_id,
        idempotency_key=request.idempotency_key,
        recorded_by=request.recorded_by,
        request_sha256=request.request_sha256,
        previous_customer_bundle_version=request.previous_baseline.customer_bundle_version,
        desired_customer_bundle_version=request.desired_baseline.customer_bundle_version,
        effective_at=request.effective_at,
        evaluated_at=request.evaluated_at,
        plan_sha256="a" * 64,
        receipt_sha256="b" * 64,
        previous_baseline_sha256="c" * 64,
        desired_baseline_sha256="c" * 64,
        authority_state_sha256="d" * 64,
        operation_count=0,
        batch_count=0,
        unchanged_entity_count=len(request.previous_baseline.temporal_entity_drafts),
        unchanged_source_count=len(request.previous_baseline.source_binding_drafts),
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


def _report_sha256(document: dict) -> str:
    normalized = dict(document)
    generated_at = normalized.get("generated_at")
    if isinstance(generated_at, str) and generated_at.endswith("+00:00"):
        normalized["generated_at"] = generated_at[:-6] + "Z"
    return canonical_json_fingerprint(
        {
            key: value
            for key, value in normalized.items()
            if key != "report_sha256"
        }
    )


def _run_scenario(
    name: str,
    request: ChongqingDataPackageReconciliationRequest,
) -> ChongqingReconciliationResilienceScenario:
    started = perf_counter()
    repository = _HarnessRepository(request, name)
    result = _response(request)

    def executor(request, *, progress_callback, cancel_check):
        repository.executor_count += 1
        if name == "executor_failure_retry" and repository.executor_count == 1:
            repository.events.append("executor_failure")
            raise RuntimeError("injected executor failure")
        if name == "cancel_at_batch_boundary":
            progress_callback("applying", 1, 2)
            raise ChongqingDataPackageReconciliationCancelledError(
                "injected cancellation"
            )
        if name == "progress_lease_loss":
            progress_callback("applying", 1, 2)
        if name == "terminal_cancel_lease_loss":
            raise ChongqingDataPackageReconciliationCancelledError(
                "injected cancellation"
            )
        if name in {"terminal_fail_lease_loss", "max_attempts_fail_closed"}:
            raise RuntimeError("injected executor failure")
        return result

    worker = ChongqingDataPackageReconciliationJobWorker(
        repository=repository,
        executor=executor,
    )
    outcomes = worker.run_once(TENANT, "worker:resilience-rehearsal")
    if name == "executor_failure_retry":
        outcomes = worker.run_once(TENANT, "worker:resilience-rehearsal")

    expected = {
        "executor_failure_retry": ("succeeded", 1),
        "progress_lease_loss": ("no_outcome", 0),
        "terminal_succeed_lease_loss": ("no_outcome", 0),
        "terminal_cancel_lease_loss": ("no_outcome", 0),
        "terminal_fail_lease_loss": ("no_outcome", 0),
        "cancel_at_batch_boundary": ("cancelled", 0),
        "duplicate_claim_prevention": ("succeeded", 0),
        "max_attempts_fail_closed": ("failed", 1),
    }[name]
    observed = outcomes[0].status if outcomes else "no_outcome"
    passed = observed == expected[0] and repository.failure_count == expected[1]
    if name == "executor_failure_retry":
        passed = passed and repository.executor_count == 2
    if name == "duplicate_claim_prevention":
        second = worker.run_once(TENANT, "worker:resilience-rehearsal")
        passed = passed and not second and repository.claim_count == 2
    return ChongqingReconciliationResilienceScenario(
        scenario=name,
        status="passed" if passed else "failed",
        expected_outcome=expected[0],
        observed_outcome=observed,
        events=tuple(repository.events),
        duration_ms=(perf_counter() - started) * 1000,
    )


def _run_capacity_microbenchmark(
    request: ChongqingDataPackageReconciliationRequest,
    iterations: int,
) -> tuple[float, float]:
    repository = _HarnessRepository(request, "capacity")
    result = _response(request)

    def executor(request, *, progress_callback, cancel_check):
        return result

    worker = ChongqingDataPackageReconciliationJobWorker(
        repository=repository,
        executor=executor,
    )
    started = perf_counter()
    for _ in range(iterations):
        repository.job = _job(request)
        worker.run_once(TENANT, "worker:resilience-capacity")
    elapsed_ms = (perf_counter() - started) * 1000
    return elapsed_ms, iterations / max(elapsed_ms / 1000, 1e-9)


def run_chongqing_reconciliation_resilience_rehearsal(
    *,
    iterations: int = 100,
) -> ChongqingReconciliationResilienceReport:
    if iterations < 1 or iterations > 100_000:
        raise ValueError("iterations must be between 1 and 100000")
    request = _request()
    results = tuple(_run_scenario(name, request) for name in SCENARIOS)
    elapsed_ms, jobs_per_second = _run_capacity_microbenchmark(request, iterations)
    payload = {
        "schema_id": "gda.chongqing-reconciliation-resilience-report.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "scenario_results": [item.model_dump(mode="json") for item in results],
        "passed_count": sum(item.status == "passed" for item in results),
        "failed_count": sum(item.status == "failed" for item in results),
        "capacity_scope": "in_memory_worker_orchestration_only",
        "capacity_iterations": iterations,
        "capacity_elapsed_ms": elapsed_ms,
        "capacity_jobs_per_second": jobs_per_second,
        "production_capacity_certified": False,
        "technical_baseline_status": "technical_baseline_unreviewed",
        "decision_status": "assisted_precheck_not_for_production_decision",
    }
    payload["report_sha256"] = _report_sha256(payload)
    return ChongqingReconciliationResilienceReport.model_validate(payload)


def write_chongqing_reconciliation_resilience_report(
    report: ChongqingReconciliationResilienceReport,
    path: str | Path,
) -> Path:
    target = Path(path)
    target.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    return target


__all__ = [
    "ChongqingReconciliationResilienceReport",
    "ChongqingReconciliationResilienceScenario",
    "SCENARIOS",
    "run_chongqing_reconciliation_resilience_rehearsal",
    "write_chongqing_reconciliation_resilience_report",
]

"""Durable leased jobs for the cross-store projection recovery worker."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import Field, ValidationError, field_validator, model_validator
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from .cross_store_projection_authority import PostgresProjectionCheckpointAuthority
from .cross_store_projection_consistency import ProjectionRepairPlan
from .cross_store_projection_recovery import ProjectionRecoveryState
from .cross_store_projection_recovery_authority import PostgresProjectionRecoveryLedger
from .cross_store_projection_recovery_compensation import (
    ProjectionRecoveryCompensationAttempt,
    ProjectionRecoveryCompensationReconciliation,
)
from .cross_store_projection_recovery_controller import (
    ControllerBindingResolver,
    ProjectionRecoveryControllerBindingError,
    ProjectionRecoveryControllerGuard,
)
from .cross_store_projection_recovery_worker import (
    Compensation,
    ProjectionRecoveryProvider,
    ProjectionRecoveryWorker,
    ProjectionRecoveryWorkerResult,
)
from .db_engine import get_engine
from .platform_contracts import (
    FrozenContract,
    ResourceURNText,
    Sha256,
    TenantId,
    parse_resource_urn,
)
from .temporal_entity_authority import GATEWAY_DATABASE_ROLE

_JOB_NAMESPACE = uuid5(
    NAMESPACE_URL,
    "https://gis-data-agent.local/cross-store-projection-recovery-job/v1",
)

RecoveryJobStatus = Literal[
    "queued",
    "running",
    "waiting_operator",
    "succeeded",
    "failed",
]


class ProjectionRecoveryJobError(RuntimeError):
    code = "projection_recovery_job_error"


class ProjectionRecoveryJobConfigurationError(ProjectionRecoveryJobError):
    code = "projection_recovery_job_configuration_error"


class ProjectionRecoveryJobConflictError(ProjectionRecoveryJobError):
    code = "projection_recovery_job_conflict"


class ProjectionRecoveryJobForbiddenError(ProjectionRecoveryJobError):
    code = "projection_recovery_job_forbidden"


class ProjectionRecoveryJobNotFoundError(ProjectionRecoveryJobError):
    code = "projection_recovery_job_not_found"


class ProjectionRecoveryJobValidationError(ProjectionRecoveryJobError):
    code = "projection_recovery_job_validation_error"


def _aware_utc(value: datetime | None, name: str) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


class ProjectionRecoveryJob(FrozenContract):
    schema_id: Literal["gda.cross-store-projection-recovery-job.v1"] = (
        "gda.cross-store-projection-recovery-job.v1"
    )
    tenant_id: TenantId
    job_id: UUID
    plan_sha256: Sha256
    plan_idempotency_key: Sha256
    projection_id: str
    target_engine: str
    target_ref: str
    plan: ProjectionRepairPlan
    status: RecoveryJobStatus
    next_action: str | None = None
    attempt_count: int = Field(ge=0)
    max_attempts: int = Field(ge=1, le=100)
    claimed_by: str | None = None
    lease_expires_at: datetime | None = None
    lease_generation: int = Field(ge=0)
    available_at: datetime
    submitted_by: str
    submitted_at: datetime
    resumed_by: str | None = None
    resumed_at: datetime | None = None
    resume_approval_case_ref: ResourceURNText | None = None
    resume_reason: str | None = Field(default=None, max_length=1024)
    resume_snapshot_sha256: Sha256 | None = None
    updated_at: datetime
    completed_at: datetime | None = None
    snapshot_sha256: Sha256 | None = None
    error_code: str | None = None
    error_message: str | None = None
    technical_baseline_status: Literal["technical_baseline_unreviewed"] = (
        "technical_baseline_unreviewed"
    )
    decision_status: Literal[
        "assisted_precheck_not_for_production_decision"
    ] = "assisted_precheck_not_for_production_decision"

    @field_validator(
        "lease_expires_at",
        "available_at",
        "submitted_at",
        "resumed_at",
        "updated_at",
        "completed_at",
    )
    @classmethod
    def _times(cls, value: datetime | None, info) -> datetime | None:
        return _aware_utc(value, info.field_name)

    @model_validator(mode="after")
    def _state_contract(self) -> ProjectionRecoveryJob:
        terminal = self.status in {"succeeded", "failed"}
        if terminal != (self.completed_at is not None):
            raise ValueError("recovery job terminal state is inconsistent")
        if (self.status == "running") != (self.claimed_by is not None):
            raise ValueError("recovery job claim state is inconsistent")
        if (self.claimed_by is None) != (self.lease_expires_at is None):
            raise ValueError("recovery job lease state is inconsistent")
        resume_evidence = (
            self.resumed_by,
            self.resumed_at,
            self.resume_approval_case_ref,
            self.resume_reason,
            self.resume_snapshot_sha256,
        )
        if any(value is not None for value in resume_evidence) and not all(
            value is not None for value in resume_evidence
        ):
            raise ValueError("recovery job resume evidence is inconsistent")
        if self.resume_reason is not None and not self.resume_reason.strip():
            raise ValueError("recovery job resume reason is empty")
        if self.resume_approval_case_ref is not None:
            approval_identity = parse_resource_urn(self.resume_approval_case_ref)
            if (
                approval_identity["tenant_id"] != self.tenant_id
                or approval_identity["resource_kind"] != "approval_case"
            ):
                raise ValueError("recovery job resume approval identity differs")
        if self.status == "succeeded" and (
            self.next_action != "none" or self.snapshot_sha256 is None
        ):
            raise ValueError("successful recovery job lacks terminal evidence")
        if self.status == "waiting_operator" and self.next_action != "manual_compensation":
            raise ValueError("waiting recovery job must require manual compensation")
        if (
            self.plan.tenant_id != self.tenant_id
            or self.plan.plan_sha256 != self.plan_sha256
            or self.plan.plan_idempotency_key != self.plan_idempotency_key
            or self.plan.projection_id != self.projection_id
            or self.plan.target_engine.value != self.target_engine
            or self.plan.target_ref != self.target_ref
        ):
            raise ValueError("recovery job plan identity differs")
        return self


class ClaimedProjectionRecoveryJob(FrozenContract):
    job: ProjectionRecoveryJob


def projection_recovery_job_id(plan: ProjectionRepairPlan) -> UUID:
    return uuid5(_JOB_NAMESPACE, f"{plan.tenant_id}:{plan.plan_sha256}")


def _sqlstate(exc: DBAPIError) -> str | None:
    original = getattr(exc, "orig", None)
    return getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)


def _json_value(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


class PostgresProjectionRecoveryJobRepository:
    """Tenant-scoped queue with idempotent enqueue and fenced leases."""

    def __init__(self, engine: Any = None):
        self._engine = engine

    def get_engine(self):
        engine = self._engine or get_engine()
        if engine is None or engine.dialect.name != "postgresql":
            raise ProjectionRecoveryJobConfigurationError(
                "projection recovery jobs require PostgreSQL"
            )
        return engine

    @contextmanager
    def _transaction(self, tenant_id: str) -> Iterator[Any]:
        try:
            with self.get_engine().connect() as connection:
                with connection.begin():
                    try:
                        connection.exec_driver_sql(
                            f'SET LOCAL ROLE "{GATEWAY_DATABASE_ROLE}"'
                        )
                    except DBAPIError as exc:
                        raise ProjectionRecoveryJobConfigurationError(
                            "database login is not a member of the platform gateway role"
                        ) from exc
                    connection.execute(
                        text("SELECT set_config('app.current_tenant', :tenant, true)"),
                        {"tenant": tenant_id},
                    )
                    yield connection
        except ProjectionRecoveryJobError:
            raise
        except DBAPIError as exc:
            state = _sqlstate(exc)
            if state in {"23505", "40001", "55000"}:
                raise ProjectionRecoveryJobConflictError(
                    "projection recovery job state changed concurrently"
                ) from exc
            if state == "42501":
                raise ProjectionRecoveryJobForbiddenError(
                    "projection recovery job tenant or role was denied"
                ) from exc
            if state in {"22023", "23514"}:
                raise ProjectionRecoveryJobValidationError(
                    "projection recovery job payload or transition is invalid"
                ) from exc
            if state == "P0002":
                raise ProjectionRecoveryJobNotFoundError(
                    "projection recovery job was not found"
                ) from exc
            raise ProjectionRecoveryJobConfigurationError(
                "projection recovery job repository is unavailable"
            ) from exc
        except SQLAlchemyError as exc:
            raise ProjectionRecoveryJobConfigurationError(
                "projection recovery job repository is unavailable"
            ) from exc

    @staticmethod
    def _job_from_row(row: Any) -> ProjectionRecoveryJob:
        value = dict(row)
        value["plan"] = _json_value(value.pop("plan_document"))
        try:
            return ProjectionRecoveryJob.model_validate(value)
        except (TypeError, ValueError, ValidationError) as exc:
            raise ProjectionRecoveryJobValidationError(
                "stored projection recovery job is invalid"
            ) from exc

    def enqueue(
        self,
        plan: ProjectionRepairPlan,
        *,
        submitted_by: str,
        max_attempts: int = 5,
    ) -> ProjectionRecoveryJob:
        with self._transaction(plan.tenant_id) as connection:
            row = connection.execute(
                text(
                    """
                    SELECT *
                    FROM gda_control.enqueue_cross_store_projection_recovery_job(
                        :tenant_id, :job_id, :plan_sha256, :plan_idempotency_key,
                        :projection_id, :target_engine, :target_ref,
                        CAST(:plan_document AS jsonb), :submitted_by, :max_attempts
                    )
                    """
                ),
                {
                    "tenant_id": plan.tenant_id,
                    "job_id": projection_recovery_job_id(plan),
                    "plan_sha256": plan.plan_sha256,
                    "plan_idempotency_key": plan.plan_idempotency_key,
                    "projection_id": plan.projection_id,
                    "target_engine": plan.target_engine.value,
                    "target_ref": plan.target_ref,
                    "plan_document": json.dumps(plan.model_dump(mode="json")),
                    "submitted_by": submitted_by,
                    "max_attempts": max_attempts,
                },
            ).mappings().one()
        return self._job_from_row(row)

    def get(self, tenant_id: str, job_id: UUID) -> ProjectionRecoveryJob:
        with self._transaction(tenant_id) as connection:
            row = connection.execute(
                text(
                    """
                    SELECT * FROM gda_control.cross_store_projection_recovery_job
                    WHERE tenant_id = :tenant_id AND job_id = :job_id
                    """
                ),
                {"tenant_id": tenant_id, "job_id": job_id},
            ).mappings().one_or_none()
        if row is None:
            raise ProjectionRecoveryJobNotFoundError(
                "projection recovery job was not found"
            )
        return self._job_from_row(row)

    def claim(
        self,
        tenant_id: str,
        worker_id: str,
        *,
        limit: int = 1,
        lease_seconds: int = 120,
    ) -> tuple[ClaimedProjectionRecoveryJob, ...]:
        with self._transaction(tenant_id) as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT *
                    FROM gda_control.claim_cross_store_projection_recovery_jobs(
                        :tenant_id, :worker_id, :limit, :lease_seconds
                    )
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "worker_id": worker_id,
                    "limit": limit,
                    "lease_seconds": lease_seconds,
                },
            ).mappings().all()
        return tuple(
            ClaimedProjectionRecoveryJob(job=self._job_from_row(row)) for row in rows
        )

    def renew(
        self,
        job: ProjectionRecoveryJob,
        worker_id: str,
        *,
        lease_seconds: int = 120,
    ) -> ProjectionRecoveryJob:
        with self._transaction(job.tenant_id) as connection:
            row = connection.execute(
                text(
                    """
                    SELECT *
                    FROM gda_control.renew_cross_store_projection_recovery_job_lease(
                        :tenant_id, :job_id, :worker_id, :lease_generation,
                        :lease_seconds
                    )
                    """
                ),
                {
                    "tenant_id": job.tenant_id,
                    "job_id": job.job_id,
                    "worker_id": worker_id,
                    "lease_generation": job.lease_generation,
                    "lease_seconds": lease_seconds,
                },
            ).mappings().one()
        return self._job_from_row(row)

    def _finish(
        self,
        job: ProjectionRecoveryJob,
        worker_id: str,
        *,
        status: str,
        next_action: str | None,
        snapshot_sha256: str | None,
        error_code: str | None,
        error_message: str | None,
        retry_delay_seconds: int,
    ) -> ProjectionRecoveryJob:
        with self._transaction(job.tenant_id) as connection:
            row = connection.execute(
                text(
                    """
                    SELECT *
                    FROM gda_control.finish_cross_store_projection_recovery_job(
                        :tenant_id, :job_id, :worker_id, :lease_generation,
                        :status, :next_action, :snapshot_sha256, :error_code,
                        :error_message, :retry_delay_seconds
                    )
                    """
                ),
                {
                    "tenant_id": job.tenant_id,
                    "job_id": job.job_id,
                    "worker_id": worker_id,
                    "lease_generation": job.lease_generation,
                    "status": status,
                    "next_action": next_action,
                    "snapshot_sha256": snapshot_sha256,
                    "error_code": error_code,
                    "error_message": error_message,
                    "retry_delay_seconds": retry_delay_seconds,
                },
            ).mappings().one()
        return self._job_from_row(row)

    def finish(
        self,
        job: ProjectionRecoveryJob,
        worker_id: str,
        result: ProjectionRecoveryWorkerResult,
        *,
        retry_delay_seconds: int = 30,
    ) -> ProjectionRecoveryJob:
        snapshot = result.snapshot
        if snapshot.state is ProjectionRecoveryState.AUTHORITY_COMMITTED:
            status = "succeeded"
        elif snapshot.next_action == "manual_compensation":
            status = "waiting_operator"
        elif snapshot.state is ProjectionRecoveryState.FAILED_CLOSED:
            status = "failed"
        else:
            status = "queued"
        error_code = result.error_code or snapshot.last_error_code
        return self._finish(
            job,
            worker_id,
            status=status,
            next_action=snapshot.next_action,
            snapshot_sha256=snapshot.snapshot_sha256,
            error_code=error_code,
            error_message=error_code,
            retry_delay_seconds=retry_delay_seconds,
        )

    def fail(
        self,
        job: ProjectionRecoveryJob,
        worker_id: str,
        error: Exception,
        *,
        retry_delay_seconds: int = 30,
    ) -> ProjectionRecoveryJob:
        code = str(getattr(error, "code", "recovery_worker_error"))[:128]
        message = str(error).strip()[:1024] or type(error).__name__
        operator_required = code in {
            "compensation_execution_outcome_is_indeterminate",
            "compensation_terminal_evidence_write_failed",
        }
        return self._finish(
            job,
            worker_id,
            status="waiting_operator" if operator_required else "queued",
            next_action="manual_compensation" if operator_required else job.next_action,
            snapshot_sha256=job.snapshot_sha256,
            error_code=code,
            error_message=message,
            retry_delay_seconds=retry_delay_seconds,
        )

    def resume(
        self,
        job: ProjectionRecoveryJob,
        *,
        requested_by: str,
        approval_case_ref: str,
        reason: str,
    ) -> ProjectionRecoveryJob:
        with self._transaction(job.tenant_id) as connection:
            row = connection.execute(
                text(
                    """
                    SELECT *
                    FROM gda_control.resume_cross_store_projection_recovery_job(
                        :tenant_id, :job_id, :requested_by,
                        :approval_case_ref, :reason
                    )
                    """
                ),
                {
                    "tenant_id": job.tenant_id,
                    "job_id": job.job_id,
                    "requested_by": requested_by,
                    "approval_case_ref": approval_case_ref,
                    "reason": reason,
                },
            ).mappings().one()
        return self._job_from_row(row)

    def assert_compensation_authorized(
        self,
        job: ProjectionRecoveryJob,
        snapshot: Any,
    ) -> None:
        """Recheck the consumed ApprovalCase and current durable snapshot."""

        if (
            job.status != "running"
            or job.claimed_by is None
            or job.resume_approval_case_ref is None
            or job.resume_snapshot_sha256 is None
            or job.resume_reason is None
            or job.resumed_by is None
            or job.resumed_at is None
            or getattr(snapshot, "snapshot_sha256", None)
            != job.resume_snapshot_sha256
        ):
            raise ProjectionRecoveryJobValidationError(
                "projection recovery compensation authority evidence is incomplete"
            )
        expected_target = (
            f"gda://{job.tenant_id}/projection_recovery_job/{job.job_id}"
        )
        with self._transaction(job.tenant_id) as connection:
            authorized = connection.execute(
                text(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM gda_control.cross_store_projection_recovery_job AS job
                        JOIN gda_control.approval_case AS approval
                          ON approval.tenant_id = job.tenant_id
                         AND approval.approval_case_ref = job.resume_approval_case_ref
                        JOIN gda_control.cross_store_projection_recovery_resume_event AS event
                          ON event.tenant_id = job.tenant_id
                         AND event.approval_case_ref = job.resume_approval_case_ref
                         AND event.job_id = job.job_id
                        JOIN gda_control.cross_store_projection_recovery_snapshot_current
                             AS recovery
                          ON recovery.tenant_id = job.tenant_id
                         AND recovery.plan_sha256 = job.plan_sha256
                        WHERE job.tenant_id = :tenant_id
                          AND job.job_id = :job_id
                          AND job.status = 'running'
                          AND job.claimed_by = :claimed_by
                          AND job.lease_generation = :lease_generation
                          AND job.lease_expires_at > clock_timestamp()
                          AND job.plan_sha256 = :plan_sha256
                          AND job.plan_idempotency_key = :plan_idempotency_key
                          AND job.projection_id = :projection_id
                          AND job.target_engine = :target_engine
                          AND job.target_ref = :target_ref
                          AND job.snapshot_sha256 = :resume_snapshot_sha256
                          AND job.resume_snapshot_sha256 = :resume_snapshot_sha256
                          AND job.resume_approval_case_ref = :approval_case_ref
                          AND job.resumed_by = :resumed_by
                          AND job.resumed_at = :resumed_at
                          AND job.resume_reason = :resume_reason
                          AND approval.status = 'approved'
                          AND clock_timestamp() < approval.expires_at
                          AND approval.target_resource_urn = :expected_target
                          AND approval.target_fingerprint = :resume_snapshot_sha256
                          AND approval.action = 'projection.recovery.compensate'
                          AND event.resume_snapshot_sha256 = :resume_snapshot_sha256
                          AND event.resumed_by = :resumed_by
                          AND event.resumed_at = :resumed_at
                          AND event.resume_reason = :resume_reason
                          AND recovery.plan_idempotency_key = :plan_idempotency_key
                          AND recovery.projection_id = :projection_id
                          AND recovery.target_engine = :target_engine
                          AND recovery.target_ref = :target_ref
                          AND recovery.snapshot_sha256 = :resume_snapshot_sha256
                          AND recovery.snapshot_document ->> 'state' IN (
                              'reconciliation_required', 'compensation_required'
                          )
                          AND recovery.snapshot_document ->> 'next_action'
                              = 'manual_compensation'
                    )
                    """
                ),
                {
                    "tenant_id": job.tenant_id,
                    "job_id": job.job_id,
                    "claimed_by": job.claimed_by,
                    "lease_generation": job.lease_generation,
                    "plan_sha256": job.plan_sha256,
                    "plan_idempotency_key": job.plan_idempotency_key,
                    "projection_id": job.projection_id,
                    "target_engine": job.target_engine,
                    "target_ref": job.target_ref,
                    "resume_snapshot_sha256": job.resume_snapshot_sha256,
                    "approval_case_ref": job.resume_approval_case_ref,
                    "resumed_by": job.resumed_by,
                    "resumed_at": job.resumed_at,
                    "resume_reason": job.resume_reason,
                    "expected_target": expected_target,
                },
            ).scalar_one()
        if not authorized:
            raise ProjectionRecoveryJobValidationError(
                "projection recovery compensation authority evidence drifted"
            )

    @staticmethod
    def _compensation_attempt_from_row(row: Any) -> ProjectionRecoveryCompensationAttempt:
        try:
            return ProjectionRecoveryCompensationAttempt(
                compensation_attempt_id=row["compensation_attempt_id"],
                outcome=row["outcome"],
                provider_commit_ref=row.get("provider_commit_ref"),
                receipt_sha256=row.get("receipt_sha256"),
                error_code=row.get("error_code"),
            )
        except (TypeError, ValueError, ValidationError) as exc:
            raise ProjectionRecoveryJobValidationError(
                "stored projection compensation attempt is invalid"
            ) from exc

    def begin_compensation_execution(
        self,
        job: ProjectionRecoveryJob,
        snapshot: Any,
        *,
        strategy: str,
        compensation_attempt_id: UUID,
    ) -> ProjectionRecoveryCompensationAttempt:
        with self._transaction(job.tenant_id) as connection:
            row = connection.execute(
                text(
                    """
                    SELECT *
                    FROM gda_control.begin_projection_recovery_compensation(
                        :tenant_id, :job_id, :worker_id, :lease_generation,
                        :approval_case_ref, :resume_snapshot_sha256,
                        :plan_sha256, :plan_idempotency_key, :strategy,
                        :compensation_attempt_id
                    )
                    """
                ),
                {
                    "tenant_id": job.tenant_id,
                    "job_id": job.job_id,
                    "worker_id": job.claimed_by,
                    "lease_generation": job.lease_generation,
                    "approval_case_ref": job.resume_approval_case_ref,
                    "resume_snapshot_sha256": job.resume_snapshot_sha256,
                    "plan_sha256": job.plan_sha256,
                    "plan_idempotency_key": job.plan_idempotency_key,
                    "strategy": strategy,
                    "compensation_attempt_id": compensation_attempt_id,
                },
            ).mappings().one()
        return self._compensation_attempt_from_row(row)

    @staticmethod
    def _compensation_reconciliation_from_row(
        row: Any,
    ) -> ProjectionRecoveryCompensationReconciliation:
        try:
            return ProjectionRecoveryCompensationReconciliation(
                tenant_id=row["tenant_id"],
                reconciliation_event_id=row["reconciliation_event_id"],
                compensation_attempt_id=row["compensation_attempt_id"],
                job_id=row["job_id"],
                original_approval_case_ref=row["original_approval_case_ref"],
                reconciliation_approval_case_ref=row[
                    "reconciliation_approval_case_ref"
                ],
                target_fingerprint=row["target_fingerprint"],
                resume_snapshot_sha256=row["resume_snapshot_sha256"],
                plan_sha256=row["plan_sha256"],
                plan_idempotency_key=row["plan_idempotency_key"],
                strategy=row["strategy"],
                verdict=row["verdict"],
                observed_by=row["observed_by"],
                observation_ref=row["observation_ref"],
                observation_sha256=row["observation_sha256"],
                reason=row["reason"],
                provider_commit_ref=row.get("provider_commit_ref"),
                receipt_sha256=row.get("receipt_sha256"),
            )
        except (TypeError, ValueError, ValidationError) as exc:
            raise ProjectionRecoveryJobValidationError(
                "stored projection compensation reconciliation is invalid"
            ) from exc

    def reconcile_compensation_execution(
        self,
        *,
        tenant_id: str,
        job_id: UUID,
        original_approval_case_ref: str,
        reconciliation_approval_case_ref: str,
        compensation_attempt_id: UUID,
        target_fingerprint: str,
        verdict: Literal["provider_committed", "provider_not_committed"],
        observed_by: str,
        observation_ref: str,
        observation_sha256: str,
        reason: str,
        provider_commit_ref: dict[str, Any] | None = None,
        receipt_sha256: str | None = None,
    ) -> ProjectionRecoveryCompensationReconciliation:
        with self._transaction(tenant_id) as connection:
            row = connection.execute(
                text(
                    """
                    SELECT *
                    FROM gda_control.reconcile_projection_recovery_compensation(
                        :tenant_id, :job_id, :original_approval_case_ref,
                        :reconciliation_approval_case_ref,
                        :compensation_attempt_id, :target_fingerprint,
                        :verdict, :observed_by, :observation_ref,
                        :observation_sha256, :reason,
                        CAST(:provider_commit_ref AS jsonb), :receipt_sha256
                    )
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "job_id": job_id,
                    "original_approval_case_ref": original_approval_case_ref,
                    "reconciliation_approval_case_ref": (
                        reconciliation_approval_case_ref
                    ),
                    "compensation_attempt_id": compensation_attempt_id,
                    "target_fingerprint": target_fingerprint,
                    "verdict": verdict,
                    "observed_by": observed_by,
                    "observation_ref": observation_ref,
                    "observation_sha256": observation_sha256,
                    "reason": reason,
                    "provider_commit_ref": (
                        None
                        if provider_commit_ref is None
                        else json.dumps(
                            provider_commit_ref,
                            ensure_ascii=True,
                            sort_keys=True,
                            separators=(",", ":"),
                        )
                    ),
                    "receipt_sha256": receipt_sha256,
                },
            ).mappings().one()
        return self._compensation_reconciliation_from_row(row)

    def finish_compensation_execution(
        self,
        job: ProjectionRecoveryJob,
        *,
        compensation_attempt_id: UUID,
        outcome: Literal["succeeded", "failed_known", "failed_unknown"],
        provider_commit_ref: dict[str, Any] | None = None,
        receipt_sha256: str | None = None,
        error_code: str | None = None,
    ) -> ProjectionRecoveryCompensationAttempt:
        with self._transaction(job.tenant_id) as connection:
            row = connection.execute(
                text(
                    """
                    SELECT *
                    FROM gda_control.finish_projection_recovery_compensation(
                        :tenant_id, :job_id, :worker_id, :lease_generation,
                        :approval_case_ref, :compensation_attempt_id,
                        :outcome, CAST(:provider_commit_ref AS jsonb),
                        :receipt_sha256, :error_code
                    )
                    """
                ),
                {
                    "tenant_id": job.tenant_id,
                    "job_id": job.job_id,
                    "worker_id": job.claimed_by,
                    "lease_generation": job.lease_generation,
                    "approval_case_ref": job.resume_approval_case_ref,
                    "compensation_attempt_id": compensation_attempt_id,
                    "outcome": outcome,
                    "provider_commit_ref": (
                        None
                        if provider_commit_ref is None
                        else json.dumps(
                            provider_commit_ref,
                            ensure_ascii=True,
                            sort_keys=True,
                            separators=(",", ":"),
                        )
                    ),
                    "receipt_sha256": receipt_sha256,
                    "error_code": error_code,
                },
            ).mappings().one()
        return self._compensation_attempt_from_row(row)


ProviderResolver = Callable[[ProjectionRepairPlan], ProjectionRecoveryProvider]
AuthorityResolver = Callable[[ProjectionRepairPlan], Any]
LedgerResolver = Callable[[ProjectionRepairPlan], Any]
CompensationResolver = Callable[
    [ProjectionRecoveryJob, ProjectionRecoveryProvider, Any],
    Compensation | None,
]


class ProjectionRecoveryJobLeaseHeartbeat:
    """Renew one claimed lease while provider/authority work is running."""

    def __init__(
        self,
        repository: Any,
        job: ProjectionRecoveryJob,
        worker_id: str,
        *,
        lease_seconds: int,
        interval_seconds: float,
    ) -> None:
        if interval_seconds <= 0 or interval_seconds >= lease_seconds:
            raise ProjectionRecoveryJobValidationError(
                "lease heartbeat interval must be positive and shorter than the lease"
            )
        self._repository = repository
        self._job = job
        self._worker_id = worker_id
        self._lease_seconds = lease_seconds
        self._interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._error: Exception | None = None

    def start(self) -> None:
        if self._thread is not None:
            raise ProjectionRecoveryJobValidationError("lease heartbeat already started")
        self._thread = threading.Thread(
            target=self._run,
            name=f"projection-recovery-heartbeat-{self._worker_id.removeprefix('worker:')}",
            daemon=True,
        )
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.wait(self._interval_seconds):
            try:
                self._job = self._repository.renew(
                    self._job,
                    self._worker_id,
                    lease_seconds=self._lease_seconds,
                )
            except Exception as exc:  # noqa: BLE001 - lease loss is fail-closed
                self._error = exc
                return

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, self._interval_seconds * 2))
            if self._thread.is_alive() and self._error is None:
                self._error = RuntimeError("lease heartbeat thread did not stop")

    def raise_if_lost(self) -> None:
        if self._error is not None:
            raise ProjectionRecoveryJobConflictError(
                "projection recovery job lease heartbeat was lost"
            ) from self._error


class ProjectionRecoveryJobWorker:
    """Claim fenced jobs and execute one recovery action per claim."""

    def __init__(
        self,
        *,
        provider_resolver: ProviderResolver,
        repository: PostgresProjectionRecoveryJobRepository | Any = None,
        authority_resolver: AuthorityResolver | None = None,
        ledger_resolver: LedgerResolver | None = None,
        compensation_resolver: CompensationResolver | None = None,
        controller_binding_resolver: ControllerBindingResolver | None = None,
    ) -> None:
        self.repository = repository or PostgresProjectionRecoveryJobRepository()
        self.provider_resolver = provider_resolver
        engine = getattr(self.repository, "get_engine", lambda: None)()
        self.authority_resolver = authority_resolver or (
            lambda _plan: PostgresProjectionCheckpointAuthority(engine)
        )
        self.ledger_resolver = ledger_resolver or (
            lambda plan: PostgresProjectionRecoveryLedger(plan.tenant_id, engine)
        )
        self.compensation_resolver = compensation_resolver or (
            lambda _job, _provider, _ledger: None
        )
        self.controller_binding_resolver = controller_binding_resolver

    def run_once(
        self,
        tenant_id: str,
        worker_id: str,
        *,
        limit: int = 1,
        lease_seconds: int = 120,
        retry_delay_seconds: int = 30,
        heartbeat_interval_seconds: float | None = None,
    ) -> tuple[ProjectionRecoveryJob, ...]:
        outcomes: list[ProjectionRecoveryJob] = []
        claims = self.repository.claim(
            tenant_id,
            worker_id,
            limit=limit,
            lease_seconds=lease_seconds,
        )
        for claim in claims:
            current = claim.job
            heartbeat: ProjectionRecoveryJobLeaseHeartbeat | None = None
            controller_guard: ProjectionRecoveryControllerGuard | None = None
            try:
                current = self.repository.renew(
                    current, worker_id, lease_seconds=lease_seconds
                )
                heartbeat = ProjectionRecoveryJobLeaseHeartbeat(
                    self.repository,
                    current,
                    worker_id,
                    lease_seconds=lease_seconds,
                    interval_seconds=(
                        heartbeat_interval_seconds
                        if heartbeat_interval_seconds is not None
                        else max(1.0, lease_seconds / 3)
                    ),
                )
                heartbeat.start()
                plan = current.plan
                if self.controller_binding_resolver is not None:
                    try:
                        controller_guard = ProjectionRecoveryControllerGuard(
                            self.controller_binding_resolver(current),
                            tenant_id=current.tenant_id,
                        )
                    except ProjectionRecoveryControllerBindingError:
                        raise
                    except Exception as exc:
                        raise ProjectionRecoveryControllerBindingError(
                            "cross-store recovery controller binding could not be loaded"
                        ) from exc
                ledger = self.ledger_resolver(plan)
                if controller_guard is not None:
                    recovery_current = getattr(ledger, "current", lambda _key: None)(
                        plan.plan_sha256
                    )
                    controller_guard.admit_before_execution(recovery_current)
                provider = self.provider_resolver(plan)
                try:
                    result = ProjectionRecoveryWorker(
                        plan,
                        checkpointed_by=f"workload:{worker_id}",
                        provider=provider,
                        authority=self.authority_resolver(plan),
                        ledger=ledger,
                        compensation=self.compensation_resolver(
                            current,
                            provider,
                            ledger,
                        ),
                    ).run_once()
                finally:
                    heartbeat.stop()
                heartbeat.raise_if_lost()
                if controller_guard is not None:
                    controller_guard.settle(result.snapshot)
                current = self.repository.finish(
                    current,
                    worker_id,
                    result,
                    retry_delay_seconds=retry_delay_seconds,
                )
            except ProjectionRecoveryJobConflictError:
                continue
            except Exception as exc:
                try:
                    if heartbeat is not None:
                        heartbeat.raise_if_lost()
                    if controller_guard is not None:
                        controller_guard.fail_closed(
                            "projection_recovery_worker_error:"
                            f"{getattr(exc, 'code', type(exc).__name__)}"
                        )
                    current = self.repository.fail(
                        current,
                        worker_id,
                        exc,
                        retry_delay_seconds=retry_delay_seconds,
                    )
                except ProjectionRecoveryJobConflictError:
                    continue
            outcomes.append(current)
        return tuple(outcomes)


__all__ = [
    "ClaimedProjectionRecoveryJob",
    "PostgresProjectionRecoveryJobRepository",
    "ProjectionRecoveryJob",
    "ProjectionRecoveryJobConfigurationError",
    "ProjectionRecoveryJobConflictError",
    "ProjectionRecoveryJobError",
    "ProjectionRecoveryJobForbiddenError",
    "ProjectionRecoveryJobLeaseHeartbeat",
    "ProjectionRecoveryJobNotFoundError",
    "ProjectionRecoveryJobValidationError",
    "ProjectionRecoveryJobWorker",
    "projection_recovery_job_id",
]

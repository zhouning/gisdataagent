"""Durable asynchronous jobs for governed Chongqing package reconciliation."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import Field, ValidationError, field_validator, model_validator
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from .chongqing_data_package_reconciliation import (
    ChongqingDataPackageReconciliationCancelledError,
)
from .chongqing_data_package_reconciliation_service import (
    ChongqingDataPackageReconciliationRequest,
    ChongqingDataPackageReconciliationResponse,
    execute_chongqing_data_package_reconciliation,
)
from .db_engine import get_engine
from .platform_contracts import FrozenContract, Sha256, TenantId
from .temporal_entity_authority import GATEWAY_DATABASE_ROLE

_JOB_NAMESPACE = uuid5(
    NAMESPACE_URL,
    "https://gis-data-agent.local/chongqing-data-package-reconciliation-job/v1",
)

JobStatus = Literal[
    "queued",
    "running",
    "cancel_requested",
    "cancelled",
    "succeeded",
    "failed",
]
JobPhase = Literal[
    "queued",
    "planning",
    "applying",
    "finalizing",
    "completed",
    "cancelled",
    "failed",
]


class ChongqingDataPackageReconciliationJobError(RuntimeError):
    code = "chongqing_data_package_reconciliation_job_error"


class ChongqingDataPackageReconciliationJobConfigurationError(
    ChongqingDataPackageReconciliationJobError
):
    code = "chongqing_data_package_reconciliation_job_configuration_error"


class ChongqingDataPackageReconciliationJobConflictError(
    ChongqingDataPackageReconciliationJobError
):
    code = "chongqing_data_package_reconciliation_job_conflict"


class ChongqingDataPackageReconciliationJobForbiddenError(
    ChongqingDataPackageReconciliationJobError
):
    code = "chongqing_data_package_reconciliation_job_forbidden"


class ChongqingDataPackageReconciliationJobNotFoundError(
    ChongqingDataPackageReconciliationJobError
):
    code = "chongqing_data_package_reconciliation_job_not_found"


class ChongqingDataPackageReconciliationJobValidationError(
    ChongqingDataPackageReconciliationJobError
):
    code = "chongqing_data_package_reconciliation_job_validation_error"


def _aware_utc(value: datetime | None, name: str) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


class ChongqingDataPackageReconciliationJobQuery(FrozenContract):
    job_id: UUID


class ChongqingDataPackageReconciliationJobCancelRequest(FrozenContract):
    schema_id: Literal[
        "gda.chongqing-data-package-reconciliation-job-cancel-request.v1"
    ] = "gda.chongqing-data-package-reconciliation-job-cancel-request.v1"
    job_id: UUID
    requested_by: str = Field(
        min_length=3,
        max_length=512,
        pattern=r"^(human|agent|workload):[^\s]{1,128}$",
    )
    reason: str = Field(min_length=3, max_length=1024)

    @field_validator("reason")
    @classmethod
    def _trim_reason(cls, value: str) -> str:
        return value.strip()


class ChongqingDataPackageReconciliationJob(FrozenContract):
    schema_id: Literal["gda.chongqing-data-package-reconciliation-job.v1"] = (
        "gda.chongqing-data-package-reconciliation-job.v1"
    )
    tenant_id: TenantId
    job_id: UUID
    idempotency_key: str
    request_sha256: Sha256
    status: JobStatus
    phase: JobPhase
    phase_detail: str
    phase_completed: int = Field(ge=0)
    phase_total: int = Field(ge=0)
    progress_percent: int = Field(ge=0, le=100)
    attempt_count: int = Field(ge=0)
    max_attempts: int = Field(ge=1, le=100)
    submitted_by: str
    submitted_at: datetime
    started_at: datetime | None = None
    updated_at: datetime
    completed_at: datetime | None = None
    lease_expires_at: datetime | None = None
    cancel_requested_by: str | None = None
    cancel_reason: str | None = None
    cancel_requested_at: datetime | None = None
    result: ChongqingDataPackageReconciliationResponse | None = None
    error_code: str | None = None
    error_message: str | None = None
    cancellation_mode: Literal[
        "cooperative_between_atomic_batches_no_rollback"
    ] = "cooperative_between_atomic_batches_no_rollback"
    technical_baseline_status: Literal["technical_baseline_unreviewed"] = (
        "technical_baseline_unreviewed"
    )
    decision_status: Literal[
        "assisted_precheck_not_for_production_decision"
    ] = "assisted_precheck_not_for_production_decision"

    @field_validator(
        "submitted_at",
        "started_at",
        "updated_at",
        "completed_at",
        "lease_expires_at",
        "cancel_requested_at",
    )
    @classmethod
    def _times(cls, value: datetime | None, info) -> datetime | None:
        return _aware_utc(value, info.field_name)

    @model_validator(mode="after")
    def _consistent_state(self) -> ChongqingDataPackageReconciliationJob:
        terminal = self.status in {"cancelled", "succeeded", "failed"}
        if terminal != (self.completed_at is not None):
            raise ValueError("terminal job state and completed_at are inconsistent")
        if self.status == "succeeded":
            if self.result is None or self.phase != "completed":
                raise ValueError("succeeded job must expose its completed result")
            if self.progress_percent != 100:
                raise ValueError("succeeded job progress must be 100")
        elif self.result is not None:
            raise ValueError("only a succeeded job may expose a result")
        if self.status == "failed" and not (self.error_code and self.error_message):
            raise ValueError("failed job must expose a bounded error")
        if self.status != "failed" and self.phase == "failed":
            raise ValueError("failed phase requires failed status")
        cancel_fields = (
            self.cancel_requested_by,
            self.cancel_reason,
            self.cancel_requested_at,
        )
        if self.status in {"cancel_requested", "cancelled"} and any(
            item is None for item in cancel_fields
        ):
            raise ValueError("cancelled job must preserve cancellation evidence")
        if self.phase_completed > self.phase_total and self.phase_total != 0:
            raise ValueError("phase progress exceeds its total")
        return self


class _ClaimedJob(FrozenContract):
    job: ChongqingDataPackageReconciliationJob
    request: ChongqingDataPackageReconciliationRequest


def reconciliation_job_id(
    request: ChongqingDataPackageReconciliationRequest,
) -> UUID:
    return uuid5(_JOB_NAMESPACE, f"{request.tenant_id}:{request.idempotency_key}")


def _sqlstate(exc: DBAPIError) -> str | None:
    original = getattr(exc, "orig", None)
    return getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)


def _json_value(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


class ChongqingDataPackageReconciliationJobRepository:
    """Tenant-scoped job queue with lease recovery and cooperative cancellation."""

    def __init__(self, engine: Any = None):
        self._engine = engine

    def _get_engine(self):
        engine = self._engine or get_engine()
        if engine is None or engine.dialect.name != "postgresql":
            raise ChongqingDataPackageReconciliationJobConfigurationError(
                "asynchronous reconciliation jobs require PostgreSQL"
            )
        return engine

    @contextmanager
    def _transaction(self, tenant_id: str) -> Iterator[Any]:
        try:
            with self._get_engine().connect() as connection:
                with connection.begin():
                    try:
                        connection.exec_driver_sql(
                            f'SET LOCAL ROLE "{GATEWAY_DATABASE_ROLE}"'
                        )
                    except DBAPIError as exc:
                        raise ChongqingDataPackageReconciliationJobConfigurationError(
                            "database login is not a member of the platform gateway role"
                        ) from exc
                    connection.execute(
                        text("SELECT set_config('app.current_tenant', :tenant, true)"),
                        {"tenant": tenant_id},
                    )
                    yield connection
        except ChongqingDataPackageReconciliationJobError:
            raise
        except DBAPIError as exc:
            state = _sqlstate(exc)
            if state in {"23505", "40001", "55000"}:
                raise ChongqingDataPackageReconciliationJobConflictError(
                    "reconciliation job state changed concurrently"
                ) from exc
            if state == "42501":
                raise ChongqingDataPackageReconciliationJobForbiddenError(
                    "reconciliation job tenant or role was denied"
                ) from exc
            if state in {"22023", "23514"}:
                raise ChongqingDataPackageReconciliationJobValidationError(
                    "reconciliation job payload or transition is invalid"
                ) from exc
            if state == "P0002":
                raise ChongqingDataPackageReconciliationJobNotFoundError(
                    "reconciliation job was not found"
                ) from exc
            raise ChongqingDataPackageReconciliationJobConfigurationError(
                "reconciliation job repository is unavailable"
            ) from exc

    @staticmethod
    def _job_from_row(row: Any) -> ChongqingDataPackageReconciliationJob:
        value = dict(row)
        response = _json_value(value.pop("response_document", None))
        value.pop("request_document", None)
        value.pop("claimed_by", None)
        value.pop("available_at", None)
        value["result"] = response
        try:
            return ChongqingDataPackageReconciliationJob.model_validate(value)
        except (TypeError, ValidationError) as exc:
            raise ChongqingDataPackageReconciliationJobValidationError(
                "stored reconciliation job is invalid"
            ) from exc

    def enqueue(
        self,
        request: ChongqingDataPackageReconciliationRequest,
    ) -> ChongqingDataPackageReconciliationJob:
        with self._transaction(request.tenant_id) as connection:
            row = connection.execute(
                text(
                    """
                    SELECT *
                    FROM gda_control.enqueue_chongqing_data_package_reconciliation_job(
                        :tenant_id, :job_id, :idempotency_key, :request_sha256,
                        :submitted_by, CAST(:request_document AS jsonb)
                    )
                    """
                ),
                {
                    "tenant_id": request.tenant_id,
                    "job_id": reconciliation_job_id(request),
                    "idempotency_key": request.idempotency_key,
                    "request_sha256": request.request_sha256,
                    "submitted_by": request.recorded_by,
                    "request_document": json.dumps(request.model_dump(mode="json")),
                },
            ).mappings().one()
        return self._job_from_row(row)

    def get(
        self,
        query: ChongqingDataPackageReconciliationJobQuery,
        *,
        tenant_id: str,
    ) -> ChongqingDataPackageReconciliationJob:
        with self._transaction(tenant_id) as connection:
            row = connection.execute(
                text(
                    """
                    SELECT *
                    FROM gda_control.chongqing_data_package_reconciliation_job
                    WHERE tenant_id = :tenant_id AND job_id = :job_id
                    """
                ),
                {"tenant_id": tenant_id, "job_id": query.job_id},
            ).mappings().one_or_none()
        if row is None:
            raise ChongqingDataPackageReconciliationJobNotFoundError(
                "reconciliation job was not found"
            )
        return self._job_from_row(row)

    def request_cancel(
        self,
        request: ChongqingDataPackageReconciliationJobCancelRequest,
        *,
        tenant_id: str,
    ) -> ChongqingDataPackageReconciliationJob:
        with self._transaction(tenant_id) as connection:
            row = connection.execute(
                text(
                    """
                    SELECT *
                    FROM gda_control.cancel_chongqing_data_package_reconciliation_job(
                        :tenant_id, :job_id, :requested_by, :reason
                    )
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    **request.model_dump(mode="python", exclude={"schema_id"}),
                },
            ).mappings().one()
        return self._job_from_row(row)

    def claim(
        self,
        tenant_id: str,
        worker_id: str,
        *,
        limit: int = 1,
        lease_seconds: int = 600,
    ) -> list[_ClaimedJob]:
        with self._transaction(tenant_id) as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT *
                    FROM gda_control.claim_chongqing_data_package_reconciliation_jobs(
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
        claimed: list[_ClaimedJob] = []
        for row in rows:
            document = _json_value(row["request_document"])
            try:
                request = ChongqingDataPackageReconciliationRequest.model_validate(document)
            except (TypeError, ValidationError) as exc:
                raise ChongqingDataPackageReconciliationJobValidationError(
                    "claimed reconciliation request is invalid"
                ) from exc
            claimed.append(_ClaimedJob(job=self._job_from_row(row), request=request))
        return claimed

    def checkpoint(
        self,
        job: ChongqingDataPackageReconciliationJob,
        worker_id: str,
        *,
        phase_detail: str,
        phase_completed: int,
        phase_total: int,
        lease_seconds: int,
    ) -> ChongqingDataPackageReconciliationJob:
        with self._transaction(job.tenant_id) as connection:
            row = connection.execute(
                text(
                    """
                    SELECT *
                    FROM gda_control.checkpoint_chongqing_data_package_reconciliation_job(
                        :tenant_id, :job_id, :worker_id, :phase_detail,
                        :phase_completed, :phase_total, :lease_seconds
                    )
                    """
                ),
                {
                    "tenant_id": job.tenant_id,
                    "job_id": job.job_id,
                    "worker_id": worker_id,
                    "phase_detail": phase_detail,
                    "phase_completed": phase_completed,
                    "phase_total": phase_total,
                    "lease_seconds": lease_seconds,
                },
            ).mappings().one()
        return self._job_from_row(row)

    def succeed(
        self,
        job: ChongqingDataPackageReconciliationJob,
        worker_id: str,
        result: ChongqingDataPackageReconciliationResponse,
    ) -> ChongqingDataPackageReconciliationJob:
        with self._transaction(job.tenant_id) as connection:
            row = connection.execute(
                text(
                    """
                    SELECT *
                    FROM gda_control.complete_chongqing_data_package_reconciliation_job(
                        :tenant_id, :job_id, :worker_id,
                        CAST(:response_document AS jsonb)
                    )
                    """
                ),
                {
                    "tenant_id": job.tenant_id,
                    "job_id": job.job_id,
                    "worker_id": worker_id,
                    "response_document": json.dumps(result.model_dump(mode="json")),
                },
            ).mappings().one()
        return self._job_from_row(row)

    def mark_cancelled(
        self,
        job: ChongqingDataPackageReconciliationJob,
        worker_id: str,
    ) -> ChongqingDataPackageReconciliationJob:
        with self._transaction(job.tenant_id) as connection:
            row = connection.execute(
                text(
                    """
                    SELECT *
                    FROM gda_control.finish_chongqing_data_package_reconciliation_cancel(
                        :tenant_id, :job_id, :worker_id
                    )
                    """
                ),
                {
                    "tenant_id": job.tenant_id,
                    "job_id": job.job_id,
                    "worker_id": worker_id,
                },
            ).mappings().one()
        return self._job_from_row(row)

    def fail(
        self,
        job: ChongqingDataPackageReconciliationJob,
        worker_id: str,
        *,
        error_code: str,
        error_message: str,
        retry_delay_seconds: int = 30,
    ) -> ChongqingDataPackageReconciliationJob:
        with self._transaction(job.tenant_id) as connection:
            row = connection.execute(
                text(
                    """
                    SELECT *
                    FROM gda_control.fail_chongqing_data_package_reconciliation_job(
                        :tenant_id, :job_id, :worker_id, :error_code,
                        :error_message, :retry_delay_seconds
                    )
                    """
                ),
                {
                    "tenant_id": job.tenant_id,
                    "job_id": job.job_id,
                    "worker_id": worker_id,
                    "error_code": error_code,
                    "error_message": error_message,
                    "retry_delay_seconds": retry_delay_seconds,
                },
            ).mappings().one()
        return self._job_from_row(row)


class ChongqingDataPackageReconciliationJobWorker:
    """Claim and execute jobs; expired leases make interrupted jobs reclaimable."""

    def __init__(
        self,
        *,
        repository: Any = None,
        executor: Callable[..., ChongqingDataPackageReconciliationResponse] | None = None,
    ) -> None:
        self.repository = repository or ChongqingDataPackageReconciliationJobRepository()
        self.executor = executor or execute_chongqing_data_package_reconciliation

    def run_once(
        self,
        tenant_id: str,
        worker_id: str,
        *,
        limit: int = 1,
        lease_seconds: int = 600,
        retry_delay_seconds: int = 30,
    ) -> tuple[ChongqingDataPackageReconciliationJob, ...]:
        outcomes: list[ChongqingDataPackageReconciliationJob] = []
        claims = self.repository.claim(
            tenant_id,
            worker_id,
            limit=limit,
            lease_seconds=lease_seconds,
        )
        for claim in claims:
            current = claim.job
            progress_state = {"detail": "planning", "completed": 0, "total": 1}

            def checkpoint(
                detail: str,
                completed: int,
                total: int,
                _progress=progress_state,
            ) -> None:
                nonlocal current
                _progress.update(
                    {"detail": detail, "completed": completed, "total": total}
                )
                current = self.repository.checkpoint(
                    current,
                    worker_id,
                    phase_detail=detail,
                    phase_completed=completed,
                    phase_total=total,
                    lease_seconds=lease_seconds,
                )
                if current.status == "cancel_requested":
                    raise ChongqingDataPackageReconciliationCancelledError(
                        "asynchronous reconciliation cancellation was requested"
                    )

            def cancel_check(_progress=progress_state) -> None:
                checkpoint(
                    str(_progress["detail"]),
                    int(_progress["completed"]),
                    int(_progress["total"]),
                )

            try:
                result = self.executor(
                    claim.request,
                    progress_callback=checkpoint,
                    cancel_check=cancel_check,
                )
            except ChongqingDataPackageReconciliationCancelledError:
                try:
                    outcomes.append(self.repository.mark_cancelled(current, worker_id))
                except ChongqingDataPackageReconciliationJobConflictError:
                    continue
            except ChongqingDataPackageReconciliationJobConflictError:
                # A lease/claim conflict means another worker owns the job now.
                # The stale worker must not write a failure over that claim.
                continue
            except Exception as exc:
                code = str(getattr(exc, "code", "reconciliation_execution_failed"))
                code = re.sub(r"[^a-z0-9_]", "_", code.lower()).strip("_")
                if not code or not code[0].isalpha():
                    code = "reconciliation_execution_failed"
                try:
                    outcomes.append(
                        self.repository.fail(
                            current,
                            worker_id,
                            error_code=code[:128],
                            error_message=str(exc)[:2000] or type(exc).__name__,
                            retry_delay_seconds=retry_delay_seconds,
                        )
                    )
                except ChongqingDataPackageReconciliationJobConflictError:
                    continue
            else:
                try:
                    outcomes.append(self.repository.succeed(current, worker_id, result))
                except ChongqingDataPackageReconciliationJobConflictError:
                    continue
        return tuple(outcomes)


def submit_chongqing_data_package_reconciliation_job(
    request: ChongqingDataPackageReconciliationRequest,
    *,
    repository: Any = None,
) -> ChongqingDataPackageReconciliationJob:
    return (repository or ChongqingDataPackageReconciliationJobRepository()).enqueue(
        request
    )


def get_chongqing_data_package_reconciliation_job(
    query: ChongqingDataPackageReconciliationJobQuery,
    *,
    tenant_id: str,
    repository: Any = None,
) -> ChongqingDataPackageReconciliationJob:
    return (repository or ChongqingDataPackageReconciliationJobRepository()).get(
        query,
        tenant_id=tenant_id,
    )


def cancel_chongqing_data_package_reconciliation_job(
    request: ChongqingDataPackageReconciliationJobCancelRequest,
    *,
    tenant_id: str,
    repository: Any = None,
) -> ChongqingDataPackageReconciliationJob:
    return (
        repository or ChongqingDataPackageReconciliationJobRepository()
    ).request_cancel(
        request,
        tenant_id=tenant_id,
    )


__all__ = [
    "ChongqingDataPackageReconciliationJob",
    "ChongqingDataPackageReconciliationJobCancelRequest",
    "ChongqingDataPackageReconciliationJobConfigurationError",
    "ChongqingDataPackageReconciliationJobConflictError",
    "ChongqingDataPackageReconciliationJobError",
    "ChongqingDataPackageReconciliationJobForbiddenError",
    "ChongqingDataPackageReconciliationJobNotFoundError",
    "ChongqingDataPackageReconciliationJobQuery",
    "ChongqingDataPackageReconciliationJobRepository",
    "ChongqingDataPackageReconciliationJobValidationError",
    "ChongqingDataPackageReconciliationJobWorker",
    "cancel_chongqing_data_package_reconciliation_job",
    "get_chongqing_data_package_reconciliation_job",
    "reconciliation_job_id",
    "submit_chongqing_data_package_reconciliation_job",
]

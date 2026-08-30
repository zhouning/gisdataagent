"""Durable retry-budget authority for provider-bound AgentOps activities.

The retry budget is keyed by a ToolCall/provider operation family, not by a
worker process or an individual activity attempt.  A worker replacement can
therefore replay the same request without consuming another retry slot, while
an explicitly scheduled new attempt consumes one slot exactly once.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from .agentops_temporal_contracts import TemporalActivityRequest, temporal_contract_fingerprint
from .platform_contracts import canonical_json_bytes
from .temporal_entity_authority import GATEWAY_DATABASE_ROLE

RETRY_BUDGET_MIGRATION = (
    Path(__file__).resolve().parent
    / "migrations"
    / "248_agentops_specialist_retry_budget_authority.sql"
)
_TENANT_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_WORKER_RE = re.compile(r"^(workload|agent):[^\s]{1,128}$")
_KEY_RE = re.compile(r"^\S{1,512}$")


class SpecialistRetryBudgetError(RuntimeError):
    """Retry-budget authority rejected or could not persist an admission."""


class SpecialistRetryBudgetAuthority(Protocol):
    def admit(
        self,
        request: TemporalActivityRequest,
        *,
        operation_key: str,
        max_attempts: int,
        worker_id: str,
    ) -> SpecialistRetryAdmission: ...

    def observe(
        self, *, tenant_id: str, operation_key: str
    ) -> SpecialistRetryBudgetObservation | None: ...


@dataclass(frozen=True)
class SpecialistRetryAdmission:
    tenant_id: str
    operation_key: str
    request_sha256: str
    attempt_no: int
    max_attempts: int
    worker_id: str
    admitted: bool
    reason: str
    event_sha256: str

    @classmethod
    def build(
        cls,
        request: TemporalActivityRequest,
        *,
        operation_key: str,
        max_attempts: int,
        worker_id: str,
        admitted: bool,
        reason: str,
    ) -> SpecialistRetryAdmission:
        values = {
            "tenant_id": request.tenant_id,
            "operation_key": operation_key,
            "request_sha256": request.request_sha256,
            "attempt_no": request.attempt_no,
            "max_attempts": max_attempts,
            "worker_id": worker_id,
            "admitted": admitted,
            "reason": reason,
        }
        event_sha256 = temporal_contract_fingerprint(
            "gda.specialist_retry_admission.v1", values, "event_sha256"
        )
        return cls(event_sha256=event_sha256, **values)


@dataclass(frozen=True)
class SpecialistRetryBudgetObservation:
    tenant_id: str
    operation_key: str
    max_attempts: int
    attempt_count: int
    status: str
    admissions: tuple[SpecialistRetryAdmission, ...]


def _validate_identity(tenant_id: str, operation_key: str, worker_id: str) -> None:
    if _TENANT_RE.fullmatch(str(tenant_id or "")) is None:
        raise SpecialistRetryBudgetError("retry budget tenant_id is invalid")
    if _KEY_RE.fullmatch(str(operation_key or "")) is None:
        raise SpecialistRetryBudgetError("retry budget operation_key is invalid")
    if _WORKER_RE.fullmatch(str(worker_id or "")) is None:
        raise SpecialistRetryBudgetError("retry budget worker_id is invalid")


def provider_operation_family_key(request: TemporalActivityRequest) -> str:
    """Return a stable key shared by all attempts and worker processes."""

    provider = request.provider_spec.provider_ref if request.provider_spec else "unbound"
    return f"{provider}://{request.run_id}/{request.tool_call_id}"


def _admission_fingerprint_payload(admission: SpecialistRetryAdmission) -> str:
    values = {
        key: value
        for key, value in admission.__dict__.items()
        if key != "event_sha256"
    }
    return canonical_json_bytes(
        {"schema": "gda.specialist_retry_admission.v1", "data": values}
    ).decode("ascii")


class InMemorySpecialistRetryBudgetAuthority:
    """Deterministic authority for contract tests and disposable rehearsals."""

    def __init__(self) -> None:
        self._budgets: dict[tuple[str, str], dict[str, Any]] = {}
        self._events: dict[tuple[str, str], list[SpecialistRetryAdmission]] = {}

    def admit(
        self,
        request: TemporalActivityRequest,
        *,
        operation_key: str,
        max_attempts: int,
        worker_id: str,
    ) -> SpecialistRetryAdmission:
        _validate_identity(request.tenant_id, operation_key, worker_id)
        if not 1 <= max_attempts <= 100:
            raise SpecialistRetryBudgetError("retry budget max_attempts must be 1..100")
        if request.attempt_no < 1:
            raise SpecialistRetryBudgetError("retry budget attempt_no must be positive")
        key = (request.tenant_id, operation_key)
        budget = self._budgets.setdefault(
            key, {"max_attempts": max_attempts, "attempt_count": 0, "status": "active"}
        )
        if budget["max_attempts"] != max_attempts:
            raise SpecialistRetryBudgetError(
                "retry budget max_attempts differs from existing family"
            )
        events = self._events.setdefault(key, [])
        for existing in events:
            if (
                existing.request_sha256 == request.request_sha256
                and existing.attempt_no == request.attempt_no
            ):
                return existing
        attempt_number = budget["attempt_count"] + 1
        admitted = budget["status"] == "active" and attempt_number <= max_attempts
        reason = "budget_admitted" if admitted else "retry_budget_exhausted"
        if admitted:
            budget["attempt_count"] = attempt_number
            if attempt_number >= max_attempts:
                budget["status"] = "exhausted"
        admission = SpecialistRetryAdmission.build(
            request,
            operation_key=operation_key,
            max_attempts=max_attempts,
            worker_id=worker_id,
            admitted=admitted,
            reason=reason,
        )
        events.append(admission)
        return admission

    def observe(
        self, *, tenant_id: str, operation_key: str
    ) -> SpecialistRetryBudgetObservation | None:
        _validate_identity(tenant_id, operation_key, "workload:retry-budget-observer")
        key = (tenant_id, operation_key)
        budget = self._budgets.get(key)
        if budget is None:
            return None
        return SpecialistRetryBudgetObservation(
            tenant_id=tenant_id,
            operation_key=operation_key,
            max_attempts=budget["max_attempts"],
            attempt_count=budget["attempt_count"],
            status=budget["status"],
            admissions=tuple(self._events.get(key, ())),
        )


class PostgresSpecialistRetryBudgetAuthority:
    """Tenant-scoped PostgreSQL retry-budget authority."""

    def __init__(self, tenant_id: str, engine: Any, *, recorded_by: str) -> None:
        self.tenant_id = tenant_id
        self._engine = engine
        self.recorded_by = recorded_by
        _validate_identity(tenant_id, "provider://retry-budget-init", recorded_by)

    @contextmanager
    def _transaction(self) -> Iterator[Any]:
        try:
            with self._engine.connect() as connection:
                with connection.begin():
                    connection.exec_driver_sql(f'SET LOCAL ROLE "{GATEWAY_DATABASE_ROLE}"')
                    connection.execute(
                        text("SELECT set_config('app.current_tenant', :tenant, true)"),
                        {"tenant": self.tenant_id},
                    )
                    yield connection
        except DBAPIError as exc:
            raise SpecialistRetryBudgetError("retry budget PostgreSQL operation failed") from exc
        except SQLAlchemyError as exc:
            raise SpecialistRetryBudgetError("retry budget PostgreSQL operation failed") from exc

    @staticmethod
    def _admission(row: Any) -> SpecialistRetryAdmission:
        try:
            values = dict(row)
            event = values.pop("event_document", None)
            if event is not None:
                if isinstance(event, str):
                    event = json.loads(event)
                expected_hash = temporal_contract_fingerprint(
                    "gda.specialist_retry_admission.v1",
                    event,
                    "event_sha256",
                )
                if expected_hash != event.get("event_sha256"):
                    raise SpecialistRetryBudgetError("stored retry admission hash is invalid")
                return SpecialistRetryAdmission(**event)
            return SpecialistRetryAdmission(**values)
        except Exception as exc:
            raise SpecialistRetryBudgetError("stored retry admission is invalid") from exc

    def admit(
        self,
        request: TemporalActivityRequest,
        *,
        operation_key: str,
        max_attempts: int,
        worker_id: str,
    ) -> SpecialistRetryAdmission:
        _validate_identity(request.tenant_id, operation_key, worker_id)
        if request.tenant_id != self.tenant_id:
            raise SpecialistRetryBudgetError("retry budget tenant differs from authority tenant")
        if not 1 <= max_attempts <= 100:
            raise SpecialistRetryBudgetError("retry budget max_attempts must be 1..100")
        if request.attempt_no < 1:
            raise SpecialistRetryBudgetError("retry budget attempt_no must be positive")
        admitted_candidate = SpecialistRetryAdmission.build(
            request,
            operation_key=operation_key,
            max_attempts=max_attempts,
            worker_id=worker_id,
            admitted=True,
            reason="budget_admitted",
        )
        denied_candidate = SpecialistRetryAdmission.build(
            request,
            operation_key=operation_key,
            max_attempts=max_attempts,
            worker_id=worker_id,
            admitted=False,
            reason="retry_budget_exhausted",
        )
        with self._transaction() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT event_document, created
                    FROM gda_control.record_agentops_specialist_retry_admission(
                        :tenant_id, :operation_key,
                        CAST(:admitted_document AS jsonb), :admitted_fingerprint_payload,
                        CAST(:denied_document AS jsonb), :denied_fingerprint_payload,
                        :max_attempts, :recorded_by
                    )
                    """
                ),
                {
                    "tenant_id": self.tenant_id,
                    "operation_key": operation_key,
                    "admitted_document": json.dumps(
                        admitted_candidate.__dict__, sort_keys=True
                    ),
                    "admitted_fingerprint_payload": _admission_fingerprint_payload(
                        admitted_candidate
                    ),
                    "denied_document": json.dumps(
                        denied_candidate.__dict__, sort_keys=True
                    ),
                    "denied_fingerprint_payload": _admission_fingerprint_payload(
                        denied_candidate
                    ),
                    "max_attempts": max_attempts,
                    "recorded_by": self.recorded_by,
                },
            ).mappings().one()
        try:
            return self._admission({"event_document": row["event_document"]})
        except (TypeError, json.JSONDecodeError, KeyError) as exc:
            raise SpecialistRetryBudgetError("retry budget returned invalid admission") from exc

    def observe(
        self, *, tenant_id: str, operation_key: str
    ) -> SpecialistRetryBudgetObservation | None:
        _validate_identity(tenant_id, operation_key, "workload:retry-budget-observer")
        if tenant_id != self.tenant_id:
            raise SpecialistRetryBudgetError("retry budget tenant differs from authority tenant")
        with self._transaction() as connection:
            budget = connection.execute(
                text(
                    """
                    SELECT max_attempts, attempt_count, status
                    FROM gda_control.agentops_specialist_retry_budget
                    WHERE tenant_id = :tenant_id AND operation_key = :operation_key
                    """
                ),
                {"tenant_id": tenant_id, "operation_key": operation_key},
            ).mappings().one_or_none()
            if budget is None:
                return None
            rows = connection.execute(
                text(
                    """
                    SELECT event_document
                    FROM gda_control.agentops_specialist_retry_admission_history
                    WHERE tenant_id = :tenant_id AND operation_key = :operation_key
                    ORDER BY event_sequence
                    """
                ),
                {"tenant_id": tenant_id, "operation_key": operation_key},
            ).mappings().all()
        admissions = tuple(
            self._admission({"event_document": row["event_document"]}) for row in rows
        )
        return SpecialistRetryBudgetObservation(
            tenant_id=tenant_id,
            operation_key=operation_key,
            max_attempts=int(budget["max_attempts"]),
            attempt_count=int(budget["attempt_count"]),
            status=str(budget["status"]),
            admissions=admissions,
        )


__all__ = [
    "RETRY_BUDGET_MIGRATION",
    "InMemorySpecialistRetryBudgetAuthority",
    "PostgresSpecialistRetryBudgetAuthority",
    "SpecialistRetryAdmission",
    "SpecialistRetryBudgetAuthority",
    "SpecialistRetryBudgetError",
    "SpecialistRetryBudgetObservation",
    "provider_operation_family_key",
]

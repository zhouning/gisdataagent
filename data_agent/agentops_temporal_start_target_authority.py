"""Durable registration and discovery authority for Temporal start receipts.

The authority deliberately stores the complete GDA start request, provider
receipt and start reconciliation evidence.  It does not copy Temporal history
or execute workflows; those remain provider responsibilities.  Claim state is
lease based so a terminated discovery worker can be replaced without losing a
registered start or allowing a stale worker to settle it.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import Field, model_validator
from sqlalchemy import text

from .agentops_temporal_adapter import (
    TEMPORAL_START_RECONCILIATION_SCHEMA,
    TEMPORAL_START_REQUEST_SCHEMA,
    TEMPORAL_START_RESULT_SCHEMA,
    TemporalProviderStartResult,
    TemporalProviderStartStatus,
    TemporalProviderWorkflowInputObservation,
    TemporalStartReconciliation,
    TemporalStartReconciliationVerdict,
    TemporalWorkflowStartRequest,
)
from .agentops_temporal_checkpoint_authority import (
    AgentOpsTemporalCheckpointAuthorityConfigurationError,
    PostgresAgentOpsTemporalCheckpointAuthority,
)
from .agentops_temporal_contracts import temporal_contract_fingerprint
from .platform_contracts import FrozenContract, NonEmptyText, Sha256, TenantId, canonical_json_bytes

AGENTOPS_TEMPORAL_START_TARGET_AUTHORITY_MIGRATION = (
    Path(__file__).resolve().parent
    / "migrations"
    / "242_agentops_temporal_start_target_authority.sql"
)


class AgentOpsTemporalStartTargetStatus(StrEnum):
    PENDING_START_RECONCILIATION = "pending_start_reconciliation"
    READY = "ready"
    CLAIMED = "claimed"
    COMPLETED = "completed"
    FAILED = "failed"


def _json(value: Any) -> str:
    return canonical_json_bytes(value).decode("ascii")


def _fingerprint_payload(schema_id: str, document: dict[str, Any], field: str) -> str:
    payload = dict(document)
    payload.pop(field, None)
    return _json({"schema": schema_id, "data": payload})


class TemporalStartTarget(FrozenContract):
    """One registered Temporal start and its recoverable discovery state."""

    schema_id: str = "gda.temporal_start_target.v1"
    tenant_id: TenantId
    target_id: UUID
    namespace_ref: NonEmptyText
    workflow_id: NonEmptyText
    workflow_type: NonEmptyText
    task_queue_ref: NonEmptyText
    idempotency_key: NonEmptyText
    start_request_sha256: Sha256
    start_request_document: dict[str, Any]
    start_result_sha256: Sha256
    start_result_document: dict[str, Any]
    start_reconciliation_sha256: Sha256 | None = None
    start_reconciliation_document: dict[str, Any] | None = None
    provider_run_id: NonEmptyText | None = None
    status: str
    attempt_count: int = Field(ge=0)
    available_at: datetime
    claimed_by: NonEmptyText | None = None
    claimed_until: datetime | None = None
    last_error: str | None = None
    registered_by: NonEmptyText
    registered_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None

    @model_validator(mode="after")
    def _consistent_target(self) -> TemporalStartTarget:
        request = TemporalWorkflowStartRequest.model_validate(self.start_request_document)
        result = TemporalProviderStartResult.model_validate(self.start_result_document)
        if (
            request.tenant_id != self.tenant_id
            or request.namespace_ref != self.namespace_ref
            or request.workflow_id != self.workflow_id
            or request.workflow_type != self.workflow_type
            or request.task_queue_ref != self.task_queue_ref
            or request.payload_sha256 != self.start_request_sha256
            or result.tenant_id != self.tenant_id
            or result.namespace_ref != self.namespace_ref
            or result.workflow_id != self.workflow_id
            or result.result_sha256 != self.start_result_sha256
            or request.payload.get("identity", {}).get("idempotency_key")
                != self.idempotency_key
        ):
            raise ValueError("Temporal start target evidence correlation differs")
        if result.status is not TemporalProviderStartStatus.UNKNOWN and (
            self.start_reconciliation_document is None
            or self.start_reconciliation_sha256 is None
        ):
            raise ValueError("known Temporal start target requires reconciliation evidence")
        expected_run = result.provider_run_id
        if self.provider_run_id != expected_run:
            if result.status is not TemporalProviderStartStatus.UNKNOWN:
                raise ValueError("known Temporal start target run differs from receipt")
            if self.provider_run_id is not None and expected_run is not None:
                raise ValueError("Temporal start target provider run differs")
        if result.status is TemporalProviderStartStatus.UNKNOWN:
            pending = self.start_reconciliation_document is None or (
                self.start_reconciliation_document.get("verdict") ==
                TemporalStartReconciliationVerdict.UNKNOWN_PENDING.value
            )
            if pending and self.provider_run_id is not None:
                raise ValueError("unknown pending Temporal start cannot claim provider run")
        if self.start_reconciliation_document is not None:
            reconciliation = TemporalStartReconciliation.model_validate(
                self.start_reconciliation_document
            )
            if (
                reconciliation.reconciliation_sha256 != self.start_reconciliation_sha256
                or reconciliation.tenant_id != self.tenant_id
                or reconciliation.namespace_ref != self.namespace_ref
                or reconciliation.workflow_id != self.workflow_id
                or reconciliation.provider_status is not result.status
                or reconciliation.request_sha256 != self.start_request_sha256
                or reconciliation.provider_receipt_ref
                    != result.provider_receipt_ref
                or reconciliation.provider_run_id != self.provider_run_id
            ):
                raise ValueError("Temporal start reconciliation correlation differs")
        if self.status not in set(AgentOpsTemporalStartTargetStatus):
            raise ValueError("Temporal start target status is invalid")
        if (self.claimed_by is None) != (self.claimed_until is None):
            raise ValueError("Temporal start target claim fields must be paired")
        if self.status == AgentOpsTemporalStartTargetStatus.CLAIMED and self.claimed_by is None:
            raise ValueError("claimed Temporal start target requires a worker")
        if self.status in {
            AgentOpsTemporalStartTargetStatus.READY,
            AgentOpsTemporalStartTargetStatus.COMPLETED,
        } and (self.provider_run_id is None or self.start_reconciliation_document is None):
            raise ValueError("ready Temporal start target requires reconciliation evidence")
        if self.status in {
            AgentOpsTemporalStartTargetStatus.READY,
            AgentOpsTemporalStartTargetStatus.COMPLETED,
        } and self.start_reconciliation_document.get("verdict") == (
            TemporalStartReconciliationVerdict.UNKNOWN_PENDING.value
        ):
            raise ValueError("ready Temporal start target cannot have pending reconciliation")
        if self.status == AgentOpsTemporalStartTargetStatus.COMPLETED and self.completed_at is None:
            raise ValueError("completed Temporal start target requires completed_at")
        if self.status == AgentOpsTemporalStartTargetStatus.FAILED:
            if self.completed_at is None or not (self.last_error or "").strip():
                raise ValueError("failed Temporal start target requires an error")
        return self


def build_unknown_start_reconciliation(
    target: TemporalStartTarget,
    observation: TemporalProviderWorkflowInputObservation,
) -> TemporalStartReconciliation:
    """Turn a provider input observation into matched evidence for an unknown start."""

    if target.start_result_document.get("status") != TemporalProviderStartStatus.UNKNOWN.value:
        raise ValueError("only unknown starts can be attached from input observation")
    if target.provider_run_id is not None:
        raise ValueError("unknown Temporal start already has a provider run")
    existing_reconciliation = target.start_reconciliation_document
    if existing_reconciliation is not None and existing_reconciliation.get("verdict") != (
        TemporalStartReconciliationVerdict.UNKNOWN_PENDING.value
    ):
        raise ValueError("unknown Temporal start is already reconciled")
    if (
        observation.tenant_id != target.tenant_id
        or observation.namespace_ref != target.namespace_ref
        or observation.workflow_id != target.workflow_id
        or observation.observed_input_sha256 != target.start_request_sha256
    ):
        raise ValueError("Temporal input observation does not match registered start")
    values: dict[str, Any] = {
        "tenant_id": target.tenant_id,
        "namespace_ref": target.namespace_ref,
        "workflow_id": target.workflow_id,
        "provider_status": TemporalProviderStartStatus.UNKNOWN,
        "verdict": TemporalStartReconciliationVerdict.ALREADY_EXISTS_MATCHED,
        "provider_run_id": observation.provider_run_id,
        "provider_receipt_ref": target.start_result_document["provider_receipt_ref"],
        "request_sha256": target.start_request_sha256,
        "observed_input_sha256": observation.observed_input_sha256,
    }
    values["reconciliation_sha256"] = temporal_contract_fingerprint(
        TEMPORAL_START_RECONCILIATION_SCHEMA, values, "reconciliation_sha256"
    )
    return TemporalStartReconciliation(**values)


class PostgresAgentOpsTemporalStartTargetAuthority:
    """PostgreSQL repository for start registration, claim and settlement."""

    def __init__(self, engine: Any = None):
        self._authority = PostgresAgentOpsTemporalCheckpointAuthority(engine)

    @staticmethod
    def _target(row: Any) -> TemporalStartTarget:
        try:
            values = dict(row)
            for field in (
                "start_request_document",
                "start_result_document",
                "start_reconciliation_document",
            ):
                value = values.get(field)
                if isinstance(value, str):
                    values[field] = json.loads(value)
            return TemporalStartTarget.model_validate(values)
        except Exception as exc:
            raise AgentOpsTemporalCheckpointAuthorityConfigurationError(
                "stored Temporal start target is invalid"
            ) from exc

    def _read(self, *, tenant_id: str, target_id: UUID | None = None,
              workflow_id: str | None = None) -> TemporalStartTarget | None:
        with self._authority._transaction(tenant_id) as connection:
            clauses = ["tenant_id = :tenant_id"]
            params: dict[str, Any] = {"tenant_id": tenant_id}
            if target_id is not None:
                clauses.append("target_id = :target_id")
                params["target_id"] = target_id
            if workflow_id is not None:
                clauses.append("workflow_id = :workflow_id")
                params["workflow_id"] = workflow_id
            row = connection.execute(
                text(
                    "SELECT * FROM gda_control.agentops_temporal_start_target "
                    "WHERE " + " AND ".join(clauses)
                ), params
            ).mappings().one_or_none()
        return None if row is None else self._target(row)

    def register_start_target(
        self,
        request: TemporalWorkflowStartRequest,
        result: TemporalProviderStartResult,
        reconciliation: TemporalStartReconciliation | None,
        *,
        registered_by: str,
        registered_at: datetime | None = None,
        available_at: datetime | None = None,
    ) -> TemporalStartTarget:
        if (
            result.tenant_id != request.tenant_id
            or result.namespace_ref != request.namespace_ref
            or result.workflow_id != request.workflow_id
        ):
            raise ValueError("Temporal start request/result identity differs")
        if reconciliation is not None and (
            reconciliation.tenant_id != request.tenant_id
            or reconciliation.namespace_ref != request.namespace_ref
            or reconciliation.workflow_id != request.workflow_id
            or reconciliation.provider_status is not result.status
        ):
            raise ValueError("Temporal start reconciliation identity differs")
        idempotency_key = request.payload.get("identity", {}).get("idempotency_key")
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise ValueError("Temporal start request requires an idempotency key")
        now = (registered_at or datetime.now(UTC)).astimezone(UTC)
        due = (available_at or now).astimezone(UTC)
        request_document = request.model_dump(mode="json")
        result_document = result.model_dump(mode="json")
        reconciliation_document = (
            reconciliation.model_dump(mode="json") if reconciliation is not None else None
        )
        with self._authority._transaction(request.tenant_id) as connection:
            row = connection.execute(
                text(
                    """
                    SELECT target_id, created
                    FROM gda_control.register_agentops_temporal_start_target(
                        :tenant_id, :namespace_ref, :workflow_id, :workflow_type,
                        :task_queue_ref, :idempotency_key,
                        CAST(:request_document AS jsonb), :request_fingerprint,
                        CAST(:result_document AS jsonb), :result_fingerprint,
                        CAST(:reconciliation_document AS jsonb), :reconciliation_fingerprint,
                        :registered_by, :registered_at, :available_at
                    )
                    """
                ),
                {
                    "tenant_id": request.tenant_id,
                    "namespace_ref": request.namespace_ref,
                    "workflow_id": request.workflow_id,
                    "workflow_type": request.workflow_type,
                    "task_queue_ref": request.task_queue_ref,
                    "idempotency_key": idempotency_key,
                    "request_document": _json(request_document),
                    "request_fingerprint": _fingerprint_payload(
                        TEMPORAL_START_REQUEST_SCHEMA, request_document, "payload_sha256"
                    ),
                    "result_document": _json(result_document),
                    "result_fingerprint": _fingerprint_payload(
                        TEMPORAL_START_RESULT_SCHEMA, result_document, "result_sha256"
                    ),
                    "reconciliation_document": (
                        None if reconciliation_document is None else _json(reconciliation_document)
                    ),
                    "reconciliation_fingerprint": (
                        None if reconciliation_document is None else _fingerprint_payload(
                            TEMPORAL_START_RECONCILIATION_SCHEMA,
                            reconciliation_document,
                            "reconciliation_sha256",
                        )
                    ),
                    "registered_by": registered_by,
                    "registered_at": now,
                    "available_at": due,
                },
            ).mappings().one()
        target = self._read(tenant_id=request.tenant_id, target_id=row["target_id"])
        if target is None:
            raise AgentOpsTemporalCheckpointAuthorityConfigurationError(
                "registered Temporal start target was not visible"
            )
        return target

    def get_target(self, *, tenant_id: str, target_id: UUID) -> TemporalStartTarget | None:
        return self._read(tenant_id=tenant_id, target_id=target_id)

    def target_for_workflow(
        self, *, tenant_id: str, workflow_id: str
    ) -> TemporalStartTarget | None:
        return self._read(tenant_id=tenant_id, workflow_id=workflow_id)

    def claim_due_targets(
        self, *, tenant_id: str, worker_id: str, namespace_ref: str | None = None,
        limit: int = 10, lease_seconds: int = 60,
    ) -> tuple[TemporalStartTarget, ...]:
        with self._authority._transaction(tenant_id) as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT * FROM gda_control.claim_agentops_temporal_start_targets(
                        :tenant_id, :namespace_ref, :worker_id, :limit, :lease_seconds
                    )
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "namespace_ref": namespace_ref,
                    "worker_id": worker_id,
                    "limit": limit,
                    "lease_seconds": lease_seconds,
                },
            ).mappings().all()
        return tuple(self._target(row) for row in rows)

    def renew_target_claim(
        self, target: TemporalStartTarget, *, worker_id: str, lease_seconds: int = 60
    ) -> TemporalStartTarget:
        with self._authority._transaction(target.tenant_id) as connection:
            row = connection.execute(
                text(
                    """
                    SELECT * FROM gda_control.renew_agentops_temporal_start_target_claim(
                        :tenant_id, :target_id, :worker_id, :lease_seconds)
                    """
                ),
                {
                    "tenant_id": target.tenant_id,
                    "target_id": target.target_id,
                    "worker_id": worker_id,
                    "lease_seconds": lease_seconds,
                },
            ).mappings().one()
        return self._target(row)

    def attach_provider_run(
        self, target: TemporalStartTarget, observation: TemporalProviderWorkflowInputObservation,
        *, worker_id: str,
    ) -> TemporalStartTarget:
        reconciliation = build_unknown_start_reconciliation(target, observation)
        document = reconciliation.model_dump(mode="json")
        with self._authority._transaction(target.tenant_id) as connection:
            row = connection.execute(
                text(
                    """
                    SELECT * FROM gda_control.attach_agentops_temporal_start_target_run(
                        :tenant_id, :target_id, :worker_id, :provider_run_id,
                        CAST(:reconciliation_document AS jsonb), :reconciliation_fingerprint
                    )
                    """
                ),
                {
                    "tenant_id": target.tenant_id,
                    "target_id": target.target_id,
                    "worker_id": worker_id,
                    "provider_run_id": observation.provider_run_id,
                    "reconciliation_document": _json(document),
                    "reconciliation_fingerprint": _fingerprint_payload(
                        TEMPORAL_START_RECONCILIATION_SCHEMA, document, "reconciliation_sha256"
                    ),
                },
            ).mappings().one()
        return self._target(row)

    def release_target_claim(
        self, target: TemporalStartTarget, *, worker_id: str, error: str,
        retry_after_seconds: float = 1.0,
    ) -> TemporalStartTarget:
        if not error.strip():
            raise ValueError("target retry error must not be empty")
        with self._authority._transaction(target.tenant_id) as connection:
            row = connection.execute(
                text(
                    """
                    SELECT * FROM gda_control.release_agentops_temporal_start_target_claim(
                        :tenant_id, :target_id, :worker_id, :error, :available_at)
                    """
                ),
                {
                    "tenant_id": target.tenant_id,
                    "target_id": target.target_id,
                    "worker_id": worker_id,
                    "error": error,
                    "available_at": datetime.now(UTC) + timedelta(seconds=retry_after_seconds),
                },
            ).mappings().one()
        return self._target(row)

    def complete_target(
        self, target: TemporalStartTarget, *, worker_id: str
    ) -> TemporalStartTarget:
        with self._authority._transaction(target.tenant_id) as connection:
            row = connection.execute(
                text(
                    """
                    SELECT * FROM gda_control.complete_agentops_temporal_start_target(
                        :tenant_id, :target_id, :worker_id)
                    """
                ),
                {
                    "tenant_id": target.tenant_id,
                    "target_id": target.target_id,
                    "worker_id": worker_id,
                },
            ).mappings().one()
        return self._target(row)

    def fail_target(
        self, target: TemporalStartTarget, *, worker_id: str, error: str
    ) -> TemporalStartTarget:
        with self._authority._transaction(target.tenant_id) as connection:
            row = connection.execute(
                text(
                    """
                    SELECT * FROM gda_control.fail_agentops_temporal_start_target(
                        :tenant_id, :target_id, :worker_id, :error)
                    """
                ),
                {
                    "tenant_id": target.tenant_id,
                    "target_id": target.target_id,
                    "worker_id": worker_id,
                    "error": error,
                },
            ).mappings().one()
        return self._target(row)


__all__ = [
    "AGENTOPS_TEMPORAL_START_TARGET_AUTHORITY_MIGRATION",
    "AgentOpsTemporalStartTargetStatus",
    "PostgresAgentOpsTemporalStartTargetAuthority",
    "TemporalStartTarget",
    "build_unknown_start_reconciliation",
]

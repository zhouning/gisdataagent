"""PostgreSQL authority for AgentOps checkpoints and Temporal reconciliation evidence."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import Field, TypeAdapter, ValidationError, field_validator, model_validator
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from .agentops_temporal_reconciliation import (
    TemporalCheckpointReconciliation,
    TemporalProviderWorkflowHistoryObservation,
)
from .agentops_temporal_workflow import TemporalTaskGraphWorkflowCheckpoint
from .db_engine import get_engine
from .platform_contracts import FrozenContract, TenantId, canonical_json_bytes
from .temporal_entity_authority import GATEWAY_DATABASE_ROLE

AGENTOPS_TEMPORAL_CHECKPOINT_AUTHORITY_MIGRATION = (
    Path(__file__).resolve().parent
    / "migrations"
    / "240_agentops_temporal_checkpoint_authority.sql"
)
AGENTOPS_TEMPORAL_RECONCILER_FENCING_MIGRATION = (
    Path(__file__).resolve().parent
    / "migrations"
    / "241_agentops_temporal_reconciler_fencing.sql"
)

_TENANT_ADAPTER = TypeAdapter(TenantId)
_WORKFLOW_ID_RE = re.compile(r"^[a-z][a-z0-9._:-]{1,254}$")
_ACTOR_RE = re.compile(r"^(human|workload|agent):[^\s]{1,128}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class AgentOpsTemporalCheckpointAuthorityError(RuntimeError):
    """Base error for the durable AgentOps checkpoint authority."""


class AgentOpsTemporalCheckpointAuthorityConfigurationError(
    AgentOpsTemporalCheckpointAuthorityError
):
    """The database or gateway role cannot enforce the authority contract."""


class AgentOpsTemporalCheckpointAuthorityConflictError(
    AgentOpsTemporalCheckpointAuthorityError
):
    """A checkpoint predecessor or idempotency identity conflicts."""


class AgentOpsTemporalCheckpointAuthorityForbiddenError(
    AgentOpsTemporalCheckpointAuthorityError
):
    """The current database role or tenant context was denied."""


class AgentOpsTemporalCheckpointAuthorityValidationError(
    AgentOpsTemporalCheckpointAuthorityError
):
    """A checkpoint or reconciliation contract is invalid."""


class AgentOpsTemporalReconcilerLease(FrozenContract):
    """Database-issued fencing token for one tenant/workflow reconciler."""

    tenant_id: TenantId
    workflow_id: str = Field(pattern=r"^[a-z][a-z0-9._:-]{1,254}$")
    lease_owner: str = Field(pattern=r"^(workload|agent):[^\s]{1,128}$")
    lease_epoch: int = Field(ge=1)
    lease_acquired_at: datetime
    lease_expires_at: datetime
    lease_updated_at: datetime

    @field_validator(
        "lease_acquired_at", "lease_expires_at", "lease_updated_at"
    )
    @classmethod
    def _aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("AgentOps reconciler lease timestamp must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _consistent_time(self) -> AgentOpsTemporalReconcilerLease:
        if (
            self.lease_expires_at < self.lease_acquired_at
            or self.lease_updated_at < self.lease_acquired_at
        ):
            raise ValueError("AgentOps reconciler lease timestamps are inconsistent")
        return self


@dataclass(frozen=True)
class AgentOpsTemporalFencedWriteBinding:
    tenant_id: str
    workflow_id: str
    write_sha256: str
    lease_owner: str
    lease_epoch: int
    bound_at: datetime


@dataclass(frozen=True)
class AgentOpsTemporalCheckpointWriteResult:
    checkpoint: TemporalTaskGraphWorkflowCheckpoint
    checkpoint_sequence: int
    created: bool


@dataclass(frozen=True)
class AgentOpsTemporalReconciliationEvidence:
    observation: TemporalProviderWorkflowHistoryObservation
    reconciliation: TemporalCheckpointReconciliation
    recorded_by: str
    recorded_at: datetime


@dataclass(frozen=True)
class AgentOpsTemporalReconciliationWriteResult:
    evidence: AgentOpsTemporalReconciliationEvidence
    created: bool


@dataclass(frozen=True)
class AgentOpsTemporalRecoveredCheckpointWrite:
    checkpoint: TemporalTaskGraphWorkflowCheckpoint
    checkpoint_sequence: int
    binding: AgentOpsTemporalFencedWriteBinding


@dataclass(frozen=True)
class AgentOpsTemporalRecoveredReconciliationWrite:
    evidence: AgentOpsTemporalReconciliationEvidence
    binding: AgentOpsTemporalFencedWriteBinding


def _sqlstate(exc: DBAPIError) -> str | None:
    original = getattr(exc, "orig", None)
    return getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)


def _json(value: Any) -> str:
    return canonical_json_bytes(value).decode("ascii")


def _json_value(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _fingerprint_payload(schema_id: str, document: dict[str, Any], field: str) -> str:
    data = dict(document)
    data.pop(field, None)
    return _json({"schema": schema_id, "data": data})


def _identity(tenant_id: str, workflow_id: str) -> tuple[str, str]:
    try:
        tenant = _TENANT_ADAPTER.validate_python(tenant_id)
    except ValidationError as exc:
        raise AgentOpsTemporalCheckpointAuthorityValidationError(
            "AgentOps checkpoint tenant_id is invalid"
        ) from exc
    workflow = str(workflow_id or "").strip()
    if _WORKFLOW_ID_RE.fullmatch(workflow) is None:
        raise AgentOpsTemporalCheckpointAuthorityValidationError(
            "AgentOps checkpoint workflow_id is invalid"
        )
    return tenant, workflow


def _tenant(tenant_id: str) -> str:
    try:
        return _TENANT_ADAPTER.validate_python(tenant_id)
    except ValidationError as exc:
        raise AgentOpsTemporalCheckpointAuthorityValidationError(
            "AgentOps checkpoint tenant_id is invalid"
        ) from exc


def _actor(value: str) -> str:
    actor = str(value or "").strip()
    if _ACTOR_RE.fullmatch(actor) is None:
        raise AgentOpsTemporalCheckpointAuthorityValidationError(
            "AgentOps checkpoint recorded_by must be a typed subject"
        )
    return actor


def _lease_owner(value: str) -> str:
    owner = _actor(value)
    if not owner.startswith(("workload:", "agent:")):
        raise AgentOpsTemporalCheckpointAuthorityValidationError(
            "AgentOps reconciler lease owner must be a workload or agent"
        )
    return owner


def _lease_seconds(value: int) -> int:
    if isinstance(value, bool) or not 1 <= value <= 3_600:
        raise AgentOpsTemporalCheckpointAuthorityValidationError(
            "AgentOps reconciler lease duration must be 1..3600 seconds"
        )
    return value


class PostgresAgentOpsTemporalCheckpointAuthority:
    """Tenant-bound, append-only checkpoint and reconciliation repository."""

    def __init__(self, engine: Any = None):
        self._engine = engine

    def _get_engine(self):
        engine = self._engine or get_engine()
        if engine is None or engine.dialect.name != "postgresql":
            raise AgentOpsTemporalCheckpointAuthorityConfigurationError(
                "AgentOps Temporal checkpoint authority requires PostgreSQL"
            )
        return engine

    @contextmanager
    def _transaction(self, tenant_id: str) -> Iterator[Any]:
        tenant = _tenant(tenant_id)
        try:
            with self._get_engine().connect() as connection:
                with connection.begin():
                    try:
                        connection.exec_driver_sql(
                            f'SET LOCAL ROLE "{GATEWAY_DATABASE_ROLE}"'
                        )
                    except DBAPIError as exc:
                        raise AgentOpsTemporalCheckpointAuthorityConfigurationError(
                            "database login is not a member of the platform gateway role"
                        ) from exc
                    connection.execute(
                        text("SELECT set_config('app.current_tenant', :tenant, true)"),
                        {"tenant": tenant},
                    )
                    yield connection
        except AgentOpsTemporalCheckpointAuthorityError:
            raise
        except DBAPIError as exc:
            state = _sqlstate(exc)
            if state in {"23503", "23505", "40001", "55000"}:
                raise AgentOpsTemporalCheckpointAuthorityConflictError(
                    "AgentOps checkpoint predecessor or idempotency conflict"
                ) from exc
            if state == "42501":
                raise AgentOpsTemporalCheckpointAuthorityForbiddenError(
                    "AgentOps checkpoint tenant or database role was denied"
                ) from exc
            if state in {"22023", "22P02", "23514"}:
                raise AgentOpsTemporalCheckpointAuthorityValidationError(
                    "AgentOps checkpoint or reconciliation evidence was rejected"
                ) from exc
            raise AgentOpsTemporalCheckpointAuthorityConfigurationError(
                "AgentOps Temporal checkpoint authority operation failed"
            ) from exc
        except SQLAlchemyError as exc:
            raise AgentOpsTemporalCheckpointAuthorityConfigurationError(
                "AgentOps Temporal checkpoint authority operation failed"
            ) from exc

    @staticmethod
    def _checkpoint(document: Any) -> TemporalTaskGraphWorkflowCheckpoint:
        try:
            return TemporalTaskGraphWorkflowCheckpoint.model_validate(
                _json_value(document)
            )
        except (TypeError, ValueError, ValidationError) as exc:
            raise AgentOpsTemporalCheckpointAuthorityConfigurationError(
                "stored AgentOps checkpoint is invalid"
            ) from exc

    @staticmethod
    def _observation(
        document: Any,
    ) -> TemporalProviderWorkflowHistoryObservation:
        try:
            return TemporalProviderWorkflowHistoryObservation.model_validate(
                _json_value(document)
            )
        except (TypeError, ValueError, ValidationError) as exc:
            raise AgentOpsTemporalCheckpointAuthorityConfigurationError(
                "stored Temporal history observation is invalid"
            ) from exc

    @staticmethod
    def _reconciliation(document: Any) -> TemporalCheckpointReconciliation:
        try:
            return TemporalCheckpointReconciliation.model_validate(
                _json_value(document)
            )
        except (TypeError, ValueError, ValidationError) as exc:
            raise AgentOpsTemporalCheckpointAuthorityConfigurationError(
                "stored Temporal checkpoint reconciliation is invalid"
            ) from exc

    @staticmethod
    def _lease(row: Any) -> AgentOpsTemporalReconcilerLease:
        try:
            return AgentOpsTemporalReconcilerLease.model_validate(dict(row))
        except (TypeError, ValueError, ValidationError) as exc:
            raise AgentOpsTemporalCheckpointAuthorityConfigurationError(
                "stored AgentOps reconciler lease is invalid"
            ) from exc

    @staticmethod
    def _binding(row: Any, *, field: str) -> AgentOpsTemporalFencedWriteBinding:
        try:
            return AgentOpsTemporalFencedWriteBinding(
                tenant_id=str(row["tenant_id"]),
                workflow_id=str(row["workflow_id"]),
                write_sha256=str(row[field]),
                lease_owner=str(row["lease_owner"]),
                lease_epoch=int(row["lease_epoch"]),
                bound_at=row["bound_at"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise AgentOpsTemporalCheckpointAuthorityConfigurationError(
                "stored AgentOps fenced write binding is invalid"
            ) from exc

    @staticmethod
    def _correlate_lease(
        lease: AgentOpsTemporalReconcilerLease,
        *,
        tenant_id: str,
        workflow_id: str,
        recorded_by: str | None = None,
    ) -> None:
        if lease.tenant_id != tenant_id or lease.workflow_id != workflow_id:
            raise AgentOpsTemporalCheckpointAuthorityValidationError(
                "AgentOps reconciler lease identity differs from write"
            )
        if recorded_by is not None and lease.lease_owner != recorded_by:
            raise AgentOpsTemporalCheckpointAuthorityValidationError(
                "AgentOps reconciler lease owner differs from recorded_by"
            )

    def acquire_reconciler_lease(
        self,
        *,
        tenant_id: str,
        workflow_id: str,
        lease_owner: str,
        lease_seconds: int = 60,
    ) -> AgentOpsTemporalReconcilerLease:
        tenant, workflow = _identity(tenant_id, workflow_id)
        owner = _lease_owner(lease_owner)
        duration = _lease_seconds(lease_seconds)
        with self._transaction(tenant) as connection:
            row = connection.execute(
                text(
                    """
                    SELECT *
                    FROM gda_control.acquire_agentops_temporal_reconciler_lease(
                        :tenant_id, :workflow_id, :lease_owner, :lease_seconds
                    )
                    """
                ),
                {
                    "tenant_id": tenant,
                    "workflow_id": workflow,
                    "lease_owner": owner,
                    "lease_seconds": duration,
                },
            ).mappings().one()
        return self._lease(row)

    def current_reconciler_lease(
        self, *, tenant_id: str, workflow_id: str
    ) -> AgentOpsTemporalReconcilerLease | None:
        tenant, workflow = _identity(tenant_id, workflow_id)
        with self._transaction(tenant) as connection:
            row = connection.execute(
                text(
                    """
                    SELECT tenant_id, workflow_id, lease_owner, lease_epoch,
                           lease_acquired_at, lease_expires_at, lease_updated_at
                    FROM gda_control.agentops_temporal_reconciler_lease
                    WHERE tenant_id = :tenant_id AND workflow_id = :workflow_id
                    """
                ),
                {"tenant_id": tenant, "workflow_id": workflow},
            ).mappings().one_or_none()
        return None if row is None else self._lease(row)

    def renew_reconciler_lease(
        self,
        lease: AgentOpsTemporalReconcilerLease,
        *,
        lease_seconds: int = 60,
    ) -> AgentOpsTemporalReconcilerLease:
        duration = _lease_seconds(lease_seconds)
        with self._transaction(lease.tenant_id) as connection:
            row = connection.execute(
                text(
                    """
                    SELECT *
                    FROM gda_control.renew_agentops_temporal_reconciler_lease(
                        :tenant_id, :workflow_id, :lease_owner,
                        :lease_epoch, :lease_seconds
                    )
                    """
                ),
                {
                    "tenant_id": lease.tenant_id,
                    "workflow_id": lease.workflow_id,
                    "lease_owner": lease.lease_owner,
                    "lease_epoch": lease.lease_epoch,
                    "lease_seconds": duration,
                },
            ).mappings().one()
        return self._lease(row)

    def release_reconciler_lease(
        self, lease: AgentOpsTemporalReconcilerLease
    ) -> AgentOpsTemporalReconcilerLease:
        with self._transaction(lease.tenant_id) as connection:
            row = connection.execute(
                text(
                    """
                    SELECT *
                    FROM gda_control.release_agentops_temporal_reconciler_lease(
                        :tenant_id, :workflow_id, :lease_owner, :lease_epoch
                    )
                    """
                ),
                {
                    "tenant_id": lease.tenant_id,
                    "workflow_id": lease.workflow_id,
                    "lease_owner": lease.lease_owner,
                    "lease_epoch": lease.lease_epoch,
                },
            ).mappings().one()
        return self._lease(row)

    def record_checkpoint(
        self,
        checkpoint: TemporalTaskGraphWorkflowCheckpoint,
        *,
        previous_checkpoint_sha256: str | None = None,
        recorded_by: str,
        lease: AgentOpsTemporalReconcilerLease | None = None,
    ) -> AgentOpsTemporalCheckpointWriteResult:
        tenant = checkpoint.workflow_input.tenant_id
        workflow_id = checkpoint.workflow_input.identity.workflow_id
        _identity(tenant, workflow_id)
        actor = _actor(recorded_by)
        if previous_checkpoint_sha256 is not None and (
            _SHA256_RE.fullmatch(previous_checkpoint_sha256) is None
        ):
            raise AgentOpsTemporalCheckpointAuthorityValidationError(
                "previous AgentOps checkpoint fingerprint is invalid"
            )
        if lease is not None:
            self._correlate_lease(
                lease,
                tenant_id=tenant,
                workflow_id=workflow_id,
                recorded_by=actor,
            )
        document = checkpoint.model_dump(mode="json")
        with self._transaction(tenant) as connection:
            row = connection.execute(
                text(
                    """SELECT checkpoint_document, checkpoint_sequence, created
                    FROM gda_control.record_agentops_temporal_checkpoint_fenced(
                        :tenant_id, :workflow_id, :previous_checkpoint_sha256,
                        CAST(:checkpoint_document AS jsonb),
                        :fingerprint_payload, :recorded_by,
                        :lease_owner, :lease_epoch
                    )
                    """
                    if lease is not None
                    else """
                    SELECT checkpoint_document, checkpoint_sequence, created
                    FROM gda_control.record_agentops_temporal_checkpoint(
                        :tenant_id, :workflow_id, :previous_checkpoint_sha256,
                        CAST(:checkpoint_document AS jsonb),
                        :fingerprint_payload, :recorded_by
                    )
                    """
                ),
                {
                    "tenant_id": tenant,
                    "workflow_id": workflow_id,
                    "previous_checkpoint_sha256": previous_checkpoint_sha256,
                    "checkpoint_document": _json(document),
                    "fingerprint_payload": _fingerprint_payload(
                        checkpoint.schema_id, document, "checkpoint_sha256"
                    ),
                    "recorded_by": actor,
                    "lease_owner": lease.lease_owner if lease is not None else None,
                    "lease_epoch": lease.lease_epoch if lease is not None else None,
                },
            ).mappings().one()
        return AgentOpsTemporalCheckpointWriteResult(
            checkpoint=self._checkpoint(row["checkpoint_document"]),
            checkpoint_sequence=int(row["checkpoint_sequence"]),
            created=bool(row["created"]),
        )

    def current_checkpoint(
        self, *, tenant_id: str, workflow_id: str
    ) -> TemporalTaskGraphWorkflowCheckpoint | None:
        tenant, workflow = _identity(tenant_id, workflow_id)
        with self._transaction(tenant) as connection:
            row = connection.execute(
                text(
                    """
                    SELECT checkpoint_document
                    FROM gda_control.agentops_temporal_checkpoint_current
                    WHERE tenant_id = :tenant_id AND workflow_id = :workflow_id
                    """
                ),
                {"tenant_id": tenant, "workflow_id": workflow},
            ).mappings().one_or_none()
        return None if row is None else self._checkpoint(row["checkpoint_document"])

    def resolve_checkpoint_write(
        self,
        checkpoint: TemporalTaskGraphWorkflowCheckpoint,
    ) -> AgentOpsTemporalRecoveredCheckpointWrite | None:
        """Resolve an unknown commit by exact hash without performing another write."""

        tenant = checkpoint.workflow_input.tenant_id
        workflow = checkpoint.workflow_input.identity.workflow_id
        _identity(tenant, workflow)
        with self._transaction(tenant) as connection:
            row = connection.execute(
                text(
                    """
                    SELECT history.checkpoint_document,
                           history.checkpoint_sequence,
                           binding.tenant_id, binding.workflow_id,
                           binding.checkpoint_sha256, binding.lease_owner,
                           binding.lease_epoch, binding.bound_at
                    FROM gda_control.agentops_temporal_checkpoint_history AS history
                    JOIN gda_control.agentops_temporal_checkpoint_lease_binding
                        AS binding
                      ON binding.tenant_id = history.tenant_id
                     AND binding.workflow_id = history.workflow_id
                     AND binding.checkpoint_sha256 = history.checkpoint_sha256
                    WHERE history.tenant_id = :tenant_id
                      AND history.workflow_id = :workflow_id
                      AND history.checkpoint_sha256 = :checkpoint_sha256
                    """
                ),
                {
                    "tenant_id": tenant,
                    "workflow_id": workflow,
                    "checkpoint_sha256": checkpoint.checkpoint_sha256,
                },
            ).mappings().one_or_none()
        if row is None:
            return None
        stored = self._checkpoint(row["checkpoint_document"])
        if stored != checkpoint:
            raise AgentOpsTemporalCheckpointAuthorityConfigurationError(
                "resolved AgentOps checkpoint differs from expected write"
            )
        return AgentOpsTemporalRecoveredCheckpointWrite(
            checkpoint=stored,
            checkpoint_sequence=int(row["checkpoint_sequence"]),
            binding=self._binding(row, field="checkpoint_sha256"),
        )

    def checkpoint_history(
        self, *, tenant_id: str, workflow_id: str, limit: int = 1_000
    ) -> tuple[TemporalTaskGraphWorkflowCheckpoint, ...]:
        if limit < 1 or limit > 10_000:
            raise AgentOpsTemporalCheckpointAuthorityValidationError(
                "AgentOps checkpoint history limit must be 1..10000"
            )
        tenant, workflow = _identity(tenant_id, workflow_id)
        with self._transaction(tenant) as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT checkpoint_document
                    FROM gda_control.agentops_temporal_checkpoint_history
                    WHERE tenant_id = :tenant_id AND workflow_id = :workflow_id
                    ORDER BY checkpoint_sequence
                    LIMIT :limit
                    """
                ),
                {
                    "tenant_id": tenant,
                    "workflow_id": workflow,
                    "limit": limit,
                },
            ).mappings().all()
        return tuple(self._checkpoint(row["checkpoint_document"]) for row in rows)

    def record_reconciliation(
        self,
        observation: TemporalProviderWorkflowHistoryObservation,
        reconciliation: TemporalCheckpointReconciliation,
        *,
        recorded_by: str,
        lease: AgentOpsTemporalReconcilerLease | None = None,
    ) -> AgentOpsTemporalReconciliationWriteResult:
        tenant, workflow = _identity(observation.tenant_id, observation.workflow_id)
        actor = _actor(recorded_by)
        if (
            reconciliation.tenant_id != tenant
            or reconciliation.workflow_id != workflow
            or reconciliation.provider_run_id != observation.provider_run_id
            or reconciliation.history_sha256 != observation.history_sha256
            or reconciliation.provider_workflow_status != observation.status
        ):
            raise AgentOpsTemporalCheckpointAuthorityValidationError(
                "Temporal observation and checkpoint reconciliation differ"
            )
        if lease is not None:
            self._correlate_lease(
                lease,
                tenant_id=tenant,
                workflow_id=workflow,
                recorded_by=actor,
            )
        observation_document = observation.model_dump(mode="json")
        reconciliation_document = reconciliation.model_dump(mode="json")
        with self._transaction(tenant) as connection:
            row = connection.execute(
                text(
                    """SELECT observation_document, reconciliation_document, created
                    FROM gda_control.record_agentops_temporal_reconciliation_fenced(
                        :tenant_id, :workflow_id, :provider_run_id,
                        :checkpoint_sha256,
                        CAST(:observation_document AS jsonb),
                        :observation_fingerprint_payload,
                        CAST(:reconciliation_document AS jsonb),
                        :reconciliation_fingerprint_payload,
                        :recorded_by, :lease_owner, :lease_epoch
                    )
                    """
                    if lease is not None
                    else """
                    SELECT observation_document, reconciliation_document, created
                    FROM gda_control.record_agentops_temporal_reconciliation(
                        :tenant_id, :workflow_id, :provider_run_id,
                        :checkpoint_sha256,
                        CAST(:observation_document AS jsonb),
                        :observation_fingerprint_payload,
                        CAST(:reconciliation_document AS jsonb),
                        :reconciliation_fingerprint_payload,
                        :recorded_by
                    )
                    """
                ),
                {
                    "tenant_id": tenant,
                    "workflow_id": workflow,
                    "provider_run_id": observation.provider_run_id,
                    "checkpoint_sha256": reconciliation.checkpoint_sha256,
                    "observation_document": _json(observation_document),
                    "observation_fingerprint_payload": _fingerprint_payload(
                        observation.schema_id,
                        observation_document,
                        "observation_sha256",
                    ),
                    "reconciliation_document": _json(reconciliation_document),
                    "reconciliation_fingerprint_payload": _fingerprint_payload(
                        reconciliation.schema_id,
                        reconciliation_document,
                        "reconciliation_sha256",
                    ),
                    "recorded_by": actor,
                    "lease_owner": lease.lease_owner if lease is not None else None,
                    "lease_epoch": lease.lease_epoch if lease is not None else None,
                },
            ).mappings().one()
            stored = connection.execute(
                text(
                    """
                    SELECT recorded_by, recorded_at
                    FROM gda_control.agentops_temporal_reconciliation_evidence
                    WHERE tenant_id = :tenant_id
                      AND reconciliation_sha256 = :reconciliation_sha256
                    """
                ),
                {
                    "tenant_id": tenant,
                    "reconciliation_sha256": (
                        reconciliation.reconciliation_sha256
                    ),
                },
            ).mappings().one()
        evidence = AgentOpsTemporalReconciliationEvidence(
            observation=self._observation(row["observation_document"]),
            reconciliation=self._reconciliation(row["reconciliation_document"]),
            recorded_by=str(stored["recorded_by"]),
            recorded_at=stored["recorded_at"],
        )
        return AgentOpsTemporalReconciliationWriteResult(
            evidence=evidence,
            created=bool(row["created"]),
        )

    def reconciliation_history(
        self, *, tenant_id: str, workflow_id: str, limit: int = 1_000
    ) -> tuple[AgentOpsTemporalReconciliationEvidence, ...]:
        if limit < 1 or limit > 10_000:
            raise AgentOpsTemporalCheckpointAuthorityValidationError(
                "AgentOps reconciliation history limit must be 1..10000"
            )
        tenant, workflow = _identity(tenant_id, workflow_id)
        with self._transaction(tenant) as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT observation_document, reconciliation_document,
                           recorded_by, recorded_at
                    FROM gda_control.agentops_temporal_reconciliation_evidence
                    WHERE tenant_id = :tenant_id AND workflow_id = :workflow_id
                    ORDER BY recorded_at, reconciliation_sha256
                    LIMIT :limit
                    """
                ),
                {
                    "tenant_id": tenant,
                    "workflow_id": workflow,
                    "limit": limit,
                },
            ).mappings().all()
        return tuple(
            AgentOpsTemporalReconciliationEvidence(
                observation=self._observation(row["observation_document"]),
                reconciliation=self._reconciliation(row["reconciliation_document"]),
                recorded_by=str(row["recorded_by"]),
                recorded_at=row["recorded_at"],
            )
            for row in rows
        )

    def resolve_reconciliation_write(
        self,
        observation: TemporalProviderWorkflowHistoryObservation,
        reconciliation: TemporalCheckpointReconciliation,
    ) -> AgentOpsTemporalRecoveredReconciliationWrite | None:
        """Resolve an unknown evidence commit by exact immutable identities."""

        tenant, workflow = _identity(observation.tenant_id, observation.workflow_id)
        if (
            reconciliation.tenant_id != tenant
            or reconciliation.workflow_id != workflow
            or reconciliation.provider_run_id != observation.provider_run_id
            or reconciliation.history_sha256 != observation.history_sha256
        ):
            raise AgentOpsTemporalCheckpointAuthorityValidationError(
                "Temporal observation and checkpoint reconciliation differ"
            )
        with self._transaction(tenant) as connection:
            row = connection.execute(
                text(
                    """
                    SELECT evidence.observation_document,
                           evidence.reconciliation_document,
                           evidence.recorded_by, evidence.recorded_at,
                           binding.tenant_id, binding.workflow_id,
                           binding.reconciliation_sha256, binding.lease_owner,
                           binding.lease_epoch, binding.bound_at
                    FROM gda_control.agentops_temporal_reconciliation_evidence
                        AS evidence
                    JOIN gda_control.agentops_temporal_reconciliation_lease_binding
                        AS binding
                      ON binding.tenant_id = evidence.tenant_id
                     AND binding.reconciliation_sha256
                         = evidence.reconciliation_sha256
                    WHERE evidence.tenant_id = :tenant_id
                      AND evidence.workflow_id = :workflow_id
                      AND evidence.reconciliation_sha256
                          = :reconciliation_sha256
                    """
                ),
                {
                    "tenant_id": tenant,
                    "workflow_id": workflow,
                    "reconciliation_sha256": (
                        reconciliation.reconciliation_sha256
                    ),
                },
            ).mappings().one_or_none()
        if row is None:
            return None
        stored_observation = self._observation(row["observation_document"])
        stored_reconciliation = self._reconciliation(
            row["reconciliation_document"]
        )
        if (
            stored_observation != observation
            or stored_reconciliation != reconciliation
        ):
            raise AgentOpsTemporalCheckpointAuthorityConfigurationError(
                "resolved AgentOps reconciliation differs from expected write"
            )
        return AgentOpsTemporalRecoveredReconciliationWrite(
            evidence=AgentOpsTemporalReconciliationEvidence(
                observation=stored_observation,
                reconciliation=stored_reconciliation,
                recorded_by=str(row["recorded_by"]),
                recorded_at=row["recorded_at"],
            ),
            binding=self._binding(row, field="reconciliation_sha256"),
        )


__all__ = [
    "AGENTOPS_TEMPORAL_CHECKPOINT_AUTHORITY_MIGRATION",
    "AGENTOPS_TEMPORAL_RECONCILER_FENCING_MIGRATION",
    "AgentOpsTemporalCheckpointAuthorityConfigurationError",
    "AgentOpsTemporalCheckpointAuthorityConflictError",
    "AgentOpsTemporalCheckpointAuthorityError",
    "AgentOpsTemporalCheckpointAuthorityForbiddenError",
    "AgentOpsTemporalCheckpointAuthorityValidationError",
    "AgentOpsTemporalCheckpointWriteResult",
    "AgentOpsTemporalFencedWriteBinding",
    "AgentOpsTemporalRecoveredCheckpointWrite",
    "AgentOpsTemporalRecoveredReconciliationWrite",
    "AgentOpsTemporalReconcilerLease",
    "AgentOpsTemporalReconciliationEvidence",
    "AgentOpsTemporalReconciliationWriteResult",
    "PostgresAgentOpsTemporalCheckpointAuthority",
]

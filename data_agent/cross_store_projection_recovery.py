"""Fail-closed recovery state machine for cross-store projection repairs.

Provider commits and the PostgreSQL checkpoint authority are deliberately not
treated as one distributed transaction.  This module records the boundary and
provides a deterministic recovery decision:

* a known provider receipt permits an authority-only retry after re-observation;
* target drift requires reconciliation and never advances the checkpoint;
* an unknown provider outcome requires observation/manual compensation instead
  of blindly replaying a potentially non-idempotent side effect.

The in-memory ledger is for contract tests and local rehearsal.  A production
deployment must back the same append-only event contract with durable storage.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, ClassVar, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .cross_store_projection_consistency import (
    ProjectionCheckpoint,
    ProjectionCheckpointConflictError,
    ProjectionConsistencyError,
    ProjectionEngine,
    ProjectionRepairPlan,
    ProjectionTargetObservation,
    build_projection_checkpoint_from_repair,
)
from .platform_contracts import NonEmptyText, Sha256, canonical_json_fingerprint


class ProjectionRecoveryError(ProjectionConsistencyError):
    """Base error for invalid recovery evidence or state transitions."""


class ProjectionRecoveryState(StrEnum):
    PLANNED = "planned"
    PROVIDER_FAILED = "provider_failed"
    PROVIDER_COMMITTED = "provider_committed"
    AUTHORITY_PENDING = "authority_pending"
    AUTHORITY_COMMITTED = "authority_committed"
    RECONCILIATION_REQUIRED = "reconciliation_required"
    COMPENSATION_REQUIRED = "compensation_required"
    FAILED_CLOSED = "failed_closed"


RecoveryAction = Literal[
    "execute_provider",
    "retry_authority",
    "reobserve_target",
    "manual_compensation",
    "none",
]


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ProjectionRecoveryEvent(_FrozenModel):
    """One append-only transition in the recovery ledger."""

    schema_id: ClassVar[str] = "gda.projection-recovery-event.v1"
    event_type: Literal[
        "planned",
        "provider_failed",
        "provider_committed",
        "authority_failed",
        "authority_committed",
        "target_drift",
        "reconcile_required",
        "compensation_required",
        "failed_closed",
    ]
    attempt: int = Field(ge=0)
    occurred_at: datetime
    detail: dict[str, Any] = Field(default_factory=dict)
    event_sha256: Sha256

    @model_validator(mode="after")
    def _canonical(self) -> ProjectionRecoveryEvent:
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("recovery event timestamp must be timezone-aware")
        expected = recovery_event_fingerprint(
            event_type=self.event_type,
            attempt=self.attempt,
            occurred_at=self.occurred_at,
            detail=self.detail,
        )
        if self.event_sha256 != expected:
            raise ValueError("recovery event fingerprint does not match content")
        return self


class ProjectionRecoverySnapshot(_FrozenModel):
    """Current append-only recovery state for one sealed repair plan."""

    schema_id: ClassVar[str] = "gda.projection-recovery-snapshot.v1"
    tenant_id: NonEmptyText
    projection_id: NonEmptyText
    target_engine: ProjectionEngine
    target_ref: NonEmptyText
    plan_sha256: Sha256
    plan_idempotency_key: Sha256
    state: ProjectionRecoveryState
    next_action: RecoveryAction
    provider_attempts: int = Field(ge=0)
    authority_attempts: int = Field(ge=0)
    provider_commit_ref: dict[str, Any] | None = None
    checkpoint_sha256: Sha256 | None = None
    last_error_code: NonEmptyText | None = None
    events: tuple[ProjectionRecoveryEvent, ...] = ()
    snapshot_sha256: Sha256

    @model_validator(mode="after")
    def _state_contract(self) -> ProjectionRecoverySnapshot:
        if self.state is ProjectionRecoveryState.PROVIDER_COMMITTED:
            if self.provider_commit_ref is None or self.next_action != "retry_authority":
                raise ValueError("provider committed state requires authority retry")
        if self.state is ProjectionRecoveryState.AUTHORITY_PENDING:
            if self.provider_commit_ref is None or self.next_action != "retry_authority":
                raise ValueError("authority pending state requires provider evidence")
        if self.state is ProjectionRecoveryState.AUTHORITY_COMMITTED:
            if self.checkpoint_sha256 is None or self.next_action != "none":
                raise ValueError("authority committed state requires checkpoint evidence")
        if self.state in {
            ProjectionRecoveryState.RECONCILIATION_REQUIRED,
            ProjectionRecoveryState.COMPENSATION_REQUIRED,
            ProjectionRecoveryState.FAILED_CLOSED,
        } and self.next_action == "none":
            raise ValueError("non-terminal recovery state requires an operator action")
        expected = recovery_snapshot_fingerprint(
            tenant_id=self.tenant_id,
            projection_id=self.projection_id,
            target_engine=self.target_engine,
            target_ref=self.target_ref,
            plan_sha256=self.plan_sha256,
            plan_idempotency_key=self.plan_idempotency_key,
            state=self.state,
            next_action=self.next_action,
            provider_attempts=self.provider_attempts,
            authority_attempts=self.authority_attempts,
            provider_commit_ref=self.provider_commit_ref,
            checkpoint_sha256=self.checkpoint_sha256,
            last_error_code=self.last_error_code,
            events=self.events,
        )
        if self.snapshot_sha256 != expected:
            raise ValueError("recovery snapshot fingerprint does not match content")
        return self


class ProjectionRecoveryLedger(Protocol):
    def current(self, plan_sha256: str) -> ProjectionRecoverySnapshot | None: ...

    def append(self, snapshot: ProjectionRecoverySnapshot) -> ProjectionRecoverySnapshot: ...


class InMemoryProjectionRecoveryLedger:
    """Append-only ledger for tests and local rehearsal only."""

    def __init__(self) -> None:
        self._current: dict[str, ProjectionRecoverySnapshot] = {}
        self._history: dict[str, list[ProjectionRecoverySnapshot]] = {}

    def current(self, plan_sha256: str) -> ProjectionRecoverySnapshot | None:
        return self._current.get(plan_sha256)

    def history(self, plan_sha256: str) -> tuple[ProjectionRecoverySnapshot, ...]:
        return tuple(self._history.get(plan_sha256, ()))

    def append(self, snapshot: ProjectionRecoverySnapshot) -> ProjectionRecoverySnapshot:
        current = self._current.get(snapshot.plan_sha256)
        if current is not None:
            if current.snapshot_sha256 == snapshot.snapshot_sha256:
                return current
            if snapshot.events[: len(current.events)] != current.events:
                raise ProjectionRecoveryError("recovery ledger history is not append-only")
        self._current[snapshot.plan_sha256] = snapshot
        self._history.setdefault(snapshot.plan_sha256, []).append(snapshot)
        return snapshot


class CheckpointAuthority(Protocol):
    def record(
        self,
        checkpoint: ProjectionCheckpoint,
        *,
        previous_checkpoint_sha256: str | None = None,
    ) -> Any: ...


def _json_ready(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_ready(item) for item in value]
    return value


def recovery_event_fingerprint(**values: Any) -> str:
    return canonical_json_fingerprint(
        {"schema": ProjectionRecoveryEvent.schema_id, "data": _json_ready(values)}
    )


def recovery_snapshot_fingerprint(**values: Any) -> str:
    values.pop("snapshot_sha256", None)
    return canonical_json_fingerprint(
        {"schema": ProjectionRecoverySnapshot.schema_id, "data": _json_ready(values)}
    )


def _typed_error_code(error: Exception | str) -> str:
    text = str(error).strip().replace(" ", "_")
    return text[:128] or "unknown_error"


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ProjectionRecoveryError("recovery clock must return an aware timestamp")
    return value.astimezone(UTC)


class ProjectionRecoveryCoordinator:
    """Drive safe recovery decisions around one sealed repair plan."""

    def __init__(
        self,
        plan: ProjectionRepairPlan,
        *,
        checkpointed_by: str,
        ledger: ProjectionRecoveryLedger | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if plan.action in {"fail_closed", "noop"}:
            raise ProjectionRecoveryError("recovery requires an executable repair plan")
        if not checkpointed_by.startswith(("human:", "workload:", "agent:")):
            raise ProjectionRecoveryError("recovery actor must use a typed subject identity")
        self.plan = plan
        self.checkpointed_by = checkpointed_by
        self.ledger = ledger or InMemoryProjectionRecoveryLedger()
        self._now = now or (lambda: datetime.now(UTC))
        if self.ledger.current(plan.plan_sha256) is None:
            self._append(
                state=ProjectionRecoveryState.PLANNED,
                next_action="execute_provider",
                event_type="planned",
                detail={"action": plan.action},
            )

    @property
    def snapshot(self) -> ProjectionRecoverySnapshot:
        snapshot = self.ledger.current(self.plan.plan_sha256)
        if snapshot is None:
            raise ProjectionRecoveryError("recovery ledger has no plan state")
        return snapshot

    def _append(
        self,
        *,
        state: ProjectionRecoveryState,
        next_action: RecoveryAction,
        event_type: str,
        detail: dict[str, Any],
        provider_commit_ref: dict[str, Any] | None = None,
        checkpoint_sha256: str | None = None,
        error_code: str | None = None,
        provider_attempts: int | None = None,
        authority_attempts: int | None = None,
    ) -> ProjectionRecoverySnapshot:
        previous = self.ledger.current(self.plan.plan_sha256)
        occurred_at = self._now()
        if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
            raise ProjectionRecoveryError("recovery clock must return an aware timestamp")
        occurred_at = occurred_at.astimezone(UTC)
        attempts = previous.provider_attempts if previous else 0
        authority_attempt = previous.authority_attempts if previous else 0
        if provider_attempts is not None:
            attempts = provider_attempts
        if authority_attempts is not None:
            authority_attempt = authority_attempts
        event_values = {
            "event_type": event_type,
            "attempt": attempts + authority_attempt,
            "occurred_at": occurred_at,
            "detail": detail,
        }
        event = ProjectionRecoveryEvent(
            **event_values,
            event_sha256=recovery_event_fingerprint(**event_values),
        )
        events = previous.events + (event,) if previous else (event,)
        values = {
            "tenant_id": self.plan.tenant_id,
            "projection_id": self.plan.projection_id,
            "target_engine": self.plan.target_engine,
            "target_ref": self.plan.target_ref,
            "plan_sha256": self.plan.plan_sha256,
            "plan_idempotency_key": self.plan.plan_idempotency_key,
            "state": state,
            "next_action": next_action,
            "provider_attempts": attempts,
            "authority_attempts": authority_attempt,
            "provider_commit_ref": provider_commit_ref
            if provider_commit_ref is not None
            else (previous.provider_commit_ref if previous else None),
            "checkpoint_sha256": checkpoint_sha256
            if checkpoint_sha256 is not None
            else (previous.checkpoint_sha256 if previous else None),
            "last_error_code": error_code
            if error_code is not None
            else (previous.last_error_code if previous else None),
            "events": events,
        }
        snapshot = ProjectionRecoverySnapshot(
            **values,
            snapshot_sha256=recovery_snapshot_fingerprint(**values),
        )
        return self.ledger.append(snapshot)

    def provider_committed(
        self,
        receipt: Any,
    ) -> ProjectionRecoverySnapshot:
        commit_ref = self._provider_commit_ref(receipt)
        previous = self.snapshot
        if previous.state is ProjectionRecoveryState.AUTHORITY_COMMITTED:
            if previous.provider_commit_ref != commit_ref:
                raise ProjectionRecoveryError("authority-committed recovery cannot be replaced")
            return previous
        if previous.state in {
            ProjectionRecoveryState.RECONCILIATION_REQUIRED,
            ProjectionRecoveryState.COMPENSATION_REQUIRED,
        }:
            if previous.next_action != "manual_compensation":
                raise ProjectionRecoveryError(
                    "recovery requires explicit compensation before a provider commit"
                )
        elif previous.state is ProjectionRecoveryState.FAILED_CLOSED:
            raise ProjectionRecoveryError(
                "recovery is closed pending reconciliation or compensation"
            )
        if (
            previous.state in {
                ProjectionRecoveryState.PROVIDER_COMMITTED,
                ProjectionRecoveryState.AUTHORITY_PENDING,
            }
            and previous.provider_commit_ref == commit_ref
        ):
            return previous
        return self._append(
            state=ProjectionRecoveryState.PROVIDER_COMMITTED,
            next_action="retry_authority",
            event_type="provider_committed",
            detail={"provider": commit_ref.get("provider", "unknown")},
            provider_commit_ref=commit_ref,
            provider_attempts=previous.provider_attempts + 1,
        )

    def _provider_commit_ref(self, receipt: Any) -> dict[str, Any]:
        if getattr(receipt, "plan_sha256", None) != self.plan.plan_sha256:
            raise ProjectionRecoveryError("provider receipt is not bound to the repair plan")
        if getattr(receipt, "idempotency_key", None) != self.plan.plan_idempotency_key:
            raise ProjectionRecoveryError("provider receipt idempotency key is not bound")
        commit_ref = getattr(receipt, "provider_commit_ref", None)
        if not isinstance(commit_ref, dict):
            raise ProjectionRecoveryError("provider receipt lacks commit evidence")
        if (
            commit_ref.get("plan_sha256") != self.plan.plan_sha256
            or commit_ref.get("idempotency_key") != self.plan.plan_idempotency_key
        ):
            raise ProjectionRecoveryError("provider commit evidence is not plan-bound")
        return commit_ref

    def provider_receipt_recovered(
        self,
        receipt: Any,
    ) -> ProjectionRecoverySnapshot:
        """Promote an unknown outcome using provider-local transaction evidence."""

        commit_ref = self._provider_commit_ref(receipt)
        previous = self.snapshot
        if (
            previous.state is not ProjectionRecoveryState.RECONCILIATION_REQUIRED
            or previous.next_action != "reobserve_target"
            or previous.provider_commit_ref is not None
        ):
            raise ProjectionRecoveryError(
                "provider receipt recovery is not pending for an unknown outcome"
            )
        return self._append(
            state=ProjectionRecoveryState.PROVIDER_COMMITTED,
            next_action="retry_authority",
            event_type="provider_committed",
            detail={
                "provider": commit_ref.get("provider", "unknown"),
                "receipt_recovered": True,
            },
            provider_commit_ref=commit_ref,
            provider_attempts=previous.provider_attempts,
        )

    def provider_failed(
        self,
        error: Exception | str,
        *,
        outcome_known: bool,
    ) -> ProjectionRecoverySnapshot:
        previous = self.snapshot
        if previous.state is ProjectionRecoveryState.AUTHORITY_COMMITTED:
            raise ProjectionRecoveryError("authority-committed recovery cannot be failed")
        if not outcome_known:
            return self._append(
                state=ProjectionRecoveryState.RECONCILIATION_REQUIRED,
                next_action="reobserve_target",
                event_type="reconcile_required",
                detail={"reason": "provider_outcome_unknown"},
                error_code=_typed_error_code(error),
                provider_attempts=previous.provider_attempts + 1,
            )
        return self._append(
            state=ProjectionRecoveryState.PROVIDER_FAILED,
            next_action="execute_provider",
            event_type="provider_failed",
            detail={"reason": "provider_outcome_known_no_commit"},
            error_code=_typed_error_code(error),
            provider_attempts=previous.provider_attempts + 1,
        )

    def authority_failed(
        self,
        error: Exception | str,
    ) -> ProjectionRecoverySnapshot:
        previous = self.snapshot
        if previous.provider_commit_ref is None:
            raise ProjectionRecoveryError("authority failure requires provider commit evidence")
        return self._append(
            state=ProjectionRecoveryState.AUTHORITY_PENDING,
            next_action="retry_authority",
            event_type="authority_failed",
            detail={"reason": "provider_committed_authority_not_committed"},
            error_code=_typed_error_code(error),
            authority_attempts=previous.authority_attempts + 1,
        )

    def recover_authority(
        self,
        observation: ProjectionTargetObservation,
        authority: CheckpointAuthority,
    ) -> tuple[ProjectionRecoverySnapshot, ProjectionCheckpoint | None]:
        previous = self.snapshot
        if previous.state is ProjectionRecoveryState.AUTHORITY_COMMITTED:
            current = getattr(authority, "current", None)
            if current is None:
                return previous, None
            checkpoint = current(
                tenant_id=self.plan.tenant_id,
                projection_id=self.plan.projection_id,
                target_engine=self.plan.target_engine,
                target_ref=self.plan.target_ref,
            )
            return previous, checkpoint
        if previous.provider_commit_ref is None:
            raise ProjectionRecoveryError("authority recovery has no provider commit evidence")
        if (
            observation.tenant_id != self.plan.tenant_id
            or observation.projection_id != self.plan.projection_id
            or observation.target_engine != self.plan.target_engine
            or observation.target_ref != self.plan.target_ref
        ):
            raise ProjectionRecoveryError("recovery observation target identity differs")
        desired = self.plan.desired_state
        if (
            observation.target_exists != desired.target_exists
            or observation.observed_content_sha256 != desired.expected_target_content_sha256
            or observation.observed_row_count != desired.expected_row_count
        ):
            snapshot = self._append(
                state=ProjectionRecoveryState.RECONCILIATION_REQUIRED,
                next_action="manual_compensation",
                event_type="target_drift",
                detail={"reason": "target_drift_after_provider_commit"},
            )
            return snapshot, None
        try:
            checkpoint = build_projection_checkpoint_from_repair(
                self.plan,
                observation,
                target_commit_ref=previous.provider_commit_ref,
                updated_by=self.checkpointed_by,
                updated_at=max(_aware_utc(self._now()), observation.observed_at),
            )
            written = authority.record(
                checkpoint,
                previous_checkpoint_sha256=self.plan.previous_checkpoint_sha256,
            )
        except ProjectionCheckpointConflictError:
            history = getattr(authority, "history", None)
            if history is None:
                raise
            matches = tuple(
                item
                for item in history(
                    tenant_id=self.plan.tenant_id,
                    projection_id=self.plan.projection_id,
                    target_engine=self.plan.target_engine,
                    target_ref=self.plan.target_ref,
                )
                if item.target_commit_ref == previous.provider_commit_ref
            )
            if len(matches) != 1:
                raise
            snapshot = self._append(
                state=ProjectionRecoveryState.AUTHORITY_COMMITTED,
                next_action="none",
                event_type="authority_committed",
                detail={"created": False, "concurrent": True},
                checkpoint_sha256=matches[0].checkpoint_sha256,
                authority_attempts=previous.authority_attempts + 1,
            )
            return snapshot, matches[0]
        except Exception as exc:
            snapshot = self.authority_failed(exc)
            return snapshot, None
        snapshot = self._append(
            state=ProjectionRecoveryState.AUTHORITY_COMMITTED,
            next_action="none",
            event_type="authority_committed",
            detail={"created": bool(getattr(written, "created", True))},
            checkpoint_sha256=written.checkpoint.checkpoint_sha256,
            authority_attempts=previous.authority_attempts + 1,
        )
        return snapshot, written.checkpoint

    def reobserve_unknown_provider(
        self,
        observation: ProjectionTargetObservation,
    ) -> ProjectionRecoverySnapshot:
        """Close an unknown provider outcome without inventing a commit ref."""

        previous = self.snapshot
        if (
            previous.state is not ProjectionRecoveryState.RECONCILIATION_REQUIRED
            or previous.next_action != "reobserve_target"
        ):
            raise ProjectionRecoveryError(
                "unknown-provider re-observation is not pending"
            )
        if previous.provider_commit_ref is not None:
            raise ProjectionRecoveryError(
                "unknown-provider re-observation cannot replace provider evidence"
            )
        if (
            observation.tenant_id != self.plan.tenant_id
            or observation.projection_id != self.plan.projection_id
            or observation.target_engine != self.plan.target_engine
            or observation.target_ref != self.plan.target_ref
        ):
            raise ProjectionRecoveryError("recovery observation target identity differs")
        desired = self.plan.desired_state
        matches = (
            observation.target_exists == desired.target_exists
            and observation.observed_content_sha256
            == desired.expected_target_content_sha256
            and observation.observed_row_count == desired.expected_row_count
        )
        return self._append(
            state=ProjectionRecoveryState.COMPENSATION_REQUIRED,
            next_action="manual_compensation",
            event_type="compensation_required",
            detail={
                "reason": (
                    "target_matches_without_provider_commit_evidence"
                    if matches
                    else "target_drift_after_unknown_provider_outcome"
                )
            },
        )

    def require_compensation(self, reason: Exception | str) -> ProjectionRecoverySnapshot:
        return self._append(
            state=ProjectionRecoveryState.COMPENSATION_REQUIRED,
            next_action="manual_compensation",
            event_type="compensation_required",
            detail={"reason": "operator_compensation_required"},
            error_code=_typed_error_code(reason),
        )


__all__ = [
    "InMemoryProjectionRecoveryLedger",
    "ProjectionRecoveryCoordinator",
    "ProjectionRecoveryError",
    "ProjectionRecoveryEvent",
    "ProjectionRecoverySnapshot",
    "ProjectionRecoveryState",
    "recovery_event_fingerprint",
    "recovery_snapshot_fingerprint",
]
